"""Synthetic continuous-geometry and emission-normalization checks for R2."""

import copy
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
    "traffic_sources", ROOT / "integrations/traffic_sources.py"
)
traffic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(traffic)


class TrafficSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-traffic-")
        self.directory = Path(self.temp.name)
        self.streets = ROOT / "integrations/fixtures/traffic-streets-synthetic.geojson"
        self.rates = ROOT / "integrations/fixtures/traffic-rates-synthetic.csv"
        self.case = json.loads(
            (ROOT / "cases/verification/periodic-tracer.json").read_text()
        )
        self.case["domain"]["size_m"] = [10.0, 10.0, 4.0]
        self.case["grid"]["cells"] = [20, 20, 4]
        self.case["boundaries"]["x"] = "open"
        self.case["flow"]["velocity_m_s"] = [1.0, 0.0, 0.0]
        self.case["sources"] = []
        self.case["initial_conditions"] = []
        self.case["receptors"] = []
        self.map = {
            "schema_version": "cfd-craft.map-provenance/1",
            "coordinate_system": "local projected metric synthetic",
            "crop_m": [100.0, 200.0, 110.0, 210.0],
            "rotation_deg": 0.0,
            "rotation_origin_m": [105.0, 205.0],
            "translation_m": [-100.0, -200.0],
            "flat_ground_only": True,
        }

    def tearDown(self):
        self.temp.cleanup()

    def convert(self, **extra):
        options = dict(height_m=0.5)
        options.update(extra)
        return traffic.convert(self.case, self.map, self.streets, self.rates, **options)

    def write_streets(self, features):
        p = self.directory / "streets.geojson"
        p.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
        self.streets = p
        return p

    def line(self, identifier="main", points=None):
        return {
            "type": "Feature",
            "id": identifier,
            "properties": {},
            "geometry": {
                "type": "LineString",
                "coordinates": points or [[100.1, 205.0], [109.9, 205.0]],
            },
        }

    def table(self, text):
        p = self.directory / "rates.csv"
        p.write_text(text)
        self.rates = p

    def test_multiline_polyline_length_rate_and_omissions_are_explicit(self):
        old = copy.deepcopy(self.case)
        c, report = self.convert()
        self.assertEqual(self.case, old)
        self.assertEqual(c["constituents"], old["constituents"])
        self.assertEqual(len(c["sources"]), 6)
        self.assertAlmostEqual(report["total_added_rate_kg_s"], 3.7e-6, places=18)
        self.assertAlmostEqual(report["streets"]["main"]["retained_length_m"], 10.0)
        self.assertAlmostEqual(report["streets"]["elbow"]["retained_length_m"], 6.0)
        self.assertAlmostEqual(report["streets"]["branches"]["retained_length_m"], 5.0)
        self.assertEqual(
            report["streets"]["outside"]["status"], "outside_crop_or_domain"
        )
        self.assertEqual(report["streets"]["unrated"]["status"], "no_supplied_rate")
        self.assertEqual(
            report["streets_file_sha256"],
            hashlib.sha256(self.streets.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            report["rates_file_sha256"],
            hashlib.sha256(self.rates.read_bytes()).hexdigest(),
        )
        normalized = math.fsum(
            math.dist(s["from_m"], s["to_m"]) * s["rate_kg_s_m"] for s in c["sources"]
        )
        self.assertAlmostEqual(normalized, report["total_added_rate_kg_s"], places=18)
        self.assertTrue(
            all(s["from_m"][2] == 0.5 == s["to_m"][2] for s in c["sources"])
        )

    def test_upper_domain_is_exclusive_and_input_crop_is_observed(self):
        c, _ = self.convert()
        for source in c["sources"]:
            for point in (source["from_m"], source["to_m"]):
                self.assertTrue(
                    all(
                        0 <= v < limit
                        for v, limit in zip(point, [10, 10, 4], strict=True)
                    )
                )
        self.map["translation_m"] = [-105.0, -200.0]
        c, p = self.convert()
        self.assertAlmostEqual(p["streets"]["main"]["retained_length_m"], 5.0)
        self.assertTrue(
            all(s["from_m"][0] >= 0 and s["to_m"][0] >= 0 for s in c["sources"])
        )

    def test_rotation_is_same_world_to_local_transform_as_buildings(self):
        self.map["rotation_deg"] = 90.0
        self.write_streets([self.line(points=[[101.0, 205.0], [109.0, 205.0]])])
        self.table("street_id,constituent,rate_kg_s_m,units\nmain,tracer,2e-7,kg/s/m\n")
        c, p = self.convert()
        self.assertEqual(len(c["sources"]), 1)
        for actual, expected in zip(
            c["sources"][0]["from_m"], [5.0, 9.0, 0.5], strict=True
        ):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(
            c["sources"][0]["to_m"], [5.0, 1.0, 0.5], strict=True
        ):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(p["total_added_rate_kg_s"], 1.6e-6)

    def test_continuous_middle_intersection_and_boundary_touch_are_rejected(self):
        self.write_streets([self.line()])
        self.table("street_id,constituent,rate_kg_s_m,units\nmain,tracer,1e-7,kg/s/m\n")
        self.case["geometry"] = [
            {"id": "thin", "min_m": [4.999, 4.99, 0.0], "max_m": [5.001, 5.01, 2.0]}
        ]
        with self.assertRaisesRegex(ValueError, r"CFD-M002.*main.*thin"):
            self.convert()
        self.case["geometry"][0]["min_m"][1] = 5.0
        with self.assertRaisesRegex(ValueError, "touch"):
            self.convert()
        c, _ = self.convert(height_m=2.0)
        self.assertEqual(len(c["sources"]), 1)

    def test_concave_footprint_is_used_instead_of_only_its_bounds(self):
        self.write_streets([self.line(points=[[105.0, 206.0], [106.0, 206.0]])])
        self.table("street_id,constituent,rate_kg_s_m,units\nmain,tracer,1e-7,kg/s/m\n")
        self.case["geometry"] = [
            {
                "id": "L",
                "min_m": [3.0, 3.0, 0.0],
                "max_m": [7.0, 7.0, 2.0],
                "footprint_m": [[3, 3], [7, 3], [7, 4], [4, 4], [4, 7], [3, 7]],
            }
        ]
        c, _ = self.convert()
        self.assertEqual(len(c["sources"]), 1)

    def test_invalid_units_rates_ids_and_unknown_positive_streets_are_rejected(self):
        header = "street_id,constituent,rate_kg_s_m,units\n"
        for row, text in [
            ("main,tracer,-1,kg/s/m\n", "rate"),
            ("main,tracer,nan,kg/s/m\n", "rate"),
            ("main,tracer,inf,kg/s/m\n", "rate"),
            ("main,tracer,1,kg/s\n", "units"),
            ("unknown,tracer,1e-7,kg/s/m\n", "unknown"),
            ("main,unknown,1e-7,kg/s/m\n", "constituent"),
            ("main,tracer,1e-7,kg/s/m\nmain,tracer,2e-7,kg/s/m\n", "duplicate"),
        ]:
            self.table(header + row)
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, text):
                self.convert()
        self.table("street_id,constituent,rate_kg_s_m\nmain,tracer,1e-7\n")
        with self.assertRaisesRegex(ValueError, "units"):
            self.convert()

    def test_unknown_zero_rate_and_unrated_streets_do_not_invent_emissions(self):
        self.table("street_id,constituent,rate_kg_s_m,units\nunknown,tracer,0,kg/s/m\n")
        c, report = self.convert()
        self.assertEqual(c["sources"], [])
        self.assertEqual(report["total_added_rate_kg_s"], 0.0)
        self.assertEqual(len(report["unmatched_zero_rate_rows"]), 1)
        self.assertTrue(
            all(v["status"] == "no_supplied_rate" for v in report["streets"].values())
        )

    def test_duplicate_street_geometry_and_nonfinite_coordinates_are_rejected(self):
        self.write_streets([self.line(), self.line()])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.convert()
        self.write_streets([self.line(points=[[100.0, 205.0], [float("inf"), 205.0]])])
        with self.assertRaisesRegex(ValueError, "Nonfinite"):
            self.convert()

    def test_multiple_constituents_and_existing_sources_are_preserved(self):
        self.case["constituents"].append(
            {
                "id": "dust",
                "diffusivity_m2_s": 0.0,
                "particle": {"diameter_m": 1e-6, "density_kg_m3": 1000.0},
            }
        )
        self.case["sources"] = [
            {
                "id": "existing",
                "kind": "point",
                "constituent": "tracer",
                "point_m": [1.0, 1.0, 0.5],
                "rate_kg_s": 1e-8,
            }
        ]
        self.table(
            "street_id,constituent,rate_kg_s_m,units\nmain,tracer,1e-7,kg/s/m\nmain,dust,2e-7,kg/s/m\n"
        )
        c, p = self.convert()
        self.assertEqual(c["sources"][0], self.case["sources"][0])
        self.assertEqual(c["constituents"], self.case["constituents"])
        self.assertAlmostEqual(p["total_added_rate_kg_s"], 3e-6)

    def test_cli_runs_native_check_and_survives_optimized_python(self):
        case_file, map_file = self.directory / "case.json", self.directory / "map.json"
        case_file.write_text(json.dumps(self.case))
        map_file.write_text(json.dumps(self.map))
        for options, suffix in [([], "normal"), (["-O"], "optimized")]:
            output = self.directory / suffix
            result = subprocess.run(
                [
                    sys.executable,
                    *options,
                    str(ROOT / "integrations/traffic_sources.py"),
                    "--case",
                    str(case_file),
                    "--map-provenance",
                    str(map_file),
                    "--streets",
                    str(self.streets),
                    "--rates",
                    str(self.rates),
                    "--height-m",
                    "0.5",
                    "--output",
                    str(output),
                    "--binary",
                    str(ROOT / "target/release/cfd-craft"),
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            check = json.loads((output / "check.json").read_text())
            self.assertTrue(check.get("check", check)["valid"])
            self.assertEqual(
                json.loads((output / "traffic-provenance.json").read_text())[
                    "native_check_exit_code"
                ],
                0,
            )

    def test_cli_keeps_native_mask_rejection_without_relocating_street(self):
        # The exact line is outside the prism, but its coarse source cell is
        # masked: native E040 must remain visible, not repaired by the importer.
        self.case["flow"] = {
            "kind": "laminar",
            "initial_velocity_m_s": [1.0, 0.0, 0.0],
            "viscosity_m2_s": 1e-3,
        }
        self.case["geometry"] = [
            {"id": "coarse-wall", "min_m": [4.0, 4.0, 0.0], "max_m": [6.0, 6.3, 2.0]}
        ]
        self.write_streets([self.line(points=[[104.5, 206.35], [105.5, 206.35]])])
        self.table("street_id,constituent,rate_kg_s_m,units\nmain,tracer,1e-7,kg/s/m\n")
        source, provenance = self.directory / "case.json", self.directory / "map.json"
        source.write_text(json.dumps(self.case))
        provenance.write_text(json.dumps(self.map))
        out = self.directory / "rejected"
        process = subprocess.run(
            [
                sys.executable,
                str(ROOT / "integrations/traffic_sources.py"),
                "--case",
                str(source),
                "--map-provenance",
                str(provenance),
                "--streets",
                str(self.streets),
                "--rates",
                str(self.rates),
                "--height-m",
                "0.5",
                "--output",
                str(out),
                "--binary",
                str(ROOT / "target/release/cfd-craft"),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(process.returncode, 1)
        self.assertIn("CFD-E040", (out / "check.json").read_text())
        self.assertEqual(
            json.loads((out / "diagnostic.json").read_text())["path"], "native_check"
        )
        self.assertEqual(
            json.loads((out / "traffic-provenance.json").read_text())[
                "native_check_exit_code"
            ],
            1,
        )
        converted = json.loads((out / "case.json").read_text())
        self.assertEqual(converted["sources"][0]["from_m"][1], 206.35 - 200.0)

    def test_native_emission_normalization_matches_supplied_street_rates(self):
        converted, provenance = self.convert()
        converted["output"].update(fields=True, checkpoint=False)
        source = self.directory / "native-case.json"
        source.write_text(json.dumps(converted))
        out = self.directory / "native-run"
        process = subprocess.run(
            [
                str(ROOT / "target/release/cfd-craft"),
                "run",
                str(source),
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        summary = json.loads((out / "summary.json").read_text())
        tracer = next(x for x in summary["constituents"] if x["id"] == "tracer")
        self.assertAlmostEqual(
            tracer["source_rate_kg_s"], provenance["total_added_rate_kg_s"], places=18
        )
        self.assertLess(tracer["relative_budget_defect"], 1e-12)

    def test_declared_height_map_frame_and_error_hashes_are_checked(self):
        for height in [-1.0, 4.0, float("nan")]:
            with (
                self.subTest(height=height),
                self.assertRaisesRegex(ValueError, "height_m"),
            ):
                self.convert(height_m=height)
        self.map["rotation_origin_m"] = [0.0]
        with self.assertRaises(traffic.TrafficSourceError) as caught:
            self.convert()
        self.assertEqual(
            caught.exception.diagnostic["path"], "map_provenance.rotation_origin_m"
        )
        self.assertEqual(
            caught.exception.diagnostic["input_sha256"]["rates"],
            hashlib.sha256(self.rates.read_bytes()).hexdigest(),
        )
        self.map = []
        with self.assertRaisesRegex(ValueError, "map_provenance"):
            self.convert()

    def test_malformed_case_structures_return_coded_paths_without_traceback(self):
        original = copy.deepcopy(self.case)
        for field, value, path in [
            ("geometry", [None], "case.geometry[0]"),
            ("geometry", [42], "case.geometry[0]"),
            ("constituents", [None], "case.constituents[0].id"),
            ("sources", [None], "case.sources[0].id"),
        ]:
            self.case = copy.deepcopy(original)
            self.case[field] = value
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(traffic.TrafficSourceError) as caught,
            ):
                self.convert()
            self.assertEqual(caught.exception.diagnostic["path"], path)
        case_file, map_file = self.directory / "bad.json", self.directory / "map.json"
        original["geometry"] = [None]
        case_file.write_text(json.dumps(original))
        map_file.write_text(json.dumps(self.map))
        out = self.directory / "malformed-output"
        process = subprocess.run(
            [
                sys.executable,
                "-O",
                str(ROOT / "integrations/traffic_sources.py"),
                "--case",
                str(case_file),
                "--map-provenance",
                str(map_file),
                "--streets",
                str(self.streets),
                "--rates",
                str(self.rates),
                "--height-m",
                "0.5",
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(process.returncode, 1)
        self.assertNotIn("Traceback", process.stderr)
        self.assertEqual(
            json.loads((out / "diagnostic.json").read_text())["path"],
            "case.geometry[0]",
        )


if __name__ == "__main__":
    unittest.main()
