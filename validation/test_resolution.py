#!/usr/bin/env python3
"""Known-mesh, flux-corruption and recipe tests. Unit data are synthetic."""

import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
import openfoam_backend as backend
import openfoam_cases as cases

sys.path.insert(0, str(ROOT / "tutorials"))
import backstep_resolution
from audit_openfoam_mesh import (
    cartesian_mesh,
    cell_divergence,
    audit,
    vector_values,
    patches,
    checked_wall_distances,
)


def synthetic_data():
    return {
        "profiles": {
            x: [
                [i, (1.1 if x == -4 else 0.1) + i * 0.5, 1, 0, 1, 1, 0, 0, 0, 0, 0]
                for i in range(10)
            ]
            for x in [-4, 1, 4, 6, 10]
        },
        "raw_sha256": {"unit": "synthetic"},
    }


def two_cells(path):
    path = Path(path) / "constant/polyMesh"
    path.mkdir(parents=True)
    coordinates = [(x, y, z) for z in [0, 1] for y in [0, 1] for x in [0, 1, 2]]
    ids = {p: i for i, p in enumerate(coordinates)}
    found = {}
    for cell in [0, 1]:
        v = [
            ids[(x, y, z)]
            for x, y, z in [
                (cell, 0, 0),
                (cell + 1, 0, 0),
                (cell + 1, 1, 0),
                (cell, 1, 0),
                (cell, 0, 1),
                (cell + 1, 0, 1),
                (cell + 1, 1, 1),
                (cell, 1, 1),
            ]
        ]
        for indices in [
            [0, 1, 2, 3],
            [4, 5, 6, 7],
            [0, 4, 5, 1],
            [3, 2, 6, 7],
            [0, 3, 7, 4],
            [1, 5, 6, 2],
        ]:
            f = [v[i] for i in indices]
            key = tuple(sorted(f))
            if key in found:
                found[key][2] = cell
            else:
                found[key] = [f, cell, None]
    faces = sorted(found.values(), key=lambda row: row[2] is None)

    def write(name, rows):
        (path / name).write_text(
            cases.header(name) + str(len(rows)) + "\n(\n" + "\n".join(rows) + "\n)\n"
        )

    write("points", ["(" + " ".join(map(str, p)) + ")" for p in coordinates])
    write("faces", ["4(" + " ".join(map(str, r[0])) + ")" for r in faces])
    write("owner", [str(r[1]) for r in faces])
    write("neighbour", [str(r[2]) for r in faces if r[2] is not None])
    write("boundary", [])


class Resolution(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-resolution-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_known_mesh_recovers_cell_geometry(self):
        two_cells(self.root)
        m = cartesian_mesh(self.root)
        self.assertEqual(m["cells"], 2)
        np.testing.assert_allclose(m["volumes"], [1, 1])
        np.testing.assert_allclose(
            m["cell_centres"], [[0.5, 0.5, 0.5], [1.5, 0.5, 0.5]]
        )

    def test_local_flux_corruption_is_not_a_global_balance(self):
        m = {
            "cells": 2,
            "owner": np.array([0, 0, 1]),
            "neighbour": np.array([1]),
            "volumes": np.ones(2),
        }
        np.testing.assert_allclose(cell_divergence(m, [1, -1, 1]), [0, 0])
        divergence = cell_divergence(m, [1.1, -1, 1])
        self.assertAlmostEqual(sum(divergence), 0)
        self.assertGreater(max(abs(divergence)), 1e-4)

    def test_wrong_faces_and_missing_cell_faces_are_rejected(self):
        two_cells(self.root)
        p = self.root / "constant/polyMesh/faces"
        p.write_text(p.read_text().replace("4(", "3(", 1))
        with self.assertRaisesRegex(ValueError, "CFD-X011 mesh.faces"):
            cartesian_mesh(self.root)

    def test_nonfinite_or_noncartesian_points_are_rejected(self):
        two_cells(self.root)
        p = self.root / "constant/polyMesh/points"
        p.write_text(p.read_text().replace("(0 0 0)", "(nan 0 0)", 1))
        with self.assertRaisesRegex(ValueError, "mesh.points"):
            cartesian_mesh(self.root)
        p.write_text(p.read_text().replace("(nan 0 0)", "(0.1 0 0)", 1))
        with self.assertRaisesRegex(ValueError, "mesh.faces"):
            cartesian_mesh(self.root)

    def test_vector_wall_field_counts_and_finiteness(self):
        self.assertEqual(
            vector_values("value uniform (1 0 0);", 2, "wall").shape, (2, 3)
        )
        for text in [
            "value uniform (nan 0 0);",
            "value nonuniform List<vector> 2 ((1 0 0));",
        ]:
            with self.assertRaises(ValueError):
                vector_values(text, 2, "wall")

    def test_geometric_series_has_requested_length_and_expansion(self):
        for count in [24, 48, 72]:
            first = cases.first_width(0.5, count, 100)
            widths = first * np.geomspace(1, 100, count)
            self.assertAlmostEqual(sum(widths), 0.5, places=12)
            self.assertAlmostEqual(widths[-1] / widths[0], 100)

    def test_claimed_wall_height_cannot_replace_actual_distance(self):
        mesh = {
            "owner": np.array([0]),
            "cell_centres": np.array([[0.5, 0.5, 0.5]]),
            "face_centres": np.array([[0, 0, 0.5]]),
        }
        names = ["lowerWall", "stepWall", "upperWall", "upstreamWall"]
        parts = {name: (0, 1) for name in names}
        meta = {"height_m": 1, "wall_first_cell_height_h": dict.fromkeys(names, 1)}
        checked_wall_distances(mesh, parts, meta)
        meta["wall_first_cell_height_h"]["stepWall"] = 0.1
        with self.assertRaisesRegex(ValueError, "CFD-X011 mesh.*stepWall"):
            checked_wall_distances(mesh, parts, meta)

    def test_recipe_options_are_closed_and_cavity_is_unchanged(self):
        for kwargs in [
            {"mesh_family": "unknown"},
            {"solver_profile": "unknown"},
            {"mesh_family": "wall-resolved"},
        ]:
            with self.assertRaisesRegex(ValueError, "CFD-X001"):
                cases.build("cavity", 1, 100, **kwargs)
        _, meta = cases.build("cavity", 1, 100)
        self.assertEqual(meta["cells"], 576)

    def test_resolved_recipe_covers_every_wall_and_refines(self):
        for level in [1, 2, 3]:
            files, meta = cases.build(
                "backstep", level, 6000, synthetic_data(), "wall-resolved", "simple"
            )
            self.assertEqual(meta["cells"], 47616 * level**2)
            self.assertEqual(
                set(meta["wall_first_cell_height_h"]),
                {"lowerWall", "stepWall", "upperWall", "upstreamWall"},
            )
            self.assertIn("type fixedValue; value uniform 0;", files["0/k"])
            self.assertIn("nutLowReWallFunction", files["0/nut"])
            self.assertIn("solver PCG;", files["system/fvSolution"])
            self.assertIn("relTol 0;", files["system/fvSolution"])
            self.assertIn("internalField uniform (0 0 0);", files["0/U"])
            self.assertIn("p 1e-7;", files["system/fvSolution"])
            self.assertIn("bounded Gauss upwind", files["system/fvSchemes"])

    def test_legacy_dictionaries_match_the_merged_baseline(self):
        # Frozen from 4ea88a3 using the same explicitly synthetic inlet table.
        expected = {
            "system/blockMeshDict": "14ca7ecebcfbd625ed75aa4a5da7ea3a7482a22d64fe779eec1073fc34009237",
            "system/fvSchemes": "db584cf632e21acf03f2124fc102717793287ab014de15af78c26c02410920a5",
            "system/fvSolution": "fea33c932eb3a0a9cda3259d1fd0588efeeaf5b7d7396f784515fc785967a044",
        }
        files, _ = cases.build("backstep", 1, 6000, synthetic_data())
        for name, digest in expected.items():
            self.assertEqual(
                hashlib.sha256(files[name].encode()).hexdigest(), digest, name
            )

    def test_nonfinite_solver_output_stops_before_the_deadline(self):
        (self.root / "case").mkdir()
        start = time.monotonic()
        with self.assertRaisesRegex(backend.ExecutionError, "CFD-X010"):
            backend.execute(
                [
                    sys.executable,
                    "-c",
                    "import time; print('Initial residual = nan',flush=True); time.sleep(5)",
                ],
                os.environ.copy(),
                self.root,
                "solve",
                time.monotonic() + 4,
                1024**2,
                512,
                backend.Stop(),
            )
        self.assertLess(time.monotonic() - start, 2)

    def test_zero_exit_with_nonfinite_output_is_rejected(self):
        (self.root / "case").mkdir()
        with self.assertRaisesRegex(backend.ExecutionError, "CFD-X010"):
            backend.execute(
                [sys.executable, "-c", "print('Final residual = -Inf')"],
                os.environ.copy(),
                self.root,
                "solve",
                time.monotonic() + 4,
                1024**2,
                512,
                backend.Stop(),
            )

    def test_refinement_is_not_started_after_a_failed_coarse_run(self):
        failed = {"passed": False, "numerical": None, "execution_status": "failed"}
        with (
            patch.object(backstep_resolution, "load", return_value=synthetic_data()),
            patch.object(backend, "prepare"),
            patch.object(backend, "run", return_value=failed) as run,
        ):
            report = backstep_resolution.study(
                self.root, self.root / "study", self.root, preset="study"
            )
        self.assertEqual(run.call_count, 1)
        self.assertTrue(report["workflow_completed"])
        self.assertFalse(report["passed"])
        self.assertEqual(
            [r.get("reason") for r in report["rows"][1:]],
            ["coarser_level_not_accepted"] * 2,
        )

    def test_invalid_study_options_fail_before_creating_outputs(self):
        for kwargs in [{"timeout_s": 0}, {"iterations": 1}, {"preset": "unknown"}]:
            with self.assertRaisesRegex(ValueError, "CFD-X001"):
                backstep_resolution.study(
                    self.root, self.root / "unused", self.root, **kwargs
                )
        self.assertFalse((self.root / "unused").exists())


@unittest.skipUnless(
    os.environ.get("CFD_OPENFOAM_ROOT"),
    "set CFD_OPENFOAM_ROOT for actual mesh/flux audit",
)
class ActualArchive(unittest.TestCase):
    def test_generated_wall_mesh_has_the_claimed_distances(self):
        with tempfile.TemporaryDirectory(prefix="cfd-real-mesh-") as directory:
            root = Path(directory)
            files, meta = cases.build(
                "backstep", 1, 50, synthetic_data(), "wall-resolved", "simple"
            )
            for name, text in files.items():
                path = root / "case" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            binaries, env, _ = backend.runtime(Path(os.environ["CFD_OPENFOAM_ROOT"]))
            backend.execute(
                [str(binaries["blockMesh"])],
                env,
                root,
                "mesh",
                time.monotonic() + 30,
                128 * 1024**2,
                1024,
                backend.Stop(),
            )
            mesh = cartesian_mesh(root / "case")
            self.assertEqual(mesh["cells"], 47616)
            self.assertAlmostEqual(sum(mesh["volumes"]), 48.2, places=8)
            checked_wall_distances(mesh, patches(mesh, "backstep"), meta)

    def test_returned_internal_flux_corruption_is_detected(self):
        with tempfile.TemporaryDirectory(prefix="cfd-real-audit-") as directory:
            root = Path(directory)
            backend.prepare("cavity", 1, 3000, root / "input")
            record = backend.run(
                root / "input",
                root / "run",
                Path(os.environ["CFD_OPENFOAM_ROOT"]),
                timeout_s=60,
            )
            self.assertTrue(record["passed"])
            self.assertTrue(audit(root / "run")["passed"])
            path = (
                root / "run/case" / record["numerical"]["final_time_directory"] / "phi"
            )
            text = path.read_text()
            match = re.search(
                r"(internalField\s+nonuniform\s+List<scalar>\s+\d+\s*\(\s*)("
                + backend.NUMBER
                + ")",
                text,
            )
            self.assertIsNotNone(match)
            text = (
                text[: match.start(2)]
                + str(float(match[2]) + 0.01)
                + text[match.end(2) :]
            )
            path.write_text(text)
            manifest = json.loads((root / "run/manifest.json").read_text())
            entries = backend.inventory(root / "run")
            entries.pop("manifest.json")
            entries.pop("complete.json")
            manifest["files"] = entries
            backend.write_json(root / "run/manifest.json", manifest)
            backend.write_json(
                root / "run/complete.json",
                {"manifest_sha256": backend.sha256(root / "run/manifest.json")},
            )
            self.assertTrue(
                backend.verify(root / "run")["passed"]
            )  # Its global budget is unchanged.
            self.assertFalse(audit(root / "run")["passed"])


if __name__ == "__main__":
    unittest.main()
