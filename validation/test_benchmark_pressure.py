#!/usr/bin/env python3
"""Performance evidence must reject failed, changed or malformed measurements."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import benchmark_pressure as bp


class PressureBenchmark(unittest.TestCase):
    def test_unaccepted_or_nonrepeating_rows_never_produce_a_speedup(self):
        rows = []
        for method in bp.METHODS:
            for round_index in range(3):
                rows.append(
                    dict(
                        method=method,
                        warmup=round_index == 0,
                        passed=True,
                        iterations=10,
                        result_sha256="same",
                        source_sha256="source",
                        cold_s=2.0,
                        reused_s=1.0,
                        hierarchy=None,
                        measurement=dict(peak_rss_kib_linux=None),
                    )
                )
        self.assertEqual(
            bp.summarize(rows, "kernel", 2)["ic0_over_multigrid"]["reused_s"], 1
        )
        for changed in ["passed", "iterations", "result_sha256", "source_sha256"]:
            with self.subTest(changed=changed):
                bad = copy.deepcopy(rows)
                bad[-1][changed] = False if changed == "passed" else "changed"
                result = bp.summarize(bad, "kernel", 2)
                self.assertIsNone(result["ic0_over_multigrid"]["reused_s"])
        self.assertIsNone(
            bp.summarize(rows[:-1], "kernel", 2)["ic0_over_multigrid"]["reused_s"]
        )

    def test_all_failed_children_and_original_measurements_remain_in_report(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "campaign"
            report = bp.campaign(
                Path("/bin/false"), Path("/bin/false"), out, "cavity", [24], 1
            )
            self.assertFalse(report["passed"])
            self.assertEqual(len(report["rows"]), 4)
            self.assertEqual(report, json.loads((out / "report.json").read_text()))
            for row in report["rows"]:
                self.assertFalse(row["passed"])
                self.assertEqual(row["measurement"]["returncode"], 1)
                self.assertTrue(
                    (out / row["directory"] / "process/stderr.log").is_file()
                )

    def test_field_equivalence_uses_actual_arrays_and_fixed_bounds(self):
        with tempfile.TemporaryDirectory() as temp:
            left, right = Path(temp) / "left", Path(temp) / "right"
            for path in [left, right]:
                (path / "run").mkdir(parents=True)
                bp.write(
                    path / "run/fields.json",
                    dict(velocity=[0.0, 1.0], pressure=[0.0, 1.0]),
                )
            self.assertEqual(
                bp.equivalent_fields(left, right), dict(velocity=0.0, pressure=0.0)
            )
            bp.write(
                right / "run/fields.json",
                dict(velocity=[0.0, 1.001], pressure=[0.0, 1.0]),
            )
            with self.assertRaisesRegex(
                ValueError, "CFD-B005 pressure_benchmark.equivalence.velocity"
            ):
                bp.equivalent_fields(left, right)

    def test_bool_negative_and_nonfinite_timings_are_not_measurements(self):
        for value in [True, -1.0, float("nan"), float("inf"), None]:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "CFD-B005"):
                    bp.finite(value, "time", positive=True)


if __name__ == "__main__":
    unittest.main()
