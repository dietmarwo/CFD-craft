"""Independent numerical/statistical and actual native-MIP regressions for R3."""

import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mobile_inference", ROOT / "integrations/mobile_inference.py"
)
mobile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mobile)


def rows(names, winds=None):
    return [
        dict(kind="ride", receptor=name, wind=(winds[i] if winds is not None else 270))
        for i, name in enumerate(names)
    ]


class IdentifiabilityAndNoise(unittest.TestCase):
    def test_identical_and_proportional_sources_have_named_null_combinations(self):
        a = np.array([[1, 1, 0], [2, 2, 1], [3, 3, 2]], dtype=float)
        ids = ["street-west", "street-east", "background-source"]
        report = mobile.identifiability(a, ids)
        self.assertEqual(report["rank"], 2)
        self.assertEqual(report["nullity"], 1)
        self.assertFalse(report["full_column_rank"])
        self.assertIn(
            ["street-west", "street-east"], report["identical_response_groups"]
        )
        for combination in report["named_ambiguous_combinations"]:
            vector = np.array([combination.get(name, 0) for name in ids])
            self.assertLess(np.linalg.norm(a @ vector), 1e-12)
        proportional = a.copy()
        proportional[:, 1] *= 2
        report = mobile.identifiability(proportional, ids)
        self.assertEqual(report["rank"], 2)
        self.assertEqual(report["identical_response_groups"], [])
        vector = np.array(
            [report["named_ambiguous_combinations"][0].get(name, 0) for name in ids]
        )
        self.assertLess(np.linalg.norm(proportional @ vector), 1e-12)
        wide = mobile.identifiability([[1, 2, 3]], ["a", "b", "c"])
        self.assertEqual((wide["rank"], wide["nullity"]), (1, 2))
        self.assertEqual(len(wide["named_ambiguous_combinations"]), 2)

    def test_named_null_combination_keeps_small_but_essential_scaled_coefficients(self):
        response = np.array([[1e9, 1.0], [2e9, 2.0], [3e9, 3.0]])
        ids = ["large-reference-rate", "small-reference-rate"]
        report = mobile.identifiability(response, ids)
        self.assertEqual(report["rank"], 1)
        combination = report["named_ambiguous_combinations"][0]
        self.assertEqual(set(combination), set(ids))
        vector = np.array([combination[name] for name in ids])
        self.assertLess(np.linalg.norm(response @ vector), 1e-12)
        self.assertLess(abs(vector[0]), 1e-7)

    def test_rank_one_whitening_matches_independent_dense_covariance_inverse(self):
        a = (
            np.array([[1, 2], [3, 0], [2, 4], [1, 1], [0, 2], [3, 5]], dtype=float)
            * 1e-9
        )
        y = np.array([1, 2, 3, 4, 5, 6], dtype=float) * 1e-9
        metadata = rows(["a", "b", "a", "b", "a", "a"], [270, 270, 270, 270, 180, 270])
        sensor, scatter = 2e-10, 1e-9
        aw, yw = mobile.whiten(a, y, metadata, sensor, scatter)
        covariance = np.eye(6) * sensor**2
        for i, first in enumerate(metadata):
            for j, second in enumerate(metadata):
                if (first["wind"], first["receptor"]) == (
                    second["wind"],
                    second["receptor"],
                ):
                    covariance[i, j] += scatter**2
        expected_gram = a.T @ np.linalg.solve(covariance, a)
        expected_cross = a.T @ np.linalg.solve(covariance, y)
        np.testing.assert_allclose(aw.T @ aw, expected_gram, rtol=2e-13, atol=1e-13)
        np.testing.assert_allclose(aw.T @ yw, expected_cross, rtol=2e-13, atol=1e-13)
        self.assertAlmostEqual(
            float(yw @ yw), float(y @ np.linalg.solve(covariance, y)), places=10
        )
        reference = mobile.noise_covariance(3, sensor, scatter)
        np.testing.assert_allclose(
            reference, np.eye(3) * sensor**2 + np.ones((3, 3)) * scatter**2
        )

    def test_tall_rank_and_pass_whitening_stay_within_a_bounded_address_space(self):
        # This subprocess allows at most 128 MiB of additional virtual memory.
        # A 20000-square U/covariance would require 3.2 GB and is rejected by
        # the OS before allocation; the thin/rank-one implementation fits.
        source = f"""
import importlib.util,json,os,resource
import numpy as np
spec=importlib.util.spec_from_file_location("mobile",{str(ROOT / "integrations/mobile_inference.py")!r})
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
current=int(open("/proc/self/statm").read().split()[0])*os.sysconf("SC_PAGE_SIZE")
resource.setrlimit(resource.RLIMIT_AS,(current+128*1024**2,current+128*1024**2))
x=np.linspace(0,1,20000);a=np.column_stack((np.ones(len(x)),x,x*x));y=a@np.array([1.0,2.0,3.0])
metadata=[dict(kind="ride",wind=270,receptor="long-ride") for _ in x]
aw,yw=module.whiten(a,y,metadata,0.1,0.2)
report=module.identifiability(aw,["a","b","c"])
print(json.dumps(dict(rank=report["rank"],rows=len(aw),finite=bool(np.isfinite(yw).all()))))
"""
        environment = dict(
            os.environ,
            OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="1",
            MKL_NUM_THREADS="1",
        )
        result = subprocess.run(
            [sys.executable, "-c", source],
            capture_output=True,
            text=True,
            env=environment,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            json.loads(result.stdout), dict(rank=3, rows=20000, finite=True)
        )

    def test_reference_covariance_and_source_dimension_caps_reject_before_large_work(
        self,
    ):
        with self.assertRaisesRegex(ValueError, "CFD-M003"):
            mobile.noise_covariance(2049, 1.0, 1.0)
        with self.assertRaisesRegex(ValueError, "CFD-M003"):
            mobile.identifiability(np.ones((1, 65)), [f"source-{i}" for i in range(65)])

    def test_station_rows_do_not_enter_mobile_whitening(self):
        with self.assertRaisesRegex(ValueError, "CFD-M003"):
            mobile.whiten(
                [[1, 2]],
                [1],
                [dict(kind="station", wind=270, receptor="fixed")],
                1.0,
                1.0,
            )


class InferenceIsolation(unittest.TestCase):
    def data(self):
        a = np.array([[1, 0], [0, 1], [1, 1], [2, 1], [1, 2], [3, 5]], dtype=float)
        truth = np.array([1.3, 0.7])
        metadata = rows(["train", "train", "train", "held", "held", "station"])
        metadata[-1]["kind"] = "station"
        return a, a @ truth, metadata, truth

    def infer(self, a, y, metadata):
        return mobile.infer_sources(
            a,
            y,
            metadata,
            ["west", "east"],
            ["train"],
            ["held"],
            sensor_sigma_kg_m3=0.1,
            pass_scatter_sigma_kg_m3=0.2,
        )

    def test_heldout_values_and_station_data_cannot_change_fitted_rates(self):
        a, y, metadata, truth = self.data()
        original = self.infer(a, y, metadata)
        np.testing.assert_allclose(
            original["multipliers"], truth, rtol=1e-13, atol=1e-13
        )
        altered = y.copy()
        altered[3:] += [100.0, 1000.0, 10000.0]
        result = self.infer(a, altered, metadata)
        self.assertEqual(result["multipliers"], original["multipliers"])
        self.assertEqual(result["training_row_indices"], [0, 1, 2])
        self.assertEqual(result["heldout_row_indices"], [3, 4])
        self.assertGreater(result["heldout_relative_error"], 0.9)
        modified_response = a.copy()
        modified_response[3:] *= 100
        result = self.infer(modified_response, y, metadata)
        self.assertEqual(result["multipliers"], original["multipliers"])

    def test_heldout_identification_is_not_used_to_claim_unique_training_rates(self):
        a = [[1, 1], [2, 2], [1, 0], [0, 1]]
        metadata = rows(["train", "train", "held", "held"])
        result = self.infer(a, np.asarray(a) @ [1.3, 0.7], metadata)
        self.assertFalse(result["individual_rates_unique"])
        self.assertEqual(
            result["estimate_label"], "one_nonnegative_solution_ambiguous_rates"
        )
        self.assertEqual(result["identifiability"]["rank"], 1)
        self.assertIn(
            ["west", "east"], result["identifiability"]["identical_response_groups"]
        )

    def test_training_and_heldout_names_are_disjoint_and_must_exist(self):
        a, y, metadata, _ = self.data()
        for train, held in [
            (["train"], ["train"]),
            (["unknown"], ["held"]),
            (["station"], ["held"]),
        ]:
            with (
                self.subTest(train=train, held=held),
                self.assertRaisesRegex(ValueError, "CFD-M003"),
            ):
                mobile.infer_sources(a, y, metadata, ["west", "east"], train, held)


class PassPlanning(unittest.TestCase):
    def parameters(self):
        return dict(
            sensor_sigma_kg_m3=2.0,
            pass_scatter_sigma_kg_m3=3.0,
            effective_samples_per_pass=4.0,
            relative_half_width=0.1,
            confidence_z=2.0,
            systematic_sigma_kg_m3=0.2,
        )

    def test_pass_count_matches_gaussian_mean_variance_and_is_minimal(self):
        report = mobile.required_passes(10.0, **self.parameters())
        self.assertEqual(report["passes"], 48)
        self.assertTrue(report["achievable"])
        variance = 3.0**2 + 2.0**2 / 4.0
        self.assertLessEqual(2 * math.sqrt(variance / 48 + 0.2**2), 1.0)
        self.assertGreater(2 * math.sqrt(variance / 47 + 0.2**2), 1.0)
        self.assertFalse(report["simulated"])

    def test_systematic_floor_zero_mean_and_work_budget_stay_explicit(self):
        parameters = self.parameters()
        parameters["systematic_sigma_kg_m3"] = 0.5
        floor = mobile.required_passes(10.0, **parameters)
        self.assertIsNone(floor["passes"])
        self.assertFalse(floor["achievable"])
        zero = mobile.required_passes(0.0, **self.parameters())
        self.assertIsNone(zero["passes"])
        absolute = mobile.required_passes(
            0.0, absolute_half_width_kg_m3=1.0, **self.parameters()
        )
        self.assertEqual(absolute["passes"], 48)
        limited = mobile.required_passes(10.0, max_passes=20, **self.parameters())
        self.assertFalse(limited["achievable"])
        self.assertIsNone(limited["passes"])

    def test_pass_budget_must_be_a_positive_integer(self):
        for maximum in [0, -1, 1.5]:
            with (
                self.subTest(maximum=maximum),
                self.assertRaisesRegex(ValueError, "CFD-M003"),
            ):
                mobile.required_passes(10.0, max_passes=maximum, **self.parameters())


class ActualNativeRouteMIP(unittest.TestCase):
    def test_native_e_optimal_integer_solution_matches_all_small_subsets(self):
        information = np.array(
            [
                [[1, 0], [0, 0]],
                [[0, 0], [0, 1]],
                [[0.7, 0.6], [0.6, 0.7]],
                [[0.5, -0.4], [-0.4, 0.5]],
                [[0.3, 0.1], [0.1, 0.8]],
            ],
            dtype=float,
        )
        candidates = [
            dict(id=f"route-{i}", riding_time_s=cost)
            for i, cost in enumerate([2, 2, 3, 1, 2])
        ]
        result = mobile.select_routes(
            information, candidates, 5.0, wall_time_limit_s=20.0
        )
        exhaustive = mobile.exhaustive_route_check(information, candidates, 5.0)
        self.assertTrue(result["certified"], result)
        self.assertAlmostEqual(
            result["minimum_eigenvalue"],
            exhaustive["optimum_minimum_eigenvalue"],
            places=7,
        )
        self.assertLessEqual(result["riding_time_s"], 5.0)
        self.assertEqual(
            len(result["selected_indices"]), len(set(result["selected_indices"]))
        )
        optimum = exhaustive["optimum_minimum_eigenvalue"] / result["information_scale"]
        for iteration in result["iterations"]:
            self.assertLessEqual(iteration["normalized_lower_bound"], optimum + 2e-7)
            self.assertGreaterEqual(iteration["normalized_upper_bound"], optimum - 2e-7)
            self.assertEqual(iteration["native"]["status"], "optimal")

    def test_certificate_uses_the_proven_master_bound_not_the_incumbent(self):
        import dataclasses

        import lp_ip_craft

        information = np.array(
            [[[1, 0], [0, 0]], [[0, 0], [0, 1]], [[0.7, 0.6], [0.6, 0.7]]],
            dtype=float,
        )
        candidates = [dict(id=f"route-{i}", riding_time_s=1.0) for i in range(3)]
        native_solve = lp_ip_craft.solve

        def weaker_bound(*args, **kwargs):
            # An "optimal" stop within a positive gap: the proven bound
            # exceeds the incumbent's objective value.
            result = native_solve(*args, **kwargs)
            return dataclasses.replace(result, best_bound=result.best_bound + 0.25)

        with mock.patch.object(lp_ip_craft, "solve", side_effect=weaker_bound):
            result = mobile.select_routes(
                information, candidates, 2.0, max_cuts=4, wall_time_limit_s=20.0
            )
        self.assertFalse(result["certified"], result)
        for iteration in result["iterations"]:
            self.assertGreaterEqual(
                iteration["normalized_upper_bound"],
                iteration["native"]["best_bound"],
            )

        def no_bound(*args, **kwargs):
            return dataclasses.replace(native_solve(*args, **kwargs), best_bound=None)

        with mock.patch.object(lp_ip_craft, "solve", side_effect=no_bound):
            result = mobile.select_routes(
                information, candidates, 2.0, wall_time_limit_s=20.0
            )
        self.assertFalse(result["certified"])
        self.assertIn("proven bound", result["iterations"][0]["error"])

    def test_cut_budget_retains_actual_incumbent_without_certifying_relaxation(self):
        information = np.array(
            [[[1, 0.99], [0.99, 1]], [[0.8, 0], [0, 0.8]]], dtype=float
        )
        candidates = [
            dict(id="correlated", riding_time_s=1.0),
            dict(id="balanced", riding_time_s=1.0),
        ]
        result = mobile.select_routes(
            information, candidates, 1.0, max_cuts=1, wall_time_limit_s=20.0
        )
        self.assertFalse(result["certified"])
        self.assertEqual(len(result["iterations"]), 1)
        self.assertEqual(result["selected"], ["correlated"])
        self.assertAlmostEqual(result["minimum_eigenvalue"], 0.01, places=12)
        exhaustive = mobile.exhaustive_route_check(information, candidates, 1.0)
        self.assertAlmostEqual(exhaustive["optimum_minimum_eigenvalue"], 0.8)
        self.assertIn("native", result["iterations"][0])

    def test_duplicate_route_ids_and_nonpositive_information_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate route"):
            mobile.select_routes(
                [np.eye(2), np.eye(2)],
                [
                    dict(id="same", riding_time_s=1.0),
                    dict(id="same", riding_time_s=1.0),
                ],
                1.0,
            )
        with self.assertRaisesRegex(ValueError, "positive semidefinite"):
            mobile.select_routes(
                [[[-1.0, 0.0], [0.0, 1.0]]], [dict(id="bad", riding_time_s=1.0)], 1.0
            )

    def test_route_information_uses_declared_correlated_pass_noise(self):
        a = np.array([[1.0, 2.0], [2.0, 1.0], [3.0, 0.0]])
        metadata = rows(["first", "first", "second"], [270, 270, 180])
        candidates = [
            dict(id="a", wind=270, ride="first", riding_time_s=10.0),
            dict(id="b", wind=180, ride="second", riding_time_s=20.0),
        ]
        information = mobile.route_information(
            a,
            metadata,
            candidates,
            sensor_sigma_kg_m3=0.5,
            pass_scatter_sigma_kg_m3=0.8,
        )
        cov = np.eye(2) * 0.5**2 + np.ones((2, 2)) * 0.8**2
        np.testing.assert_allclose(
            information[0],
            a[:2].T @ np.linalg.solve(cov, a[:2]),
            rtol=2e-13,
            atol=1e-13,
        )
        np.testing.assert_allclose(
            information[1], np.outer(a[2], a[2]) / (0.5**2 + 0.8**2), rtol=2e-13
        )


if __name__ == "__main__":
    unittest.main()
