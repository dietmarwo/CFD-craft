#!/usr/bin/env python3
"""Campaign boundaries plus real Foundation-13 mapped/continued cavity runs.

Mocked workflow records below are synthetic control-flow tests, not CFD evidence.
Set CFD_OPENFOAM_ROOT to exercise the actual solver and complete archives.
"""

import contextlib
import copy
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "integrations"), str(ROOT / "validation")]
import openfoam_backend as backend
import openfoam_restart as restart
import refinement_campaign as campaign
import external_notices


class Boundaries(unittest.TestCase):
    def test_ci_archive_keeps_empty_directories_and_original_bytes(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        step = re.search(
            r"(?ms)^      - name: Archive complete refinement evidence\n.*?"
            r"        run: \|\n(.*?)(?=^      - uses: actions/upload-artifact)",
            workflow,
        )
        self.assertIsNotNone(step, "CI must preserve complete evidence before upload")
        with tempfile.TemporaryDirectory(prefix="cfd-refinement-ci-zip-") as tmp:
            root = Path(tmp)
            source = root / "runs/refinement-campaign"
            (source / "case/500/uniform").mkdir(parents=True)
            blob = b'{"controlled_fixture": "not CFD evidence"}\n'
            (source / "report.json").write_bytes(blob)
            process = subprocess.run(
                ["bash", "-c", textwrap.dedent(step[1])],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=20,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            with zipfile.ZipFile(
                root / "runs/refinement-campaign-evidence.zip"
            ) as archive:
                self.assertIsNone(archive.testzip())
                archive.extractall(root / "extracted")
            copied = root / "extracted/refinement-campaign"
            self.assertTrue((copied / "case/500/uniform").is_dir())
            self.assertEqual(list((copied / "case/500/uniform").iterdir()), [])
            self.assertEqual((copied / "report.json").read_bytes(), blob)
            self.assertEqual((source / "report.json").read_bytes(), blob)
            archive_path = root / "runs/refinement-campaign-evidence.zip"
            before = archive_path.read_bytes()
            (root / "outside").write_text("outside the campaign; never serialize")
            (source / "linked").symlink_to(root / "outside")
            rejected = subprocess.run(
                ["bash", "-c", textwrap.dedent(step[1])],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=20,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("CFD-X015 refinement.archive.linked", rejected.stderr)
            self.assertEqual(archive_path.read_bytes(), before)

    def test_invalid_limits_are_coded_and_do_not_create_an_output(self):
        defaults = [3000, 4, 3500, 900, 1024, 4096]
        for index, value in [
            (0, True),
            (0, 49),
            (0, 251),
            (0, 20001),
            (1, 0),
            (1, 9),
            (1, 1.0),
            (2, float("nan")),
            (2, float("inf")),
            (2, True),
            (2, 3601),
            (3, 0),
            (4, 2049),
            (5, 255),
        ]:
            args = defaults.copy()
            args[index] = value
            with (
                self.subTest(index=index, value=value),
                self.assertRaisesRegex(ValueError, "CFD-X015 refinement"),
            ):
                campaign.limits(*args)

    def test_supported_stage_cadences_and_all_limits_are_recorded(self):
        found = campaign.limits(4000, 3, 3500, 900, 1024, 4096)
        self.assertEqual(found["iterations_per_stage"], 4000)
        self.assertEqual(found["max_stages"], 3)
        self.assertEqual(found["wall_s_per_stage"], 3500)
        self.assertEqual(found["preparation_wall_s"], 900)
        self.assertEqual(found["output_mib_per_stage"], 1024)
        self.assertEqual(found["child_address_space_mib"], 4096)

    def test_exit_codes_distinguish_workflow_errors_from_unaccepted_evidence(self):
        for report, expected in [
            ({"passed": True}, 0),
            ({"passed": False}, 2),
            ({"passed": False, "stop_reason": "cancelled"}, 2),
            ({"passed": False, "error": "CFD-X015 x: invalid"}, 1),
        ]:
            with (
                patch.object(campaign, "campaign", return_value=report),
                patch.object(
                    sys,
                    "argv",
                    ["x", "--source", "s", "--foam-root", "r", "--output", "o"],
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(campaign.main(), expected)

    def test_paired_velocity_identities_must_be_complete_unique_and_finite(self):
        rows = [
            {
                "station_x_over_h": 1,
                "sample_id": i,
                "y_over_h": i / 2,
                "predicted_u_over_u_ref": i / 3,
            }
            for i in [1, 2]
        ]
        first = {
            "comparison": {
                "paired_velocity_samples": rows,
                "reattachment": {"predicted_x_over_h": 6.7},
            }
        }
        for change in ["length", "identity", "duplicate", "nan"]:
            second = copy.deepcopy(first)
            values = second["comparison"]["paired_velocity_samples"]
            if change == "length":
                values.pop()
            elif change == "identity":
                values[0]["sample_id"] = 5
            elif change == "duplicate":
                values[1] = copy.deepcopy(values[0])
            else:
                values[0]["predicted_u_over_u_ref"] = float("nan")
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(ValueError, "CFD-X015 refinement.pair.samples"),
            ):
                campaign.paired_metrics(first, second)
        second = copy.deepcopy(first)
        second["comparison"]["paired_velocity_samples"][0][
            "predicted_u_over_u_ref"
        ] += 0.2
        second["comparison"]["reattachment"]["predicted_x_over_h"] = None
        result = campaign.paired_metrics(first, second)
        self.assertAlmostEqual(result["maximum_velocity_change_u_ref"], 0.2)
        self.assertIsNone(result["reattachment_change_h"])

    def test_cavity_pair_rejects_nonfinite_differences(self):
        first = {
            "comparison": {"sample_positions": [0.5], "predicted_u_over_u_ref": [0.1]}
        }
        second = copy.deepcopy(first)
        second["comparison"]["predicted_u_over_u_ref"] = [float("nan")]
        with self.assertRaisesRegex(ValueError, "CFD-X015 refinement.pair.samples"):
            campaign.paired_metrics(first, second)

    def test_ci_notice_exposes_unaccepted_stage_and_separate_work(self):
        report = {
            "schema_version": campaign.SCHEMA,
            "workflow_completed": True,
            "passed": False,
            "stop_reason": "stage_limit",
            "source_iterations": 18412,
            "completed_fine_iterations": 4000,
            "physical_qualification": False,
            "stages": [
                {
                    "stage": 1,
                    "execution": {
                        "execution_status": "completed",
                        "passed": False,
                        "numerical": {
                            "iterations": 4000,
                            "solver_reported_convergence": False,
                        },
                    },
                }
            ],
            "mesh_sensitivity": {"assessed": False, "passed": False},
        }
        with tempfile.TemporaryDirectory(prefix="cfd-refinement-notice-") as tmp:
            path = Path(tmp) / "report.json"
            backend.write_json(path, report)
            output = io.StringIO()
            with (
                patch.object(sys, "argv", ["notices", str(path), "fine campaign"]),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(external_notices.main(), 0)
        text = output.getvalue()
        for required in [
            "::notice title=fine campaign",
            "passed False",
            "stop stage_limit",
            "source iterations 18412",
            "completed fine iterations 4000",
            "converged False",
            "physical qualification False",
        ]:
            self.assertIn(required, text)

    def test_ci_notice_states_every_stage_check_and_metric(self):
        backstep = {
            "numerically_accepted": True,
            "independent": {"passed": True},
            "comparison": {
                "measurement_screen_passed": True,
                "reattachment": {"predicted_x_over_h": 6.7064},
                "skin_friction": {"rmse": 4.17e-4},
                "profiles": {"1": {"rmse_u_ref": 0.0449}},
            },
        }
        report = {
            "schema_version": campaign.SCHEMA,
            "stop_reason": "execution_timeout",
            "error": None,
            "started_fine_iterations": 4123,
            "source_rejection": None,
            "mesh_initialization": {"nearest_replay": {"other_candidate": 9600}},
            "coarse_observation": backstep,
            "stages": [
                {
                    "stage": 1,
                    "execution": {
                        "execution_status": "timeout",
                        "passed": False,
                        "error": "CFD-X004 execution.deadline: wall-time limit",
                        "progress": {"started_iterations": 4123},
                        "numerical": {
                            "iterations": 4000,
                            "initial_residuals_final_iteration": {"Uy": 1.04e-5},
                            "residual_trend": {
                                "p": {
                                    "median_last_window": 2.5e-6,
                                    "median_previous_window": 2.6e-6,
                                }
                            },
                        },
                    },
                    "observation": {
                        "status": "invalid",
                        "error": "CFD-X001 refinement.observation: centerline.xy",
                    },
                },
                {
                    "stage": 2,
                    "execution": {"execution_status": "completed", "numerical": {}},
                    "observation": {
                        "numerically_accepted": True,
                        "independent": {"passed": True},
                        "comparison": {"passed": True, "maximum_error": 0.00708},
                    },
                },
            ],
        }
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            external_notices.refinement(report, "fine campaign")
        text = printed.getvalue()
        for required in [
            "started 4123",
            '"other_candidate"%3A 9600',
            "coarse source%3A numerically accepted True; independent accepted True; "
            "observable check True",
            "coarse source%3A reattachment 6.7064 H; Cf RMSE 0.000417; profiles 1 0.0449",
            "stage 1%3A timeout; iterations 4000; started 4123",
            "error CFD-X004 execution.deadline%3A wall-time limit",
            '{"Uy"%3A 1.04e-05}; p median last/previous window 2.5e-06 / 2.6e-06',
            "stage 1%3A observation invalid%3A CFD-X001 refinement.observation",
            "stage 2%3A numerically accepted True; independent accepted True; "
            "observable check True",
            "stage 2%3A Ghia centerline error 0.00708",
        ]:
            self.assertIn(required, text.replace(":", "%3A"))


class ArchiveSnapshot(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-refinement-copy-")
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for name in ["a", "b"]:
            (self.source / name).write_text("synthetic snapshot bytes " + name)

    def tearDown(self):
        self.temp.cleanup()

    def test_snapshot_preserves_exact_bytes_and_checks_the_copy(self):
        with patch.object(backend, "verify", return_value={"fixture": True}) as verify:
            result = campaign.copy_archive(self.source, self.root / "copy", 10000)
        self.assertEqual(result, {"fixture": True})
        verify.assert_called_once_with(self.root / "copy")
        self.assertEqual(
            backend.inventory(self.source), backend.inventory(self.root / "copy")
        )

    def test_the_copy_must_be_the_archive_the_plan_froze(self):
        (self.source / "manifest.json").write_text("{}")
        frozen = backend.sha256(self.source / "manifest.json")
        with patch.object(backend, "verify", return_value={"fixture": True}):
            campaign.copy_archive(self.source, self.root / "copy", 10000, frozen)
            # The source was replaced after the plan was frozen.
            (self.source / "manifest.json").write_text('{"other": 1}')
            with self.assertRaisesRegex(ValueError, "refinement.source.manifest"):
                campaign.copy_archive(self.source, self.root / "other", 10000, frozen)

    def test_snapshot_budget_is_checked_before_copy_creation(self):
        with self.assertRaisesRegex(ValueError, "refinement.source.bytes"):
            campaign.copy_archive(self.source, self.root / "copy", 1)
        self.assertFalse((self.root / "copy").exists())

    def test_source_copy_race_is_rejected(self):
        original = Path.read_bytes
        reads = 0

        def race(path):
            nonlocal reads
            blob = original(path)
            if path == self.source / "a":
                reads += 1
                if reads == 2:
                    (self.source / "b").write_text("changed")
            return blob

        with (
            patch.object(Path, "read_bytes", race),
            self.assertRaisesRegex(ValueError, "refinement.source.copy.b"),
        ):
            campaign.copy_archive(self.source, self.root / "copy", 10000)

    def test_new_source_file_after_copy_is_rejected(self):
        original = backend.inventory
        calls = 0

        def changed(path, *args, **kwargs):
            nonlocal calls
            if Path(path) == self.source:
                calls += 1
                if calls == 2:
                    (self.source / "late").write_text("late writer")
            return original(path, *args, **kwargs)

        with (
            patch.object(backend, "inventory", side_effect=changed),
            self.assertRaisesRegex(ValueError, "refinement.source.inventory"),
        ):
            campaign.copy_archive(self.source, self.root / "copy", 10000)


class ParentChain(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-refinement-lineage-")
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.runs = [self.root / "first", self.root / "second"]
        self.records = {}
        self.jobs = {}
        for i, path in enumerate([self.source, *self.runs]):
            (path / "case").mkdir(parents=True)
            entries = {"synthetic": i}
            if i == 1:
                entries = {
                    f"case/400/{name}": {"bytes": 1, "sha256": str(k) * 64}
                    for k, name in enumerate(["U", "p", "phi"], 1)
                }
                entries.update(
                    {
                        "case/constant/polyMesh/" + name: {
                            "bytes": 2,
                            "sha256": "b" * 64,
                        }
                        for name in restart.MESH_FILES
                    }
                )
            backend.write_json(path / "manifest.json", {"files": entries})
            self.records[path] = {
                "case": "cavity",
                "case_sha256": str(i) * 64,
                "passed": i == 0,
                "runtime": {"fixture": "runtime"},
                "numerical": {
                    "iterations": 696 if i == 0 else 400,
                    "final_time_directory": "696" if i == 0 else "400",
                },
            }
            self.jobs[path] = {"level": 1 if i == 0 else 2}
        self.jobs[self.runs[0]]["mesh_initialization"] = {
            "source_manifest_sha256": backend.sha256(self.source / "manifest.json"),
            "source_case_sha256": self.records[self.source]["case_sha256"],
            "source_iterations": 696,
        }
        entries = json.loads((self.runs[0] / "manifest.json").read_text())["files"]
        self.jobs[self.runs[1]]["initial_state"] = {
            "source_manifest_sha256": backend.sha256(self.runs[0] / "manifest.json"),
            "source_case_sha256": self.records[self.runs[0]]["case_sha256"],
            "source_completed_iterations": 400,
            "source_time": "400",
            "source_numerical_passed": False,
            "source_runtime_sha256": restart.identity(
                self.records[self.runs[0]]["runtime"]
            ),
            "source_fields": {n: entries["case/400/" + n] for n in ["U", "p", "phi"]},
            "source_mesh": {
                n: entries["case/constant/polyMesh/" + n] for n in restart.MESH_FILES
            },
        }
        self.write()

    def write(self):
        for path, job in self.jobs.items():
            backend.write_json(path / "case/case.json", job)

    def tearDown(self):
        self.temp.cleanup()

    def check(self):
        with patch.object(
            backend, "verify", side_effect=lambda p: self.records[Path(p)]
        ):
            return campaign.lineage(self.source, self.runs)

    def test_coarse_work_is_not_counted_as_fine_work(self):
        total, records = self.check()
        self.assertEqual(total, 800)
        self.assertEqual(len(records), len(self.runs))

    def test_resealed_parent_receipt_mismatches_are_rejected(self):
        state = self.jobs[self.runs[1]]["initial_state"]
        for key, value in [
            ("source_manifest_sha256", "f" * 64),
            ("source_case_sha256", "f" * 64),
            ("source_completed_iterations", 1096),
            ("source_time", "250"),
            ("source_numerical_passed", True),
            ("source_runtime_sha256", "f" * 64),
        ]:
            old = state[key]
            state[key] = value
            self.write()
            with (
                self.subTest(field=key),
                self.assertRaisesRegex(ValueError, "refinement.stages\\[2\\].parent"),
            ):
                self.check()
            state[key] = old
        self.write()

    def test_parent_field_and_mesh_hashes_must_match_retained_archive(self):
        state = self.jobs[self.runs[1]]["initial_state"]
        for name in ["source_fields", "source_mesh"]:
            key = next(iter(state[name]))
            old = state[name][key]
            state[name][key] = {"bytes": 8, "sha256": "f" * 64}
            self.write()
            with (
                self.subTest(kind=name),
                self.assertRaisesRegex(ValueError, "refinement.stages\\[2\\].parent"),
            ):
                self.check()
            state[name][key] = old
        self.write()

    def test_first_mapping_must_bind_retained_coarse_archive(self):
        self.jobs[self.runs[0]]["mesh_initialization"]["source_iterations"] = 800
        self.write()
        with self.assertRaisesRegex(ValueError, "refinement.stages\\[1\\].parent"):
            self.check()


class Checkpoints(ParentChain):
    """checkpoint() on the parent-chain fixture: identities, summaries, producers."""

    def report(self):
        return {
            "plan": {
                "implementation_sha256": {
                    name: backend.sha256(path)
                    for name, path in campaign.producers().items()
                }
            },
            "stages": [
                {"run_directory": p.name, "execution": copy.deepcopy(self.records[p])}
                for p in self.runs
            ],
            "archive_checkpoints": [],
        }

    def checkpoint(self, report, label="final_collection"):
        with patch.object(
            backend, "verify", side_effect=lambda p: self.records[Path(p)]
        ):
            campaign.checkpoint(self.root, report, label)

    def test_a_checkpoint_records_work_and_every_archive(self):
        report = self.report()
        self.checkpoint(report, "stage_2_returned")
        self.assertEqual(report["completed_fine_iterations"], 800)
        entry = report["archive_checkpoints"][-1]
        self.assertEqual(entry["label"], "stage_2_returned")
        self.assertEqual(
            [a["directory"] for a in entry["archives"]], ["source", "first", "second"]
        )
        saved = json.loads((self.root / "report.json").read_text())
        self.assertEqual(saved["completed_fine_iterations"], 800)

    def test_an_archive_resealed_between_checkpoints_is_rejected(self):
        report = self.report()
        self.checkpoint(report, "stage_2_returned")
        # The last stage is bound by no child receipt; its manifest is.
        backend.write_json(self.runs[1] / "manifest.json", {"files": {"resealed": 1}})
        with self.assertRaisesRegex(
            ValueError,
            "CFD-X015 refinement.archives.final_collection: "
            "CFD-X015 refinement.archives.second: archive changed",
        ):
            self.checkpoint(report)

    def test_the_sealed_summary_must_state_what_the_run_returned(self):
        for key, value in [
            ("passed", True),
            ("execution_status", "timeout"),
            ("error", "CFD-X007 numerical: not reached"),
            ("numerical", {"iterations": 401, "final_time_directory": "400"}),
        ]:
            report = self.report()
            report["stages"][0]["execution"][key] = value
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(
                    ValueError, "refinement.stages\\[1\\].summary." + key
                ),
            ):
                self.checkpoint(report)

    def test_stages_and_producers_must_be_the_frozen_implementation(self):
        self.records[self.runs[0]]["implementation_sha256"] = {
            "openfoam_backend.py": "0" * 64
        }
        report = self.report()
        with self.assertRaisesRegex(
            ValueError, "refinement.stages\\[1\\].implementation.openfoam_backend.py"
        ):
            self.checkpoint(report)
        self.records[self.runs[0]].pop("implementation_sha256")
        report = self.report()
        report["plan"]["implementation_sha256"]["refinement_campaign.py"] = "0" * 64
        with self.assertRaisesRegex(
            ValueError, "refinement.plan.implementation.refinement_campaign.py"
        ):
            self.checkpoint(report)


class Workflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-refinement-workflow-")
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        (self.source / "case").mkdir(parents=True)
        backend.write_json(self.source / "case/case.json", {"level": 1})
        backend.write_json(self.source / "manifest.json", {"fixture": "synthetic"})
        self.parent = {
            "passed": True,
            "execution_status": "completed",
            "case": "cavity",
            "case_sha256": "a" * 64,
            "numerical": {"iterations": 696},
        }

    def tearDown(self):
        self.temp.cleanup()

    def run_campaign(
        self,
        records,
        observed=None,
        restart_error=None,
        mapping_error=None,
        observe=None,
        checkpoint=None,
        stop=None,
    ):
        found = observed or {"accepted": False, "passed": False}
        accepted_source = {
            "accepted": True,
            "passed": True,
            "independent": {"passed": True},
        }

        def observation(run, data):
            return accepted_source if Path(run) == self.source else found

        with (
            patch.object(backend, "verify", return_value=self.parent),
            patch.object(campaign, "audit", return_value={"passed": True}),
            patch.object(campaign, "copy_archive"),
            patch.object(campaign, "checkpoint", side_effect=checkpoint),
            patch.object(campaign, "observation", side_effect=observe or observation),
            patch.object(backend, "Stop", return_value=stop or backend.Stop()),
            patch.object(
                campaign, "mesh_pair", return_value={"passed": found["passed"]}
            ),
            patch.object(
                campaign.mapping,
                "prepare",
                return_value={"mesh_initialization": {"fixture": True}},
                side_effect=mapping_error,
            ),
            patch.object(restart, "prepare", side_effect=restart_error) as prepare,
            patch.object(backend, "run", side_effect=records) as run,
        ):
            report = campaign.campaign(
                self.source,
                self.root,
                self.output,
                iterations=400,
                max_stages=3,
                timeout_s=60,
            )
        return report, run, prepare

    @property
    def output(self):
        # A fresh output for every campaign in one test, so subtests stay independent.
        self.calls = getattr(self, "calls", 0) + 1
        return self.root / f"out-{self.calls}"

    def test_iteration_limited_completed_stages_continue_to_declared_limit(self):
        r = {
            "execution_status": "completed",
            "passed": False,
            "numerical": {"solver_reported_convergence": False},
        }
        report, run, prepare = self.run_campaign([r, r, r])
        self.assertEqual(run.call_count, 3)
        self.assertEqual(prepare.call_count, 2)
        self.assertEqual(report["stop_reason"], "stage_limit")
        self.assertFalse(report["passed"])
        self.assertTrue(report["workflow_completed"])

    def test_converged_but_unaccepted_stage_is_not_restarted(self):
        r = {
            "execution_status": "completed",
            "passed": False,
            "numerical": {"solver_reported_convergence": True},
        }
        report, run, prepare = self.run_campaign([r])
        self.assertEqual(run.call_count, 1)
        prepare.assert_not_called()
        self.assertEqual(
            report["stop_reason"], "converged_without_numerical_acceptance"
        )

    def test_numerical_convergence_does_not_override_independent_or_measurement_failure(
        self,
    ):
        r = {
            "execution_status": "completed",
            "passed": True,
            "numerical": {"solver_reported_convergence": True},
        }
        for observation, reason in [
            (
                {"accepted": False, "passed": False},
                "converged_without_independent_acceptance",
            ),
            ({"accepted": True, "passed": False}, "measurement_screen_failed"),
        ]:
            with self.subTest(reason=reason):
                report, run, prepare = self.run_campaign([r], observation)
                self.assertEqual(report["stop_reason"], reason)
                self.assertFalse(report["passed"])
                prepare.assert_not_called()

    def test_timeout_is_retained_and_never_continued(self):
        r = {"execution_status": "timeout", "passed": False, "numerical": None}
        report, run, prepare = self.run_campaign([r])
        self.assertEqual(report["stop_reason"], "execution_timeout")
        self.assertEqual(len(report["stages"]), 1)
        prepare.assert_not_called()

    def test_source_flux_rejection_is_evidence_not_workflow_error(self):
        r = {
            "execution_status": "completed",
            "passed": False,
            "numerical": {"solver_reported_convergence": False},
        }
        report, run, prepare = self.run_campaign(
            [r],
            restart_error=restart.IneligibleSource(
                "CFD-X012 initial_state.phi.local_continuity: rejected"
            ),
        )
        self.assertEqual(run.call_count, 1)
        self.assertEqual(report["stop_reason"], "source_ineligible")
        self.assertIn("CFD-X012", report["source_rejection"])
        self.assertNotIn("error", report)
        self.assertEqual(campaign.exit_code(report), 2)

    def test_cancelled_mapping_retains_report_and_starts_no_stage(self):
        def cancelled(*args, **kwargs):
            kwargs["stop"].cancelled = True
            backend.require(False, "execution.cancel", "cancelled", "CFD-X008")

        report, run, prepare = self.run_campaign([], mapping_error=cancelled)
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertIn("CFD-X008", report["cancellation_diagnostic"])
        self.assertFalse(report["workflow_completed"])
        self.assertFalse(report["passed"])
        saved = json.loads((self.root / f"out-{self.calls}/report.json").read_text())
        self.assertEqual(saved["stop_reason"], "cancelled")
        self.assertEqual(saved["phase"], "finished")
        self.assertEqual(campaign.exit_code(report), 2)
        run.assert_not_called()
        prepare.assert_not_called()

    def test_cancel_after_completed_solve_cannot_report_accepted_campaign(self):
        def cancelled(*args, **kwargs):
            kwargs["stop"].cancelled = True
            return {
                "execution_status": "completed",
                "passed": True,
                "numerical": {"solver_reported_convergence": True},
            }

        report, run, prepare = self.run_campaign(
            cancelled, {"accepted": True, "passed": True}
        )
        self.assertEqual(run.call_count, 1)
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertFalse(report["passed"])
        self.assertFalse(report["workflow_completed"])
        self.assertEqual(campaign.exit_code(report), 2)
        prepare.assert_not_called()

    def test_a_failed_observation_of_a_returned_stage_is_evidence(self):
        # The solver finished near the deadline; sampling then timed out.
        r = {
            "execution_status": "timeout",
            "passed": False,
            "numerical": {"solver_reported_convergence": False},
        }
        source = {"accepted": True, "passed": True, "independent": {"passed": True}}

        def observation(run, data):
            if Path(run) == self.source:
                return source
            raise FileNotFoundError(2, "No such file", "centerline.xy")

        report, run, prepare = self.run_campaign([r], observe=observation)
        self.assertEqual(report["stop_reason"], "execution_timeout")
        self.assertNotIn("error", report)
        self.assertEqual(campaign.exit_code(report), 2)
        stage = report["stages"][0]["observation"]
        self.assertEqual(stage["status"], "invalid")
        self.assertIn("centerline.xy", stage["error"])

    def test_an_integrity_error_after_a_cancellation_stays_an_error(self):
        stop = backend.Stop()
        calls = []

        def checkpoint(output, report, label):
            calls.append(label)
            if label == "stage_1_returned":
                stop.cancelled = True
                raise ValueError(
                    "CFD-X015 refinement.archives.stage_1_returned: "
                    "CFD-X006 archive.files: changed, missing or additional files"
                )

        r = {
            "execution_status": "completed",
            "passed": False,
            "numerical": {"solver_reported_convergence": False},
        }
        report, run, prepare = self.run_campaign([r], checkpoint=checkpoint, stop=stop)
        self.assertEqual(report["stop_reason"], "workflow_error")
        self.assertIn("CFD-X006 archive.files", report["error"])
        self.assertNotIn("cancellation_diagnostic", report)
        self.assertFalse(report["workflow_completed"])
        self.assertEqual(campaign.exit_code(report), 1)

    def test_started_fine_iterations_include_a_stopped_stage(self):
        r = {
            "execution_status": "completed",
            "passed": False,
            "numerical": {"solver_reported_convergence": False},
            "progress": {"started_iterations": 400},
        }
        stopped = {
            "execution_status": "timeout",
            "passed": False,
            "numerical": None,
            "progress": {"started_iterations": 123},
        }
        report, run, prepare = self.run_campaign([r, stopped])
        self.assertEqual(report["started_fine_iterations"], 523)

    def test_a_source_that_fails_its_screen_is_rejected_before_output(self):
        for found, field in [
            (
                {"accepted": False, "passed": False, "independent": {"passed": False}},
                "source.audit",
            ),
            (
                {"accepted": True, "passed": False, "independent": {"passed": True}},
                "source.screen",
            ),
        ]:
            output = self.root / ("screen-" + field)
            with (
                patch.object(backend, "verify", return_value=self.parent),
                patch.object(campaign, "observation", return_value=found),
                self.assertRaisesRegex(ValueError, "CFD-X015 refinement." + field),
            ):
                campaign.campaign(self.source, self.root, output)
            self.assertFalse(output.exists())

    def test_an_output_inside_the_source_is_rejected_before_creation(self):
        for output in [self.source / "campaign", self.root]:
            with self.assertRaisesRegex(ValueError, "CFD-X015 refinement.output"):
                campaign.campaign(self.source, self.root, output)
        self.assertFalse((self.source / "campaign").exists())

    def test_an_unreadable_source_record_is_coded(self):
        backend.write_json(self.source / "case/case.json", {})
        with (
            patch.object(backend, "verify", return_value=self.parent),
            self.assertRaisesRegex(ValueError, "CFD-X015 refinement.source: "),
        ):
            campaign.campaign(self.source, self.root, self.root / "never")
        self.assertFalse((self.root / "never").exists())

    def test_nonreference_backstep_is_rejected_before_creating_output(self):
        self.parent["case"] = "backstep"
        backend.write_json(
            self.source / "case/case.json",
            {
                "level": 1,
                "metadata": {"mesh_family": "legacy", "solver_profile": "legacy"},
            },
        )
        with (
            patch.object(backend, "verify", return_value=self.parent),
            self.assertRaisesRegex(ValueError, "CFD-X015 refinement.source.recipe"),
        ):
            campaign.campaign(self.source, self.root, self.root / "out", data=self.root)
        self.assertFalse((self.root / "out").exists())


class MeshPair(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-refinement-pair-")
        self.root = Path(self.temp.name)
        self.paths = [self.root / name for name in ["coarse", "fine"]]
        for level, path in enumerate(self.paths, 1):
            (path / "case").mkdir(parents=True)
            backend.write_json(
                path / "case/case.json",
                {"level": level, "metadata": {"reynolds": 100}, "inputs": {}},
            )

    def tearDown(self):
        self.temp.cleanup()

    def compare(self, observations):
        with (
            patch.object(
                backend,
                "verify",
                return_value={"case": "cavity", "runtime": {"fixture": True}},
            ),
            patch.object(campaign, "observation", side_effect=observations),
        ):
            return campaign.mesh_pair(*self.paths, None)

    def test_an_unaccepted_stage_is_not_compared_or_read(self):
        with (
            patch.object(backend, "verify", side_effect=KeyError("runtime")) as verify,
            patch.object(
                campaign,
                "observation",
                side_effect=[{"accepted": True}, {"accepted": False}],
            ),
        ):
            found = campaign.mesh_pair(*self.paths, None)
        self.assertEqual(found["status"], "not_assessed")
        verify.assert_not_called()

    def test_unaccepted_grid_does_not_enter_mesh_comparison(self):
        with patch.object(campaign, "paired_metrics") as compare:
            found = self.compare([{"accepted": True}, {"accepted": False}])
        self.assertFalse(found["assessed"])
        self.assertFalse(found["passed"])
        compare.assert_not_called()

    def test_large_change_is_reported_without_inventing_a_grid_convergence_gate(self):
        observations = [
            {
                "accepted": True,
                "passed": True,
                "comparison": {
                    "sample_positions": [0.2, 0.8],
                    "predicted_u_over_u_ref": x,
                },
            }
            for x in [[0.1, 0.5], [0.5, 0.9]]
        ]
        found = self.compare(observations)
        self.assertTrue(found["passed"])
        self.assertAlmostEqual(found["maximum_velocity_change_u_ref"], 0.4)
        self.assertFalse(found["physical_qualification"])
        self.assertIn("two grids", found["grid_convergence_estimate"])


@unittest.skipUnless(
    os.environ.get("CFD_OPENFOAM_ROOT"), "set CFD_OPENFOAM_ROOT for actual refinement"
)
class ActualRefinement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="cfd-refinement-actual-source-")
        cls.root = Path(cls.temp.name)
        cls.foam = Path(os.environ["CFD_OPENFOAM_ROOT"])
        backend.prepare("cavity", 1, 3000, cls.root / "input")
        cls.source = cls.root / "source"
        result = backend.run(cls.root / "input", cls.source, cls.foam, timeout_s=60)
        if not result["passed"]:
            raise RuntimeError("actual coarse cavity did not converge")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-refinement-actual-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_mapped_cavity_continues_to_accepted_two_grid_observations(self):
        report = campaign.campaign(
            self.source,
            self.foam,
            self.root / "campaign",
            iterations=400,
            max_stages=4,
            timeout_s=60,
            preparation_s=60,
        )
        self.assertTrue(report["passed"], report.get("error") or report["stop_reason"])
        self.assertEqual(report["stop_reason"], "accepted")
        self.assertGreater(len(report["stages"]), 1)
        self.assertEqual(
            report["completed_fine_iterations"],
            sum(s["execution"]["numerical"]["iterations"] for s in report["stages"]),
        )
        self.assertEqual(report["source_iterations"], 696)
        self.assertTrue(report["mesh_sensitivity"]["assessed"])
        self.assertFalse(report["physical_qualification"])
        last = report["stages"][-1]
        state = last["execution"]["initial_state"]
        self.assertEqual(
            state["source_completed_iterations"],
            sum(
                s["execution"]["numerical"]["iterations"] for s in report["stages"][:-1]
            ),
        )
        self.assertEqual(report["archive_checkpoints"][-1]["label"], "final_collection")
        for row in report["stages"]:
            backend.verify(self.root / "campaign" / row["run_directory"])

    def test_bounded_unconverged_cavity_is_retained_without_a_mesh_pair_claim(self):
        report = campaign.campaign(
            self.source,
            self.foam,
            self.root / "campaign",
            iterations=200,
            max_stages=1,
            timeout_s=60,
            preparation_s=60,
        )
        self.assertNotIn("error", report)
        self.assertEqual(report["stop_reason"], "stage_limit")
        self.assertEqual(report["completed_fine_iterations"], 200)
        self.assertFalse(report["mesh_sensitivity"]["assessed"])
        self.assertEqual(campaign.exit_code(report), 2)

    def test_post_seal_extra_time_directory_stops_the_campaign_without_resealing(self):
        run = backend.run

        def extra(*args, **kwargs):
            record = run(*args, **kwargs)
            path = Path(args[1])
            (path / "case/123").mkdir()
            (path / "case/123/U").write_text("late writer; deliberate test corruption")
            return record

        with patch.object(backend, "run", side_effect=extra):
            report = campaign.campaign(
                self.source,
                self.foam,
                self.root / "campaign",
                iterations=400,
                max_stages=3,
                timeout_s=60,
                preparation_s=60,
            )
        self.assertEqual(len(report["stages"]), 1)
        self.assertIn("CFD-X015 refinement.archives.stage_1_returned", report["error"])
        self.assertIn("CFD-X006", report["error"])
        self.assertTrue((self.root / "campaign/stage-01/case/123/U").exists())
        self.assertFalse(report["passed"])
        self.assertEqual(campaign.exit_code(report), 1)

    def test_occupied_campaign_output_is_not_overwritten(self):
        output = self.root / "occupied"
        output.mkdir()
        (output / "keep").write_text("keep")
        with self.assertRaisesRegex(ValueError, "CFD-E062"):
            campaign.campaign(
                self.source, self.foam, output, iterations=400, max_stages=1
            )
        self.assertEqual((output / "keep").read_text(), "keep")

    def test_post_seal_empty_purged_time_directory_is_rejected_and_preserved(self):
        original = backend.run
        manifest = []

        def late_empty_directory(*args, **kwargs):
            record = original(*args, **kwargs)
            path = Path(args[1])
            backend.verify(path)
            manifest.append(backend.sha256(path / "manifest.json"))
            (path / "case/200/uniform").mkdir(parents=True)
            return record

        with patch.object(backend, "run", side_effect=late_empty_directory):
            report = campaign.campaign(
                self.source,
                self.foam,
                self.root / "campaign",
                iterations=400,
                max_stages=3,
                timeout_s=60,
                preparation_s=60,
            )
        self.assertEqual(len(report["stages"]), 1)
        self.assertIn("CFD-X015 refinement.archives.stage_1_returned", report["error"])
        self.assertIn("CFD-X006 archive.progress", report["error"])
        path = self.root / "campaign/stage-01"
        self.assertTrue((path / "case/200/uniform").is_dir())
        self.assertEqual(list((path / "case/200/uniform").iterdir()), [])
        self.assertEqual(backend.sha256(path / "manifest.json"), manifest[0])
        self.assertEqual(campaign.exit_code(report), 1)


if __name__ == "__main__":
    unittest.main()
