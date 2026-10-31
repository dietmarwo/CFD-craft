#!/usr/bin/env python3
"""A failed warmup or field-equivalence check cannot acquire a timing ratio."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import benchmark_anisotropic_flow as f
import external_notices


class FlowEvidence(unittest.TestCase):
    def run_campaign(self, accepted, fail_equivalence=False):
        with tempfile.TemporaryDirectory() as temp:

            def row(binary, mode, method, destination):
                destination.mkdir()
                return dict(
                    valid=True,
                    accepted=accepted,
                    mode=mode,
                    method=method,
                    measurement=dict(returncode=2),
                    solver_s=1.0,
                    workflow_s=2.0,
                )

            with patch.object(f, "run_row", side_effect=row):
                with patch.object(
                    f.bp,
                    "equivalent_fields",
                    side_effect=ValueError("field bound failed")
                    if fail_equivalence
                    else None,
                ):
                    return f.campaign(
                        Path("/bin/true"), Path(temp) / "campaign", 3, ["steady"]
                    )

    def test_unaccepted_warmup_is_retained_and_stops_the_configuration(self):
        r = self.run_campaign(False)
        self.assertTrue(r["workflow_valid"])
        self.assertFalse(r["passed"])
        self.assertEqual(len(r["rows"]), 2)
        self.assertTrue(r["results"]["steady"]["stopped_after_unaccepted_warmup"])
        self.assertIsNone(r["results"]["steady"]["ic0_over_multigrid"]["solver_s"])
        self.assertTrue(all("measurement" in row for row in r["rows"]))

    def test_unequal_returned_fields_cannot_be_qualified(self):
        r = self.run_campaign(True, True)
        self.assertFalse(r["passed"])
        self.assertTrue(all("equivalence_error" in row for row in r["rows"]))
        self.assertIsNone(r["results"]["steady"]["ic0_over_multigrid"]["workflow_s"])

    def test_notice_keeps_failed_warmup_and_absent_ratio_visible(self):
        report = self.run_campaign(False)
        with patch.object(external_notices, "notice") as emit:
            self.assertEqual(external_notices.anisotropic_flow(report, "flow"), 0)
        message = emit.call_args.args[1]
        self.assertIn("steady discrete solution", message)
        self.assertIn("unaccepted steady-warmup", message)
        self.assertIn('"solver_s": null', message)


if __name__ == "__main__":
    unittest.main()
