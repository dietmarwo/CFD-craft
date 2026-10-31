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
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

import numpy as np
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
            # The campaign directory itself may not be a link either.
            (source / "linked").unlink()
            source.rename(root / "real-campaign")
            source.symlink_to(root / "real-campaign")
            rejected = subprocess.run(
                ["bash", "-c", textwrap.dedent(step[1])],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=20,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("CFD-X015 refinement.archive.source", rejected.stderr)

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
            field = [
                "iterations",
                "max_stages",
                "timeout_s",
                "preparation_s",
                "output_mib",
                "memory_mib",
            ][index]
            with (
                self.subTest(index=index, value=value),
                self.assertRaisesRegex(ValueError, "CFD-X015 refinement." + field),
            ):
                campaign.limits(*args)
        for index, value in [(3, 3601), (4, 0), (5, 8193), (3, float("nan"))]:
            args = defaults.copy()
            args[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                campaign.limits(*args)
        # The edges themselves are accepted.
        campaign.limits(50, 1, 3600, 3600, 1, 256)
        campaign.limits(20000, 8, 0.5, 0.5, 2048, 8192)
        # The campaign checks its limits before it reads the source.
        with tempfile.TemporaryDirectory(prefix="cfd-refinement-limits-") as tmp:
            with self.assertRaisesRegex(ValueError, "CFD-X015 refinement.max_stages"):
                campaign.campaign(
                    Path(tmp) / "missing", tmp, Path(tmp) / "out", max_stages=9
                )
            self.assertFalse((Path(tmp) / "out").exists())

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

    def test_the_command_line_forwards_limits_and_codes_failures(self):
        argv = [
            "x",
            "--source",
            "s",
            "--foam-root",
            "r",
            "--output",
            "o",
            "--data",
            "d",
            "--iterations",
            "400",
            "--max-stages",
            "2",
            "--timeout-s",
            "450",
            "--preparation-s",
            "180",
            "--output-mib",
            "512",
            "--memory-mib",
            "2048",
        ]
        with (
            patch.object(campaign, "campaign", return_value={"passed": True}) as run,
            patch.object(sys, "argv", argv),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(campaign.main(), 0)
        self.assertEqual(
            run.call_args.args,
            (
                Path("s"),
                Path("r"),
                Path("o"),
                Path("d"),
                400,
                2,
                450.0,
                180.0,
                512,
                2048,
            ),
        )
        printed = io.StringIO()
        with (
            patch.object(
                campaign,
                "campaign",
                side_effect=ValueError("CFD-X015 refinement.source: x"),
            ),
            patch.object(sys, "argv", argv),
            contextlib.redirect_stdout(printed),
        ):
            self.assertEqual(campaign.main(), 1)
        self.assertEqual(
            json.loads(printed.getvalue())["error"], "CFD-X015 refinement.source: x"
        )

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
        for change in [
            "length",
            "identity",
            "duplicate",
            "nan",
            "empty",
            "station",
            "height",
            "both duplicate",
            "longer",
        ]:
            second = copy.deepcopy(first)
            left = first
            values = second["comparison"]["paired_velocity_samples"]
            if change == "length":
                values.pop()
            elif change == "identity":
                values[0]["sample_id"] = 5
            elif change == "duplicate":
                values[1] = copy.deepcopy(values[0])
            elif change == "empty":
                values.clear()
            elif change == "station":
                values[0]["station_x_over_h"] = 4
            elif change == "height":
                values[0]["y_over_h"] = 9
            elif change == "longer":
                values.append(dict(values[0], sample_id=7))
            elif change == "both duplicate":
                values[1] = copy.deepcopy(values[0])
                left = copy.deepcopy(second)
            else:
                values[0]["predicted_u_over_u_ref"] = float("nan")
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(ValueError, "CFD-X015 refinement.pair.samples"),
            ):
                campaign.paired_metrics(left, second)
        second = copy.deepcopy(first)
        second["comparison"]["paired_velocity_samples"][0][
            "predicted_u_over_u_ref"
        ] += 0.2
        second["comparison"]["reattachment"]["predicted_x_over_h"] = None
        result = campaign.paired_metrics(first, second)
        self.assertAlmostEqual(result["maximum_velocity_change_u_ref"], 0.2)
        self.assertIsNone(result["reattachment_change_h"])
        # Decreases count by magnitude; RMS and the reattachment change are reported.
        second = copy.deepcopy(first)
        samples = second["comparison"]["paired_velocity_samples"]
        samples[0]["predicted_u_over_u_ref"] -= 0.3
        samples[1]["predicted_u_over_u_ref"] -= 0.4
        second["comparison"]["reattachment"]["predicted_x_over_h"] = 6.5
        result = campaign.paired_metrics(first, second)
        self.assertAlmostEqual(result["maximum_velocity_change_u_ref"], 0.4)
        self.assertAlmostEqual(result["rms_velocity_change_u_ref"], (0.125) ** 0.5)
        self.assertAlmostEqual(result["reattachment_change_h"], 0.2)
        self.assertEqual(result["coarse_reattachment_x_over_h"], 6.7)
        self.assertEqual(result["fine_reattachment_x_over_h"], 6.5)

    def test_cavity_pair_compares_the_same_positions_by_magnitude(self):
        first = {
            "comparison": {
                "sample_positions": [0.2, 0.8],
                "predicted_u_over_u_ref": [0.1, 0.5],
            }
        }
        second = copy.deepcopy(first)
        second["comparison"]["predicted_u_over_u_ref"] = [0.05, 0.2]
        found = campaign.paired_metrics(first, second)
        self.assertAlmostEqual(found["maximum_velocity_change_u_ref"], 0.3)
        second["comparison"]["sample_positions"] = [0.2, 0.9]
        with self.assertRaisesRegex(
            ValueError, "CFD-X015 refinement.pair.samples: cavity"
        ):
            campaign.paired_metrics(first, second)

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
            "started_fine_iterations": 5000,
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
            "started 5000;",
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

    def test_the_copy_is_a_new_directory_of_identical_bytes(self):
        total = sum(e["bytes"] for e in backend.inventory(self.source).values())
        with patch.object(backend, "verify", return_value={"fixture": True}):
            campaign.copy_archive(self.source, self.root / "exact", total)
            with self.assertRaises(FileExistsError):
                campaign.copy_archive(self.source, self.root / "exact", total)
        original = Path.write_bytes

        def altered(path, data):
            return original(path, data.replace(b"bytes", b"BYTES"))

        with (
            patch.object(Path, "write_bytes", altered),
            self.assertRaisesRegex(ValueError, "refinement.source.copy: snapshot"),
        ):
            campaign.copy_archive(self.source, self.root / "altered", total)

    def test_a_same_length_change_while_copying_is_found_by_its_hash(self):
        original = Path.read_bytes
        reads = 0

        def race(path):
            nonlocal reads
            blob = original(path)
            if path == self.source / "a":
                reads += 1
                if reads == 2:
                    (self.source / "b").write_text("synthetic snapshot BYTES b")
            return blob

        with (
            patch.object(Path, "read_bytes", race),
            self.assertRaisesRegex(ValueError, "refinement.source.copy.b"),
        ):
            campaign.copy_archive(self.source, self.root / "copy", 10000)

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
        state = self.jobs[self.runs[0]]["mesh_initialization"]
        for key, value in [
            ("source_iterations", 800),
            ("source_manifest_sha256", "f" * 64),
            ("source_case_sha256", "f" * 64),
        ]:
            old = state[key]
            state[key] = value
            self.write()
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ValueError, "refinement.stages\\[1\\].parent"),
            ):
                self.check()
            state[key] = old
        self.write()

    def test_every_stage_is_the_next_level_of_the_same_case(self):
        self.records[self.runs[1]]["case"] = "backstep"
        with self.assertRaisesRegex(ValueError, "refinement.stages\\[2\\].parent"):
            self.check()
        self.records[self.runs[1]]["case"] = "cavity"
        self.jobs[self.runs[0]]["level"] = 3
        self.write()
        with self.assertRaisesRegex(
            ValueError, "refinement.stages\\[1\\].parent: wrong case"
        ):
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
        mapping=False,
        copy=True,
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
            patch.object(campaign, "copy_archive")
            if copy
            else contextlib.nullcontext(),
            patch.object(campaign, "checkpoint", side_effect=checkpoint),
            patch.object(campaign, "observation", side_effect=observe or observation),
            patch.object(backend, "Stop", return_value=stop or backend.Stop()),
            patch.object(
                campaign, "mesh_pair", return_value={"passed": found["passed"]}
            ),
            contextlib.nullcontext()
            if mapping
            else patch.object(
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

    def test_only_an_accepted_cold_level_one_or_two_source_is_used(self):
        for change, job, field in [
            ({"passed": False}, {}, "source.acceptance"),
            ({"execution_status": "timeout"}, {}, "source.acceptance"),
            ({}, {"initial_state": {"x": 1}}, "source.initialization"),
            ({}, {"mesh_initialization": {"x": 1}}, "source.initialization"),
            ({}, {"level": 3}, "source.level"),
            ({"case": "backstep"}, {}, "data"),
        ]:
            backend.write_json(self.source / "case/case.json", {"level": 1, **job})
            output = self.root / ("pre-" + field + str(len(job)) + str(len(change)))
            with (
                self.subTest(field=field, change=change, job=job),
                patch.object(backend, "verify", return_value={**self.parent, **change}),
                self.assertRaisesRegex(ValueError, "CFD-X015 refinement." + field),
            ):
                campaign.campaign(self.source, self.root, output)
            self.assertFalse(output.exists())

    def test_the_backstep_source_must_be_the_reference_recipe(self):
        self.parent["case"] = "backstep"
        for metadata in [
            {"mesh_family": "wall-resolved", "solver_profile": "simple"},
            {"mesh_family": "legacy", "solver_profile": "simplec"},
        ]:
            backend.write_json(
                self.source / "case/case.json", {"level": 1, "metadata": metadata}
            )
            with (
                patch.object(backend, "verify", return_value=self.parent),
                self.assertRaisesRegex(ValueError, "CFD-X015 refinement.source.recipe"),
            ):
                campaign.campaign(self.source, self.root, self.root / "never", data="d")
        backend.write_json(
            self.source / "case/case.json",
            {
                "level": 1,
                "metadata": {
                    "mesh_family": "wall-resolved",
                    "solver_profile": "simplec",
                },
            },
        )
        with (
            patch.object(backend, "verify", return_value=self.parent),
            patch.object(
                campaign, "load", side_effect=ValueError("CFD-D001 data: changed")
            ) as load,
            self.assertRaisesRegex(ValueError, "CFD-D001 data"),
        ):
            campaign.campaign(self.source, self.root, self.root / "never", data="d")
        load.assert_called_once_with("d")
        self.assertFalse((self.root / "never").exists())

    def test_declared_limits_reach_the_mapping_and_every_stage(self):
        r = {
            "execution_status": "completed",
            "passed": False,
            "numerical": {"solver_reported_convergence": False},
        }
        with patch.object(
            campaign.mapping,
            "prepare",
            return_value={"mesh_initialization": {"recorded": True}},
        ) as mapped:
            report, run, prepare = self.run_campaign([r, r, r], mapping=True)
        call = mapped.call_args
        self.assertEqual(call.args[1:3], (2, 400))
        self.assertEqual(call.args[3].name, "mapped-input")
        self.assertEqual(
            {k: call.kwargs[k] for k in ["timeout_s", "output_mib", "memory_mib"]},
            {"timeout_s": 900, "output_mib": 1024, "memory_mib": 4096},
        )
        self.assertEqual(report["mesh_initialization"], {"recorded": True})
        self.assertEqual(prepare.call_args.args[0].name, "stage-02")
        self.assertEqual(prepare.call_args.args[1], 400)
        self.assertEqual(prepare.call_args.args[2].name, "stage-03-input")
        for number, call in enumerate(run.call_args_list, 1):
            self.assertEqual(
                call.args[0].name,
                "mapped-input" if number == 1 else f"stage-{number:02d}-input",
            )
            self.assertEqual(call.args[1].name, f"stage-{number:02d}")
            self.assertEqual(
                {k: call.kwargs[k] for k in ["timeout_s", "output_mib", "memory_mib"]},
                {"timeout_s": 60, "output_mib": 1024, "memory_mib": 4096},
            )
        saved = json.loads((self.root / f"out-{self.calls}/report.json").read_text())
        self.assertEqual(saved["phase"], "finished")
        self.assertIs(saved["physical_qualification"], False)
        self.assertEqual(saved["source_iterations"], 696)
        self.assertIn("total_wall_s", saved)

    def test_the_source_snapshot_gets_the_stage_budget_and_frozen_manifest(self):
        r = {"execution_status": "timeout", "passed": False, "numerical": None}
        with patch.object(campaign, "copy_archive") as copied:
            report, run, prepare = self.run_campaign([r], copy=False)
        source, target, budget, frozen = copied.call_args.args
        self.assertEqual((source, target.name), (self.source, "source"))
        self.assertEqual(budget, 1024 * 1024**2)
        self.assertEqual(frozen, report["plan"]["source_manifest_sha256"])
        self.assertEqual(frozen, backend.sha256(self.source / "manifest.json"))

    def test_a_cancellation_between_steps_starts_nothing_more(self):
        stop = backend.Stop()
        r = {
            "execution_status": "completed",
            "passed": False,
            "numerical": {"solver_reported_convergence": False},
        }

        def cancelled(*args, **kwargs):
            # While a stage runs, SIGINT and SIGTERM request a graceful stop.
            for s in [signal.SIGINT, signal.SIGTERM]:
                self.assertEqual(signal.getsignal(s), stop.signal)
            stop.cancelled = True
            return r

        before = {s: signal.getsignal(s) for s in [signal.SIGINT, signal.SIGTERM]}
        report, run, prepare = self.run_campaign(cancelled, stop=stop)
        self.assertEqual(run.call_count, 1)
        prepare.assert_not_called()
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertEqual(
            {s: signal.getsignal(s) for s in [signal.SIGINT, signal.SIGTERM]}, before
        )
        # Cancelled while the source was being copied: no mapping either.
        stop = backend.Stop()
        with patch.object(
            campaign,
            "copy_archive",
            side_effect=lambda *a: setattr(stop, "cancelled", True),
        ):
            report, run, prepare = self.run_campaign([r], stop=stop, copy=False)
        self.assertEqual(report["stop_reason"], "cancelled")
        run.assert_not_called()

    def test_a_completed_stage_without_a_final_field_stops(self):
        r = {"execution_status": "completed", "passed": False, "numerical": None}
        report, run, prepare = self.run_campaign([r])
        self.assertEqual(report["stop_reason"], "no_final_field")
        prepare.assert_not_called()

    def test_a_workflow_error_is_reported_as_one(self):
        report, run, prepare = self.run_campaign(
            [], mapping_error=ValueError("CFD-X014 mapping.source.audit: failed")
        )
        self.assertEqual(report["stop_reason"], "workflow_error")
        self.assertIn("CFD-X014 mapping.source.audit", report["error"])
        self.assertFalse(report["passed"] or report["workflow_completed"])
        self.assertEqual(campaign.exit_code(report), 1)
        run.assert_not_called()

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


class Observations(unittest.TestCase):
    """observation() with mocked archive, audit and screen; Ghia from a sample file."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-refinement-observe-")
        self.root = Path(self.temp.name)
        reference = np.loadtxt(
            ROOT / "validation/ghia-re100-u.csv", delimiter=",", skiprows=1
        )
        self.reference = reference

    def tearDown(self):
        self.temp.cleanup()

    def centerline(self, shift):
        path = self.root / "case/postProcessing/sampleProfiles/9/centerline.xy"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.reference[(self.reference[:, 0] > 0) & (self.reference[:, 0] < 1)]
        path.write_text(
            "# y U_x U_y U_z\n"
            + "".join(f"{float(y)!r} {float(u + shift)!r} 0 0\n" for y, u in rows)
        )

    def observe(self, record, independent=True, assessed=None):
        record = {
            "case": "cavity",
            "execution_status": "completed",
            "numerical": {"final_time_directory": "9"},
            **record,
        }
        with (
            patch.object(backend, "verify", return_value=record),
            patch.object(campaign, "audit", return_value={"passed": independent}),
            patch.object(campaign, "assess", return_value=assessed) as assess,
        ):
            return campaign.observation(self.root, "data"), assess

    def test_ghia_reference_within_and_outside_its_target(self):
        self.centerline(0.0)
        found, _ = self.observe({"passed": True})
        self.assertLess(found["comparison"]["maximum_error"], 1e-12)
        self.assertTrue(found["accepted"] and found["passed"])
        self.centerline(0.0601)
        found, _ = self.observe({"passed": True})
        self.assertAlmostEqual(found["comparison"]["maximum_error"], 0.0601)
        self.assertTrue(found["accepted"])
        self.assertFalse(found["passed"])
        self.centerline(0.0599)
        self.assertTrue(self.observe({"passed": True})[0]["passed"])

    def test_acceptance_needs_the_numerical_and_independent_verdicts(self):
        self.centerline(0.0)
        found, _ = self.observe({"passed": False})
        self.assertFalse(found["accepted"] or found["passed"])
        found, _ = self.observe({"passed": True}, independent=False)
        self.assertFalse(found["accepted"] or found["passed"])
        found, _ = self.observe({"passed": False, "numerical": None})
        self.assertIsNone(found["independent"])
        self.assertFalse(found["accepted"])

    def test_the_backstep_uses_the_frozen_measurement_screen(self):
        found, assess = self.observe(
            {"passed": True, "case": "backstep"}, assessed={"passed": True}
        )
        self.assertEqual(assess.call_args.args, (self.root, "data"))
        self.assertTrue(found["passed"])
        found, _ = self.observe(
            {"passed": True, "case": "backstep"}, assessed={"passed": False}
        )
        self.assertTrue(found["accepted"])
        self.assertFalse(found["passed"])


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

    def accepted_pair(self, records=None, passed=(True, True)):
        records = records or [
            {"case": "cavity", "runtime": {"fixture": True}},
            {"case": "cavity", "runtime": {"fixture": True}},
        ]
        observations = [
            {
                "accepted": True,
                "passed": ok,
                "comparison": {
                    "sample_positions": [0.5],
                    "predicted_u_over_u_ref": [0.1],
                },
            }
            for ok in passed
        ]
        with (
            patch.object(
                backend,
                "verify",
                side_effect=lambda p: records[self.paths.index(Path(p))],
            ),
            patch.object(campaign, "observation", side_effect=observations),
        ):
            return campaign.mesh_pair(*self.paths, None)

    def test_two_accepted_grids_must_be_the_same_recipe_one_level_apart(self):
        self.assertTrue(self.accepted_pair()["passed"])
        self.assertFalse(self.accepted_pair(passed=(True, False))["passed"])
        self.assertFalse(self.accepted_pair(passed=(False, True))["passed"])
        backstep = {"case": "backstep", "runtime": {"fixture": True}}
        cavity = {"case": "cavity", "runtime": {"fixture": True}}
        with self.assertRaisesRegex(ValueError, "refinement.pair.level"):
            self.accepted_pair([cavity, backstep])
        with self.assertRaisesRegex(ValueError, "refinement.pair.runtime"):
            self.accepted_pair([cavity, dict(cavity, runtime={"other": 1})])
        for path, key, value, field in [
            (1, "level", 3, "pair.level"),
            (1, "metadata", {"reynolds": 200}, "pair.metadata.reynolds"),
            (
                1,
                "metadata",
                {"reynolds": 100, "mesh_family": "x"},
                "pair.metadata.mesh_family",
            ),
            (
                1,
                "metadata",
                {"reynolds": 100, "solver_profile": "x"},
                "pair.metadata.solver_profile",
            ),
            (1, "metadata", {"reynolds": 100, "height_m": 2}, "pair.metadata.height_m"),
            (
                1,
                "metadata",
                {"reynolds": 100, "reference_speed_m_s": 2},
                "pair.metadata.reference_speed_m_s",
            ),
            (
                1,
                "inputs",
                {"system/fvSchemes": {"sha256": "x"}},
                "pair.inputs.system/fvSchemes",
            ),
        ]:
            job = json.loads((self.paths[path] / "case/case.json").read_text())
            saved = copy.deepcopy(job)
            job[key] = value
            backend.write_json(self.paths[path] / "case/case.json", job)
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(
                    ValueError, "CFD-X015 refinement." + re.escape(field)
                ),
            ):
                self.accepted_pair()
            backend.write_json(self.paths[path] / "case/case.json", saved)

    def test_a_coarse_grid_that_is_not_accepted_is_not_compared(self):
        with (
            patch.object(backend, "verify") as verify,
            patch.object(
                campaign,
                "observation",
                side_effect=[{"accepted": False}, {"accepted": True}],
            ),
        ):
            found = campaign.mesh_pair(*self.paths, None)
        self.assertFalse(found["assessed"])
        verify.assert_not_called()

    def test_backstep_friction_is_compared_at_positive_measured_positions(self):
        curve = [{"x_over_h": x, "cf": 0.001 * x} for x in [-1.0, 0.0, 1.0, 2.0, 3.0]]
        finer = [{"x_over_h": x, "cf": -0.002 * x} for x in [-1.0, 0.0, 1.0, 2.0, 3.0]]
        samples = [
            {
                "station_x_over_h": 1,
                "sample_id": 1,
                "y_over_h": 0.5,
                "predicted_u_over_u_ref": 0.1,
            }
        ]
        observations = [
            {
                "accepted": True,
                "passed": True,
                "comparison": {
                    "paired_velocity_samples": samples,
                    "reattachment": {"predicted_x_over_h": 6.7},
                    "friction_curve": c,
                },
            }
            for c in [curve, finer]
        ]
        record = {"case": "backstep", "runtime": {"fixture": True}}
        with (
            patch.object(backend, "verify", return_value=record),
            patch.object(campaign, "observation", side_effect=observations),
            patch.object(
                campaign, "load", return_value={"cf": [[-0.5, 0], [1.0, 0], [2.5, 0]]}
            ),
        ):
            found = campaign.mesh_pair(*self.paths, "data")
        self.assertEqual(found["cf_comparison_x_over_h"], [1.0, 2.5])
        self.assertAlmostEqual(found["maximum_cf_change_at_measured_positions"], 0.0075)

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
