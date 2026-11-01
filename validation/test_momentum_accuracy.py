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
