"""Prevent speed ratios for changed physics or failed returned checks."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from summarize_urban import accepted_summary, paired_case_fidelity, summarize

ROOT = Path(__file__).resolve().parents[1]


class UrbanSummaryTests(unittest.TestCase):
    def test_case_fidelity_requires_identical_consumed_controls(self):
        c = json.loads((ROOT / "cases/canyon/wh1-wind270.json").read_text())
        mg = copy.deepcopy(c)
        mg["numerics"]["pressure_preconditioner"] = "multigrid"
        self.assertTrue(paired_case_fidelity(c, mg))
        for section, key, value in [
            ("grid", "cells", [36, 32, 24]),
            ("run", "wall_time_limit_s", 1.0),
        ]:
            altered = copy.deepcopy(mg)
            altered[section][key] = value
            self.assertFalse(paired_case_fidelity(c, altered))
        altered = copy.deepcopy(mg)
        altered["sources"][0]["rate_kg_s_m"] *= 2
        self.assertFalse(paired_case_fidelity(c, altered))

    def test_failed_summary_check_or_audit_cannot_be_accepted(self):
        s = dict(
            termination="completed",
            assessment="steady_discrete_solution",
            checks=[dict(passed=True), dict(passed=False)],
        )
        self.assertFalse(accepted_summary(s, True))
        s["checks"][1]["passed"] = True
        self.assertTrue(accepted_summary(s, True))
        self.assertFalse(accepted_summary(s, False))
        s["checks"] = []
        self.assertFalse(accepted_summary(s, True))

    def test_missing_or_interrupted_runs_are_retained_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # One pair member was interrupted after its summary was written.
            run = root / "block-4m-multigrid/run"
            run.mkdir(parents=True)
            (run / "summary.json").write_text(
                json.dumps(
                    dict(
                        termination="wall_time_limit",
                        assessment="incomplete",
                        steps=3,
                        elapsed_s=1.0,
                        source_sha256="1" * 64,
                        case_sha256="2" * 64,
                        physics_sha256="3" * 64,
                        pressure_iterations=4,
                        checks=[],
                    )
                )
            )
            report = summarize(root)
        self.assertEqual(len(report["records"]), 12)
        self.assertFalse(any(r["accepted"] for r in report["records"]))
        record = next(r for r in report["records"] if r["id"] == "block-4m-multigrid")
        self.assertIsNone(record["fields_sha256"])
        self.assertFalse(record["independent_check"]["passed"])
        self.assertEqual(len(report["pairs"]), 3)
        for pair in report["pairs"]:
            self.assertFalse(pair["case_fidelity_passed"])
            self.assertNotIn("ic0_over_multigrid_elapsed_ratio", pair)


if __name__ == "__main__":
    unittest.main()
