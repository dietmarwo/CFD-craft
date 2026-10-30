#!/usr/bin/env python3
"""Known-mesh, flux-corruption and recipe tests. Unit data are synthetic."""

import hashlib
import json
import os
import re
import subprocess
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
import compare_backstep
from backstep_data import FILES
from audit_openfoam_mesh import (
    cartesian_mesh,
    cell_divergence,
    audit,
    face_fluxes,
    local_continuity,
    vector_values,
    patches,
    checked_wall_distances,
    represented_domain,
    wall_resolution,
)

AUDITOR = ROOT / "validation/audit_openfoam_mesh.py"
WALLS = ["lowerWall", "stepWall", "upperWall", "upstreamWall"]


def line_divide(cells, grading):
    """blockMesh's division of one block edge, reimplemented from its documented
    multi-grading rules: normalized length and cell fractions, nearest-integer
    cell counts, the remainder in the last segment, last/first width expansion."""
    if not isinstance(grading, list):
        grading = [(1, 1, grading)]
    length = sum(g[0] for g in grading)
    fraction = sum(g[1] for g in grading)
    widths, used = [], 0
    for i, (part, share, expansion) in enumerate(grading):
        count = (
            cells - used
            if i == len(grading) - 1
            else int(share / fraction * cells + 0.5)
        )
        used += count
        ratio = expansion ** (1 / (count - 1)) if count > 1 else 1
        first = (
            part
            / length
            * (1 / count if ratio == 1 else (ratio - 1) / (ratio**count - 1))
        )
        widths += [first * ratio**k for k in range(count)]
    return np.array(widths)


def parsed_blocks(text):
    """(cells, x grading, y grading) of each hex in a generated blockMeshDict."""
    number = r"[-+.\deE]+"
    group = (
        r"("
        + number
        + r"|\((?:\s*\("
        + number
        + r"\s+"
        + number
        + r"\s+"
        + number
        + r"\s*\))+\s*\))"
    )
    found = re.findall(
        r"hex \([\d ]+\) \((\d+) (\d+) 1\) simpleGrading \("
        + group
        + r"\s+"
        + group
        + r"\s+1\)",
        text,
    )

    def grading(token):
        if not token.startswith("("):
            return float(token)
        return [
            tuple(map(float, g))
            for g in re.findall(
                r"\((" + number + r")\s+(" + number + r")\s+(" + number + r")\)", token
            )
        ]

    return [(int(nx), int(ny), grading(gx), grading(gy)) for nx, ny, gx, gy in found]


def neighbour_ratio(widths):
    widths = np.asarray(widths)
    ratio = widths[1:] / widths[:-1]
    return float(np.max(np.maximum(ratio, 1 / ratio)))


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
        # OpenFOAM orders each face so that its area vector points out of the owner.
        for indices in [
            [0, 3, 2, 1],
            [4, 5, 6, 7],
            [0, 1, 5, 4],
            [3, 7, 6, 2],
            [0, 4, 7, 3],
            [1, 2, 6, 5],
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
            self.assertEqual(meta["cells"], 48896 * level**2)
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

    def test_presets_share_one_reference_recipe(self):
        reference = ("wall-resolved", "simplec")
        self.assertEqual(backstep_resolution.scenarios("smoke"), [(*reference, 1)])
        self.assertEqual(
            backstep_resolution.scenarios("study"),
            [(*reference, level) for level in [1, 2, 3]],
        )
        controls = backstep_resolution.scenarios("controls")
        self.assertEqual(
            sorted(controls),
            sorted(
                (mesh, solver, 1)
                for mesh in ["legacy", "wall-resolved"]
                for solver in ["legacy", "simplec"]
            ),
        )
        files, meta = cases.build("backstep", 1, 6000, synthetic_data(), *reference)
        solution, schemes = files["system/fvSolution"], files["system/fvSchemes"]
        for text in [
            "consistent yes",
            "fields { p 1; } equations { U 0.7; k 0.7; omega 0.7; }",
            "solver GAMG;",
            "smoother DICGaussSeidel;",
        ]:
            self.assertIn(text, solution)
        self.assertIn("bounded Gauss linearUpwind grad(U)", schemes)
        self.assertEqual((meta["mesh_family"], meta["solver_profile"]), reference)

    def test_legacy_dictionaries_match_the_merged_baseline(self):
        # Frozen from 4ea88a3 with the same explicitly synthetic inlet table: every
        # generated file, and the metadata apart from the two recipe labels.
        expected = {
            ("cavity", 1, 3000): (
                "c75b3ebe42fccee650bd851e9aa58eb165cf4e493abaddaab3054cf71c37e827",
                "9773551e20c8b1f6534643a619b8e1ee2b8d740cb834fe6749254e96cea9403e",
            ),
            ("cavity", 2, 3000): (
                "d6c340365f4971ef72b2267a9dc4f76656c262981c4e476421f88825efba53ad",
                "3b6600944e33f97ae141c4f65253362e65210eb370cfc4d1bde30502d65a7d29",
            ),
            ("cavity", 3, 3000): (
                "9b627ae4bd571065e272126d56af0e0f212b887b381795197e5ce0dbd1bdcfcc",
                "488b7bad8b366c2deb2711a2d5b6910a5a78375511ca0b67bf90b089ef74bd2f",
            ),
            ("backstep", 1, 6000): (
                "84e332263cb7910aa9aadb731a661c44a14ab8a07fd557337ac529559289320e",
                "761a050dced6dc8901b834b24deb3308ca315eaecbee1d579136117a95b55ef9",
            ),
            ("backstep", 2, 6000): (
                "51b2ecc0751d91986651f264293691e2957af126683c82f98844b7b0fb6d7b12",
                "ea64ac94b647696e64ff6eeecc45084c3d3c881b502f99e4503a15315b28b7b3",
            ),
            ("backstep", 3, 6000): (
                "44bfe9f218a791c0b7ff5b5885d6b77198882876f42460535d0a326cfc8834b3",
                "4b12a3913f1bb967ebb4168549efd94af1222fc9d31e6ef54683a8602295889f",
            ),
        }
        for (kind, level, iterations), (files_digest, meta_digest) in expected.items():
            data = synthetic_data() if kind == "backstep" else None
            files, meta = cases.build(kind, level, iterations, data)
            digest = hashlib.sha256()
            for name in sorted(files):
                digest.update(name.encode() + b"\0" + files[name].encode() + b"\0")
            self.assertEqual(digest.hexdigest(), files_digest, (kind, level))
            if kind == "backstep":
                self.assertEqual(
                    (meta.pop("mesh_family"), meta.pop("solver_profile")),
                    ("legacy", "legacy"),
                )
            meta = json.dumps(meta, sort_keys=True).encode()
            self.assertEqual(hashlib.sha256(meta).hexdigest(), meta_digest, kind)

    def test_wall_resolved_spacing_has_no_jumps(self):
        # blocks: upstream channel, downstream channel, below the step
        for level in [1, 2, 3]:
            files, meta = cases.build(
                "backstep", level, 6000, synthetic_data(), "wall-resolved", "simple"
            )
            blocks = parsed_blocks(files["system/blockMeshDict"])
            self.assertEqual(len(blocks), 3)
            (nu, ny, gu, gy), (nd, nyd, gd, gyd), (nl, nyl, gl, gyl) = blocks
            self.assertEqual((nd, gd, nyd, gyd), (nl, gl, nyd, gy))
            self.assertEqual(nu * ny + nd * ny + nl * nyl, meta["cells"])
            upstream = 4 * line_divide(nu, gu)
            downstream = 50 * line_divide(nd, gd)
            lower = line_divide(nyl, gyl)
            upper = 8 * line_divide(ny, gy)
            for widths, length in [
                (upstream, 4),
                (downstream, 50),
                (lower, 1),
                (upper, 8),
            ]:
                self.assertAlmostEqual(sum(widths), length, places=10)
            # Across x=0 (both channel rows) and across y=1 (downstream), and within.
            self.assertLessEqual(neighbour_ratio(np.r_[upstream, downstream]), 1.2)
            self.assertLessEqual(neighbour_ratio(np.r_[lower, upper]), 1.35)
            self.assertLessEqual(downstream[0] / upstream[-1], 1.2)
            self.assertLessEqual(upstream[-1] / downstream[0], 1.2)
            heights = meta["wall_first_cell_height_h"]
            for name, width in [
                ("stepWall", downstream[0]),
                ("lowerWall", lower[0]),
                ("upstreamWall", upper[0]),
                ("upperWall", upper[-1]),
            ]:
                self.assertAlmostEqual(heights[name] / width, 1, places=9, msg=name)
            # The scored region 1 < x/H < 12 is uniform.
            x = np.cumsum(downstream)
            scored = downstream[(x > 1) & (x < 12)]
            self.assertLess(np.ptp(scored) / scored.mean(), 1e-9)

    def test_log_breakdown_is_found_after_a_long_trailer(self):
        (self.root / "case").mkdir()
        trailer = "x" * 100 + "\n"
        script = (
            "import sys; print('Solving for p, Initial residual = nan, No Iterations 1');"
            f"sys.stdout.write({trailer!r} * 400)"
        )
        with self.assertRaisesRegex(
            backend.ExecutionError, "CFD-X010 execution.solve.residual"
        ):
            backend.execute(
                [sys.executable, "-c", script],
                os.environ.copy(),
                self.root,
                "solve",
                time.monotonic() + 10,
                1024**2,
                512,
                backend.Stop(),
            )

    def test_continuity_breakdown_stops_before_the_deadline(self):
        (self.root / "case").mkdir()
        line = "time step continuity errors : sum local = 1.5, global = 0.1, cumulative = 0.1"
        start = time.monotonic()
        with self.assertRaisesRegex(
            backend.ExecutionError, "CFD-X010 execution.solve.continuity"
        ):
            backend.execute(
                [
                    sys.executable,
                    "-c",
                    f"import time; print({line!r}, flush=True); time.sleep(5)",
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

    def test_log_scan_reads_split_lines_once_and_keeps_its_finding(self):
        log = self.root / "solve.log"
        log.write_bytes(
            b"sum local = 0.000294679, global = 1e-5\nSolving for Ux, Initial resid"
        )
        scan = backend.SolverLogScan(log)
        self.assertIsNone(scan.update())
        with log.open("ab") as stream:
            stream.write(b"ual = inf, Final residual = 1\n")
        self.assertIn("residual", scan.update())
        log.write_bytes(b"")
        self.assertIn("residual", scan.update(final=True))
        # Converged and stalled runs stay far below the continuity limit.
        log.write_bytes(b"sum local = 0.999999, global = 0.1\nsum local = 2.9e-4,")
        self.assertIsNone(backend.SolverLogScan(log).update(final=True))

    def test_unscanned_labels_are_not_solver_breakdowns(self):
        (self.root / "case").mkdir()
        line = "sum local = 1.5, global = nan"
        record = backend.execute(
            [sys.executable, "-c", f"print({line!r})"],
            os.environ.copy(),
            self.root,
            "mesh",
            time.monotonic() + 4,
            1024**2,
            512,
            backend.Stop(),
        )
        self.assertEqual(record["returncode"], 0)

    def test_boundary_fluxes_enter_the_local_balance(self):
        two_cells(self.root)
        mesh = cartesian_mesh(self.root)
        internal = len(mesh["neighbour"])
        x = mesh["face_centres"][:, 0]
        # Uniform unit x-velocity through unit faces; empty span faces carry none.
        flux = np.where(x[internal:] == 0, -1.0, np.where(x[internal:] == 2, 1.0, 0.0))
        parts = {f"b{i}": (internal + i, 1) for i in range(len(flux))}
        boundary = " ".join(
            f"b{i} {{ type patch; value uniform {v}; }}" for i, v in enumerate(flux)
        )
        text = f"internalField uniform 1; boundaryField {{ {boundary} }}"
        balanced = local_continuity(mesh, face_fluxes(mesh, parts, text), 1, 1)
        self.assertTrue(balanced["passed"])
        self.assertLess(balanced["maximum_abs_divergence_h_over_u"], 1e-14)
        inlet = int(np.flatnonzero(x[internal:] == 0)[0])
        text = text.replace(
            f"b{inlet} {{ type patch; value uniform -1.0;",
            f"b{inlet} {{ type patch; value uniform -1.1;",
        )
        broken = local_continuity(mesh, face_fluxes(mesh, parts, text), 1, 1)
        self.assertFalse(broken["passed"])
        self.assertAlmostEqual(broken["maximum_abs_divergence_h_over_u"], 0.1)
        with self.assertRaisesRegex(ValueError, "CFD-X011 fields.phi.b0"):
            face_fluxes(mesh, parts, text.replace("b0 {", "c0 {"))

    def test_patch_ranges_must_cover_each_boundary_face_once(self):
        mesh = {"neighbour": np.zeros(2), "owner": np.zeros(10)}
        good = "lid { nFaces 2; startFace 2; } walls { nFaces 2; startFace 4; } span { nFaces 4; startFace 6; }"
        self.assertEqual(patches({**mesh, "boundary": good}, "cavity")["walls"], (4, 2))
        for text, field in [
            (
                good.replace("nFaces 2; startFace 4", "nFaces 3; startFace 3"),
                "mesh.boundary:",
            ),
            (
                good.replace("nFaces 4; startFace 6", "nFaces 3; startFace 6"),
                "mesh.boundary:",
            ),
            (good.replace("lid { nFaces 2;", "lid {"), "mesh.boundary.lid"),
            (good.replace("walls {", "wall {"), "mesh.boundary.walls"),
        ]:
            with self.assertRaisesRegex(ValueError, "CFD-X011 " + field):
                patches({**mesh, "boundary": text}, "cavity")

    def test_every_hexahedron_needs_six_faces_and_outward_orientation(self):
        two_cells(self.root)
        directory = self.root / "constant/polyMesh"
        original = {n: (directory / n).read_text() for n in ["faces", "owner"]}

        def drop_last(name):
            lines = original[name].splitlines()
            lines[1] = str(int(lines[1]) - 1)
            (directory / name).write_text("\n".join(lines[:-2] + lines[-1:]) + "\n")

        drop_last("faces")
        drop_last("owner")
        with self.assertRaisesRegex(ValueError, "CFD-X011 mesh.cells"):
            cartesian_mesh(self.root)
        # Reverse the shared face: its area vector now points into its owner.
        text = original["faces"]
        first = re.search(r"4\(([\d ]+)\)", text)
        reverse = "4(" + " ".join(reversed(first[1].split())) + ")"
        (directory / "faces").write_text(
            text[: first.start()] + reverse + text[first.end() :]
        )
        (directory / "owner").write_text(original["owner"])
        with self.assertRaisesRegex(
            ValueError, "CFD-X011 mesh.faces: face orientation"
        ):
            cartesian_mesh(self.root)
        # Swapping owner and neighbour with a consistent orientation still breaks
        # OpenFOAM's owner-below-neighbour face order.
        (directory / "owner").write_text(original["owner"].replace("\n0\n", "\n1\n", 1))
        (directory / "neighbour").write_text(
            (directory / "neighbour").read_text().replace("(\n1\n)", "(\n0\n)")
        )
        with self.assertRaisesRegex(ValueError, "CFD-X011 mesh.neighbour"):
            cartesian_mesh(self.root)

    def test_ascii_header_and_point_groups_are_parsed_strictly(self):
        two_cells(self.root)
        points = self.root / "constant/polyMesh/points"
        text = points.read_text()
        for broken in [
            text.replace("format ascii;", "format binary; // format ascii;"),
            text.replace("(2 1 1)\n)", "(2 1 1)\n"),
            text.replace("(2 1 1)", "(2 1)"),
            text.replace("(0 0 0)", "(0 0 0 0)"),
        ]:
            points.write_text(broken)
            with self.assertRaisesRegex(ValueError, "CFD-X011 mesh.points"):
                cartesian_mesh(self.root)
        points.write_text(text.replace("(0 0 0)", "(abc 0 0)"))
        with self.assertRaisesRegex(ValueError, "CFD-X011 mesh.points: nonnumeric"):
            cartesian_mesh(self.root)

    def test_represented_domain_is_checked(self):
        represented_domain({"volumes": np.array([48.0, 0.2])}, "backstep")
        with self.assertRaisesRegex(ValueError, "CFD-X011 mesh.volume"):
            represented_domain({"volumes": np.array([48.0, 0.2 + 1e-6])}, "backstep")
        with self.assertRaisesRegex(ValueError, "CFD-X011 mesh.volume"):
            represented_domain({"volumes": np.array([48.2])}, "cavity")

    def wall_case(self, traction):
        mesh = {
            "owner": np.array([0]),
            "cell_centres": np.array([[0.5, 0.5, 0.5]]),
            "face_centres": np.array([[0, 0, 0.5]]),
        }
        metadata = {
            "height_m": 1,
            "reference_speed_m_s": 1,
            "reynolds": 1,
            "wall_first_cell_height_h": dict.fromkeys(WALLS, 1),
        }
        entries = " ".join(
            f"{w} {{ type calculated; value uniform ({' '.join(map(str, traction.get(w, (0, 0, 1))))}); }}"
            for w in WALLS
        )
        parts = {w: (0, 1) for w in WALLS}
        return mesh, parts, metadata, f"boundaryField {{ {entries} }}"

    def test_wall_y_plus_uses_tangential_traction_and_its_limit(self):
        # nu = 1 and a 0.5 first-cell-centre distance: y+ = 0.5 sqrt(|tau_t|).
        wall = wall_resolution(
            *self.wall_case({"lowerWall": (1, 100, 0), "stepWall": (100, 0, 1)})
        )
        self.assertTrue(wall["passed"])
        for name in WALLS:
            self.assertAlmostEqual(
                wall["patches"][name]["maximum_y_plus"], 0.5, msg=name
            )
        self.assertEqual(
            wall["patches"]["lowerWall"]["maximum_y_plus_at_xy_over_h"], [0, 0]
        )
        wall = wall_resolution(*self.wall_case({"upperWall": (16.0001, 0, 0)}))
        self.assertFalse(wall["passed"])
        self.assertFalse(wall["patches"]["upperWall"]["passed"])
        self.assertTrue(wall["patches"]["lowerWall"]["passed"])

    def test_an_unsampled_wall_does_not_pass_its_y_plus_gate(self):
        for traction in [(0, 0, 0), (0, 5, 0)]:
            with self.assertRaisesRegex(
                ValueError, "CFD-X011 wallShearStress.upstreamWall"
            ):
                wall_resolution(*self.wall_case({"upstreamWall": traction}))

    def assessed(self, independent):
        """assess() of a synthetic, numerically passed wall-resolved archive whose
        samples agree with the synthetic reference exactly."""
        run = self.root / "run"
        rows = {
            station: [[i, 0.1 + 0.5 * i, 0.2 + 0.05 * i] for i in range(10)]
            for station in [-4, 1, 4, 6, 10]
        }
        cf_x = np.arange(0.5, 39.5, 0.5)
        reference = {
            "profiles": rows,
            "cf": [[x, 1e-3 * (x - 6.26), 1e-4] for x in cf_x],
            "raw_sha256": FILES,
            "reference": "synthetic",
        }
        numerical = {"passed": True, "residual_trend": {}}
        result = {
            "case": "backstep",
            "case_metadata": {
                "reference_sha256": FILES,
                "mesh_family": "wall-resolved",
                "lower_wall_first_cell_height_h": 1e-3,
                "reference_speed_m_s": 1.0,
                "height_m": 1.0,
                "reynolds": 36000,
                "turbulence_package": "synthetic",
            },
            "numerical": numerical,
        }
        x = np.arange(0.05, 40.05, 0.05)

        def samples(run, name, columns, result):
            if name == "friction":
                return np.column_stack(
                    [x, 0 * x, 0 * x, 0 * x, -1e-3 * (x - 6.26) / 2, 0 * x, 0 * x]
                )
            r = np.array(rows[int(name.removeprefix("station"))])
            zero = 0 * r[:, 1]
            return np.column_stack([r[:, 1], r[:, 2], zero, zero, zero, zero, zero])

        with (
            patch.object(compare_backstep, "load", return_value=reference),
            patch.object(backend, "verify", return_value=result),
            patch.object(backend, "numerical_assessment", return_value=numerical),
            patch.object(compare_backstep, "samples", side_effect=samples),
        ):
            return compare_backstep.assess(run, self.root, independent=independent)

    def test_failed_independent_audit_leaves_the_screen_unassessed(self):
        (self.root / "run").mkdir()
        (self.root / "run/manifest.json").write_text("{}")
        (self.root / "run/solve.log").write_text("synthetic")
        digest = backend.sha256(self.root / "run/manifest.json")
        passed = self.assessed({"passed": True, "run_manifest_sha256": digest})
        self.assertTrue(passed["measurement_screen_passed"])
        self.assertTrue(passed["passed"])
        failed = self.assessed({"passed": False, "run_manifest_sha256": digest})
        self.assertFalse(failed["measurement_prerequisites_passed"])
        self.assertIsNone(failed["measurement_screen_passed"])
        self.assertFalse(failed["passed"])
        self.assertTrue(failed["measurement_screen"].startswith("not_assessed"))
        with self.assertRaisesRegex(ValueError, "CFD-D001 independent_mesh_audit"):
            self.assessed({"passed": True, "run_manifest_sha256": "0" * 64})

    def study_with(self, execution, audited, compared, preset="smoke"):
        with (
            patch.object(backstep_resolution, "load", return_value=synthetic_data()),
            patch.object(backend, "prepare"),
            patch.object(backend, "run", return_value=execution) as run,
            patch.object(backstep_resolution, "audit", return_value=audited),
            patch.object(
                backstep_resolution, "assess", return_value=compared
            ) as assess,
            patch.object(backstep_resolution, "save"),
        ):
            report = backstep_resolution.study(
                self.root,
                self.root / ("study-" + str(len(list(self.root.iterdir())))),
                self.root,
                preset=preset,
            )
        return report, run, assess

    def test_acceptance_requires_the_independent_audit(self):
        execution = {
            "passed": True,
            "numerical": {"passed": True},
            "execution_status": "completed",
        }
        compared = {"status": "evaluated", "passed": True, "comparison": "synthetic"}
        failing = {"status": "evaluated", "passed": False}
        report, run, assess = self.study_with(execution, failing, compared, "study")
        self.assertFalse(report["rows"][0]["accepted"])
        self.assertFalse(report["rows"][0]["passed"])
        self.assertEqual(run.call_count, 1)
        self.assertIs(assess.call_args.kwargs["independent"], failing)
        report, run, _ = self.study_with(
            execution, {**failing, "passed": True}, compared
        )
        self.assertTrue(report["rows"][0]["accepted"])
        self.assertTrue(report["passed"])

    def test_workflow_errors_stop_the_study_with_exit_one(self):
        with (
            patch.object(backstep_resolution, "load", return_value=synthetic_data()),
            patch.object(
                backend, "prepare", side_effect=OSError(28, "No space left on device")
            ),
            patch.object(backend, "run") as run,
            patch.object(
                sys,
                "argv",
                [
                    "backstep_resolution.py",
                    "--foam-root",
                    str(self.root),
                    "--data",
                    str(self.root),
                    "--output",
                    str(self.root / "study"),
                ],
            ),
            patch("builtins.print"),
        ):
            self.assertEqual(backstep_resolution.main(), 1)
        self.assertEqual(run.call_count, 0)
        report = json.loads((self.root / "study/report.json").read_text())
        self.assertFalse(report["workflow_completed"])
        self.assertIn("No space left", report["error"])

    def test_auditor_cli_separates_invalid_input_from_failed_evidence(self):
        def cli(*args):
            return subprocess.run(
                [sys.executable, str(AUDITOR), *map(str, args)],
                capture_output=True,
                text=True,
                timeout=60,
            )

        result = cli(
            "--run", self.root / "missing", "--output", self.root / "audit.json"
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        report = json.loads((self.root / "audit.json").read_text())
        self.assertEqual(report["status"], "invalid")
        self.assertNotIn(str(self.root), report["error"].split(":", 1)[0])
        result = cli(
            "--run", self.root / "missing", "--output", self.root / "audit.json"
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("CFD-E062", result.stdout)
        result = cli("--run", self.root, "--output", self.root / "absent/audit.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("CFD-E063", result.stdout)
        self.assertEqual(result.stderr, "")

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
            self.assertEqual(mesh["cells"], 48896)
            self.assertAlmostEqual(sum(mesh["volumes"]), 48.2, places=8)
            checked_wall_distances(mesh, patches(mesh, "backstep"), meta)
            # The actual spacing equals the tested blockMesh model and has no jump.
            (nu, ny, gu, gy), (nd, _, gd, _), (_, nyl, _, gyl) = parsed_blocks(
                files["system/blockMeshDict"]
            )
            centres, lengths = mesh["cell_centres"], mesh["lengths"]
            above = centres[:, 1] > 1
            row = above & (abs(centres[:, 1] - centres[above, 1].min()) < 1e-9)
            order = np.argsort(centres[row, 0])
            x_widths = lengths[row, 0][order]
            model = np.r_[4 * line_divide(nu, gu), 50 * line_divide(nd, gd)]
            np.testing.assert_allclose(x_widths, model, rtol=1e-9, atol=1e-12)
            self.assertLessEqual(neighbour_ratio(x_widths), 1.2)
            near = abs(centres[:, 0] - 6)
            column = near - near.min() < 1e-9
            order = np.argsort(centres[column, 1])
            y_widths = lengths[column, 1][order]
            model = np.r_[line_divide(nyl, gyl), 8 * line_divide(ny, gy)]
            np.testing.assert_allclose(y_widths, model, rtol=1e-9, atol=1e-12)
            self.assertLessEqual(neighbour_ratio(y_widths), 1.35)

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
