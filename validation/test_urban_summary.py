"""Prevent speed ratios for changed physics or failed returned checks."""

import copy
import json
from pathlib import Path
import unittest

from summarize_urban import accepted_summary, paired_case_fidelity

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


if __name__ == "__main__":
    unittest.main()
