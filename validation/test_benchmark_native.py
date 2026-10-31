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
            ("timeout_s", float("nan")),
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
