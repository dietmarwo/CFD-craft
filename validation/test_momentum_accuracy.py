#!/usr/bin/env python3
"""Analytic-fixture and evidence-failure tests; no synthetic CFD performance claims."""

import json
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import momentum_accuracy as m
import momentum_baseline as b


class Momentum(unittest.TestCase):
    def test_occupied_baseline_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, "report.json")
            path.write_text("prior evidence")
            with (
                patch("sys.argv", ["momentum_baseline", "--output", temp]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(b.main(), 1)
            self.assertEqual(path.read_text(), "prior evidence")

    def test_sampled_vortex_is_discretely_divergence_free_and_translates(self):
        n = 32
        time_s = 0.013
        u = m.exact_vortex([n, 2, n], time_s).reshape(3, n, 2, n)
        divergence = n * (np.roll(u[0], -1, axis=2) - u[0]) + n * (
            np.roll(u[2], -1, axis=0) - u[2]
        )
        self.assertLess(float(np.max(abs(divergence))), 3e-14)
        self.assertTrue(np.all(u[1] == m.OFFSET[1]))
        self.assertFalse(np.array_equal(u.ravel(), m.exact_vortex([n, 2, n], 0)))
        for axis in [0, 2]:
            self.assertAlmostEqual(float(np.mean(u[axis])), m.OFFSET[axis], places=14)

    def test_orders_distinguish_first_and_second_order_in_all_norms(self):
        for exponent in [1, 2]:
            errors = [
                {key: (1 / n) ** exponent for key in ["l1", "l2", "linf"]}
                for n in [16, 32, 64]
            ]
            for order in m.orders([16, 32, 64], errors).values():
                self.assertAlmostEqual(order, exponent, places=12)
        with self.assertRaisesRegex(ValueError, "momentum.orders"):
            m.orders([16, 32], [{key: 0 for key in ["l1", "l2", "linf"]}])

    def test_nonfinite_error_and_false_conservation_are_not_hidden(self):
        with self.assertRaisesRegex(ValueError, "momentum.norms"):
            m.norms([float("nan")])
        drift = m.momentum_change([1, 2, 3], [1.01, 2, 3], [1, 1, 1])
        self.assertGreater(drift[0]["normalized_change"], 0.009)

    def notices(self, report):
        import external_notices

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, "report.json")
            path.write_text(json.dumps(report))
            output = io.StringIO()
            with (
                patch("sys.argv", ["external_notices", str(path), "momentum"]),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(external_notices.main(), 0)
        return output.getvalue()

    def test_fixture_report_reaches_the_checks_view(self):
        text = self.notices(
            dict(
                schema_version="cfd-craft.momentum-accuracy/0.1",
                passed=True,
                runs=[],
                vortices=[
                    dict(
                        grid=64,
                        max_dt_s=0.0005,
                        accepted=True,
                        steps=100,
                        error=dict(l1=0.00122074),
                        momentum=[dict(normalized_change=0.00049480891)],
                    )
                ],
                spatial_orders=dict(l1=0.9739, l2=0.97475, linf=0.95906),
                temporal=dict(
                    difference_order=2.00022,
                    fine_difference_over_spatial_error=4.95e-06,
                ),
                stability=dict(
                    steps=1000, final_min=0.4235, final_max=0.5765, new_extrema=0.0
                ),
            )
        )
        self.assertIn("::notice title=momentum::passed True", text)
        for expected in ["0.9739 / 0.97475 / 0.95906", "0.00122074", "2.0002"]:
            self.assertIn(expected, text)
        self.assertNotIn("title=cavity", text)

    def test_reference_report_reaches_the_checks_view(self):
        text = self.notices(
            dict(
                schema_version="cfd-craft.momentum-baseline/0.1",
                passed=False,
                error="CFD-B007 momentum.defaults.fields.json: canonical artifacts differ",
                reference=dict(
                    grid=96,
                    accepted=True,
                    steps=21390,
                    solver_s=1074.45,
                    reference_error=0.00920541,
                ),
                self_convergence=dict(
                    available=True,
                    orders=dict(l1=1.28),
                    rows=[dict(grid=16, accepted=True, l1=0.01, l2=0.02, linf=0.03)],
                ),
                default_controls=[
                    dict(
                        case="cavity",
                        passed=True,
                        steps=2010,
                        pressure_iterations=204850,
                        assessment="steady_discrete_solution",
                    )
                ],
            )
        )
        for expected in [
            "native 96² reference: accepted True; steps 21390",
            "Ghia error 0.00920541",
            "canonical artifacts differ",
            "default cavity: byte-identical True; steps 2010",
        ]:
            self.assertIn(expected, text)
        self.assertNotIn("title=cavity", text)

    def test_byte_controls_reject_changed_artifacts_and_work(self):
        with tempfile.TemporaryDirectory() as temp:
            a, c = Path(temp, "a"), Path(temp, "b")
            a.mkdir()
            c.mkdir()
            for name in b.ARTIFACTS:
                (a / name).write_text("canonical bytes")
                (c / name).write_text("canonical bytes")
            summary = dict(
                steps=3,
                pressure_iterations=27,
                assessment="incomplete",
                termination="iteration_limit",
            )
            for directory in [a, c]:
                (directory / "summary.json").write_text(json.dumps(summary))
            self.assertTrue(b.compare_defaults(a, c)["passed"])
            for name in b.ARTIFACTS:
                (c / name).write_text("changed")
                with self.assertRaisesRegex(ValueError, "momentum.defaults"):
                    b.compare_defaults(a, c)
                (c / name).write_text("canonical bytes")
            summary["pressure_iterations"] += 1
            (c / "summary.json").write_text(json.dumps(summary))
            with self.assertRaisesRegex(
                ValueError, "momentum.defaults.pressure_iterations"
            ):
                b.compare_defaults(a, c)


if __name__ == "__main__":
    unittest.main()
