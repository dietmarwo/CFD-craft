#!/usr/bin/env python3
"""Steady restart boundaries and actual cavity equivalence.

Unit receipts and workflow returns are synthetic, never CFD evidence. Set
CFD_OPENFOAM_ROOT for the real Foundation-13 field/rejection tests.
"""

import contextlib
import copy
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "integrations"),
    str(ROOT / "tutorials"),
    str(ROOT / "validation"),
]
import openfoam_backend as backend
import openfoam_restart as restart
import backstep_resolution
import compare_restart
import restart_equivalence
from audit_openfoam_mesh import audit, cartesian_mesh
from external_notices import backstep_lines, restart_comparison
from test_resolution import two_cells


def reseal(run):
    entries = backend.inventory(run)
    entries.pop("manifest.json", None)
    entries.pop("complete.json", None)
    backend.write_json(
        Path(run) / "manifest.json",
        {"schema_version": "cfd-craft.external-archive/0.1", "files": entries},
    )
    backend.write_json(
        Path(run) / "complete.json",
        {"manifest_sha256": backend.sha256(Path(run) / "manifest.json")},
    )


class Receipt(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-restart-unit-")
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        definition = backend.prepare("cavity", 1, 50, self.source / "case")
        snapshot = self.source / "case/2"
        shutil.copytree(self.source / "case/0", snapshot)
        for path in snapshot.iterdir():
            path.write_text(
                path.read_text().replace("; object", '; location "2"; object')
            )
        (snapshot / "phi").write_text(
            'FoamFile { version 2.0; format ascii; class surfaceScalarField; location "2"; '
            "object phi; }\ninternalField uniform 0; // synthetic fixture\n"
        )
        mesh = self.source / "case/constant/polyMesh"
        mesh.mkdir()
        for name in restart.MESH_FILES:
            (mesh / name).write_text("synthetic receipt fixture, not a mesh\n")
        self.report = {
            "case": "cavity",
            "case_sha256": backend.sha256(self.source / "case/case.json"),
            "case_metadata": definition["metadata"],
            "execution_status": "completed",
            "passed": False,
            "numerical": {"iterations": 2, "final_time_directory": "2"},
            "runtime": {"fixture": "synthetic runtime identity"},
        }
        backend.write_json(self.source / "summary.json", self.report)
        reseal(self.source)
        self.local = {
            "passed": True,
            "maximum_abs_divergence_h_over_u": 0.0,
            "target_max": 1e-4,
        }

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, output=None, iterations=400):
        with (
            patch.object(backend, "verify", return_value=self.report),
            patch.object(restart, "local_flux", return_value=self.local),
        ):
            return restart.prepare(
                self.source, iterations, output or self.root / "input"
            )

    def test_cadence_writes_the_final_snapshot_without_changing_defaults(self):
        for steps in [50, 100, 250, 400, 600, 1000, 6000, 18400, 20000]:
            interval = backend.snapshot_interval(steps)
            self.assertEqual(steps % interval, 0)
            self.assertTrue(50 <= interval <= 250, steps)
        self.assertEqual(backend.snapshot_interval(6000), 250)
        self.assertEqual(backend.snapshot_interval(20000), 250)
        self.assertEqual(backend.snapshot_interval(400), 200)
        cold = backend.prepare("cavity", 1, 400, self.root / "cold")
        self.assertIn(
            "writeInterval 200;", (self.root / "cold/system/controlDict").read_text()
        )
        self.assertEqual(cold["max_iterations"], 400)

    def test_limits_that_would_write_every_few_iterations_are_rejected(self):
        # 251 and 19997 are prime; 1234 = 2 * 617; 11797 = 47 * 251.
        for steps in [251, 1234, 11797, 19997]:
            with self.assertRaisesRegex(ValueError, "CFD-X001 iterations"):
                backend.snapshot_interval(steps)
            with self.assertRaisesRegex(ValueError, "CFD-X001 iterations"):
                backend.prepare("cavity", 1, steps, self.root / f"cold{steps}")
            self.assertFalse((self.root / f"cold{steps}").exists())
            with self.assertRaisesRegex(ValueError, "CFD-X001 iterations"):
                self.prepare(iterations=steps)
        self.assertFalse((self.root / "input").exists())

    def test_invalid_stage_limit_is_rejected_before_output_creation(self):
        for steps in [0, 49, 20001, True, 100.0]:
            with self.assertRaisesRegex(
                ValueError, "CFD-X012 initial_state.iterations"
            ):
                self.prepare(iterations=steps)
        self.assertFalse((self.root / "input").exists())

    def test_fields_phi_and_fixed_inputs_retain_their_exact_source_bytes(self):
        definition = self.prepare()
        state = definition["initial_state"]
        self.assertFalse(state["source_numerical_passed"])
        self.assertEqual(state["source_completed_iterations"], 2)
        self.assertEqual(state["source_time"], "2")
        for name, entry in state["source_fields"].items():
            self.assertEqual(
                (self.root / "input/0" / name).read_bytes(),
                (self.source / "case/2" / name).read_bytes(),
            )
            self.assertEqual(restart.file_identity(self.root / "input/0" / name), entry)
        for name in state["fixed_inputs"]:
            self.assertEqual(
                (self.root / "input" / name).read_bytes(),
                (self.source / "case" / name).read_bytes(),
            )
        self.assertIn(
            "writeInterval 200;", (self.root / "input/system/controlDict").read_text()
        )

    def test_failed_timeout_and_cancelled_sources_are_ineligible(self):
        for status in ["failed", "timeout", "cancelled", "incomplete"]:
            self.report["execution_status"] = status
            with self.assertRaisesRegex(
                ValueError, "CFD-X012 initial_state.source.execution_status"
            ):
                self.prepare()
        self.assertFalse((self.root / "input").exists())

    def test_an_occupied_output_is_preserved(self):
        output = self.root / "input"
        output.mkdir()
        (output / "marker").write_text("keep me")
        with self.assertRaisesRegex(ValueError, "CFD-E062"):
            self.prepare()
        self.assertEqual((output / "marker").read_text(), "keep me")

    def test_changed_fields_cannot_be_hidden_by_resealing_the_input_inventory(self):
        definition = self.prepare()
        (self.root / "input/0/p").write_text("internalField uniform 0.2;\n")
        definition["inputs"]["0/p"] = restart.file_identity(self.root / "input/0/p")
        backend.write_json(self.root / "input/case.json", definition)
        with self.assertRaisesRegex(
            ValueError, "CFD-X012 initial_state.source_fields.p"
        ):
            backend.check_prepared(self.root / "input")

    def test_changed_physics_cannot_be_hidden_by_resealing_the_inventory(self):
        definition = self.prepare()
        path = self.root / "input/system/fvSolution"
        path.write_text(path.read_text().replace("p 1e-7", "p 1e-2"))
        definition["inputs"]["system/fvSolution"] = restart.file_identity(path)
        backend.write_json(self.root / "input/case.json", definition)
        with self.assertRaisesRegex(ValueError, "CFD-X012 initial_state.fixed_inputs"):
            backend.check_prepared(self.root / "input")

    def test_malformed_or_incomplete_receipts_are_rejected(self):
        good = self.prepare()
        entry = {"bytes": 1, "sha256": "0" * 64}
        mutations = [
            (lambda d: d.update(initial_state=None), "schema_version"),
            (lambda d: d["initial_state"].update(schema_version="x/0.1"), "schema"),
            (lambda d: d["initial_state"].update(method="interpolated"), "schema"),
            (lambda d: d["initial_state"].update(source_time="../2"), "source_time"),
            (
                lambda d: d["initial_state"].update(source_completed_iterations=True),
                "source_completed",
            ),
            (
                lambda d: d["initial_state"].update(source_completed_iterations=1),
                "source_completed",
            ),
            (
                lambda d: d["initial_state"].update(source_numerical_passed=1),
                "source_numerical",
            ),
            (lambda d: d["initial_state"]["source_fields"].pop("phi"), "source_fields"),
            (lambda d: d["initial_state"]["source_mesh"].pop("points"), "source_mesh"),
            (
                lambda d: d["initial_state"]["fixed_inputs"].pop("system/fvSchemes"),
                "fixed_inputs",
            ),
            (
                lambda d: d["initial_state"]["source_mesh"].update(points={"bytes": 0}),
                "source_mesh.points",
            ),
            (
                lambda d: d["initial_state"].update(source_runtime_sha256="bad"),
                "source_runtime",
            ),
            (lambda d: d["initial_state"].pop("source_controls"), "source_controls"),
            (lambda d: d.update(max_iterations=49), "iterations"),
            (lambda d: d["metadata"].update(reynolds=1000), "source_metadata"),
            (lambda d: d["inputs"].update({"constant/fvModels": entry}), "inputs"),
            (
                lambda d: d["initial_state"]["source_fields"].update(p=entry),
                "source_fields.p",
            ),
        ]
        for mutate, field in mutations:
            definition = copy.deepcopy(good)
            mutate(definition)
            with self.assertRaisesRegex(ValueError, "CFD-X012 initial_state." + field):
                restart.validate(self.root / "input", definition)

    def test_stage_controls_may_differ_only_in_end_time_and_write_interval(self):
        definition = self.prepare()
        path = self.root / "input/system/controlDict"
        text = path.read_text()
        for changed in [
            text.replace("writePrecision 15", "writePrecision 6"),
            text.replace("purgeWrite 1", "purgeWrite 0"),
            text.replace("endTime 400", "endTime 450"),
            text.replace("writeInterval 200", "writeInterval 150"),
            text + "functions { }\n",
        ]:
            path.write_text(changed)
            definition["inputs"]["system/controlDict"] = restart.file_identity(path)
            with self.assertRaisesRegex(ValueError, "CFD-X012 initial_state.controls"):
                restart.validate(self.root / "input", definition)

    def test_copied_fields_must_come_from_the_source_snapshot(self):
        definition = self.prepare()
        path = self.root / "input/0/U"
        path.write_text(path.read_text().replace('location "2"', 'location "1"'))
        definition["inputs"]["0/U"] = restart.file_identity(path)
        definition["initial_state"]["source_fields"]["U"] = restart.file_identity(path)
        with self.assertRaisesRegex(
            ValueError, "CFD-X012 initial_state.source_fields.U: copied field does not"
        ):
            restart.validate(self.root / "input", definition)

    def test_a_nonfinite_copied_field_is_rejected(self):
        definition = self.prepare()
        path = self.root / "input/0/p"
        path.write_text(path.read_text().replace("uniform 0;", "uniform nan;"))
        definition["inputs"]["0/p"] = restart.file_identity(path)
        definition["initial_state"]["source_fields"]["p"] = restart.file_identity(path)
        with self.assertRaisesRegex(ValueError, "CFD-X006 fields.p: nonfinite"):
            restart.validate(self.root / "input", definition)

    def test_cumulative_work_continues_along_a_chain(self):
        path = self.source / "case/case.json"
        definition = json.loads(path.read_text())
        definition["initial_state"] = {"source_completed_iterations": 10}

        def chained():
            path.write_text(json.dumps(definition))

        self.resealed_source(chained)
        state = self.prepare()["initial_state"]
        self.assertEqual(state["source_completed_iterations"], 12)

    def test_the_prepared_case_is_deterministic(self):
        definition = self.prepare()
        self.assertEqual(list(definition["inputs"]), sorted(definition["inputs"]))
        self.assertEqual(
            list(definition["initial_state"]["fixed_inputs"]),
            sorted(definition["initial_state"]["fixed_inputs"]),
        )
        self.assertEqual(
            restart.fixed_names("backstep"), sorted(restart.fixed_names("backstep"))
        )

    def resealed_source(self, edit):
        edit()
        definition = json.loads((self.source / "case/case.json").read_text())
        backend.write_json(self.source / "case/case.json", definition)
        self.report["case_sha256"] = backend.sha256(self.source / "case/case.json")
        backend.write_json(self.source / "summary.json", self.report)
        reseal(self.source)

    def test_sources_from_other_generators_or_controls_are_rejected(self):
        path = self.source / "case/case.json"
        original = path.read_text()

        def generator():
            definition = json.loads(original)
            definition["generator_sha256"] = "0" * 64
            path.write_text(json.dumps(definition))

        self.resealed_source(generator)
        with self.assertRaisesRegex(
            ValueError, r"CFD-X012 initial_state\.source\.generator:"
        ):
            self.prepare()
        path.write_text(original)
        controls = self.source / "case/system/controlDict"

        def precision():
            controls.write_text(
                controls.read_text().replace("Precision 15", "Precision 6")
            )
            definition = json.loads(original)
            definition["inputs"]["system/controlDict"] = restart.file_identity(controls)
            path.write_text(json.dumps(definition))

        self.resealed_source(precision)
        with self.assertRaisesRegex(
            ValueError, r"CFD-X012 initial_state\.source\.controls:"
        ):
            self.prepare()
        self.assertFalse((self.root / "input").exists())

    def test_source_bytes_are_checked_where_they_are_read(self):
        # Each file changes after the archive was verified and before it is read.
        for name, field in [
            ("case/case.json", "source.case"),
            ("case/system/controlDict", "source.controls"),
            ("case/2/phi", "source.phi"),
        ]:
            path = self.source / name
            original = path.read_bytes()

            def verified(*args, _path=path, _original=original):
                _path.write_bytes(_original + b"\n")
                return self.report

            with (
                patch.object(backend, "verify", side_effect=verified),
                patch.object(restart, "local_flux", return_value=self.local),
            ):
                with self.assertRaisesRegex(
                    ValueError, "CFD-X012 initial_state." + field
                ):
                    restart.prepare(self.source, 400, self.root / "input")
            path.write_bytes(original)
            self.assertFalse((self.root / "input").exists())
        manifest = self.source / "manifest.json"
        original = manifest.read_bytes()

        def moved(*args):
            manifest.write_bytes(original.replace(b"{", b"{ ", 1))
            return self.report

        with patch.object(backend, "verify", side_effect=moved):
            with self.assertRaisesRegex(
                ValueError, "CFD-X012 initial_state.source.manifest"
            ):
                restart.prepare(self.source, 400, self.root / "input")

    def test_missing_source_entries_and_files_name_their_field(self):
        del self.report["runtime"]
        with self.assertRaisesRegex(
            ValueError, "CFD-X012 initial_state.source.runtime"
        ):
            self.prepare()
        self.report["runtime"] = {"fixture": "synthetic runtime identity"}
        (self.source / "case/system/controlDict").unlink()
        with self.assertRaisesRegex(
            ValueError, "CFD-X012 initial_state.source: cannot read controlDict"
        ):
            self.prepare()
        self.assertFalse((self.root / "input").exists())

    def test_a_failed_copy_leaves_no_partial_stage(self):
        with patch.object(
            restart.backend, "check_prepared", side_effect=OSError(28, "full")
        ):
            with self.assertRaises(ValueError):
                self.prepare()
        self.assertFalse((self.root / "input").exists())

    def test_a_solved_stage_must_carry_its_runtime_and_mesh_checks(self):
        definition = self.prepare()
        case = self.root / "input"
        (case / "constant/polyMesh").mkdir(parents=True)
        for name in restart.MESH_FILES:
            shutil.copyfile(
                self.source / "case/constant/polyMesh" / name,
                case / "constant/polyMesh" / name,
            )
        (self.root / "check-mesh.log").write_text("Mesh OK.\n")
        solved = {
            "execution_status": "completed",
            "runtime": self.report["runtime"],
            "commands": [
                {"program": "checkMesh", "returncode": 0},
                {"program": "foamRun", "returncode": 0},
            ],
        }
        with patch.object(restart, "local_flux", return_value=self.local) as flux:
            restart.verify_receipt(case, definition, solved)
            self.assertEqual(flux.call_count, 1)
            for change, field in [
                (lambda r: r.pop("runtime"), "runtime"),
                (lambda r: r.update(runtime={"other": 1}), "runtime"),
                (lambda r: r["commands"].pop(0), "mesh"),
            ]:
                report = copy.deepcopy(solved)
                change(report)
                with self.assertRaisesRegex(
                    ValueError, "CFD-X012 initial_state." + field
                ):
                    restart.verify_receipt(case, definition, report)
            (self.root / "check-mesh.log").write_text("Mesh not OK\n")
            with self.assertRaisesRegex(ValueError, "CFD-X012 initial_state.mesh"):
                restart.verify_receipt(case, definition, solved)
            (self.root / "check-mesh.log").write_text("Mesh OK.\n")
            (case / "constant/polyMesh/points").write_text("another mesh\n")
            with self.assertRaisesRegex(
                ValueError, "CFD-X012 initial_state.mesh.points"
            ):
                restart.verify_receipt(case, definition, solved)

    def test_a_rejected_initialization_is_a_consistent_failed_archive(self):
        from test_openfoam import fake_runtime

        self.prepare()
        # The synthetic runtime differs from the receipt's: rejected before solving.
        foam = fake_runtime(self.root / "foam", "converged")
        run = self.root / "run"
        result = backend.run(self.root / "input", run, foam, timeout_s=30)
        self.assertEqual(result["execution_status"], "failed")
        self.assertTrue(result["error"].startswith("CFD-X012 initial_state.runtime"))
        self.assertFalse(any(c["program"] == "foamRun" for c in result["commands"]))
        backend.verify(run)
        summary = json.loads((run / "summary.json").read_text())
        for change, field in [
            (
                lambda r: r["initial_state"].update(source_time="1"),
                "archive.initial_state",
            ),
            (
                lambda r: r.update(
                    error="CFD-X012 initial_state.mesh.points: rebuilt mesh differs"
                ),
                "initial_state.archive",
            ),
        ]:
            changed = copy.deepcopy(summary)
            change(changed)
            backend.write_json(run / "summary.json", changed)
            reseal(run)
            with self.assertRaisesRegex(ValueError, field):
                backend.verify(run)
        backend.write_json(run / "summary.json", summary)
        reseal(run)
        backend.verify(run)

    def test_a_source_flux_must_pass_the_independent_local_gate(self):
        two_cells(self.root / "mesh")
        case = self.root / "mesh"
        (case / "constant/polyMesh/boundary").write_text(
            "FoamFile { version 2.0; format ascii; class polyBoundaryMesh; object boundary; }\n"
            "3 ( lid { type wall; nFaces 1; startFace 1; } "
            "walls { type wall; nFaces 9; startFace 2; } "
            "span { type empty; nFaces 0; startFace 11; } )\n"
        )
        mesh = cartesian_mesh(case)
        x = mesh["face_centres"][1:, 0]
        # Unit x-flow through unit faces: -1 at x=0, +1 at x=2, 0 elsewhere.
        values = np.where(x == 0, -1.0, np.where(x == 2, 1.0, 0.0))
        lid = values[0]
        walls = " ".join(str(v) for v in values[1:])

        def phi(internal):
            return (
                f"internalField uniform {internal};\nboundaryField {{ lid {{ type calculated; "
                f"value uniform {lid}; }} walls {{ type calculated; value nonuniform "
                f"List<scalar> 9 ({walls}); }} span {{ type empty; }} }}\n"
            )

        metadata = {"cells": 2, "height_m": 1, "reference_speed_m_s": 1}
        balanced = restart.local_flux(case, "1", metadata, "cavity", phi(1.0))
        self.assertTrue(balanced["passed"])
        self.assertLess(balanced["maximum_abs_divergence_h_over_u"], 1e-14)
        self.assertEqual(balanced["maximum_face_scaled_balance"], 0)
        self.assertTrue(
            restart.local_flux(case, "1", metadata, "cavity", phi(1.00005))["passed"]
        )
        for internal in [1.001, -1.0]:
            with self.assertRaisesRegex(
                restart.IneligibleSource, "CFD-X012 initial_state.phi.local_continuity"
            ):
                restart.local_flux(case, "1", metadata, "cavity", phi(internal))

    def test_the_checked_phi_bytes_are_the_ones_checked_for_flux(self):
        with (
            patch.object(backend, "verify", return_value=self.report),
            patch.object(restart, "local_flux", return_value=self.local) as flux,
        ):
            restart.prepare(self.source, 400, self.root / "input")
        self.assertEqual(
            flux.call_args.args[4], (self.source / "case/2/phi").read_text()
        )

    def test_a_stage_archive_failing_the_flux_gate_is_invalid_not_ineligible(self):
        definition = self.prepare()
        report = {
            "execution_status": "completed",
            "runtime": self.report["runtime"],
            "commands": [
                {"program": "checkMesh", "returncode": 0},
                {"program": "foamRun", "returncode": 0},
            ],
        }
        (self.root / "check-mesh.log").write_text("Mesh OK.\n")
        failure = restart.IneligibleSource(
            "CFD-X012 initial_state.phi.local_continuity: x"
        )
        with (
            patch.object(restart, "check_mesh", side_effect=failure),
            self.assertRaisesRegex(ValueError, "phi.local_continuity") as caught,
        ):
            restart.verify_receipt(self.root / "input", definition, report)
        self.assertNotIsInstance(caught.exception, restart.IneligibleSource)

    def test_a_mismatch_in_an_unsolved_archive_must_be_its_recorded_failure(self):
        definition = self.prepare()
        report = {
            "execution_status": "failed",
            "error": "CFD-X012 initial_state.runtime: runtime differs from the source stage",
            "runtime": {"other": 1},
            "commands": [],
        }
        restart.verify_receipt(self.root / "input", definition, report)
        for change in [{"execution_status": "completed"}, {"error": "CFD-X003 other"}]:
            with self.assertRaisesRegex(ValueError, "CFD-X012 initial_state.archive"):
                restart.verify_receipt(
                    self.root / "input", definition, {**report, **change}
                )

    def test_stage_controls_need_a_final_writing_cadence_and_generated_source_controls(
        self,
    ):
        definition = self.prepare()
        path = self.root / "input/system/controlDict"
        text = path.read_text()
        for interval in [25, 400, 300]:
            path.write_text(
                text.replace("writeInterval 200", f"writeInterval {interval}")
            )
            definition["inputs"]["system/controlDict"] = restart.file_identity(path)
            with self.assertRaisesRegex(ValueError, "CFD-X012 initial_state.controls"):
                restart.validate(self.root / "input", definition)
        changed = text.replace("writePrecision 15", "writePrecision 6")
        path.write_text(changed)
        definition["inputs"]["system/controlDict"] = restart.file_identity(path)
        state = definition["initial_state"]
        state["source_controls"] = state["source_controls"].replace(
            "writePrecision 15", "writePrecision 6"
        )
        with self.assertRaisesRegex(
            ValueError, "CFD-X012 initial_state.source_controls"
        ):
            restart.validate(self.root / "input", definition)

    def test_an_unwritable_stage_and_binary_source_name_their_side(self):
        original = shutil.copyfile

        def full(source, destination):
            if Path(destination).name == "U":
                raise OSError(28, "No space left on device", str(destination))
            return original(source, destination)

        with patch.object(restart.shutil, "copyfile", side_effect=full):
            with self.assertRaisesRegex(
                ValueError, "CFD-X012 initial_state.inputs: cannot write U"
            ):
                self.prepare()
        self.assertFalse((self.root / "input").exists())
        controls = self.source / "case/system/controlDict"
        path = self.source / "case/case.json"
        definition = json.loads(path.read_text())

        def binary():
            controls.write_bytes(b"\xff\xfe")
            definition["inputs"]["system/controlDict"] = restart.file_identity(controls)
            path.write_text(json.dumps(definition))

        self.resealed_source(binary)
        with self.assertRaisesRegex(
            ValueError, "CFD-X012 initial_state.source.controlDict: not a text file"
        ):
            self.prepare()

    def test_copy_races_leave_no_runnable_case(self):
        original = shutil.copyfile

        def changed(source, destination):
            result = original(source, destination)
            if Path(destination).name == "U":
                with Path(destination).open("a") as stream:
                    stream.write("// raced copy\n")
            return result

        with patch.object(restart.shutil, "copyfile", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "CFD-X012 initial_state.inputs"):
                self.prepare()
        self.assertFalse((self.root / "input/case.json").exists())

    def test_runtime_identity_is_order_independent_and_exact(self):
        state = {"source_runtime_sha256": restart.identity({"a": 1, "b": 2})}
        restart.check_runtime(state, {"b": 2, "a": 1})
        with self.assertRaisesRegex(ValueError, "CFD-X012 initial_state.runtime"):
            restart.check_runtime(state, {"b": 3, "a": 1})


class Stages(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-stage-unit-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def execution(self, passed=False, status="completed", steps=50, converged=None):
        return {
            "passed": passed,
            "execution_status": status,
            "numerical": {
                "passed": passed,
                "iterations": steps,
                "solver_reported_convergence": passed
                if converged is None
                else converged,
            }
            if status == "completed"
            else None,
            "progress": {"started_iterations": steps},
        }

    def run_study(self, results, preset="smoke", restart_error=None, stop=None):
        pending = iter(results)

        def returned(*args, **kwargs):
            result = next(pending)
            return result(*args, **kwargs) if callable(result) else result

        with (
            patch.object(
                backstep_resolution,
                "load",
                return_value={"raw_sha256": {"fixture": "synthetic"}},
            ),
            patch.object(backend, "prepare"),
            patch.object(backend, "run", side_effect=returned) as run,
            patch.object(
                backstep_resolution, "prepare_restart", side_effect=restart_error
            ) as prepare_restart,
            patch.object(
                backstep_resolution,
                "audit",
                return_value={"status": "evaluated", "passed": True},
            ) as audited,
            patch.object(
                backstep_resolution,
                "assess",
                return_value={"status": "evaluated", "passed": True},
            ) as assess,
            patch.object(backstep_resolution, "save"),
            patch.object(backend, "Stop", return_value=stop or backend.Stop()),
        ):
            report = backstep_resolution.study(
                self.root, self.root / "study", self.root, preset=preset, max_stages=3
            )
        self.audited = audited
        return report, run, prepare_restart, assess

    def test_stages_stop_at_numerical_convergence_and_compare_the_actual_last_run(self):
        report, run, prepared, assess = self.run_study(
            [self.execution(), self.execution(True)]
        )
        self.assertTrue(report["passed"])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(prepared.call_count, 1)
        row = report["rows"][0]
        self.assertEqual(row["completed_solver_iterations"], 100)
        self.assertEqual(row["started_iterations"], 100)
        self.assertEqual(row["continuation_stop_reason"], "numerically_accepted")
        self.assertIs(row["execution"], row["stages"][-1]["execution"])
        lines = backstep_lines({**row, "comparison": {"status": "not_assessed"}})
        self.assertIn(
            "stages 2; completed solver iterations across stages 100; started 100; "
            "stop numerically_accepted",
            lines,
        )
        self.assertTrue(any(line.startswith("stage 2: completed") for line in lines))
        for call in [assess, self.audited]:
            self.assertEqual(
                call.call_args.args[0].name, "wall-resolved-simplec-level1-stage2"
            )
        self.assertEqual(
            prepared.call_args.args[0].name, "wall-resolved-simplec-level1"
        )

    def test_stage_notices_report_the_recorded_source_gate_value(self):
        state = {"source_local_continuity": {"maximum_abs_divergence_h_over_u": 2.7e-9}}
        row = {
            "stages": [
                {"stage": 1, "execution": {"execution_status": "completed"}},
                {
                    "stage": 2,
                    "execution": {
                        "execution_status": "completed",
                        "initial_state": state,
                    },
                },
            ],
            "comparison": {"status": "not_assessed"},
        }
        lines = backstep_lines(row)
        self.assertTrue(
            any(
                line.startswith("stage 2:")
                and "source max div(phi)*H/U 2.7e-09" in line
                for line in lines
            ),
            lines,
        )
        self.assertFalse(
            any("source" in line for line in lines if line.startswith("stage 1:"))
        )

    def test_stages_keep_iteration_limit_results_and_stop_at_the_stage_budget(self):
        report, run, prepared, _ = self.run_study([self.execution()] * 3)
        self.assertTrue(report["workflow_completed"])
        self.assertFalse(report["passed"])
        self.assertEqual(run.call_count, 3)
        self.assertEqual(prepared.call_count, 2)
        row = report["rows"][0]
        self.assertEqual(row["completed_solver_iterations"], 150)
        self.assertEqual(row["continuation_stop_reason"], "stage_limit")

    def test_a_converged_but_unaccepted_stage_does_not_continue(self):
        # Residuals carry across a restart, so a further stage would report
        # convergence again at its first iteration and fail the same way.
        report, run, prepared, _ = self.run_study([self.execution(converged=True)] * 3)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(prepared.call_count, 0)
        self.assertEqual(
            report["rows"][0]["continuation_stop_reason"],
            "converged_without_numerical_acceptance",
        )
        self.assertFalse(report["passed"])

    def test_failed_timeout_and_cancelled_stages_do_not_continue_or_refine(self):
        for status in ["failed", "timeout", "cancelled"]:
            if (self.root / "study").exists():
                shutil.rmtree(self.root / "study")
            report, run, prepared, _ = self.run_study(
                [self.execution(status=status)], preset="study"
            )
            self.assertEqual(run.call_count, 1)
            self.assertEqual(prepared.call_count, 0)
            self.assertFalse(report["passed"])
            self.assertEqual(
                report["rows"][0]["continuation_stop_reason"], "execution_" + status
            )
            self.assertTrue(
                all(
                    r.get("reason") == "coarser_level_not_accepted"
                    for r in report["rows"][1:]
                )
            )

    def test_cancellation_between_stages_starts_no_further_stage(self):
        stop = backend.Stop()

        def first(*args, **kwargs):
            stop.cancelled = True
            return self.execution()

        report, run, prepared, _ = self.run_study([first], stop=stop)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(prepared.call_count, 0)
        self.assertEqual(report["rows"][0]["continuation_stop_reason"], "cancelled")
        self.assertFalse(report["workflow_completed"])

    def test_the_report_is_written_after_each_stage(self):
        seen = []

        def second(*args, **kwargs):
            written = json.loads((self.root / "study/report.json").read_text())
            seen.append(len(written["rows"][0]["stages"]))
            return self.execution(True)

        self.run_study([self.execution(), second])
        self.assertEqual(seen, [1])

    def test_restart_preparation_errors_preserve_the_completed_stage_and_fail_the_workflow(
        self,
    ):
        report, run, _, _ = self.run_study(
            [self.execution()],
            restart_error=ValueError("CFD-X012 initial_state.phi: synthetic failure"),
        )
        self.assertEqual(run.call_count, 1)
        self.assertFalse(report["workflow_completed"])
        self.assertIn("CFD-X012", report["error"])
        self.assertEqual(len(report["rows"][0]["stages"]), 1)

    def test_invalid_stage_counts_fail_before_creating_the_output(self):
        for count in [0, 9, True, 1.0]:
            with self.assertRaisesRegex(ValueError, "CFD-X001 study.max_stages"):
                backstep_resolution.study(
                    self.root, self.root / "unused", self.root, max_stages=count
                )
        with self.assertRaisesRegex(ValueError, "CFD-X001 study.iterations"):
            backstep_resolution.study(
                self.root, self.root / "unused", self.root, iterations=19997
            )
        self.assertFalse((self.root / "unused").exists())

    def test_an_ineligible_source_is_unaccepted_evidence_and_skips_refinement(self):
        report, run, _, _ = self.run_study(
            [self.execution()],
            preset="study",
            restart_error=restart.IneligibleSource(
                "CFD-X012 initial_state.phi.local_continuity: synthetic gate failure"
            ),
        )
        self.assertTrue(report["workflow_completed"])
        self.assertFalse(report["passed"])
        self.assertNotIn("error", report)
        self.assertEqual(run.call_count, 1)
        self.assertTrue(
            report["rows"][0]["continuation_stop_reason"].startswith(
                "source_ineligible: CFD-X012 initial_state.phi.local_continuity"
            )
        )
        self.assertTrue(
            all(
                r.get("reason") == "coarser_level_not_accepted"
                for r in report["rows"][1:]
            )
        )


class Comparison(unittest.TestCase):
    """compare_restart on synthetic archives: a software check, not CFD evidence."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-restart-compare-")
        self.build("fixture")

    def build(self, base):
        self.root = Path(self.temp.name) / base
        self.records = {}
        for name, work, previous in [("run", 30, 20), ("control", 50, None)]:
            run = self.root / name
            run.mkdir(parents=True)
            definition = backend.prepare("cavity", 1, 50, run / "case")
            if previous is not None:
                definition["initial_state"] = {"source_completed_iterations": previous}
            backend.write_json(run / "case/case.json", definition)
            (run / "case/7").mkdir()
            self.write(run, "U", "(1 0 0)")
            self.write(run, "p", "0")
            mesh = run / "case/constant/polyMesh"
            mesh.mkdir()
            for part in restart.MESH_FILES:
                (mesh / part).write_text("synthetic mesh fixture\n")
            reseal(run)
            self.records[str(run)] = {
                "case": "cavity",
                "passed": False,
                "runtime": {"fixture": 1},
                "numerical": {"iterations": work, "final_time_directory": "7"},
                **({"initial_state": definition["initial_state"]} if previous else {}),
            }

    def tearDown(self):
        self.temp.cleanup()

    def write(self, run, name, value):
        cls = "vector" if name == "U" else "scalar"
        values = " ".join([value] * 576)
        (run / "case/7" / name).write_text(
            f"internalField nonuniform List<{cls}> 576 ({values});\n"
        )

    def compare(self, mode="fixed-work", run_divergence=1e-9):
        divergence = {"run": run_divergence, "control": 1e-9}

        def continuity(run):
            largest = divergence[Path(run).name]
            return {
                "maximum_abs_divergence_h_over_u": largest,
                "target_max": 1e-4,
                "passed": largest <= 1e-4,
            }

        with (
            patch.object(
                backend, "verify", side_effect=lambda run: self.records[str(run)]
            ),
            patch.object(compare_restart, "local_continuity", side_effect=continuity),
        ):
            return compare_restart.compare(
                self.root / "run", self.root / "control", mode
            )

    def test_fixed_work_requires_both_final_fluxes_to_pass_the_local_gate(self):
        result = self.compare(run_divergence=2e-4)
        self.assertTrue(result["checks"]["U"] and result["checks"]["work"])
        self.assertFalse(result["checks"]["local_continuity"])
        self.assertFalse(result["passed"])
        self.assertEqual(
            result["local_continuity"]["run"]["maximum_abs_divergence_h_over_u"], 2e-4
        )
        self.assertTrue(self.compare()["checks"]["local_continuity"])
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            restart_comparison(result, "equivalence cavity")
        self.assertIn("run: final max div(phi)*H/U 0.0002", printed.getvalue())

    def test_equal_fields_and_work_pass_and_differences_are_measured(self):
        result = self.compare()
        self.assertTrue(result["passed"], result["checks"])
        self.assertEqual(result["work"], {"run": 50, "control": 50})
        self.write(self.root / "run", "U", "(1.00002 0 0)")
        result = self.compare()
        self.assertFalse(result["checks"]["U"])
        self.assertAlmostEqual(result["fields"]["U"]["maximum_absolute"], 2e-5)
        self.write(self.root / "run", "U", "(1 0 0)")
        self.write(self.root / "run", "p", "0.5")
        result = self.compare()
        self.assertFalse(result["checks"]["p"])
        self.assertAlmostEqual(result["fields"]["p"]["offset"], 0.5)
        self.assertAlmostEqual(
            result["fields"]["p"]["maximum_absolute_offset_removed"], 0
        )

    def test_work_and_acceptance_are_part_of_the_converged_mode(self):
        self.records[str(self.root / "run")]["numerical"]["iterations"] = 33
        self.assertFalse(self.compare()["checks"]["work"])
        result = self.compare("converged")
        self.assertFalse(result["checks"]["numerical"])
        for record in self.records.values():
            record["passed"] = True
        self.assertFalse(self.compare("converged")["checks"]["work"])  # 53 vs 50
        self.records[str(self.root / "run")]["numerical"]["iterations"] = 32
        result = self.compare("converged")
        self.assertTrue(result["checks"]["numerical"])
        self.assertTrue(result["checks"]["work"])  # 52 against 50, within 5%
        self.assertTrue(result["passed"])
        self.records[str(self.root / "run")]["numerical"]["iterations"] = 40
        self.assertFalse(self.compare("converged")["checks"]["work"])

    def test_different_recipes_meshes_or_runtimes_are_not_compared(self):
        control = self.root / "control"
        (control / "case/system/fvSchemes").write_text("changed\n")
        definition = json.loads((control / "case/case.json").read_text())
        definition["inputs"]["system/fvSchemes"] = restart.file_identity(
            control / "case/system/fvSchemes"
        )
        backend.write_json(control / "case/case.json", definition)
        with self.assertRaisesRegex(
            ValueError, "CFD-X013 comparison.inputs.system/fvSchemes"
        ):
            self.compare()
        self.build("mesh")
        (self.root / "control/case/constant/polyMesh/points").write_text("other\n")
        reseal(self.root / "control")
        with self.assertRaisesRegex(ValueError, "CFD-X013 comparison.mesh.points"):
            self.compare()
        self.build("runtime")
        self.records[str(self.root / "control")]["runtime"] = {"fixture": 2}
        with self.assertRaisesRegex(ValueError, "CFD-X013 comparison.runtime"):
            self.compare()


class BackstepComparison(unittest.TestCase):
    """compare_restart's backstep checks with mocked fields and metrics."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-restart-backstep-")
        self.root = Path(self.temp.name)
        self.metrics = {
            "audit_passed": True,
            "screen_passed": True,
            "reattachment_x_over_h": 6.7064,
            "cf_rmse": 4.17e-4,
            "profile_rmse": {"1": 0.0449, "4": 0.0646},
            "maximum_y_plus": {"stepWall": 0.963, "lowerWall": 0.484},
        }
        self.fields = {
            name: {"maximum_absolute": 0.0, "maximum_over_control_maximum": 0.0}
            for name in ["U", "p", "k", "omega", "nut"]
        }
        self.records = {
            "run": {
                "case": "backstep",
                "passed": True,
                "numerical": {"iterations": 412},
                "initial_state": {"source_completed_iterations": 18000},
            },
            "control": {
                "case": "backstep",
                "passed": True,
                "numerical": {"iterations": 18412},
            },
        }

    def tearDown(self):
        self.temp.cleanup()

    def compare(self, run_metrics=None, data="data", fields=None):
        found = {"run": run_metrics or self.metrics, "control": self.metrics}
        for name in ["run", "control"]:
            (self.root / name).mkdir(exist_ok=True)
            (self.root / name / "manifest.json").write_text("{}")
        with (
            patch.object(
                backend, "verify", side_effect=lambda r: self.records[Path(r).name]
            ),
            patch.object(
                compare_restart, "same_recipe", return_value=("backstep", {"cells": 1})
            ),
            patch.object(
                compare_restart, "field_differences", return_value=fields or self.fields
            ),
            patch.object(
                compare_restart, "metrics", side_effect=lambda r, d: found[Path(r).name]
            ),
        ):
            return compare_restart.compare(
                self.root / "run", self.root / "control", "converged", data
            )

    def test_equal_metrics_pass_and_each_metric_is_checked(self):
        self.assertTrue(self.compare()["passed"])
        for change, check in [
            ({"reattachment_x_over_h": 6.72}, "reattachment"),
            ({"reattachment_x_over_h": None}, "reattachment"),
            ({"cf_rmse": 4.3e-4}, "cf_rmse"),
            ({"profile_rmse": {"1": 0.0451, "4": 0.0646}}, "profile_rmse"),
            ({"maximum_y_plus": {"stepWall": 0.98, "lowerWall": 0.484}}, "y_plus"),
            ({"maximum_y_plus": {"stepWall": 0.963}}, "y_plus"),
            ({"screen_passed": None}, "audit_and_screen"),
            ({"audit_passed": False}, "audit_and_screen"),
        ]:
            result = self.compare({**self.metrics, **change})
            self.assertFalse(result["checks"][check], check)
            self.assertFalse(result["passed"])

    def test_turbulence_fields_and_measurements_are_required(self):
        fields = {
            **self.fields,
            "nut": {"maximum_absolute": 1, "maximum_over_control_maximum": 2e-3},
        }
        self.assertFalse(self.compare(fields=fields)["checks"]["turbulence"])
        with self.assertRaisesRegex(ValueError, "CFD-X013 comparison.data"):
            self.compare(data=None)
        with self.assertRaisesRegex(ValueError, "CFD-X013 comparison.mode"):
            compare_restart.compare(self.root, self.root, "nearby")

    def test_the_command_lines_exit_one_for_invalid_input(self):
        for script, args in [
            (
                "compare_restart.py",
                [
                    "--run",
                    self.root / "missing",
                    "--control",
                    self.root / "missing",
                    "--mode",
                    "converged",
                    "--output",
                    self.root / "out.json",
                ],
            ),
            (
                "restart_equivalence.py",
                [
                    "--case",
                    "cavity",
                    "--first",
                    "50",
                    "--second",
                    "50",
                    "--foam-root",
                    self.root,
                    "--output",
                    self.root,
                ],
            ),
        ]:
            result = subprocess.run(
                [sys.executable, str(ROOT / "validation" / script), *map(str, args)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(
                result.returncode, 1, (script, result.stdout, result.stderr)
            )
            self.assertIn("CFD-", result.stdout)


class Equivalence(unittest.TestCase):
    """The fixed-work driver's sequence and verdicts, with mocked runs."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-restart-equivalence-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def experiment(self, status="completed", passed=True, second=250):
        record = {
            "execution_status": status,
            "numerical": {"iterations": 250} if status == "completed" else None,
            "wall_s": 1.0,
        }
        with (
            patch.object(backend, "prepare") as prepare,
            patch.object(backend, "run", return_value=record) as run,
            patch.object(restart, "prepare") as continued,
            patch.object(
                restart_equivalence, "compare", return_value={"passed": passed}
            ) as compare,
        ):
            report = restart_equivalence.experiment(
                "backstep",
                "simple",
                250,
                second,
                self.root,
                self.root / "x",
                self.root,
                600,
            )
        return report, prepare, run, continued, compare

    def test_source_split_and_control_are_compared_at_equal_work(self):
        report, prepare, run, continued, compare = self.experiment(second=300)
        self.assertTrue(report["passed"])
        self.assertEqual([c.args[2] for c in prepare.call_args_list], [250, 550])
        self.assertEqual(
            [c.args[1].name for c in run.call_args_list],
            ["source", "split", "continuous"],
        )
        self.assertEqual(continued.call_args.args[1], 300)
        self.assertEqual(compare.call_args.args[2], "fixed-work")
        self.assertEqual(
            json.loads((self.root / "x/report.json").read_text())["solver_profile"],
            "simple",
        )
        self.assertFalse(self.experiment_in("y", passed=False)["passed"])

    def experiment_in(self, name, **kwargs):
        shutil.rmtree(self.root / "x", ignore_errors=True)
        return self.experiment(**kwargs)[0]

    def test_an_incomplete_stage_is_an_error_without_a_comparison(self):
        report = self.experiment(status="timeout")[0]
        self.assertFalse(report["passed"])
        self.assertIn("CFD-X013 comparison.source", report["error"])
        self.assertNotIn("comparison", report)


@unittest.skipUnless(
    os.environ.get("CFD_OPENFOAM_ROOT"),
    "set CFD_OPENFOAM_ROOT for actual restart verification",
)
class ActualRestart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="cfd-real-restart-")
        cls.root = Path(cls.temp.name)
        cls.foam = Path(os.environ["CFD_OPENFOAM_ROOT"])
        backend.prepare("cavity", 1, 400, cls.root / "source-input")
        cls.source = cls.root / "source"
        cls.record = backend.run(
            cls.root / "source-input", cls.source, cls.foam, timeout_s=60
        )
        if cls.record["execution_status"] != "completed":
            raise ValueError(cls.record.get("error"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.directory = self.root / self._testMethodName
        self.directory.mkdir()

    def test_nonmultiple_limit_has_final_fields_and_split_work_matches_continuous(self):
        self.assertTrue((self.source / "case/400/U").is_file())
        prepared = self.directory / "input"
        definition = restart.prepare(self.source, 200, prepared)
        run = self.directory / "split"
        result = backend.run(prepared, run, self.foam, timeout_s=60)
        self.assertEqual(result["execution_status"], "completed", result.get("error"))
        self.assertFalse(result["passed"])
        self.assertFalse(backend.verify(run)["passed"])
        self.assertTrue(audit(run)["passed"])
        backend.prepare("cavity", 1, 600, self.directory / "continuous-input")
        continuous = backend.run(
            self.directory / "continuous-input",
            self.directory / "continuous",
            self.foam,
            timeout_s=60,
        )
        self.assertEqual(continuous["execution_status"], "completed")
        self.assertEqual(
            definition["initial_state"]["source_completed_iterations"], 400
        )
        result = compare_restart.compare(
            run, self.directory / "continuous", "fixed-work"
        )
        self.assertTrue(result["passed"], result["checks"])
        for name in ["U", "p"]:
            x = np.array(
                backend.internal_values(run / "case/200" / name, 576, name == "U")
            )
            y = np.array(
                backend.internal_values(
                    self.directory / "continuous/case/600" / name, 576, name == "U"
                )
            )
            if name == "p":
                x = x - x.mean()
                y = y - y.mean()
            self.assertLess(max(abs(x - y)), 1e-6)

    def test_a_restart_reaches_the_unchanged_numerical_gate(self):
        prepared = self.directory / "input"
        restart.prepare(self.source, 1000, prepared)
        result = backend.run(prepared, self.directory / "run", self.foam, timeout_s=60)
        self.assertTrue(result["passed"], result.get("error"))
        self.assertTrue(backend.verify(self.directory / "run")["passed"])
        self.assertTrue(audit(self.directory / "run")["passed"])
        self.assertGreater(
            result["initial_state"]["source_completed_iterations"]
            + result["numerical"]["iterations"],
            400,
        )
        next_definition = restart.prepare(
            self.directory / "run", 50, self.directory / "next-input"
        )
        self.assertTrue(next_definition["initial_state"]["source_numerical_passed"])
        self.assertEqual(
            next_definition["initial_state"]["source_completed_iterations"],
            400 + result["numerical"]["iterations"],
        )

    def rejected(self, field):
        prepared = self.directory / "input"
        definition = restart.prepare(self.source, 200, prepared)
        if field == "runtime":
            definition["initial_state"]["source_runtime_sha256"] = "0" * 64
        else:
            definition["initial_state"]["source_mesh"]["points"]["sha256"] = "0" * 64
        backend.write_json(prepared / "case.json", definition)
        result = backend.run(prepared, self.directory / "run", self.foam, timeout_s=60)
        self.assertEqual(result["execution_status"], "failed")
        self.assertIn("CFD-X012 initial_state." + field, result["error"])
        self.assertFalse(any(c["program"] == "foamRun" for c in result["commands"]))
        self.assertEqual(
            backend.verify(self.directory / "run")["error"], result["error"]
        )

    def test_runtime_mismatch_stops_before_solving_and_retains_a_verifiable_failure(
        self,
    ):
        self.rejected("runtime")

    def test_mesh_mismatch_stops_before_solving_and_retains_a_verifiable_failure(self):
        self.rejected("mesh")

    def test_corrupted_source_is_rejected_before_creating_an_input(self):
        source = self.directory / "corrupted"
        shutil.copytree(self.source, source)
        with (source / "case/400/U").open("a") as stream:
            stream.write("// changed\n")
        with self.assertRaisesRegex(ValueError, "CFD-X006 archive.files"):
            restart.prepare(source, 200, self.directory / "input")
        self.assertFalse((self.directory / "input").exists())

    def test_resealed_bad_local_flux_is_rejected_before_copying(self):
        source = self.directory / "corrupted"
        shutil.copytree(self.source, source)
        path = source / "case/400/phi"
        text = path.read_text()
        match = re.search(
            r"(internalField\s+nonuniform\s+List<scalar>\s+\d+\s*\(\s*)("
            + backend.NUMBER
            + ")",
            text,
        )
        self.assertIsNotNone(match)
        path.write_text(
            text[: match.start(2)] + str(float(match[2]) + 0.01) + text[match.end(2) :]
        )
        reseal(source)
        backend.verify(source)
        with self.assertRaisesRegex(
            restart.IneligibleSource, "CFD-X012 initial_state.phi.local_continuity"
        ):
            restart.prepare(source, 200, self.directory / "input")
        self.assertFalse((self.directory / "input").exists())

    def test_a_converged_chain_reproduces_the_converged_control(self):
        backend.prepare("cavity", 1, 3000, self.directory / "control-input")
        control = backend.run(
            self.directory / "control-input",
            self.directory / "control",
            self.foam,
            timeout_s=60,
        )
        self.assertTrue(control["passed"], control.get("error"))
        restart.prepare(self.source, 3000, self.directory / "input")
        chain = backend.run(
            self.directory / "input", self.directory / "chain", self.foam, timeout_s=60
        )
        self.assertTrue(chain["passed"], chain.get("error"))
        result = compare_restart.compare(
            self.directory / "chain", self.directory / "control", "converged"
        )
        self.assertTrue(result["passed"], result["checks"])
        # Same cumulative work; the fields agree to round-off.
        self.assertEqual(result["work"]["run"], result["work"]["control"])
        for name in ["U", "p"]:
            self.assertLess(result["fields"][name]["maximum_absolute"], 1e-10)


if __name__ == "__main__":
    unittest.main()
