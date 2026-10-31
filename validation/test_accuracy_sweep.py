#!/usr/bin/env python3
"""Fault-injection contracts; these synthetic timings are not CFD evidence."""

import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

import accuracy_sweep as s


class Sweep(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-sweep-")
        self.root = Path(self.temp.name)
        self.binary = self.root / "binary"
        self.binary.write_text("synthetic")
        self.foam = self.root / "foam"
        self.foam.mkdir()
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, method, grid, destination, *args):
        destination.mkdir()
        self.calls.append((method, grid, destination.name))
        foam = method == "openfoam-steady"
        error = 0.009 if foam else 0.027 if grid == 24 else 0.017
        return dict(
            method=method,
            grid=grid,
            error=None,
            accepted=True,
            numerical_accepted=True,
            independent_passed=True,
            reference_screen_passed=True,
            reference_error=error,
            workflow_s=1.0 if foam else 5.0,
            solver_s=0.5 if foam else 4.0,
            steps=696 if foam else 2010,
            cells=grid * grid * (1 if foam else 2),
            predicted_u=[error],
            case_sha256=f"{method}-{grid}",
            runtime_identity="foam-runtime",
            source_sha256="native-source",
            pressure_iterations=200,
            initial_state_sha256="zero",
            peak_rss_kib_linux=12345,
        )

    def run_sweep(self, runner=None, **kw):
        return s.sweep(
            self.binary,
            self.foam,
            self.root / "out",
            runner=runner or self.runner,
            **kw,
        )

    def test_target_missing_has_no_invented_ratio(self):
        r = self.run_sweep(rounds=3)
        self.assertTrue(r["passed"], r.get("error"))
        self.assertTrue(r["cost_at_target"]["openfoam-steady"]["target_reached"])
        self.assertFalse(r["cost_at_target"]["native-steady"]["target_reached"])
        self.assertIsNone(r["native_over_openfoam_at_target"])
        self.assertEqual(len(r["rows"]), 20)
        self.assertEqual(r["groups"][0]["timed_rows"], 3)
        self.assertEqual(sum(row["warmup"] for row in r["rows"]), 5)

    def test_orders_alternate_and_warmups_are_not_cost_samples(self):
        def runner(*args):
            row = self.runner(*args)
            if args[2].name.startswith("warmup"):
                row["workflow_s"] = 1000.0
            return row

        r = self.run_sweep(runner, levels=[1], rounds=2, native_diagnostic=False)
        timed = [row for row in r["rows"] if not row["warmup"]]
        self.assertEqual(
            [row["method"] for row in timed], s.METHODS + list(reversed(s.METHODS))
        )
        self.assertEqual([g["workflow_median_s"] for g in r["groups"]], [5.0, 1.0])

    def test_cost_uses_cheapest_qualifying_grid_and_each_timer(self):
        def runner(*args):
            row = self.runner(*args)
            if row["grid"] == 48:
                row.update(reference_error=0.005, predicted_u=[0.005])
            row["workflow_s"] *= 2 if row["grid"] == 48 else 1
            return row

        r = self.run_sweep(runner, native_diagnostic=False)
        self.assertTrue(r["passed"], r.get("error"))
        c = r["cost_at_target"]
        self.assertEqual(c["native-steady"]["workflow_best"]["grid"], 48)
        self.assertEqual(c["openfoam-steady"]["workflow_best"]["grid"], 24)
        self.assertEqual(
            r["native_over_openfoam_at_target"], dict(workflow=10.0, solver=8.0)
        )

    def test_incomplete_rows_remain_and_do_not_qualify(self):
        def runner(*args):
            row = self.runner(*args)
            if row["method"] == "native-steady":
                row.update(
                    accepted=False,
                    numerical_accepted=False,
                    reference_error=0.001,
                    predicted_u=[0.001],
                )
            return row

        r = self.run_sweep(runner, levels=[1], rounds=2, native_diagnostic=False)
        self.assertTrue(r["completed"])
        self.assertTrue(r["workflow_valid"])
        self.assertFalse(r["passed"])
        self.assertIsNone(r["cost_at_target"]["native-steady"]["workflow_best"])
        self.assertEqual(len(r["rows"]), 6)
        self.assertIsNotNone(r["groups"][0]["workflow_median_s"])

    def test_an_error_is_retained_and_remaining_rows_are_attempted(self):
        def runner(*args):
            if args[2].name.startswith("round-00") and args[0] == "native-steady":
                raise ValueError("CFD-B004 sweep.test: retained failure")
            return self.runner(*args)

        r = self.run_sweep(runner, levels=[1], rounds=2, native_diagnostic=False)
        self.assertTrue(r["completed"])
        self.assertFalse(r["workflow_valid"])
        self.assertEqual(len(r["rows"]), 6)
        self.assertIn("retained failure", r["rows"][2]["error"])
        disk = json.loads((self.root / "out/report.json").read_text())
        self.assertEqual(disk, r)

    def test_changed_inputs_fail_with_an_incremental_report(self):
        def runner(*args):
            row = self.runner(*args)
            self.binary.write_text("changed")
            return row

        r = self.run_sweep(runner, levels=[1])
        self.assertFalse(r["completed"])
        self.assertIn("sweep.inputs", r["error"])
        self.assertEqual(len(r["rows"]), 1)

    def test_accepted_fields_work_and_producer_must_repeat(self):
        for key, value in [
            ("steps", 2011),
            ("predicted_u", [0.03]),
            ("source_sha256", "changed"),
            ("pressure_iterations", 201),
            ("initial_state_sha256", "changed"),
        ]:

            def runner(*args):
                row = self.runner(*args)
                if args[0] == "native-steady" and args[2].name.startswith("round-01"):
                    row[key] = value
                return row

            with self.subTest(key=key):
                out = self.root / "out"
                if out.exists():
                    import shutil

                    shutil.rmtree(out)
                r = self.run_sweep(
                    runner, levels=[1], rounds=2, native_diagnostic=False
                )
                self.assertFalse(r["workflow_valid"])
                self.assertIn("repeat." + key, r["error"])

    def test_bad_rows_are_coded_and_kept(self):
        row = self.runner("native-steady", 24, self.root / "fixture")
        for key, value in [
            ("accepted", 1),
            ("workflow_s", float("nan")),
            ("solver_s", -1),
            ("reference_error", float("inf")),
            ("predicted_u", [float("nan")]),
            ("steps", True),
            ("cells", 0),
        ]:
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ValueError, "CFD-B004 sweep.row"),
            ):
                altered = copy.deepcopy(row)
                altered[key] = value
                s.validate_row(altered)

    def test_a_rejected_measurement_stays_in_the_report(self):
        def runner(method, grid, destination, *args):
            row = self.runner(method, grid, destination, *args)
            if (
                method == "native-steady"
                and grid == 24
                and "round-01" in str(destination)
            ):
                # Claimed accepted above the frozen 0.06 screen: inconsistent.
                row.update(reference_error=0.07)
            if method == "openfoam-steady" and "round-02" in str(destination):
                raise AttributeError("runner defect")
            return row

        report = self.run_sweep(runner, levels=[1], native_diagnostic=False)
        rows = {r["run_directory"]: r for r in report["rows"]}
        rejected = rows["round-01-n24-native-steady"]
        self.assertIn("row.reference_screen_passed", rejected["error"])
        self.assertEqual(rejected["rejected_measurement"]["reference_error"], 0.07)
        self.assertNotIn("reference_error", rejected)
        self.assertIn("runner defect", rows["round-02-n24-openfoam-steady"]["error"])
        self.assertTrue(report["completed"])
        self.assertFalse(report["workflow_valid"])
        self.assertNotIn("rejected_measurement", rows["round-00-n24-native-steady"])

    def test_arguments_are_checked_before_claiming_output(self):
        for kw in [
            dict(levels=[]),
            dict(levels=[1, 1]),
            dict(levels=[4]),
            dict(rounds=True),
            dict(rounds=0),
            dict(target=float("nan")),
            dict(target=0.061),
            dict(native_wall_s=0),
            dict(foam_wall_s=601),
            dict(native_max_steps=0),
            dict(foam_iterations=251),
        ]:
            with self.subTest(kw=kw), self.assertRaisesRegex(ValueError, "CFD-"):
                self.run_sweep(**kw)
            self.assertFalse((self.root / "out").exists())

    def test_existing_and_dangling_outputs_are_refused(self):
        for dangling in [False, True]:
            out = self.root / "out"
            if dangling:
                out.symlink_to(self.root / "missing")
            else:
                out.mkdir()
            with (
                self.subTest(dangling=dangling),
                self.assertRaisesRegex(ValueError, "CFD-E062"),
            ):
                self.run_sweep()
            if dangling:
                out.unlink()
            else:
                out.rmdir()

    def test_ci_notice_reports_unreached_target_without_dispatching_resolution(self):
        import external_notices

        r = self.run_sweep(levels=[1], rounds=1, native_diagnostic=False)
        buf = io.StringIO()
        with (
            patch.object(
                sys, "argv", ["notices", str(self.root / "out/report.json"), "accuracy"]
            ),
            contextlib.redirect_stdout(buf),
        ):
            self.assertEqual(external_notices.main(), 0)
        text = buf.getvalue().replace("%0A", "\n")
        self.assertIn("native-steady 24²", text)
        self.assertIn("target_not_reached_within_tested_grids_and_budgets", text)
        self.assertIn("native/OpenFOAM at target: null", text)
        self.assertTrue(r["completed"])

    def test_cli_distinguishes_valid_unaccepted_and_invalid_workflows(self):
        import compare_backends

        argv = [
            "compare_backends.py",
            "--binary",
            str(self.binary),
            "--foam-root",
            str(self.foam),
            "--output",
            str(self.root / "out"),
            "--grid-sweep",
        ]
        for valid, passed, code in [
            (True, True, 0),
            (True, False, 2),
            (False, False, 1),
        ]:
            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    s, "sweep", return_value=dict(workflow_valid=valid, passed=passed)
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(compare_backends.main(), code)


if __name__ == "__main__":
    unittest.main()
