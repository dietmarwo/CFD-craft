"""Acceptance failures, analytic LP and finite-coverage controls."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import record
from allocation import vertex_reference
from coupled import mean_square_speed
from sensors import coverage, inversion, optimal_subsets, selection
from support import native_linear, require, steady


class ScienceChecks(unittest.TestCase):
    def test_require_survives_optimization(self):
        with self.assertRaisesRegex(ValueError, "^CFD-T001 optimization.arms: "):
            require(False, "arms", "negative control")

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

    def test_mean_square_speed_uses_cells_not_a_third_of_the_faces(self):
        # 2 x 2 x 2 cells; x and z walls (3 faces per line), y periodic (2).
        case = dict(
            geometry=[],
            grid=dict(cells=[2, 2, 2]),
            boundaries=dict(x="wall", y="periodic", z="wall"),
        )
        x = np.zeros((2, 2, 3))  # z, y, x faces
        x[:, :, 1] = 2.0  # interior x faces; wall faces stay zero
        y = np.zeros(8)
        z = np.zeros((3, 2, 2))
        velocity = np.concatenate([x.ravel(), y, z.ravel()])
        # Trapezoid per x line: (0 + 4 + 0) / 2 cells = 2 in every cell.
        self.assertAlmostEqual(mean_square_speed(velocity, case), 2.0)
        self.assertEqual(len(velocity), 32)  # a third of 32 is not 8 cells
        with self.assertRaises(ValueError):
            mean_square_speed(velocity[:-1], case)

    def test_optimal_subsets_lists_every_coverage_tie(self):
        detection = np.array(
            [[1, 1, 1], [1, 1, 1], [1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]],
            dtype=float,
        )
        a = np.vstack([np.eye(3), np.eye(3)])
        optimum, rows = optimal_subsets(detection, np.ones(3), a)
        self.assertEqual(optimum, 3)
        self.assertEqual(
            [r["sensors"] for r in rows if len(r["sensors"]) == 1], [[0], [1]]
        )
        self.assertTrue(
            all(r["condition_number"] is None for r in rows if len(r["sensors"]) < 3)
        )
        self.assertTrue(any(r["condition_number"] == 1.0 for r in rows))

    def test_verified_record_holds_only_complete_passed_runs(self):
        path = Path(__file__).parent / "results/verified.json"
        verified = json.loads(path.read_text())
        self.assertEqual(
            verified["schema_version"], "cfd-craft.optimization-record/0.1"
        )
        for preset in ["smoke", "study"]:
            for name in record.CHAPTERS:
                row = verified["presets"][preset][name]
                self.assertIs(row["passed"], True)
                self.assertTrue(row["checks"])
                self.assertNotIn("source_sha256", row)
            self.assertEqual(
                verified["presets"][preset]["F3"]["results"]["supported_designs"], 0
            )

    def test_record_refuses_an_incomplete_run(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "F1"
            folder.mkdir()
            (folder / "summary.json").write_text(
                json.dumps(dict(state="running", passed=False, preset="smoke"))
            )
            with self.assertRaisesRegex(ValueError, "F1.state"):
                record.chapter(Path(temp), "F1")


if __name__ == "__main__":
    unittest.main()
