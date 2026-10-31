#!/usr/bin/env python3
"""Independent recovery and incomplete rows govern eligibility, not iteration count."""

import copy
import math
import unittest
from unittest.mock import patch
import external_notices
import numpy as np
import benchmark_anisotropy as b


class PressureEvidence(unittest.TestCase):
    def fixture(self):
        c = b.case_for("isotropic", "ic0")
        n = math.prod(c["grid"]["cells"])
        i = np.arange(n, dtype=float)
        x = np.sin(0.73 * i) + 0.3 * np.cos(0.17 * i)
        x -= x.mean()
        sample = dict(
            wall_s=1.0,
            iterations=5,
            true_relative_residual=0.0,
            rms_error=0.0,
            result_sha256="a" * 64,
            error=None,
            profile=dict(
                phases=dict(
                    pressure_solve=dict(
                        work_units=5,
                        operator_applications=6,
                        preconditioner_applications=5,
                        true_residual_checks=1,
                    )
                )
            ),
        )
        p = dict(
            schema_version="cfd-craft.anisotropic-pressure/0.1",
            case=c,
            threads=1,
            repetitions=2,
            tolerance=b.TOL,
            max_iterations=1200,
            passed=True,
            source_sha256="b" * 64,
            samples=[copy.deepcopy(sample), copy.deepcopy(sample)],
            result=dict(values=x.tolist(), result_sha256="a" * 64),
            hierarchy=None,
        )
        return c, p

    def test_actual_returned_fields_decide_recovery(self):
        c, p = self.fixture()
        self.assertTrue(b.audit_probe(p, c)["accepted"])
        p["result"]["values"][0] += 0.01
        r = b.audit_probe(p, c)
        self.assertTrue(r["valid"])
        self.assertFalse(r["accepted"])

    def test_a_pressure_failure_never_promotes_a_prefailure_field(self):
        c, p = self.fixture()
        p["passed"] = False
        p["samples"][-1]["error"] = "CFD-E033: pressure iteration limit 1200"
        r = b.audit_probe(p, c)
        self.assertFalse(r["accepted"])
        self.assertNotIn("reused_s", r)
        self.assertIn("CFD-E033", r["errors"][0])

    def test_work_types_limits_and_repetitions_are_strict(self):
        for field, value in [
            ("threads", True),
            ("tolerance", 1e-10),
            ("max_iterations", True),
        ]:
            c, p = self.fixture()
            p[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "CFD-B006"):
                    b.audit_probe(p, c)
        c, p = self.fixture()
        p["samples"][-1]["result_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "CFD-B006 pressure_suite.repetitions"):
            b.audit_probe(p, c)
        for value in [True, 10**400, float("nan"), -1.0]:
            with self.assertRaisesRegex(ValueError, "CFD-B006"):
                b.number(value, "value")

    def test_unaccepted_method_never_gets_a_speedup(self):
        rows = [dict(method=m, warmup=False, accepted=False) for m in b.METHODS]
        result = b.summary(rows, 1)
        self.assertIsNone(result["reused_speedup"]["point_mg"])
        self.assertIsNone(result["reused_speedup"]["ic0"])

    def test_notice_preserves_nonqualifying_groups_and_null_ratios(self):
        result = b.summary(
            [dict(method=m, warmup=False, accepted=False) for m in b.METHODS], 1
        )
        with patch.object(external_notices, "notice") as emit:
            external_notices.anisotropy_performance(
                dict(
                    workflow_valid=True,
                    candidate_passed=False,
                    results=dict(thin=result),
                    rows=[
                        dict(
                            directory="thin-failed", accepted=False, errors=["CFD-E033"]
                        )
                    ],
                ),
                "kernels",
            )
        message = emit.call_args.args[1]
        self.assertIn("qualifying False", message)
        self.assertIn('"point_mg": null', message)
        self.assertIn("CFD-E033", message)


if __name__ == "__main__":
    unittest.main()
