#!/usr/bin/env python3
"""Benchmark acceptance/identity tests; synthetic reports are not CFD evidence."""

import copy
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchmark_native as bench


def fixture():
    return {
        "schema_version": "cfd-craft.native-performance/0.1",
        "source_sha256": "a" * 64,
        "case_sha256": "b" * 64,
        "case": {"fixture": True},
        "mode": "steps",
        "repetitions": 2,
        "requested_steps": 3,
        "threads": 1,
        "cells": 8,
        "faces": 24,
        "wall_s": [1.0, 0.9],
        "result_sha256": "c" * 64,
        "result": {
            "state": {
                "steps": 3,
                "pressure_iterations": 20,
                "floor_events": 0,
                "velocity": [1.0, 0.0],
                "budgets": [{"emitted_kg": 1e-8}],
            }
        },
    }


class Comparison(unittest.TestCase):
    def test_work_and_input_identity_cannot_buy_a_speedup(self):
        for key, value in [
            ("case_sha256", "x"),
            ("case", {}),
            ("mode", "pressure"),
            ("repetitions", 1),
            ("requested_steps", 2),
            ("threads", 4),
            ("cells", 7),
            ("faces", 23),
        ]:
            a, b = fixture(), fixture()
            b[key] = value
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ValueError, "CFD-B001 benchmark.compare"),
            ):
                bench.compare_reports(a, b)

    def test_counts_floors_and_nonfinite_values_are_rejected(self):
        for key, value in [
            ("steps", 2),
            ("pressure_iterations", 19),
            ("floor_events", 1),
            ("velocity", [float("nan"), 0.0]),
            ("velocity", [1.1, 0.0]),
        ]:
            a, b = fixture(), fixture()
            b["result"]["state"][key] = value
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ValueError, "CFD-B001 benchmark.result"),
            ):
                bench.compare_reports(a, b)

    def test_roundoff_is_reported_and_bound_is_not_silently_enlarged(self):
        a, b = fixture(), fixture()
        b["result"]["state"]["velocity"][0] += 1e-12
        r = bench.compare_reports(a, b)
        self.assertTrue(r["passed"])
        self.assertFalse(r["exact_result"])
        self.assertGreater(r["maximum_absolute_difference"], 0)
        b["result"]["state"]["velocity"][1] = 1e-10
        with self.assertRaisesRegex(ValueError, "array differs"):
            bench.compare_reports(a, b)

    def test_invalid_timing_samples_fail(self):
        for values in [[1.0], [1.0, 0.0], [1.0, True], [1.0, float("inf")]]:
            a, b = fixture(), fixture()
            b["wall_s"] = values
            with (
                self.subTest(values=values),
                self.assertRaisesRegex(ValueError, "wall_s"),
            ):
                bench.compare_reports(a, b)

    def test_nested_structure_and_list_lengths_are_exact(self):
        for value in [[1.0], {"invented": 1}]:
            with self.assertRaisesRegex(ValueError, "CFD-B001"):
                bench.compare([1.0, 2.0], value)
        with self.assertRaisesRegex(ValueError, "CFD-B001"):
            bench.compare({"a": 1}, {"b": 1})
        with self.assertRaisesRegex(ValueError, "CFD-B001"):
            bench.compare(True, 1)

    def test_broadcastable_lists_and_extra_keys_differ(self):
        with self.assertRaisesRegex(ValueError, "length differs"):
            bench.compare([1.0, 1.0], [1.0])
        with self.assertRaisesRegex(ValueError, "keys differ"):
            bench.compare({"a": 1.0}, {"a": 1.0, "b": 1.0})

    def test_null_never_matches_because_the_probe_writes_nonfinite_values_as_null(self):
        for a, b in [(None, None), ({"x": None}, {"x": None}), ([None], [None])]:
            with (
                self.subTest(a=a),
                self.assertRaisesRegex(ValueError, "null"),
            ):
                bench.compare(a, b)

    def test_work_counts_are_exact_integers(self):
        for a, b in [
            (20, 20.0),
            (20.0, 20),
            ([10**13], [10**13 + 1]),
            ([1, 2], [1.0, 2]),
        ]:
            with (
                self.subTest(a=a, b=b),
                self.assertRaisesRegex(ValueError, "integer"),
            ):
                bench.compare(a, b)
        self.assertEqual(bench.compare([1, 2], [1, 2]), 0.0)

    def test_float_bound_is_1e13_absolute_plus_1e11_relative(self):
        for a, inside, outside in [
            (1.0, 1.0 + 0.9e-11, 1.0 + 1.2e-11),
            (0.0, 0.9e-13, 1.2e-13),
            (1e6, 1e6 * (1 + 0.9e-11), 1e6 * (1 + 1.2e-11)),
        ]:
            with self.subTest(a=a):
                self.assertGreater(bench.compare(a, inside), 0)
                self.assertGreater(bench.compare([a, 2.0], [inside, 2.0]), 0)
                with self.assertRaisesRegex(ValueError, "value differs"):
                    bench.compare(a, outside)
                with self.assertRaisesRegex(ValueError, "array differs"):
                    bench.compare([a, 2.0], [outside, 2.0])

    def test_both_schemas_and_both_timing_series_are_checked(self):
        a, b = fixture(), fixture()
        a["schema_version"] = b["schema_version"] = "invented/0.1"
        with self.assertRaisesRegex(ValueError, "baseline.schema"):
            bench.compare_reports(a, b)
        a, b = fixture(), fixture()
        a["wall_s"] = [1.0, -1.0]
        with self.assertRaisesRegex(ValueError, "baseline.wall_s"):
            bench.compare_reports(a, b)

    def test_a_signed_zero_is_equivalent_but_not_exact(self):
        a, b = fixture(), fixture()
        b["result"]["state"]["velocity"][1] = -0.0
        b["result_sha256"] = "d" * 64
        r = bench.compare_reports(a, b)
        self.assertTrue(r["passed"])
        self.assertFalse(r["exact_result"])
        self.assertTrue(bench.compare_reports(fixture(), fixture())["exact_result"])


class Pairing(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-bench-contract-")
        self.root = Path(self.temp.name)
        self.binaries = [self.root / name for name in ["base", "candidate"]]
        for p in self.binaries:
            p.write_text("synthetic executable bytes")
        self.case = self.root / "case.json"
        self.case.write_text("{}")

    def tearDown(self):
        self.temp.cleanup()

    def run_fake(self, measure, output="result"):
        with patch.object(bench, "measure", side_effect=measure):
            return bench.run_pair(
                *self.binaries, self.case, "steps", 3, 2, 3, 1, self.root / output
            )

    def test_pairs_alternate_and_warmup_is_excluded(self):
        order = []

        def fake(binary, *args):
            order.append(Path(binary).name)
            row = copy.deepcopy(fixture())
            if Path(binary).name == "candidate":
                row["wall_s"] = [0.5, 0.45]
            return row, {"child_cpu_s": 1.0}

        r = self.run_fake(fake)
        self.assertTrue(r["passed"])
        self.assertEqual(
            order,
            [
                "candidate",
                "base",
                "base",
                "candidate",
                "candidate",
                "base",
                "base",
                "candidate",
            ],
        )
        self.assertEqual(len(r["samples"]), 6)
        self.assertAlmostEqual(r["speedup"], 2)

    def test_differing_results_cannot_report_a_speedup(self):
        def fake(binary, *args):
            row = fixture()
            if Path(binary).name == "candidate":
                row["result"]["state"]["velocity"][0] = 1.5
                row["wall_s"] = [0.5, 0.45]
            return row, {}

        r = self.run_fake(fake)
        self.assertFalse(r["passed"])
        self.assertIn("CFD-B001 benchmark.result.state.velocity", r["error"])
        self.assertNotIn("speedup", r)
        self.assertNotIn("comparisons", r)

    def test_the_unscored_warmup_pair_must_also_agree(self):
        calls = 0

        def fake(binary, *args):
            nonlocal calls
            calls += 1
            row = fixture()
            if calls == 2:
                row["result"]["state"]["steps"] = 4
            return row, {}

        r = self.run_fake(fake)
        self.assertFalse(r["passed"])
        self.assertIn("benchmark.result.state.steps", r["error"])
        self.assertEqual(r["samples"], [])

    def test_a_binary_changed_before_its_child_is_rejected_before_launch(self):
        launched = []

        def fake(binary, *args):
            launched.append(Path(binary).name)
            if len(launched) == 1:
                # The first child (the candidate's warmup) alters the baseline.
                self.binaries[0].write_text("other executable bytes")
            return fixture(), {}

        r = self.run_fake(fake)
        self.assertFalse(r["passed"])
        self.assertTrue(
            r["error"].endswith("identity.baseline: binary or case changed"), r["error"]
        )
        self.assertEqual(launched, ["candidate"])

    def test_the_child_must_report_the_requested_work(self):
        for key, value in [
            ("repetitions", 1),
            ("requested_steps", 2),
            ("threads", 2),
            ("mode", "pressure"),
            ("repetitions", 2.0),
        ]:

            def fake(binary, *args):
                row = fixture()
                row[key] = value
                return row, {}

            with self.subTest(key=key, value=value):
                r = self.run_fake(fake, output=f"work-{key}-{value!r}")
                self.assertFalse(r["passed"])
                self.assertIn(f"benchmark.candidate.{key}", r["error"])

    def test_summary_uses_warm_medians_and_reports_the_paired_ratio(self):
        times = {
            "base": [
                [9.0, 9.0, 9.0],
                [5.0, 1.0, 3.0],
                [4.0, 3.0, 5.0],
                [7.0, 6.0, 10.0],
            ],
            "candidate": [
                [9.0, 9.0, 9.0],
                [3.0, 1.0, 1.0],
                [3.0, 2.0, 2.0],
                [3.0, 1.0, 1.0],
            ],
        }

        def fake(binary, *args):
            row = fixture()
            row["repetitions"] = 3
            row["wall_s"] = times[Path(binary).name].pop(0)
            return row, {}

        with patch.object(bench, "measure", side_effect=fake):
            r = bench.run_pair(
                *self.binaries, self.case, "steps", 3, 3, 3, 1, self.root / "stats"
            )
        self.assertTrue(r["passed"], r.get("error"))
        self.assertEqual(
            r["summary"]["baseline"],
            {"median_s": 4.0, "minimum_s": 2.0, "maximum_s": 8.0, "cold_median_s": 5.0},
        )
        self.assertEqual(
            r["summary"]["candidate"],
            {"median_s": 1.0, "minimum_s": 1.0, "maximum_s": 2.0, "cold_median_s": 3.0},
        )
        self.assertEqual(r["speedup"], 4.0)
        self.assertEqual(r["paired_speedup_median"], 2.0)

    def test_a_binary_changed_during_a_child_is_retained_as_failure(self):
        def changed(binary, *args):
            Path(binary).write_text("other executable bytes")
            return fixture(), {}

        r = self.run_fake(changed)
        self.assertFalse(r["passed"])
        self.assertIn("binary or case changed during execution", r["error"])

    def test_uncoded_record_errors_are_coded(self):
        def broken(*args):
            raise KeyError("wall_s")

        r = self.run_fake(broken)
        self.assertFalse(r["passed"])
        self.assertTrue(r["error"].startswith("CFD-B001 benchmark.record: "))

    def test_missing_inputs_are_coded_before_output_creation(self):
        self.binaries[1].unlink()
        with self.assertRaisesRegex(ValueError, "CFD-B001 benchmark.candidate"):
            bench.run_pair(
                *self.binaries, self.case, "steps", 1, 1, 1, 1, self.root / "absent"
            )
        self.assertFalse((self.root / "absent").exists())

    def test_command_line_exit_code_follows_the_report(self):
        argv = [
            "benchmark_native.py",
            "--baseline",
            str(self.binaries[0]),
            "--candidate",
            str(self.binaries[1]),
            "--case",
            str(self.case),
            "--mode",
            "steps",
            "--output",
            str(self.root / "cli"),
        ]
        for passed, code in [(True, 0), (False, 1)]:
            with (
                self.subTest(passed=passed),
                patch.object(sys, "argv", argv),
                patch.object(bench, "run_pair", return_value={"passed": passed}),
                patch("builtins.print"),
            ):
                self.assertEqual(bench.main(), code)
        with (
            patch.object(sys, "argv", argv),
            patch.object(bench, "run_pair", side_effect=ValueError("CFD-B001 x")),
            patch("builtins.print"),
        ):
            self.assertEqual(bench.main(), 1)

    def test_changed_case_is_retained_as_failure(self):
        def changed(*args):
            self.case.write_text('{"changed":true}')
            return fixture(), {}

        r = self.run_fake(changed)
        self.assertFalse(r["passed"])
        self.assertIn("changed during", r["error"])
        self.assertTrue((self.root / "result/report.json").exists())

    def test_changed_producer_and_field_failure_cannot_pass(self):
        count = 0

        def changed(*args):
            nonlocal count
            count += 1
            r = fixture()
            if count >= 3:
                r["source_sha256"] = "changed"
            return r, {}

        r = self.run_fake(changed)
        self.assertFalse(r["passed"])
        self.assertIn("compiled producer changed", r["error"])

    def test_invalid_limits_precede_output_creation_and_occupied_output_is_kept(self):
        for field, value in [
            ("rounds", True),
            ("inner", 0),
            ("steps", 1001),
            ("threads", 65),
            ("rounds", 21),
            ("timeout_s", float("nan")),
            ("timeout_s", 181),
            ("timeout_s", True),
            ("mode", "bogus"),
        ]:
            args = dict(
                baseline=self.binaries[0],
                candidate=self.binaries[1],
                case=self.case,
                mode="steps",
                rounds=1,
                inner=1,
                steps=1,
                threads=1,
                output=self.root / "out",
            )
            args[field] = value
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "CFD-B001"),
            ):
                bench.run_pair(**args)
            self.assertFalse((self.root / "out").exists())
        (self.root / "out").mkdir()
        (self.root / "out/keep").write_text("keep")
        with self.assertRaisesRegex(ValueError, "fresh path"):
            bench.run_pair(
                *self.binaries, self.case, "steps", 1, 1, 1, 1, self.root / "out"
            )
        self.assertEqual((self.root / "out/keep").read_text(), "keep")

    def test_timeout_retains_the_actual_child_record(self):
        self.case.write_text("import time\ntime.sleep(30)\n")
        with self.assertRaisesRegex(ValueError, "CFD-B001 benchmark.child"):
            bench.measure(
                sys.executable, self.case, "steps", 1, 1, 1, self.root / "timeout", 0.1
            )
        record = json.loads((self.root / "timeout/process.json").read_text())
        self.assertTrue(record["timeout"])
        self.assertLess(record["return_code"], 0)
        self.assertGreater(record["peak_rss_kib_linux"], 0)

    def test_a_failed_child_with_valid_output_is_rejected(self):
        self.case.write_text(
            "import sys\nfrom pathlib import Path\n"
            + f"Path(sys.argv[-1]).write_text({json.dumps(fixture())!r})\n"
            + "sys.exit(3)\n"
        )
        with self.assertRaisesRegex(ValueError, "CFD-B001 benchmark.child"):
            bench.measure(
                sys.executable, self.case, "steps", 1, 1, 1, self.root / "exit3", 5
            )
        record = json.loads((self.root / "exit3/process.json").read_text())
        self.assertEqual(record["return_code"], 3)

    def test_a_probe_report_without_timings_names_the_field(self):
        row = fixture()
        del row["wall_s"]
        self.case.write_text(
            "import sys\nfrom pathlib import Path\n"
            + f"Path(sys.argv[-1]).write_text({json.dumps(row)!r})\n"
        )
        with self.assertRaisesRegex(ValueError, "CFD-B001 benchmark.probe.wall_s"):
            bench.measure(
                sys.executable, self.case, "steps", 1, 1, 1, self.root / "keys", 5
            )

    def test_an_exited_probe_cannot_leave_a_late_writer(self):
        marker = self.root / "late-writer"
        child = f"import time;from pathlib import Path;time.sleep(0.5);Path({str(marker)!r}).write_text('late')"
        self.case.write_text(
            "import subprocess,sys\nfrom pathlib import Path\n"
            + f"subprocess.Popen([sys.executable,'-c',{child!r}])\n"
            + f"Path(sys.argv[-1]).write_text({json.dumps(fixture())!r})\n"
        )
        report, record = bench.measure(
            sys.executable, self.case, "steps", 1, 1, 1, self.root / "leader", 2
        )
        self.assertEqual(record["return_code"], 0)
        self.assertEqual(report["schema_version"], fixture()["schema_version"])
        time.sleep(0.6)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
