"""R1 sensor analytics, native path archives and independent tamper controls."""

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "virtual_ride", ROOT / "integrations/virtual_ride.py"
)
ride = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ride)
BIN = ROOT / "target/release/cfd-craft"


class Sensor(unittest.TestCase):
    def test_step_response_and_zero_time_constant(self):
        times = [i * 0.1 for i in range(101)]
        output = ride.first_order_response([0.0, 10.0], [2.0, 2.0], times, 1.7, 0.0)
        expected = [2 * (1 - math.exp(-time / 1.7)) for time in times]
        self.assertLess(
            max(abs(a - b) for a, b in zip(output, expected, strict=True)), 2e-15
        )
        self.assertEqual(
            ride.first_order_response([0.0, 10.0], [0.0, 10.0], times, 0.0, 0.0), times
        )

    def test_ramp_response_is_exact_independent_of_output_interval(self):
        times = [0.0, 0.1, 0.3, 1.0, 2.0]
        expected = [time - 0.7 * (1 - math.exp(-time / 0.7)) for time in times]
        output = ride.first_order_response(
            [0.0, 0.25, 2.0], [0.0, 0.25, 2.0], times, 0.7, 0.0
        )
        self.assertLess(
            max(abs(a - b) for a, b in zip(output, expected, strict=True)), 3e-16
        )

    def test_rounded_duration_does_not_duplicate_the_final_sample(self):
        endpoint = 0.30000000000000004
        path = dict(
            distance_m=[0.0, endpoint],
            concentrations_kg_m3=[1.0, 1.0],
            points_m=[[0.0, 0.0, 1.0], [endpoint, 0.0, 1.0]],
        )
        result = ride.ride(
            path, speed_m_s=1.0, sampling_interval_s=0.1, response_time_s=1.0
        )
        self.assertEqual(result["time_s"], [0.0, 0.1, 0.2, endpoint])
        self.assertEqual(result["distance_m"][-1], endpoint)
        self.assertEqual(result["points_m"][-1], path["points_m"][-1])

    def test_ride_samples_final_endpoint_and_preserves_geometric_corners(self):
        path = dict(
            distance_m=[0.0, 2.0],
            concentrations_kg_m3=[0.0, 2.0],
            points_m=[[0.0, 0.0, 1.0], [1.0, 1.0, 1.0]],
            polyline_m=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]],
            height_m=1.0,
        )
        result = ride.ride(
            path, speed_m_s=1.0, sampling_interval_s=0.6, response_time_s=0.0
        )
        self.assertEqual(result["time_s"], [0.0, 0.6, 1.2, 1.7999999999999998, 2.0])
        self.assertEqual(result["points_m"][2], [1.0, 0.19999999999999996, 1.0])
        self.assertEqual(result["position_geometry"], "declared_polyline")
        self.assertEqual(result["sensor_kg_m3"], result["steady_field_kg_m3"])
        with self.assertRaisesRegex(ValueError, "sample budget"):
            ride.ride(
                path, speed_m_s=1.0, sampling_interval_s=1e-12, response_time_s=0.0
            )


class PathArchives(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-path-archives-")
        self.root = Path(self.temp.name)
        case = json.loads((ROOT / "examples/manual/point-source.json").read_text())
        case["receptors"].append(
            dict(
                kind="path",
                id="ride",
                polyline_m=[[2.0, 1.0], [6.0, 3.0]],
                height_m=2.0,
                sample_spacing_m=0.25,
            )
        )
        source = self.root / "case.json"
        source.write_text(json.dumps(case))
        self.out = self.root / "run"
        result = subprocess.run(
            [str(BIN), "run", str(source), "--output", str(self.out)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def tearDown(self):
        self.temp.cleanup()

    def reseal(self, name):
        manifest = json.loads((self.out / "manifest.json").read_text())
        manifest["files"][name] = hashlib.sha256(
            (self.out / name).read_bytes()
        ).hexdigest()
        (self.out / "manifest.json").write_text(json.dumps(manifest))
        (self.out / "complete.json").write_text(
            json.dumps(
                dict(
                    manifest_sha256=hashlib.sha256(
                        (self.out / "manifest.json").read_bytes()
                    ).hexdigest()
                )
            )
        )

    def test_archive_path_checker_and_virtual_ride_cli(self):
        for options in [[], ["-O"]]:
            result = subprocess.run(
                [
                    sys.executable,
                    *options,
                    str(ROOT / "validation/check_fields.py"),
                    str(self.out),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path, provenance = ride.read_path(self.out, "tracer", "ride")
        self.assertEqual(provenance["path"], "ride")
        self.assertGreater(len(path["points_m"]), 2)
        output = self.root / "ride.json"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "integrations/virtual_ride.py"),
                str(self.out),
                "--constituent",
                "tracer",
                "--path",
                "ride",
                "--speed-m-s",
                "3.0",
                "--sampling-interval-s",
                "0.1",
                "--response-time-s",
                "2.0",
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads(output.read_text())
        self.assertIn("steady mean", record["scope"])
        self.assertEqual(record["provenance"]["case_sha256"], provenance["case_sha256"])

    def test_resealed_forged_path_samples_rejected_even_under_optimized_python(self):
        summary = json.loads((self.out / "summary.json").read_text())
        summary["constituents"][0]["paths"]["ride"]["concentrations_kg_m3"][2] *= 1.1
        (self.out / "summary.json").write_text(json.dumps(summary))
        self.reseal("summary.json")
        for options in [[], ["-O"]]:
            result = subprocess.run(
                [
                    sys.executable,
                    *options,
                    str(ROOT / "validation/check_fields.py"),
                    str(self.out),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("path sample concentration mismatch", result.stdout)

    def test_virtual_ride_refuses_unaccepted_or_transient_fields(self):
        summary = json.loads((self.out / "summary.json").read_text())
        summary["assessment"] = "incomplete"
        (self.out / "summary.json").write_text(json.dumps(summary))
        self.reseal("summary.json")
        with self.assertRaisesRegex(ValueError, "accepted completed steady"):
            ride.read_path(self.out, "tracer", "ride")


if __name__ == "__main__":
    unittest.main()
