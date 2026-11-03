"""Acceptance failures, analytic LP and finite-coverage controls."""

import copy
import unittest
import numpy as np
from allocation import vertex_reference
from sensors import coverage, inversion, selection
from support import native_linear, require, steady


class ScienceChecks(unittest.TestCase):
    def test_require_survives_optimization(self):
        with self.assertRaises(ValueError):
            require(False, "negative control")

    def test_steady_gate_refuses_partial_or_transient_work(self):
        valid = dict(
            returncode=0,
            summary=dict(assessment="steady_discrete_solution"),
            independent=dict(passed=True),
        )
        self.assertTrue(steady(valid))
        for change in [
            dict(returncode=1),
            dict(summary=None),
            dict(independent=dict(passed=False)),
            dict(summary=dict(assessment="transient_interval_completed")),
        ]:
            row = copy.deepcopy(valid)
            row.update(change)
            self.assertFalse(steady(row))

    def test_minimax_diagonal_problem(self):
        a = np.eye(3)
        q, value = vertex_reference(a)
        np.testing.assert_allclose(q, [1, 1, 1], atol=1e-10)
        self.assertAlmostEqual(value, 1.0)
        rows = np.vstack([np.column_stack([a, -np.ones(3)]), [1, 1, 1, 0]])
        point, _ = native_linear(
            [0, 0, 0, 1],
            [0.1, 0.1, 0.2, 0],
            [1.4, 1.4, 2.8, 3],
            rows,
            [-np.inf] * 3 + [3],
            [0] * 3 + [3],
        )
        np.testing.assert_allclose(point, [1, 1, 1, 1], atol=1e-7)

    def test_coverage_optimum_can_be_rank_deficient(self):
        detection = np.array(
            [[1, 1, 1], [1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0], [0, 0, 0]],
            dtype=float,
        )
        weights = np.array([3, 2, 1], dtype=float)
        chosen, _, exact, greedy = selection(detection, weights)
        self.assertEqual(len(exact), 20)
        self.assertEqual(coverage(detection, chosen, weights), 6)
        self.assertEqual(coverage(detection, greedy, weights), 6)
        result = inversion(np.ones((6, 3)), np.ones(6), [0], np.array([0.2, 0.3, 0.5]))
        self.assertEqual(result["rank"], 1)
        self.assertAlmostEqual(result["residual"], 0.0)


if __name__ == "__main__":
    unittest.main()
