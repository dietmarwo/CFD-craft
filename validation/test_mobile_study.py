"""Driver-level geometry, consumed-input provenance and retained failure tests.

The sealed envelopes below are synthetic consumer fixtures, not CFD results.
Actual native flow/transport and LP-IP verification are separate tests.
"""

import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mobile_study", ROOT / "tutorials/mobile_measurements.py"
)
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class MobileStudy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-mobile-driver-")
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def archive(self):
        archive = self.directory / "consumer-fixture"
        archive.mkdir()
        case = {
            "run": {"mode": "steady"},
            "receptors": [
                {
                    "kind": "path",
                    "id": "ride",
                    "polyline_m": [[1.0, 0.5], [1.1, 0.5], [1.1, 1.5]],
                    "height_m": 0.5,
                    "sample_spacing_m": 2.0,
                }
            ],
        }
        case_raw = json.dumps(case).encode()
        summary = {
            "termination": "completed",
            "assessment": "steady_discrete_solution",
            "checks": [{"name": "synthetic-consumer-fixture", "passed": True}],
            "case_sha256": sha(case_raw),
            "physics_sha256": "2" * 64,
            "source_sha256": "3" * 64,
            "experimental_validation": "synthetic_not_validated",
            "constituents": [
                {
                    "id": "tracer",
                    "paths": {
                        "ride": {
                            "points_m": [[1.0, 0.5, 0.5], [1.1, 1.5, 0.5]],
                            "distance_m": [0.0, 1.1],
                            "concentrations_kg_m3": [1e-6, 2e-6],
                            "mean_kg_m3": 1.5e-6,
                        }
                    },
                }
            ],
        }
        payload = {"case.json": case_raw, "summary.json": json.dumps(summary).encode()}
        for name, raw in payload.items():
            (archive / name).write_bytes(raw)
        manifest = {
            "schema_version": "cfd-craft.manifest/0.1",
            "files": {name: sha(raw) for name, raw in payload.items()},
        }
        raw = json.dumps(manifest).encode()
        (archive / "manifest.json").write_bytes(raw)
        (archive / "complete.json").write_text(
            json.dumps({"manifest_sha256": sha(raw)})
        )
        return archive

    def input_files(self):
        response = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [2.0, 1.0]]) * 1e-8
        truth = np.array([1.3, 0.7])
        metadata = [
            dict(kind="ride", wind="wind-270", receptor=name, sample_index=i % 2)
            for i, name in enumerate(["train", "train", "held", "held"])
        ]
        bundle = {
            "schema_version": "cfd-craft.ride-response-matrix/1",
            "source_ids": ["a", "b"],
            "rows": metadata,
            "matrix_kg_m3": response.tolist(),
            "noise_assumptions": dict(
                sensor_sigma_kg_m3=1e-10, pass_scatter_sigma_kg_m3=2e-10
            ),
            "virtual_ride": dict(
                speed_m_s=1.5,
                sampling_interval_s=0.25,
                response_time_s=1.0,
                initial_kg_m3=0.0,
            ),
            "frozen_plan_sha256": "4" * 64,
            "study_driver_sha256": "5" * 64,
            "producers": [
                dict(
                    wind="wind-270",
                    core_source_sha256="6" * 64,
                    driver_sha256="7" * 64,
                    request_sha256="8" * 64,
                    flow_state_sha256="9" * 64,
                )
            ],
        }
        path = self.directory / "matrix.json"
        path.write_text(json.dumps(bundle))
        observations = self.directory / "observations.csv"
        with observations.open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["wind", "ride", "sample_index", "concentration_kg_m3"])
            for row, value in zip(metadata, response @ truth, strict=True):
                writer.writerow(
                    [row["wind"], row["receptor"], row["sample_index"], value]
                )
        return path, observations, bundle

    def test_observed_ride_restores_original_bent_geometry_and_provenance(self):
        archive = self.archive()
        plan = {
            "virtual_ride": dict(
                speed_m_s=1.0,
                sampling_interval_s=0.1,
                response_time_s=0.0,
                initial_kg_m3=0.0,
            )
        }
        ride = study.observed_ride(archive, plan, "ride")
        self.assertEqual(ride["position_geometry"], "declared_polyline")
        at_corner = next(
            i for i, time in enumerate(ride["time_s"]) if abs(time - 0.1) < 1e-15
        )
        np.testing.assert_allclose(
            ride["points_m"][at_corner], [1.1, 0.5, 0.5], rtol=0, atol=1e-14
        )
        self.assertEqual(ride["provenance"]["path"], "ride")
        self.assertEqual(
            ride["provenance"]["summary_file_sha256"],
            sha((archive / "summary.json").read_bytes()),
        )

    def test_fit_reports_file_hashes_and_complete_operator_provenance(self):
        matrix, observations, bundle = self.input_files()
        result = study.fit_csv(matrix, observations, ["train"], ["held"])
        np.testing.assert_allclose(
            result["multipliers"], [1.3, 0.7], rtol=1e-12, atol=1e-12
        )
        self.assertLess(result["heldout_relative_error"], 1e-12)
        provenance = result["input_provenance"]
        self.assertEqual(provenance["matrix_sha256"], sha(matrix.read_bytes()))
        self.assertEqual(
            provenance["observations_sha256"], sha(observations.read_bytes())
        )
        for key in [
            "virtual_ride",
            "frozen_plan_sha256",
            "study_driver_sha256",
            "producers",
        ]:
            self.assertEqual(provenance[key], bundle[key])

    def test_fit_hashes_the_consumed_bytes_even_if_paths_change_during_analysis(self):
        matrix, observations, _ = self.input_files()
        matrix_raw, observations_raw = matrix.read_bytes(), observations.read_bytes()
        native_infer = study.infer_sources

        def changed_paths(*args, **kwargs):
            result = native_infer(*args, **kwargs)
            matrix.write_text("different bytes after parsing")
            observations.write_text("different bytes after parsing")
            return result

        with mock.patch.object(study, "infer_sources", side_effect=changed_paths):
            result = study.fit_csv(matrix, observations, ["train"], ["held"])
        self.assertEqual(result["input_provenance"]["matrix_sha256"], sha(matrix_raw))
        self.assertEqual(
            result["input_provenance"]["observations_sha256"], sha(observations_raw)
        )
        self.assertNotEqual(
            result["input_provenance"]["matrix_sha256"], sha(matrix.read_bytes())
        )

    def test_duplicate_matrix_or_observation_keys_are_rejected(self):
        matrix, observations, bundle = self.input_files()
        duplicate = copy.deepcopy(bundle)
        duplicate["rows"][1] = copy.deepcopy(duplicate["rows"][0])
        matrix.write_text(json.dumps(duplicate))
        with self.assertRaisesRegex(ValueError, "duplicate matrix sample key"):
            study.fit_csv(matrix, observations, ["train"], ["held"])
        matrix.write_text(json.dumps(bundle))
        with observations.open(newline="") as file:
            rows = list(csv.reader(file))
        with observations.open("a", newline="") as file:
            csv.writer(file).writerow(rows[1])
        with self.assertRaisesRegex(ValueError, "duplicate observed sample key"):
            study.fit_csv(matrix, observations, ["train"], ["held"])

    def test_timeout_retains_partial_native_work_and_available_archive_audits(self):
        plan = study.configuration("source-response")
        plan["winds"] = plan["winds"][:1]
        output = self.directory / "timeout-study"

        def timed_out(command, **kwargs):
            folder = Path(command[2])
            folder.mkdir()
            partial = {
                "passed": False,
                "flow_preparations": 1,
                "flow_solves": 1,
                "preparation_steps": 13,
                "columns": [
                    {
                        "id": "street-a",
                        "archive": "column-0",
                        "steps": 7,
                        "accepted": False,
                    }
                ],
            }
            (folder / "report.json").write_text(json.dumps(partial))
            (folder / "flow").mkdir()
            (folder / "flow/complete.json").write_text("{}")
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with (
            mock.patch.object(study.subprocess, "run", side_effect=timed_out),
            mock.patch.object(
                study,
                "check",
                return_value={"passed": True, "scope": "synthetic audit callback"},
            ),
        ):
            report = study.run(plan, self.directory / "unused-native", output)
        self.assertFalse(report["passed"])
        self.assertEqual(len(report["native_runs"]), 1)
        row = report["native_runs"][0]
        self.assertIsNone(row["exit_code"])
        self.assertIn("timed out", row["error"])
        self.assertEqual(row["native"]["preparation_steps"], 13)
        self.assertEqual(row["native"]["columns"][0]["steps"], 7)
        self.assertEqual(row["independent_audits"][0]["archive"], "flow")
        self.assertTrue(row["independent_audits"][0]["passed"])
        stored = json.loads((output / "report.json").read_text())
        self.assertEqual(stored, report)
        self.assertEqual(
            report["frozen_plan_sha256"],
            sha((output / "frozen-study-plan.json").read_bytes()),
        )

    def test_unsafe_ids_overlap_and_affine_sensor_initialization_are_rejected(self):
        original = study.configuration("source-response")
        study.controlled_winds(original)
        for name in ["../escape", "/absolute", "nested/name", "..", "a\\b"]:
            plan = copy.deepcopy(original)
            plan["winds"][0]["id"] = name
            with (
                self.subTest(wind=name),
                self.assertRaisesRegex(ValueError, "CFD-M003"),
            ):
                study.controlled_winds(plan)
            plan = copy.deepcopy(original)
            plan["training_rides"][0] = name
            with (
                self.subTest(route=name),
                self.assertRaisesRegex(ValueError, "CFD-M003"),
            ):
                study.controlled_winds(plan)
        plan = copy.deepcopy(original)
        plan["heldout_rides"][0] = plan["training_rides"][0]
        with self.assertRaisesRegex(ValueError, "unique and disjoint"):
            study.controlled_winds(plan)
        plan = copy.deepcopy(original)
        plan["virtual_ride"]["initial_kg_m3"] = 1e-8
        with self.assertRaisesRegex(ValueError, "initial"):
            study.controlled_winds(plan)


if __name__ == "__main__":
    unittest.main()
