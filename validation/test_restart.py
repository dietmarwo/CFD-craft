#!/usr/bin/env python3
"""Steady restart boundaries and actual cavity equivalence.

Unit receipts and workflow returns are synthetic, never CFD evidence. Set
CFD_OPENFOAM_ROOT for the real Foundation-13 field/rejection tests.
"""

import copy
import os
import re
import shutil
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
from audit_openfoam_mesh import audit
from external_notices import backstep_lines


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
        (snapshot / "phi").write_text("internalField uniform 0; // synthetic fixture\n")
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
        for steps in [50, 100, 251, 400, 600, 1234, 6000, 19997, 20000]:
            interval = backend.snapshot_interval(steps)
            self.assertEqual(steps % interval, 0)
            self.assertLessEqual(interval, 250)
        self.assertEqual(backend.snapshot_interval(6000), 250)
        self.assertEqual(backend.snapshot_interval(20000), 250)

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
        mutations = [
            lambda d: d.update(initial_state=None),
            lambda d: d["initial_state"].update(source_time="../2"),
            lambda d: d["initial_state"].update(source_completed_iterations=True),
            lambda d: d["initial_state"]["source_fields"].pop("phi"),
            lambda d: d["initial_state"]["source_mesh"].pop("points"),
            lambda d: d["initial_state"].update(source_runtime_sha256="bad"),
        ]
        for mutate in mutations:
            definition = copy.deepcopy(good)
            mutate(definition)
            with self.assertRaisesRegex(ValueError, "CFD-X012"):
                restart.validate(self.root / "input", definition)

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

    def execution(self, passed=False, status="completed", steps=50):
        return {
            "passed": passed,
            "execution_status": status,
            "numerical": {"passed": passed, "iterations": steps}
            if status == "completed"
            else None,
            "progress": {"started_iterations": steps},
        }

    def run_study(self, results, preset="smoke", restart_error=None):
        with (
            patch.object(
                backstep_resolution,
                "load",
                return_value={"raw_sha256": {"fixture": "synthetic"}},
            ),
            patch.object(backend, "prepare"),
            patch.object(backend, "run", side_effect=results) as run,
            patch.object(
                backstep_resolution, "prepare_restart", side_effect=restart_error
            ) as prepare_restart,
            patch.object(
                backstep_resolution,
                "audit",
                return_value={"status": "evaluated", "passed": True},
            ),
            patch.object(
                backstep_resolution,
                "assess",
                return_value={"status": "evaluated", "passed": results[-1]["passed"]},
            ) as assess,
            patch.object(backstep_resolution, "save"),
        ):
            report = backstep_resolution.study(
                self.root, self.root / "study", self.root, preset=preset, max_stages=3
            )
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
        self.assertIn(
            "stages 2; completed solver iterations across stages 100; started 100",
            backstep_lines({**row, "comparison": {"status": "not_assessed"}}),
        )
        self.assertEqual(
            assess.call_args.args[0].name, "wall-resolved-simplec-level1-stage2"
        )
        self.assertEqual(
            prepared.call_args.args[0].name, "wall-resolved-simplec-level1"
        )

    def test_stages_keep_iteration_limit_results_and_stop_at_the_stage_budget(self):
        report, run, prepared, _ = self.run_study([self.execution()] * 3)
        self.assertTrue(report["workflow_completed"])
        self.assertFalse(report["passed"])
        self.assertEqual(run.call_count, 3)
        self.assertEqual(prepared.call_count, 2)
        self.assertEqual(report["rows"][0]["completed_solver_iterations"], 150)

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
            self.assertTrue(
                all(
                    r.get("reason") == "coarser_level_not_accepted"
                    for r in report["rows"][1:]
                )
            )

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
        self.assertFalse((self.root / "unused").exists())

    def test_a_failed_source_flux_gate_is_unaccepted_evidence_and_skips_refinement(
        self,
    ):
        report, run, _, _ = self.run_study(
            [self.execution()],
            preset="study",
            restart_error=ValueError(
                "CFD-X012 initial_state.phi.local_continuity: synthetic gate failure"
            ),
        )
        self.assertTrue(report["workflow_completed"])
        self.assertFalse(report["passed"])
        self.assertNotIn("error", report)
        self.assertEqual(run.call_count, 1)
        self.assertIn("local_continuity", report["rows"][0]["continuation_stop_reason"])
        self.assertTrue(
            all(
                r.get("reason") == "coarser_level_not_accepted"
                for r in report["rows"][1:]
            )
        )


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
            ValueError, "CFD-X012 initial_state.phi.local_continuity"
        ):
            restart.prepare(source, 200, self.directory / "input")
        self.assertFalse((self.directory / "input").exists())


if __name__ == "__main__":
    unittest.main()
