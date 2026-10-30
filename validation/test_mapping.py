#!/usr/bin/env python3
"""Synthetic receipt boundaries and actual Foundation-13 mapping tests.

The synthetic receipts and SST utility fixture are not accepted flow evidence.
Set CFD_OPENFOAM_ROOT for actual cavity/utility/initialization checks.
"""

import contextlib
import copy
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "integrations"), str(ROOT / "validation")]
import openfoam_backend as backend
import openfoam_cases as cases
import openfoam_mapping as mapping
import openfoam_restart as restart
import external_notices
import mapped_start
import mapping_equivalence
from audit_openfoam_mesh import audit, cartesian_mesh
from test_resolution import synthetic_data


def square_mesh(case, n):
    """An n x n x 1 Cartesian polyMesh on the unit square, in blockMesh cell order."""
    path = Path(case) / "constant/polyMesh"
    path.mkdir(parents=True)

    def vertex(i, j, k):
        return i + (n + 1) * (j + (n + 1) * k)

    points = [
        f"({i / n!r} {j / n!r} {k})"
        for k in [0, 1]
        for j in range(n + 1)
        for i in range(n + 1)
    ]
    internal, boundary = [], []
    for j in range(n):
        for i in range(n):
            cell = i + n * j
            v = [
                vertex(i + a, j + b, c)
                for a, b, c in [
                    (0, 0, 0),
                    (1, 0, 0),
                    (1, 1, 0),
                    (0, 1, 0),
                    (0, 0, 1),
                    (1, 0, 1),
                    (1, 1, 1),
                    (0, 1, 1),
                ]
            ]
            # Faces point out of their owner, as OpenFOAM orders them.
            if i + 1 < n:
                internal.append(([v[1], v[2], v[6], v[5]], cell, cell + 1))
            else:
                boundary.append(([v[1], v[2], v[6], v[5]], cell))
            if j + 1 < n:
                internal.append(([v[3], v[7], v[6], v[2]], cell, cell + n))
            else:
                boundary.append(([v[3], v[7], v[6], v[2]], cell))
            if i == 0:
                boundary.append(([v[0], v[4], v[7], v[3]], cell))
            if j == 0:
                boundary.append(([v[0], v[1], v[5], v[4]], cell))
            boundary.append(([v[0], v[3], v[2], v[1]], cell))
            boundary.append(([v[4], v[5], v[6], v[7]], cell))
    faces = [(f, o) for f, o, _ in internal] + boundary

    def write(name, rows):
        (path / name).write_text(
            cases.header(name) + str(len(rows)) + "\n(\n" + "\n".join(rows) + "\n)\n"
        )

    write("points", points)
    write("faces", ["4(" + " ".join(map(str, f)) + ")" for f, _ in faces])
    write("owner", [str(o) for _, o in faces])
    write("neighbour", [str(nb) for _, _, nb in internal])
    write("boundary", [])


def internal_field(template, rows, vector):
    """The template with a nonuniform internal field of the given rows."""
    cls = "vector" if vector else "scalar"
    body = "\n".join(
        "(" + " ".join(f"{v:.15g}" for v in row) + ")" if vector else f"{row:.15g}"
        for row in rows
    )
    return re.sub(
        r"internalField\s+uniform\s+[^;]+;",
        lambda _: f"internalField nonuniform List<{cls}> {len(rows)}\n(\n{body}\n);",
        template,
    )


def coarse_values(name):
    """Distinct per-cell values on the 24 x 24 source."""
    cells = np.arange(576)
    i, j = cells % 24, cells // 24
    if name == "U":
        return np.column_stack([0.001 * i + 0.1, 0.002 * j - 0.3, 0 * i])
    return 0.01 * i - 0.003 * j + 0.5


def nearest_coarse_cell():
    """The coarse cell containing each 48 x 48 target cell centre."""
    cells = np.arange(2304)
    return (cells % 48) // 2 + 24 * ((cells // 48) // 2)


def synthetic_prepared(root):
    """Receipt fixture on real-format square meshes; no solver, no physical claim."""
    root = Path(root)
    root.mkdir()
    evidence = root / mapping.EVIDENCE
    evidence.mkdir()
    source_case = evidence / "source/case"
    source_case.parent.mkdir()
    original = backend.prepare("cavity", 1, 50, source_case)
    original_bytes = (source_case / "case.json").read_bytes()
    (source_case / "case.json").unlink()
    snapshot = source_case / "2"
    snapshot.mkdir()
    for name in ["U", "p"]:
        contents = (
            (source_case / "0" / name)
            .read_text()
            .replace("object " + name + ";", "object " + name + '; location "2";')
        )
        (snapshot / name).write_text(
            internal_field(contents, coarse_values(name), name == "U")
        )
    square_mesh(source_case, 24)
    summary = {
        "case": "cavity",
        "case_sha256": mapping.digest(original_bytes),
        "case_metadata": original["metadata"],
        "execution_status": "completed",
        "passed": True,
        "numerical": {"passed": True, "final_time_directory": "2", "iterations": 2},
        "runtime": {"fixture": "synthetic"},
    }
    entries = {
        "case/" + name: entry for name, entry in backend.inventory(source_case).items()
    }
    entries["case/case.json"] = {
        "bytes": len(original_bytes),
        "sha256": mapping.digest(original_bytes),
    }
    backend.write_json(evidence / "source-summary.json", summary)
    entries["summary.json"] = restart.file_identity(evidence / "source-summary.json")
    backend.write_json(evidence / "source-manifest.json", {"files": entries})
    (evidence / "source-case.json").write_bytes(original_bytes)
    manifest_sha = backend.sha256(evidence / "source-manifest.json")
    backend.write_json(
        evidence / "source-audit.json",
        {"passed": True, "numerical_passed": True, "run_manifest_sha256": manifest_sha},
    )
    (evidence / "target").mkdir()
    template = backend.prepare("cavity", 2, 50, evidence / "templates")
    (evidence / "templates/case.json").unlink()
    backend.write_json(evidence / "target-template.json", template)
    for name in template["inputs"]:
        target = evidence / "target/case" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        contents = (evidence / "templates" / name).read_text()
        if name.startswith("0/"):
            field = name[2:]
            # The mapper's output: nearest source values, its own boundary entries.
            mapped = coarse_values(field)[nearest_coarse_cell()]
            contents = internal_field(contents, mapped, field == "U")
        target.write_text(contents)
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if name.startswith("0/"):
            contents = mapping.replace_internal(
                (evidence / "templates" / name).read_text(),
                target,
                2304,
                field == "U",
                field,
            )
        destination.write_text(contents)
    target_mesh = evidence / "target/case/constant/polyMesh"
    square_mesh(evidence / "target/case", 48)
    backend.write_json(
        evidence / "commands.json",
        [
            {
                "program": p,
                "returncode": 0,
                "arguments": ["-case", "/fixture/mapping_evidence/target/case"]
                + (
                    [
                        "/fixture/mapping_evidence/source/case",
                        "-sourceTime",
                        "2",
                        "-consistent",
                        "-mapMethod",
                        "mapNearest",
                    ]
                    if p == "mapFields"
                    else []
                ),
            }
            for p in ["blockMesh", "checkMesh", "mapFields"]
        ],
    )
    (evidence / "target/check-mesh.log").write_text("Mesh OK.\n")
    (evidence / "target/map.log").write_text(
        "Version: 13\nBuild  : 13-synthetic\nMapping method: mapNearest\ninterpolating U\ninterpolating p\n"
    )
    state = {
        "schema_version": mapping.SCHEMA,
        "method": "mapNearest_internal_only",
        "initial_flux_policy": "solver_initializes_phi_from_new_mesh_U",
        "source_level": 1,
        "source_time": "2",
        "source_iterations": 2,
        "source_manifest_sha256": manifest_sha,
        "source_case_sha256": mapping.digest(original_bytes),
        "source_fields": {n: entries["case/2/" + n] for n in ["U", "p"]},
        "runtime_sha256": restart.identity(summary["runtime"]),
        "mapper_sha256": "a" * 64,
        "limits": {"wall_s": 300, "output_mib": 512, "memory_mib": 2048},
        "preparation_wall_s": 0.1,
        "target_metadata_sha256": restart.identity(template["metadata"]),
        "target_mesh": {
            n: restart.file_identity(target_mesh / n) for n in restart.MESH_FILES
        },
        "nearest_replay": mapping.nearest_replay(evidence, "2", ["U", "p"], 576, 2304),
    }
    definition = {
        **template,
        "mesh_initialization": state,
        "inputs": backend.inventory(root),
    }
    backend.write_json(root / "case.json", definition)
    return definition


class Receipts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-mapping-unit-")
        self.root = Path(self.temp.name)
        self.case = self.root / "input"
        self.definition = synthetic_prepared(self.case)

    def tearDown(self):
        self.temp.cleanup()

    def test_known_receipt_is_consistent_but_is_not_flow_evidence(self):
        mapping.validate(self.case, self.definition)
        self.assertEqual(backend.check_prepared(self.case)["level"], 2)

    def test_generated_boundaries_and_dimensions_are_retained(self):
        template = (self.case / mapping.EVIDENCE / "templates/0/U").read_text()
        mapped = self.root / "mapped-U"
        mapped.write_text(
            template.replace(
                "internalField uniform (0 0 0)", "internalField uniform (0.2 0.3 0)"
            ).replace("type noSlip", "type zeroGradient")
        )
        result = mapping.replace_internal(template, mapped, 2304, True, "U")
        self.assertEqual(
            backend.block(result, "boundaryField"),
            backend.block(template, "boundaryField"),
        )
        self.assertIn(
            "internalField uniform (0.20000000000000001 0.29999999999999999 0)", result
        )

    def test_wrong_mapped_field_shape_class_dimensions_and_nonfinite_data_are_rejected(
        self,
    ):
        good = (self.case / mapping.EVIDENCE / "templates/0/U").read_text()
        for change in [
            lambda s: s.replace("volVectorField", "volScalarField"),
            lambda s: s.replace("[0 1 -1 0 0 0 0]", "[0 0 0 0 0 0 0]"),
            lambda s: s.replace("(0 0 0)", "(nan 0 0)", 1),
            lambda s: s.replace("(0 0 0)", "(0 0)", 1),
        ]:
            path = self.root / "mapped"
            path.write_text(change(good))
            with self.assertRaises(ValueError):
                mapping.replace_internal(good, path, 2304, True, "U")

    def test_vector_lists_must_hold_whole_vectors(self):
        path = self.root / "U"
        for internal in [
            "nonuniform List<vector> 2 ((1 2) (3 4 5 6))",
            "nonuniform List<vector> 2 (1 2 3 4 5 6)",
            "uniform (1 2)",
        ]:
            path.write_text(f"internalField {internal};\n")
            with self.assertRaisesRegex(ValueError, "CFD-X006 fields.U"):
                backend.internal_values(path, 2, True)
        path.write_text("internalField nonuniform List<scalar> 2 ((1) 2);\n")
        with self.assertRaisesRegex(ValueError, "CFD-X006 fields.U"):
            backend.internal_values(path, 2)
        path.write_text("internalField nonuniform List<vector> 2 ((1 2 3) (4 5 6));\n")
        self.assertEqual(backend.internal_values(path, 2, True), [1, 2, 3, 4, 5, 6])

    def test_negative_turbulence_is_rejected(self):
        from openfoam_cases import field

        for name, value in [("k", "-0.1"), ("nut", "-0.1"), ("omega", "0")]:
            template = field(name, "[0 0 0 0 0 0 0]", "1", {})
            path = self.root / name
            path.write_text(template.replace("uniform 1", "uniform " + value))
            with self.assertRaisesRegex(ValueError, "CFD-X014"):
                mapping.replace_internal(template, path, 2304, False, name)

    def test_resealing_an_altered_target_boundary_does_not_bypass_the_receipt(self):
        path = self.case / "0/U"
        path.write_text(path.read_text().replace("type noSlip", "type zeroGradient"))
        self.definition["inputs"]["0/U"] = restart.file_identity(path)
        backend.write_json(self.case / "case.json", self.definition)
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.inputs.0/U"):
            backend.check_prepared(self.case)

    def reseal(self):
        self.definition["inputs"] = backend.inventory(self.case)
        self.definition["inputs"].pop("case.json")
        backend.write_json(self.case / "case.json", self.definition)

    def test_consumed_fields_must_be_the_nearest_source_values(self):
        evidence = self.case / mapping.EVIDENCE
        # A cold start relabeled as mapped: template fields in the case and as the
        # "mapper output", consistently resealed.
        for name in ["U", "p"]:
            template = (evidence / "templates/0" / name).read_text()
            (evidence / "target/case/0" / name).write_text(template)
            (self.case / "0" / name).write_text(template)
        self.reseal()
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mapper.values"):
            backend.check_prepared(self.case)

    def test_one_changed_mapped_value_is_found_by_the_replay(self):
        evidence = self.case / mapping.EVIDENCE
        mapped = coarse_values("p")[nearest_coarse_cell()].copy()
        mapped[2303] = 7.0
        template = (evidence / "templates/0/p").read_text()
        (evidence / "target/case/0/p").write_text(
            internal_field(template, mapped, False)
        )
        (self.case / "0/p").write_text(
            mapping.replace_internal(
                template, evidence / "target/case/0/p", 2304, False, "p"
            )
        )
        self.reseal()
        with self.assertRaisesRegex(
            ValueError, "CFD-X014 mapping.mapper.values: 1 target cells"
        ):
            mapping.validate(self.case, self.definition)

    def test_the_mapper_must_read_this_case_s_source_copy(self):
        path = self.case / mapping.EVIDENCE / "commands.json"
        commands = json.loads(path.read_text())
        commands[2]["arguments"][2] = "/elsewhere/mapping_evidence/source/case"
        backend.write_json(path, commands)
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mapper.arguments"):
            mapping.validate(self.case, self.definition)

    def test_malformed_receipt_values_are_coded_with_their_field(self):
        for mutate, field in [
            (lambda s: s["limits"].update(wall_s=10**400), "limits"),
            (lambda s: s["limits"].update(wall_s=True), "limits"),
            (lambda s: s.update(preparation_wall_s=10**400), "preparation_wall_s"),
            (lambda s: s.pop("source_time"), "source_time: missing"),
            (lambda s: s.update(source_time="../2"), "source_time"),
            (lambda s: s.update(source_iterations=3), "source_iterations"),
            (lambda s: s.update(source_iterations=2.0), "source_iterations"),
        ]:
            definition = copy.deepcopy(self.definition)
            mutate(definition["mesh_initialization"])
            with self.assertRaisesRegex(ValueError, "CFD-X014 mapping." + field):
                mapping.validate(self.case, definition)
        definition = copy.deepcopy(self.definition)
        definition["max_iterations"] = 0
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.max_iterations"):
            mapping.validate(self.case, definition)

    def test_invalid_preparation_numbers_are_coded(self):
        for timeout in ["300", 10**400, True]:
            with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.timeout_s"):
                mapping.prepare(
                    self.root / "missing",
                    2,
                    50,
                    self.root / "unused",
                    self.root,
                    timeout_s=timeout,
                )
        self.assertFalse((self.root / "unused").exists())

    def test_a_failed_mesh_check_is_a_consistent_preserved_failure(self):
        # checkMesh exits 0 without "Mesh OK.": the run stops with its own error.
        (self.root / "check-mesh.log").write_text("Failed 1 mesh checks.\n")
        report = {
            "commands": [
                {"program": "blockMesh", "returncode": 0},
                {"program": "checkMesh", "returncode": 0},
            ],
            "runtime": {"fixture": "synthetic"},
            "execution_status": "failed",
            "error": "CFD-X006 mesh: mesh quality failed",
        }
        mapping.verify_receipt(self.case, self.definition, report)

    def test_unreadable_archive_evidence_is_coded(self):
        report = {
            "commands": [
                {"program": "checkMesh", "returncode": 0},
                {"program": "foamRun", "returncode": 0},
            ],
            "runtime": {"fixture": "synthetic"},
        }
        with self.assertRaisesRegex(
            ValueError, "CFD-X014 mapping.archive: cannot access check-mesh.log"
        ):
            mapping.verify_receipt(self.case, self.definition, report)
        (self.root / "check-mesh.log").write_bytes(b"\xff\xfe Mesh OK.")
        with self.assertRaisesRegex(
            ValueError, "CFD-X014 mapping.archive: invalid text/JSON evidence"
        ):
            mapping.verify_receipt(self.case, self.definition, report)

    def test_coarse_phi_is_never_accepted_on_the_fine_mesh(self):
        (self.case / "0/phi").write_text("coarse face flux")
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.phi"):
            mapping.validate(self.case, self.definition)

    def test_mutually_exclusive_initializations_and_bad_levels_are_rejected(self):
        for mutate, field in [
            (lambda d: d.update(initial_state={}), "receipt"),
            (lambda d: d.update(mesh_initialization=None), "receipt"),
            (lambda d: d.update(level=3), "level"),
            (lambda d: d["mesh_initialization"].update(source_level=True), "level"),
            (lambda d: d["mesh_initialization"].update(source_level=3), "level"),
            (
                lambda d: d["mesh_initialization"].update(
                    initial_flux_policy="mapped_coarse_phi"
                ),
                "phi",
            ),
        ]:
            definition = copy.deepcopy(self.definition)
            mutate(definition)
            with self.assertRaisesRegex(ValueError, "CFD-X014 mapping." + field):
                mapping.validate(self.case, definition)

    def test_source_must_be_accepted_and_audited(self):
        evidence = self.case / mapping.EVIDENCE
        path = evidence / "source-audit.json"
        record = json.loads(path.read_text())
        record["passed"] = False
        backend.write_json(path, record)
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.source.audit"):
            mapping.validate(self.case, self.definition)

    def test_snapshot_time_mesh_and_mapper_log_are_bound(self):
        evidence = self.case / mapping.EVIDENCE
        path = evidence / "target/map.log"
        old = path.read_text()
        path.write_text(old.replace("interpolating p", "interpolating q"))
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mapper.fields"):
            mapping.validate(self.case, self.definition)
        path.write_text(old)
        path = evidence / "target/case/constant/polyMesh/points"
        path.write_text("changed mesh")
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mesh.points"):
            mapping.validate(self.case, self.definition)

    def test_target_controls_cannot_be_changed_with_the_templates(self):
        path = self.case / "system/controlDict"
        changed = path.read_text().replace("deltaT 1;", "deltaT 2;")
        path.write_text(changed)
        (self.case / mapping.EVIDENCE / "templates/system/controlDict").write_text(
            changed
        )
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.target.controls"):
            mapping.validate(self.case, self.definition)

    def test_mapper_method_and_source_time_cannot_be_relabeled(self):
        path = self.case / mapping.EVIDENCE / "commands.json"
        original = json.loads(path.read_text())
        for index, value in [(4, "0"), (7, "interpolate")]:
            changed = copy.deepcopy(original)
            changed[2]["arguments"][index] = value
            backend.write_json(path, changed)
            with self.assertRaisesRegex(
                ValueError, "CFD-X014 mapping.mapper.arguments"
            ):
                mapping.validate(self.case, self.definition)

    def test_invalid_limits_fail_before_claiming_an_output(self):
        for kwargs, field in [
            ({"level": 1}, "level"),
            ({"level": True}, "level"),
            ({"iterations": 1}, "iterations"),
            ({"iterations": 5000.0}, "iterations"),
            ({"timeout_s": 0}, "timeout_s"),
            ({"timeout_s": float("nan")}, "timeout_s"),
            ({"timeout_s": 3601}, "timeout_s"),
            ({"output_mib": 0}, "limits"),
            ({"output_mib": 4096}, "limits"),
            ({"memory_mib": 128}, "limits"),
            ({"memory_mib": 2048.0}, "limits"),
        ]:
            args = {
                "source": self.root / "missing",
                "level": 2,
                "iterations": 50,
                "output": self.root / "unused",
                "foam_root": self.root,
                **kwargs,
            }
            with self.assertRaisesRegex(ValueError, "CFD-X014 mapping." + field):
                mapping.prepare(**args)
        self.assertFalse((self.root / "unused").exists())

    def test_a_solved_case_cannot_omit_runtime_or_mesh_checks(self):
        report = {
            "commands": [{"program": "foamRun", "returncode": 0}],
            "execution_status": "completed",
        }
        with self.assertRaisesRegex(
            ValueError, "CFD-X014 mapping.runtime: solved case lacks runtime"
        ):
            mapping.verify_receipt(self.case, self.definition, report)
        report["runtime"] = {"fixture": "synthetic"}
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mesh"):
            mapping.verify_receipt(self.case, self.definition, report)

    def test_a_stopped_experiment_is_evidence_not_an_input_error(self):
        failed = {
            "passed": False,
            "execution_status": "timeout",
            "error": "CFD-X004 execution.deadline: fixture",
        }
        with (
            patch.object(backend, "prepare"),
            patch.object(backend, "run", return_value=failed),
        ):
            report = mapping_equivalence.experiment(
                self.root, self.root / "stopped", 60
            )
        self.assertFalse(report["passed"])
        self.assertNotIn("error", report)
        self.assertIn("CFD-X004", report["stop_reason"])


class Tampering(unittest.TestCase):
    """Each receipt and evidence check, by the one change it must reject.

    Every change is resealed consistently (inventories, manifests and recorded
    identities), so only the check under test can reject it.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-mapping-tamper-")
        self.root = Path(self.temp.name)
        self.case = self.root / "input"
        self.definition = synthetic_prepared(self.case)
        self.evidence = self.case / mapping.EVIDENCE
        self.state = self.definition["mesh_initialization"]

    def tearDown(self):
        self.temp.cleanup()

    def fresh(self):
        self.tearDown()
        self.setUp()

    def json(self, name):
        return json.loads((self.evidence / name).read_text())

    def reseal_inputs(self):
        self.definition["inputs"] = {
            k: v for k, v in backend.inventory(self.case).items() if k != "case.json"
        }
        backend.write_json(self.case / "case.json", self.definition)

    def reseal_source(self, case=None, summary=None, audit=None):
        """Edit the stored source case/summary/audit and recompute their chain."""
        original = self.json("source-case.json")
        if case:
            case(original)
        (self.evidence / "source-case.json").write_text(json.dumps(original))
        record = self.json("source-summary.json")
        record["case_sha256"] = backend.sha256(self.evidence / "source-case.json")
        if summary:
            summary(record)
        backend.write_json(self.evidence / "source-summary.json", record)
        files = {
            "case/" + n: e
            for n, e in backend.inventory(self.evidence / "source/case").items()
        }
        files["case/case.json"] = restart.file_identity(
            self.evidence / "source-case.json"
        )
        files["summary.json"] = restart.file_identity(
            self.evidence / "source-summary.json"
        )
        backend.write_json(self.evidence / "source-manifest.json", {"files": files})
        manifest = backend.sha256(self.evidence / "source-manifest.json")
        self.state["source_manifest_sha256"] = manifest
        self.state["source_case_sha256"] = files["case/case.json"]["sha256"]
        self.state["source_fields"] = {n: files["case/2/" + n] for n in ["U", "p"]}
        found = self.json("source-audit.json")
        found["run_manifest_sha256"] = manifest
        if audit:
            audit(found)
        backend.write_json(self.evidence / "source-audit.json", found)
        self.reseal_inputs()

    def edit(self, name, old, new):
        path = self.evidence / name
        contents = path.read_text()
        self.assertEqual(contents.count(old), 1, (name, old))
        path.write_text(contents.replace(old, new))

    def commands(self, change):
        records = self.json("commands.json")
        change(records)
        backend.write_json(self.evidence / "commands.json", records)

    def rejected(self, field):
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping." + re.escape(field)):
            mapping.validate(self.case, self.definition)

    def test_the_fixture_is_consistent(self):
        mapping.validate(self.case, self.definition)
        self.reseal_source()
        mapping.validate(self.case, self.definition)

    def test_receipt_values(self):
        for change, field in [
            (lambda s: s["limits"].update(wall_s=0), "limits"),
            (lambda s: s["limits"].update(output_mib=0), "limits"),
            (lambda s: s["limits"].update(output_mib=512.0), "limits"),
            (lambda s: s["limits"].update(memory_mib=8193), "limits"),
            (lambda s: s.update(preparation_wall_s=-1), "preparation_wall_s"),
            (
                lambda s: s.update(schema_version="cfd-craft.other/0.2"),
                "schema_version",
            ),
            (lambda s: s.update(method="interpolate"), "schema_version"),
            (lambda s: s.update(target_metadata_sha256="0" * 64), "target_metadata"),
            (lambda s: s.update(source_case_sha256="0" * 64), "source.case"),
            (lambda s: s["source_fields"].pop("p"), "receipt"),
            (lambda s: s["target_mesh"].pop("faces"), "receipt"),
            (
                lambda s: s["source_fields"].update(U=s["source_fields"]["p"]),
                "source.fields.U",
            ),
            (lambda s: s.update(mapper_sha256="0" * 63), "mapper.identity"),
            (lambda s: s.update(source_time="3"), "source.acceptance"),
        ]:
            saved = copy.deepcopy(self.state)
            change(self.state)
            self.rejected(field)
            self.state.clear()
            self.state.update(saved)

    def test_definition_values(self):
        for change, field in [
            (lambda d: d.update(generator_sha256="0" * 64), "source.generator"),
            (
                lambda d: d["inputs"].update({"system/extra": d["inputs"]["0/U"]}),
                "inputs",
            ),
        ]:
            saved = copy.deepcopy(self.definition)
            change(self.definition)
            self.rejected(field)
            self.definition = saved
            self.state = saved["mesh_initialization"]
        self.definition["mesh_initialization"]["source_level"] = 2
        self.definition["level"] = 3
        self.definition["mesh_initialization"]["target_metadata_sha256"] = (
            restart.identity(self.definition["metadata"])
        )
        self.rejected("source.metadata")

    def test_source_chain(self):
        for kwargs, field in [
            ({"case": lambda c: c.update(level=2)}, "source.metadata"),
            ({"case": lambda c: c.update(kind="backstep")}, "source.metadata"),
            ({"summary": lambda s: s.update(case_metadata={})}, "source.metadata"),
            ({"case": lambda c: c.update(initial_state={})}, "source.initialization"),
            (
                {"case": lambda c: c.update(mesh_initialization={})},
                "source.initialization",
            ),
            ({"summary": lambda s: s.update(passed=False)}, "source.acceptance"),
            (
                {"summary": lambda s: s.update(execution_status="timeout")},
                "source.acceptance",
            ),
            (
                {"summary": lambda s: s["numerical"].update(passed=False)},
                "source.acceptance",
            ),
            (
                {"summary": lambda s: s["numerical"].update(final_time_directory="3")},
                "source.acceptance",
            ),
            (
                {"summary": lambda s: s["numerical"].update(iterations=3)},
                "source_iterations",
            ),
            ({"audit": lambda a: a.update(passed=False)}, "source.audit"),
            ({"audit": lambda a: a.update(numerical_passed=False)}, "source.audit"),
            (
                {"audit": lambda a: a.update(run_manifest_sha256="0" * 64)},
                "source.audit",
            ),
            ({"summary": lambda s: s.update(runtime={"other": 1})}, "source.runtime"),
        ]:
            self.fresh()
            self.reseal_source(**kwargs)
            self.rejected(field)

    def test_source_files(self):
        for name, field in [
            ("source-manifest.json", "source.manifest"),
            ("source-summary.json", "source.summary"),
            ("source-case.json", "source.case"),
        ]:
            self.fresh()
            with (self.evidence / name).open("a") as stream:
                stream.write("\n")
            self.rejected(field)
        for name, field in [
            ("source/case/system/fvSchemes", "source.inputs.system/fvSchemes"),
            ("source/case/constant/polyMesh/points", "source.mesh.points"),
            ("source/case/2/U", "source.fields.U"),
        ]:
            self.fresh()
            with (self.evidence / name).open("a") as stream:
                stream.write("// changed\n")
            self.rejected(field)
        # A snapshot relabeled with another time, its identities resealed.
        self.fresh()
        self.edit("source/case/2/p", 'location "2";', 'location "3";')
        self.reseal_source()
        self.rejected("source.fields.p")

    def test_commands_and_logs(self):
        for change, field in [
            (lambda r: r.reverse(), "commands"),
            (lambda r: r[1].update(returncode=1), "commands"),
            (
                lambda r: r[2]["arguments"].append("-noFunctionObjects"),
                "mapper.arguments",
            ),
            (lambda r: r[2]["arguments"].__setitem__(0, "-region"), "mapper.arguments"),
            (
                lambda r: r[2]["arguments"].__setitem__(5, "-parallelSource"),
                "mapper.arguments",
            ),
            (
                lambda r: r[2]["arguments"].__setitem__(
                    1, "/fixture/other/target/case"
                ),
                "mapper.arguments",
            ),
            (
                lambda r: r[0]["arguments"].__setitem__(1, "/elsewhere/case"),
                "mapper.arguments",
            ),
        ]:
            self.fresh()
            self.commands(change)
            self.rejected(field)
        for name, old, new, field in [
            ("target/check-mesh.log", "Mesh OK.", "Failed 1 mesh checks.", "mesh"),
            (
                "target/map.log",
                "Mapping method: mapNearest",
                "Mapping method: cellVolumeWeight",
                "mapper.method",
            ),
            ("target/map.log", "Version: 13", "Version: 12", "mapper"),
            ("target/map.log", "Build  : 13-", "Build  : 12-", "mapper"),
        ]:
            self.fresh()
            self.edit(name, old, new)
            self.rejected(field)

    def test_templates_and_prepared_inputs(self):
        record = self.json("target-template.json")
        record["inputs"]["system/fvSolution"] = record["inputs"]["system/fvSchemes"]
        backend.write_json(self.evidence / "target-template.json", record)
        self.rejected("target.recipe.system/fvSolution")
        for key, value in [
            ("max_iterations", 60),
            ("level", 3),
            ("kind", "backstep"),
            ("metadata", {}),
        ]:
            self.fresh()
            record = self.json("target-template.json")
            record[key] = value
            backend.write_json(self.evidence / "target-template.json", record)
            self.rejected("target.template")
        self.fresh()
        with (self.evidence / "templates/system/blockMeshDict").open("a") as stream:
            stream.write("// changed\n")
        self.rejected("templates.system/blockMeshDict")
        self.fresh()
        with (self.case / "system/blockMeshDict").open("a") as stream:
            stream.write("// changed\n")
        self.reseal_inputs()
        self.rejected("inputs.system/blockMeshDict")
        # A non-text template, recorded consistently, is a coded error.
        self.fresh()
        path = self.evidence / "templates/0/p"
        path.write_bytes(path.read_bytes().replace(b"FoamFile", b"Foam\xffFile", 1))
        record = self.json("target-template.json")
        record["inputs"]["0/p"] = restart.file_identity(path)
        backend.write_json(self.evidence / "target-template.json", record)
        self.rejected("0/p: non-text input")
        # An extra template field that the recipe does not have.
        self.fresh()
        for directory in [self.evidence / "templates", self.case]:
            (directory / "0/T").write_text((directory / "0/p").read_text())
        record = self.json("target-template.json")
        record["inputs"]["0/T"] = restart.file_identity(self.evidence / "templates/0/T")
        backend.write_json(self.evidence / "target-template.json", record)
        self.reseal_inputs()
        self.rejected("fields")

    def test_replace_internal_checks_the_mapped_header(self):
        template = (self.evidence / "templates/0/p").read_text()
        mapped = self.evidence / "target/case/0/p"
        good = mapped.read_text()
        for old, new in [
            ("object p;", "object q;"),
            ("class volScalarField;", "class volVectorField;"),
            ("[0 2 -2 0 0 0 0]", "[0 2 -1 0 0 0 0]"),
        ]:
            self.assertEqual(good.count(old), 1, old)
            mapped.write_text(good.replace(old, new))
            with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.p.header"):
                mapping.replace_internal(template, mapped, 2304, False, "p")
        mapped.write_text(good)
        twice = template + "\ninternalField uniform 0;\n"
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.p: expected one"):
            mapping.replace_internal(twice, mapped, 2304, False, "p")

    def remap(self, choose):
        """Mapped values taken per target cell from the coarse cell `choose` picks."""
        from scipy.spatial import cKDTree

        coarse = cartesian_mesh(self.evidence / "source/case")
        fine = cartesian_mesh(self.evidence / "target/case")
        _, index = cKDTree(coarse["cell_centres"]).query(fine["cell_centres"], k=4)
        for name in ["U", "p"]:
            source = coarse_values(name)
            rows = source[[choose(name, cell, index[cell]) for cell in range(2304)]]
            template = (self.evidence / "templates/0" / name).read_text()
            mapped = self.evidence / "target/case/0" / name
            mapped.write_text(internal_field(template, rows, name == "U"))
            (self.case / "0" / name).write_text(
                mapping.replace_internal(template, mapped, 2304, name == "U", name)
            )
        self.state["nearest_replay"] = mapping.nearest_replay(
            self.evidence, "2", ["U", "p"], 576, 2304
        )
        self.reseal_inputs()

    def test_a_nearby_source_cell_is_accepted_when_every_field_agrees(self):
        # Target cell 0 takes all its values from its second-nearest source cell.
        self.remap(lambda name, cell, near: near[1] if cell == 0 else near[0])
        mapping.validate(self.case, self.definition)
        replay = self.state["nearest_replay"]
        self.assertEqual(
            (replay["nearest_source"], replay["other_candidate"]), (2303, 1)
        )
        self.assertEqual(replay["maximum_rank"], 2)
        # Different source cells for different fields of one target cell: rejected.
        self.fresh()
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mapper.values: 1 "):
            self.remap(
                lambda name, cell, near: (
                    near[1] if cell == 0 and name == "p" else near[0]
                )
            )

    def test_replay_statistics_are_part_of_the_receipt(self):
        self.state["nearest_replay"]["nearest_source"] -= 1
        self.rejected("mapper.replay")

    def test_the_replay_meshes_must_have_the_recorded_cells(self):
        target = self.evidence / "target/case"
        shutil.rmtree(target / "constant/polyMesh")
        square_mesh(target, 40)
        self.state["target_mesh"] = {
            n: restart.file_identity(target / "constant/polyMesh" / n)
            for n in restart.MESH_FILES
        }
        self.reseal_inputs()
        self.rejected("mesh.cells")

    def test_archive_receipt(self):
        mesh = self.case / "constant/polyMesh"
        shutil.copytree(self.evidence / "target/case/constant/polyMesh", mesh)
        (self.root / "check-mesh.log").write_text("Mesh OK.\n")
        solved = {
            "commands": [
                {"program": "checkMesh", "returncode": 0},
                {"program": "foamRun", "returncode": 0},
            ],
            "runtime": {"fixture": "synthetic"},
            "execution_status": "completed",
        }
        mapping.verify_receipt(self.case, self.definition, solved)
        for change, field in [
            (lambda r: r.update(runtime={"other": 1}), "runtime"),
            (lambda r: r["commands"][0].update(returncode=1), "mesh"),
        ]:
            report = copy.deepcopy(solved)
            change(report)
            with self.assertRaisesRegex(ValueError, "CFD-X014 mapping." + field):
                mapping.verify_receipt(self.case, self.definition, report)
        (self.root / "check-mesh.log").write_text("Failed 1 mesh checks.\n")
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mesh"):
            mapping.verify_receipt(self.case, self.definition, solved)
        (self.root / "check-mesh.log").write_text("Mesh OK.\n")
        with (mesh / "points").open("a") as stream:
            stream.write("\n")
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mesh.points"):
            mapping.verify_receipt(self.case, self.definition, solved)
        # Unsolved: a mismatch must be the recorded failure, and nothing else.
        failed = {
            "commands": [{"program": "checkMesh", "returncode": 0}],
            "runtime": {"fixture": "synthetic"},
            "execution_status": "failed",
            "error": "CFD-X014 mapping.mesh.points: rebuilt target mesh differs from mapping mesh",
        }
        mapping.verify_receipt(self.case, self.definition, failed)
        for change in [
            lambda r: r.update(error="CFD-X003 execution.solve: exit 1"),
            lambda r: r.update(execution_status="timeout"),
        ]:
            report = copy.deepcopy(failed)
            change(report)
            with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.archive"):
                mapping.verify_receipt(self.case, self.definition, report)
        # The archive check reruns the full receipt validation.
        self.edit("target/map.log", "interpolating p", "interpolating q")
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mapper.fields"):
            mapping.verify_receipt(self.case, self.definition, failed)


def source_archive(root):
    """A sealed-looking accepted cavity run: real-format files, no solver output."""
    run = Path(root)
    case = run / "case"
    case.parent.mkdir(parents=True, exist_ok=True)
    definition = backend.prepare("cavity", 1, 50, case)
    snapshot = case / "2"
    snapshot.mkdir()
    for name in ["U", "p"]:
        template = (case / "0" / name).read_text()
        (snapshot / name).write_text(
            internal_field(
                template.replace(
                    "object " + name + ";", "object " + name + '; location "2";'
                ),
                coarse_values(name),
                name == "U",
            )
        )
    square_mesh(case, 24)
    runtime = {"fixture": "offline runtime"}
    summary = {
        "case": "cavity",
        "case_sha256": backend.sha256(case / "case.json"),
        "case_metadata": definition["metadata"],
        "execution_status": "completed",
        "passed": True,
        "numerical": {"passed": True, "final_time_directory": "2", "iterations": 2},
        "runtime": runtime,
    }
    backend.write_json(run / "summary.json", summary)
    files = {"case/" + n: e for n, e in backend.inventory(case).items()}
    files["summary.json"] = restart.file_identity(run / "summary.json")
    backend.write_json(run / "manifest.json", {"files": files})
    return summary


class OfflinePreparation(unittest.TestCase):
    """prepare() end to end with stand-ins for the runtime and its utilities.

    The stand-in mapper writes nearest-cell values on real-format meshes; this
    tests the workflow, receipt and replay, not Foundation 13.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-mapping-offline-")
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.summary = source_archive(self.source)
        self.foam = self.root / "foam"
        self.mapper = self.foam / "platforms/linux64GccDPInt32Opt/bin/mapFields"
        self.mapper.parent.mkdir(parents=True)
        self.mapper.write_text("stand-in mapper\n")
        self.mapped_values = {}
        self.on_map = None
        self.fail_label = None

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, command, env, output, label, *args):
        if label == self.fail_label:
            raise PermissionError(13, "Permission denied", str(command[0]))
        target = Path(command[2])
        output = Path(output)
        if label == "mesh":
            square_mesh(target, 48)
        elif label == "check-mesh":
            (output / "check-mesh.log").write_text("Mesh OK.\n")
        elif label == "map":
            for name in ["U", "p"]:
                path = target / "0" / name
                values = self.mapped_values.get(
                    name, coarse_values(name)[nearest_coarse_cell()]
                )
                path.write_text(internal_field(path.read_text(), values, name == "U"))
            (output / "map.log").write_text(
                "Version: 13\nBuild  : 13-offline\nMapping method: mapNearest\n"
                "interpolating U\ninterpolating p\n"
            )
            if self.on_map:
                self.on_map()
        else:
            raise AssertionError(label)
        return {
            "program": Path(command[0]).name,
            "arguments": command[1:],
            "returncode": 0,
        }

    def prepare(
        self,
        output,
        stop=None,
        parent=None,
        audit=None,
        runtime=None,
        level=2,
        **kwargs,
    ):
        parent = parent or {**self.summary, "passed": True}
        manifest = backend.sha256(self.source / "manifest.json")
        binaries = {n: self.foam / n for n in ["blockMesh", "checkMesh", "foamRun"]}
        verify = parent if callable(parent) else (lambda run: parent)
        with (
            patch.object(backend, "verify", side_effect=verify),
            patch(
                "audit_openfoam_mesh.audit",
                return_value=audit
                or {
                    "passed": True,
                    "numerical_passed": True,
                    "run_manifest_sha256": manifest,
                },
            ),
            patch.object(
                backend,
                "runtime",
                return_value=(binaries, {}, runtime or self.summary["runtime"]),
            ),
            patch.object(backend, "execute", side_effect=self.execute),
        ):
            return mapping.prepare(
                self.source, level, 50, output, self.foam, stop=stop, **kwargs
            )

    def reseal(self, case=None, files=None):
        """Edit the source case (record and/or files) and reseal its archive."""
        path = self.source / "case/case.json"
        definition = json.loads(path.read_text())
        if files:
            files(self.source / "case")
        definition["inputs"] = {
            name: restart.file_identity(self.source / "case" / name)
            for name in definition["inputs"]
        }
        if case:
            case(definition)
        backend.write_json(path, definition)
        self.summary["case_sha256"] = backend.sha256(path)
        backend.write_json(self.source / "summary.json", self.summary)
        entries = {
            "case/" + n: e for n, e in backend.inventory(self.source / "case").items()
        }
        entries["summary.json"] = restart.file_identity(self.source / "summary.json")
        backend.write_json(self.source / "manifest.json", {"files": entries})

    def rejected(self, field, output="mapped", created=False, **kwargs):
        output = self.root / output
        with self.assertRaisesRegex(
            ValueError, "CFD-X014 mapping." + re.escape(field)
        ) as raised:
            self.prepare(output, **kwargs)
        self.assertFalse((output / "case.json").exists())
        self.assertEqual(output.exists(), created, field)
        if created:
            failure = json.loads((output / "mapping-failure.json").read_text())
            self.assertEqual(failure["error"], str(raised.exception))

    def test_source_eligibility_is_checked_before_an_output_is_claimed(self):
        self.rejected("source.acceptance", parent={**self.summary, "passed": False})
        self.rejected(
            "source.acceptance",
            parent={**self.summary, "passed": True, "execution_status": "timeout"},
        )
        self.rejected("source.level", level=3)
        self.rejected(
            "source.audit",
            audit={"passed": False, "numerical_passed": True},
        )
        self.rejected(
            "source.audit",
            audit={"passed": True, "numerical_passed": False},
        )
        self.rejected("runtime", runtime={"fixture": "another runtime"})
        self.mapper.unlink()
        self.rejected("mapper")

    def test_the_source_record_must_be_a_current_cold_recipe(self):
        for case, files, field in [
            (lambda d: d.update(initial_state={}), None, "source.initialization"),
            (lambda d: d.update(mesh_initialization={}), None, "source.initialization"),
            (lambda d: d.update(generator_sha256="0" * 64), None, "source.level"),
            (lambda d: d.update(kind="backstep"), None, "data"),
            (lambda d: d["metadata"].update(lid_speed_m_s=2.0), None, "source.recipe"),
            (
                lambda d: d["inputs"].update({"system/extra": d["inputs"]["0/p"]}),
                lambda c: (c / "system/extra").write_text((c / "0/p").read_text()),
                "source.recipe",
            ),
            (
                None,
                lambda c: (c / "system/fvSchemes").write_text(
                    (c / "system/fvSchemes").read_text() + "// changed\n"
                ),
                "source.recipe.system/fvSchemes",
            ),
        ]:
            self.tearDown()
            self.setUp()
            self.reseal(case, files)
            self.rejected(field)

    def test_source_bytes_are_checked_when_read_and_when_copied(self):
        def moved(run):
            # The archive changes after its bytes were read: verify sees another one.
            with (self.source / "manifest.json").open("a") as stream:
                stream.write("\n")
            return {**self.summary, "passed": True}

        self.rejected("source.manifest", parent=moved)
        for name, field, created in [
            ("case/case.json", "source.case", False),
            ("case/2/U", "source.2/U", True),
            ("case/constant/polyMesh/owner", "source.constant/polyMesh/owner", True),
            ("summary.json", "source.summary", True),
        ]:
            self.tearDown()
            self.setUp()
            with (self.source / name).open("a") as stream:
                stream.write("\n")
            self.rejected(field, created=created)

    def test_utility_and_budget_failures_leave_only_failure_evidence(self):
        real = self.execute

        def failed_mesh(command, env, output, label, *args):
            record = real(command, env, output, label, *args)
            if label == "check-mesh":
                (Path(output) / "check-mesh.log").write_text("Failed 1 mesh checks.\n")
            return record

        self.execute = failed_mesh
        self.rejected("mesh", created=True)
        ran = json.loads(
            (self.root / "mapped" / mapping.EVIDENCE / "commands.json").read_text()
        )
        self.assertEqual([r["program"] for r in ran], ["blockMesh", "checkMesh"])

        def large_mesh(command, env, output, label, *args):
            record = real(command, env, output, label, *args)
            if label == "mesh":
                (Path(output) / "mesh-output.log").write_bytes(b"x" * 2 * 1024**2)
            return record

        # The budget is checked before each utility, not only at the end.
        self.execute = large_mesh
        self.rejected("output", output="early", created=True, output_mib=1)
        ran = json.loads(
            (self.root / "early" / mapping.EVIDENCE / "commands.json").read_text()
        )
        self.assertEqual([r["program"] for r in ran], ["blockMesh"])
        self.execute = real
        self.on_map = lambda: self.mapper.write_text("another mapper\n")
        self.rejected("mapper.identity", output="changed", created=True)
        self.on_map = lambda: (
            self.root / "small" / mapping.EVIDENCE / "target/map-output.log"
        ).write_bytes(b"x" * 2 * 1024**2)
        self.rejected("output", output="small", created=True, output_mib=1)

    def test_preparation_records_the_source_work_and_replays_nearest_cells(self):
        definition = self.prepare(self.root / "mapped")
        state = definition["mesh_initialization"]
        self.assertEqual(state["schema_version"], "cfd-craft.mesh-initialization/0.2")
        self.assertEqual(state["source_iterations"], 2)
        mapping.validate(self.root / "mapped", definition)
        values = backend.internal_values(self.root / "mapped/0/p", 2304)
        coarse = backend.internal_values(self.source / "case/2/p", 576)
        np.testing.assert_array_equal(values, np.array(coarse)[nearest_coarse_cell()])

    def test_a_mapper_output_that_is_not_nearest_cell_leaves_no_runnable_case(self):
        wrong = coarse_values("p")[nearest_coarse_cell()].copy()
        wrong[100] += 1e-3
        self.mapped_values["p"] = wrong
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mapper.values"):
            self.prepare(self.root / "mapped")
        self.assertFalse((self.root / "mapped/case.json").exists())
        failure = json.loads((self.root / "mapped/mapping-failure.json").read_text())
        self.assertIn("mapping.mapper.values: 1 target cells", failure["error"])

    def test_cancellation_after_the_mapper_leaves_no_runnable_case(self):
        stop = backend.Stop()
        self.on_map = lambda: setattr(stop, "cancelled", True)
        with self.assertRaisesRegex(ValueError, "CFD-X008") as raised:
            self.prepare(self.root / "mapped", stop)
        self.assertFalse((self.root / "mapped/case.json").exists())
        failure = json.loads((self.root / "mapped/mapping-failure.json").read_text())
        self.assertEqual(failure["error"], str(raised.exception))

    def test_the_failure_record_states_the_raised_coded_error(self):
        self.fail_label = "check-mesh"
        with self.assertRaises(ValueError) as raised:
            self.prepare(self.root / "mapped")
        self.assertEqual(
            str(raised.exception), "CFD-X014 mapping.inputs: cannot access checkMesh"
        )
        failure = json.loads((self.root / "mapped/mapping-failure.json").read_text())
        self.assertEqual(failure["error"], str(raised.exception))


class Reports(unittest.TestCase):
    """The experiment drivers and their notices, with mocked runs."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-mapping-reports-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_the_ghia_error_reads_the_checked_sample_columns(self):
        path = self.root / "run/case/postProcessing/sampleProfiles/7/centerline.xy"
        path.parent.mkdir(parents=True)
        path.write_text("# y U_y U_x U_z\n0.5 0 0.1 0\n")
        record = {"numerical": {"final_time_directory": "7"}}
        with self.assertRaisesRegex(ValueError, "samples.centerline.columns"):
            mapping_equivalence.ghia(self.root / "run", record)
        path.write_text("# y U_x U_y U_z\n0.5 -0.2 0 0\n")
        found = mapping_equivalence.ghia(self.root / "run", record)
        reference = np.loadtxt(
            ROOT / "validation/ghia-re100-u.csv", delimiter=",", skiprows=1
        )
        predicted = np.interp(reference[:, 0], [0, 0.5, 1], [0, -0.2, 1])
        self.assertAlmostEqual(
            found["maximum_centerline_error"],
            max(abs(predicted - reference[:, 1])),
            places=12,
        )

    def cavity_experiment(self, differences=None, audits=True, ghia=True):
        passed = {
            "passed": True,
            "execution_status": "completed",
            "numerical": {"final_time_directory": "9"},
        }
        before = signal.getsignal(signal.SIGTERM)
        with (
            patch.object(backend, "prepare"),
            patch.object(mapping, "prepare"),
            patch.object(backend, "run", return_value=passed),
            patch.object(backend, "verify"),
            patch.object(
                mapping_equivalence,
                "same_recipe",
                return_value=("cavity", {"cells": 4}),
            ),
            patch.object(
                mapping_equivalence,
                "field_differences",
                return_value=differences
                or {"U": {"maximum_absolute": 1e-4}, "p": {"maximum_absolute": 0.0}},
            ),
            patch.object(mapping_equivalence, "audit", return_value={"passed": audits}),
            patch.object(
                mapping_equivalence,
                "ghia",
                return_value={"maximum_centerline_error": 0.01, "passed": ghia},
            ),
        ):
            report = mapping_equivalence.experiment(
                self.root, self.root / f"cavity-{len(list(self.root.iterdir()))}", 60
            )
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)
        return report

    def test_the_cavity_experiment_requires_every_declared_check(self):
        self.assertTrue(self.cavity_experiment()["passed"])
        for kwargs in [
            {"differences": {"U": {"maximum_absolute": 1.01e-4}}},
            {"differences": {"p": {"maximum_absolute": 2e-4}}},
            {"audits": False},
            {"ghia": False},
        ]:
            report = self.cavity_experiment(**kwargs)
            self.assertFalse(report["passed"], kwargs)
            self.assertNotIn("error", report)
        with self.assertRaisesRegex(ValueError, "mapping_experiment.timeout_s"):
            mapping_equivalence.experiment(self.root, self.root / "never", 0)
        self.assertFalse((self.root / "never").exists())

    def test_prepare_mapped_is_wired_to_the_command_line(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "integrations/openfoam_backend.py"),
                "prepare-mapped",
                "--source",
                str(self.root / "missing"),
                "--level",
                "2",
                "--iterations",
                "60",
                "--foam-root",
                str(self.root),
                "--output",
                str(self.root / "unused"),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            "CFD-X014 mapping.inputs: cannot access manifest.json", result.stdout
        )
        self.assertFalse((self.root / "unused").exists())

    def test_failing_tests_become_error_annotations(self):
        script = self.root / "test_fixture.py"
        script.write_text(
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        pass\n"
            "    def test_bad(self):\n"
            "        self.assertEqual(1, 2, 'one: two')\n"
            "unittest.main()\n"
        )
        result = subprocess.run(
            [sys.executable, str(ROOT / "validation/unittest_notices.py"), str(script)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 1)
        errors = [x for x in result.stdout.splitlines() if x.startswith("::error")]
        self.assertEqual(len(errors), 1, result.stdout)
        self.assertIn("title=FAIL __main__.T.test_bad::", errors[0])
        self.assertIn("AssertionError: 1 != 2 : one: two", errors[0])

    def test_the_cavity_experiment_exit_codes(self):
        for report, code in [
            ({"passed": True}, 0),
            ({"passed": False, "error": "CFD-X006 archive.progress: x"}, 1),
            ({"passed": False, "stop_reason": "mapped: gate not reached"}, 2),
        ]:
            with (
                patch.object(mapping_equivalence, "experiment", return_value=report),
                patch.object(sys, "argv", ["x", "--foam-root", "r", "--output", "o"]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(mapping_equivalence.main(), code)

    def mapped_start(self, prepare=None):
        source = self.root / "source"
        (source / "case").mkdir(parents=True)
        metadata = {"mesh_family": "wall-resolved", "solver_profile": "simplec"}
        (source / "case/case.json").write_text(
            json.dumps({"level": 1, "metadata": metadata})
        )
        (source / "manifest.json").write_text("{}")
        parent = {"case": "backstep", "passed": True, "numerical": {"iterations": 9}}
        returned = {
            "execution_status": "completed",
            "passed": False,
            "case": "backstep",
            "numerical": {
                "iterations": 50,
                "solver_reported_convergence": False,
                "initial_residuals_final_iteration": {"p": 1e-3},
                "residual_trend": {"p": {"median_last_window": 1e-3}},
            },
        }

        def verify(run):
            if Path(run) == source:
                return parent
            (Path(run) / "manifest.json").write_text("{}")
            return returned

        def run(prepared, output, *args, **kwargs):
            Path(output).mkdir()
            return {"wall_s": 1.0}

        independent = {
            "passed": True,
            "local_continuity": {"maximum_abs_divergence_h_over_u": 1e-9},
            "wall_resolution": {"patches": {"stepWall": {"maximum_y_plus": 1.2}}},
        }
        assessed = {
            "measurement_screen_passed": None,
            "reattachment": {"predicted_x_over_h": 6.6},
            "skin_friction": {"rmse": 4e-4},
            "profiles": {"1": {"rmse_u_ref": 0.05}},
        }
        with (
            patch.object(backend, "verify", side_effect=verify),
            patch.object(mapping, "prepare", side_effect=prepare),
            patch.object(backend, "prepare") as cold,
            patch.object(backend, "run", side_effect=run) as runs,
            patch("audit_openfoam_mesh.audit", return_value=independent),
            patch("compare_backstep.assess", return_value=assessed),
        ):
            report = mapped_start.experiment(
                source, 50, self.root, self.root / "out", "data", 60
            )
        return report, cold, runs

    def test_the_mapped_start_reports_both_runs_at_equal_limits(self):
        report, cold, runs = self.mapped_start()
        self.assertTrue(report["workflow_completed"])
        self.assertEqual(set(report["runs"]), {"mapped", "cold"})
        self.assertEqual(
            cold.call_args.args[1:3] + cold.call_args.args[4:],
            (2, 50, "data", "wall-resolved", "simplec"),
        )
        for call in runs.call_args_list:
            self.assertEqual(call.kwargs["timeout_s"], 60)
            self.assertEqual(call.kwargs["output_mib"], 1024)
        mapped = report["runs"]["mapped"]
        self.assertEqual(mapped["audit"]["maximum_y_plus"], {"stepWall": 1.2})
        self.assertEqual(mapped["final_iterate_metrics"]["reattachment_x_over_h"], 6.6)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            external_notices.mapped_start(report, "mapped start")
        text = printed.getvalue()
        self.assertIn("source level 1 (9 iterations", text)
        self.assertIn("cold%3A completed; iterations 50", text.replace(":", "%3A"))
        self.assertIn("final iterate reattachment 6.6 H", text)

    def test_a_failed_preparation_is_a_workflow_error(self):
        def failed(*args, **kwargs):
            raise ValueError("CFD-X014 mapping.source.audit: source audit did not pass")

        report, _, runs = self.mapped_start(failed)
        self.assertFalse(report["workflow_completed"])
        self.assertIn("CFD-X014 mapping.source.audit", report["error"])
        self.assertEqual(runs.call_count, 0)
        saved = json.loads((self.root / "out/report.json").read_text())
        self.assertEqual(saved["error"], report["error"])

    def test_the_cavity_experiment_notice_states_its_checks(self):
        report = {
            "schema_version": "cfd-craft.mapping-experiment/0.1",
            "passed": True,
            "preparation_wall_s": 0.7,
            "runs": {
                "mapped": {
                    "execution_status": "completed",
                    "passed": True,
                    "numerical": {"iterations": 1356},
                    "wall_s": 4.6,
                }
            },
            "field_differences": {"U": {"maximum_absolute": 5.1e-9}},
            "audits": {
                "mapped": {
                    "passed": True,
                    "local_continuity": {"maximum_abs_divergence_h_over_u": 1.7e-9},
                }
            },
            "ghia": {"mapped": {"maximum_centerline_error": 0.00708}},
        }
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            external_notices.mapping_experiment(report, "mapping cavity")
        text = printed.getvalue()
        for part in [
            "iterations 1356",
            "U%3A max abs difference 5.1e-09",
            "max div(phi)*H/U 1.7e-09",
            "Ghia centerline error 0.00708",
        ]:
            self.assertIn(part, text.replace(":", "%3A"))


@unittest.skipUnless(
    os.environ.get("CFD_OPENFOAM_ROOT"), "set CFD_OPENFOAM_ROOT for actual mapping"
)
class ActualMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="cfd-real-map-")
        cls.root = Path(cls.temp.name)
        cls.foam = Path(os.environ["CFD_OPENFOAM_ROOT"])
        backend.prepare("cavity", 1, 3000, cls.root / "source-input")
        cls.source = cls.root / "source"
        record = backend.run(
            cls.root / "source-input", cls.source, cls.foam, timeout_s=60
        )
        if not record["passed"]:
            raise ValueError(record.get("error"))
        cls.mapped = cls.root / "mapped"
        cls.definition = mapping.prepare(cls.source, 2, 5000, cls.mapped, cls.foam)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.work = self.root / self._testMethodName
        self.work.mkdir()

    def test_actual_nearest_cells_and_boundaries_match_the_declared_rule(self):
        coarse = cartesian_mesh(self.source / "case")
        fine = cartesian_mesh(self.mapped / mapping.EVIDENCE / "target/case")
        count = self.definition["metadata"]["cells"]
        coords = fine["cell_centres"]
        expected = np.floor(coords[:, 0] * 24).astype(int) + 24 * np.floor(
            coords[:, 1] * 24
        ).astype(int)
        latest = backend.verify(self.source)["numerical"]["final_time_directory"]
        for field in ["U", "p"]:
            values = np.array(
                backend.internal_values(
                    self.source / "case" / latest / field, coarse["cells"], field == "U"
                )
            )
            values = values.reshape(-1, 3) if field == "U" else values
            mapped = np.array(
                backend.internal_values(self.mapped / "0" / field, count, field == "U")
            )
            mapped = mapped.reshape(-1, 3) if field == "U" else mapped
            np.testing.assert_allclose(mapped, values[expected], rtol=0, atol=1e-14)
            template = self.mapped / mapping.EVIDENCE / "templates/0" / field
            self.assertEqual(
                backend.block((self.mapped / "0" / field).read_text(), "boundaryField"),
                backend.block(template.read_text(), "boundaryField"),
            )
        self.assertFalse((self.mapped / "0/phi").exists())
        # On the uniformly refined cavity mapNearest is the nearest-centre rule.
        replay = self.definition["mesh_initialization"]["nearest_replay"]
        self.assertEqual(replay["nearest_source"], count, replay)

    def test_mapped_run_converges_and_can_supply_a_same_mesh_continuation(self):
        record = backend.run(
            self.mapped, self.work / "run", self.foam, timeout_s=120, output_mib=512
        )
        self.assertTrue(record["passed"], record.get("error"))
        self.assertTrue(backend.verify(self.work / "run")["passed"])
        self.assertTrue(audit(self.work / "run")["passed"])
        definition = restart.prepare(self.work / "run", 50, self.work / "restart")
        self.assertNotIn("mesh_initialization", definition)
        self.assertEqual(
            definition["initial_state"]["source_completed_iterations"],
            record["numerical"]["iterations"],
        )
        continued = backend.run(
            self.work / "restart", self.work / "continued", self.foam, timeout_s=60
        )
        self.assertTrue(continued["passed"])
        self.assertTrue(backend.verify(self.work / "continued")["passed"])
        for parent, name in [
            (self.work / "run", "mapped-parent"),
            (self.work / "continued", "continued-parent"),
        ]:
            with self.assertRaisesRegex(
                ValueError, "CFD-X014 mapping.source.initialization"
            ):
                mapping.prepare(parent, 3, 50, self.work / name, self.foam)
            self.assertFalse((self.work / name).exists())

    def test_occupied_output_and_nonaccepted_source_are_rejected(self):
        output = self.work / "occupied"
        output.mkdir()
        (output / "marker").write_text("preserve")
        with self.assertRaisesRegex(ValueError, "CFD-E062"):
            mapping.prepare(self.source, 2, 5000, output, self.foam)
        self.assertEqual((output / "marker").read_text(), "preserve")
        backend.prepare("cavity", 1, 50, self.work / "cold-input")
        backend.run(
            self.work / "cold-input", self.work / "cold", self.foam, timeout_s=60
        )
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.source.acceptance"):
            mapping.prepare(
                self.work / "cold", 2, 50, self.work / "not-created", self.foam
            )
        self.assertFalse((self.work / "not-created").exists())

    def test_source_copy_race_is_rejected_without_a_runnable_case(self):
        real = mapping.checked

        def changed(path, entry, field):
            if field == "source.696/U":
                return real(path, {"bytes": 1, "sha256": "0" * 64}, field)
            return real(path, entry, field)

        with patch.object(mapping, "checked", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.source.696/U"):
                mapping.prepare(self.source, 2, 50, self.work / "failed", self.foam)
        self.assertFalse((self.work / "failed/case.json").exists())
        self.assertTrue((self.work / "failed/mapping-failure.json").exists())

    def test_deadline_and_cancellation_leave_only_nonrunnable_preparation_evidence(
        self,
    ):
        for name, timeout, stop, code in [
            ("deadline", 1e-9, backend.Stop(), "CFD-X004"),
            ("cancelled", 60, backend.Stop(), "CFD-X008"),
        ]:
            if name == "cancelled":
                stop.cancelled = True
            output = self.work / name
            with self.assertRaisesRegex(ValueError, code):
                mapping.prepare(
                    self.source, 2, 50, output, self.foam, timeout_s=timeout, stop=stop
                )
            self.assertFalse((output / "case.json").exists())
            self.assertTrue((output / "mapping-failure.json").exists())

    def test_runtime_mismatch_stops_before_the_solve_and_failure_verifies(self):
        prepared = self.work / "input"
        shutil.copytree(self.mapped, prepared)
        definition = json.loads((prepared / "case.json").read_text())
        definition["mesh_initialization"]["runtime_sha256"] = "0" * 64
        # Direct check is precise; a forged receipt is rejected before execution.
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.source.runtime"):
            mapping.validate(prepared, definition)
        binaries, env, identity = backend.runtime(self.foam)
        with patch.object(
            backend,
            "runtime",
            return_value=(binaries, env, {**identity, "fixture": "different runtime"}),
        ):
            result = backend.run(
                self.mapped,
                self.work / "failed",
                self.foam,
                timeout_s=60,
                output_mib=512,
            )
        self.assertEqual(result["execution_status"], "failed")
        self.assertIn("CFD-X014 mapping.runtime", result["error"])
        self.assertFalse(any(c["program"] == "foamRun" for c in result["commands"]))
        self.assertEqual(backend.verify(self.work / "failed")["error"], result["error"])

    def test_rebuilt_mesh_mismatch_stops_before_solving_and_failure_verifies(self):
        execute = backend.execute

        def changed(command, env, output, label, *args):
            result = execute(command, env, output, label, *args)
            if label == "mesh":
                with (Path(output) / "case/constant/polyMesh/points").open(
                    "a"
                ) as stream:
                    stream.write("\n")
            return result

        with patch.object(backend, "execute", side_effect=changed):
            result = backend.run(
                self.mapped,
                self.work / "failed",
                self.foam,
                timeout_s=60,
                output_mib=512,
            )
        self.assertEqual(result["execution_status"], "failed")
        self.assertIn("CFD-X014 mapping.mesh.points", result["error"])
        self.assertFalse(any(c["program"] == "foamRun" for c in result["commands"]))
        self.assertEqual(backend.verify(self.work / "failed")["error"], result["error"])

    def test_sst_nearest_cells_and_boundaries_on_actual_backstep_meshes(self):
        # Synthetic nonuniform SST fields, real mesh generation/mapFields only.
        # No accepted turbulent-flow result is fabricated or reported.
        from openfoam_cases import build

        binaries, env, _ = backend.runtime(self.foam)
        for name, level in [("source", 1), ("target", 2)]:
            files, metadata = build(
                "backstep", level, 50, synthetic_data(), "wall-resolved", "simplec"
            )
            case = self.work / name / "case"
            for path, contents in files.items():
                destination = case / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(contents)
            backend.execute(
                [str(binaries["blockMesh"])],
                env,
                case.parent,
                "mesh",
                time.monotonic() + 60,
                256 * 1024**2,
                2048,
                backend.Stop(),
            )
        source = self.work / "source/case"
        coarse = cartesian_mesh(source)
        x, y = coarse["cell_centres"][:, 0], coarse["cell_centres"][:, 1]
        # Distinct smooth values per cell; signs suit each turbulence field.
        values = {
            "U": np.column_stack([1 + 0.01 * x, 0.02 * y - 0.001 * x, 0 * x]),
            "p": 0.003 * x - 0.007 * y,
            "k": 1e-3 * (1 + 0.1 * x + 0.05 * y),
            "omega": 10 + x + 3 * y,
            "nut": 1e-5 * (1 + 0.2 * x),
        }
        for name, rows in values.items():
            path = source / "0" / name
            path.write_text(internal_field(path.read_text(), rows, name == "U"))
        target = self.work / "target/case"
        mapper = self.foam / "platforms/linux64GccDPInt32Opt/bin/mapFields"
        backend.execute(
            [
                str(mapper),
                str(source.resolve()),
                "-consistent",
                "-sourceTime",
                "0",
                "-mapMethod",
                "mapNearest",
            ],
            env,
            target.parent,
            "map",
            time.monotonic() + 60,
            256 * 1024**2,
            2048,
            backend.Stop(),
        )
        for name in ["U", "p", "k", "omega", "nut"]:
            template = files["0/" + name]
            combined = mapping.replace_internal(
                template, target / "0" / name, metadata["cells"], name == "U", name
            )
            self.assertEqual(
                backend.block(combined, "boundaryField"),
                backend.block(template, "boundaryField"),
            )
        self.assertFalse((target / "0/phi").exists())
        # Foundation 13's mapNearest agrees with the independent replay on the
        # graded L-shaped meshes, for every field and target cell.
        replay = mapping.nearest_replay(
            self.work, "0", list(values), coarse["cells"], metadata["cells"]
        )
        print(f"::notice title=mapNearest on backstep levels 1-2::{json.dumps(replay)}")


if __name__ == "__main__":
    unittest.main()
