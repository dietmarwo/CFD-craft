#!/usr/bin/env python3
"""Contracts of the steady-algorithm gate script; no CFD runs."""

import unittest
from unittest.mock import patch

import steady_algorithms as s


class Steady(unittest.TestCase):
    def test_tightened_cases_keep_the_ratio_and_select_the_algorithm(self):
        base = s.cavity(24, "explicit", "van_leer")
        self.assertNotIn("steady_algorithm", base["numerics"])
        self.assertEqual(base["numerics"]["momentum_limiter"], "van_leer")
        tight = s.cavity(24, "implicit_projection", "van_leer", 100)
        self.assertEqual(tight["numerics"]["steady_algorithm"], "implicit_projection")
        self.assertAlmostEqual(
            tight["numerics"]["steady_residual_tolerance"],
            base["numerics"]["steady_residual_tolerance"] / 100,
        )
        self.assertAlmostEqual(
            tight["numerics"]["steady_monitor_tolerance"],
            base["numerics"]["steady_monitor_tolerance"] / 100,
        )
        self.assertNotEqual(base["name"], tight["name"])

    def test_fields_of_different_shape_are_rejected(self):
        self.assertEqual(s.difference([1.0, 2.0], [1.0, 2.5]), 0.5)
        with self.assertRaisesRegex(ValueError, "CFD-B008 steady.fields"):
            s.difference([1.0], [1.0, 2.0])

    def test_an_unaccepted_run_is_a_coded_failure(self):
        record = dict(returncode=2, summary=dict(assessment="incomplete"))
        with (
            patch.object(s, "run_case", return_value=record),
            self.assertRaisesRegex(ValueError, "CFD-B008 steady.x"),
        ):
            s.solve("binary", dict(name="x"), s.Path("."), dict(runs=[]))

    def test_the_shrink_gate_needs_five_fold_per_decade(self):
        shrink, passed = s.shrink_gate([3e-5, 4e-6, 9e-7])
        self.assertAlmostEqual(shrink[0], 7.5)
        self.assertFalse(passed)
        self.assertTrue(s.shrink_gate([1e-5, 1e-6, 1e-7])[1])
        self.assertTrue(s.shrink_gate([1e-5, 2e-6])[1])
        self.assertFalse(s.shrink_gate([1e-5, 0.0, 0.0])[1])


if __name__ == "__main__":
    unittest.main()
