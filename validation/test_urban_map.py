"""Synthetic converter fixtures; no map dataset is committed."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "urban_map", ROOT / "integrations/urban_map.py"
)
urban_map = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(urban_map)


class UrbanMapTests(unittest.TestCase):
    def convert(self, source=None, **extra):
        options = dict(
            crop=[90, 190, 145, 245],
            cell_m=2.0,
            source_license="CC0-1.0 (synthetic)",
            attribution="CFD-craft synthetic fixture",
            coordinate_system="local metric synthetic",
            rotation_deg=0.0,
        )
        options.update(extra)
        return urban_map.convert(
            source or ROOT / "integrations/fixtures/urban-synthetic.geojson",
            json.loads((ROOT / "cases/canyon/wh1-wind270.json").read_text()),
            **options,
        )

    def test_crop_height_fallback_merge_clearances_and_provenance(self):
        case, evidence = self.convert()
        self.assertEqual(len(case["geometry"]), 3)
        self.assertEqual(
            [x["height_method"] for x in evidence["assumptions"]],
            ["attribute", "levels", "default", "attribute"],
        )
        self.assertEqual(len(evidence["source_sha256"]), 64)
        self.assertEqual(evidence["clearances_H"]["downstream"], 15.0)
        self.assertTrue(evidence["flat_ground_only"])
        self.assertEqual(case["sources"], [])
        self.assertTrue(all("footprint_m" in b for b in case["geometry"]))

    def test_refuse_nonflat_terrain_and_invalid_footprints(self):
        data = json.loads(
            (ROOT / "integrations/fixtures/urban-synthetic.geojson").read_text()
        )
        data["features"][1]["properties"]["ground_elevation_m"] = 2.0
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "map.json"
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "Terrain elevation range"):
                self.convert(p)
            data["features"][1]["properties"]["ground_elevation_m"] = 0.0
            data["features"][0]["geometry"]["coordinates"] = [
                [[100, 200], [112, 212], [100, 212], [112, 200], [100, 200]]
            ]
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "Invalid footprint"):
                self.convert(p)

    def test_small_shapes_and_geographic_coordinates_are_refused(self):
        with self.assertRaisesRegex(ValueError, "below two cells"):
            self.convert(cell_m=20.0)
        with self.assertRaisesRegex(ValueError, "projected"):
            self.convert(coordinate_system="EPSG:4326")

    def test_cityjson_transformed_vertices_and_heights(self):
        data = {
            "type": "CityJSON",
            "version": "2.0",
            "transform": {"scale": [2, 2, 2], "translate": [100, 200, 5]},
            "vertices": [
                [0, 0, 0],
                [6, 0, 0],
                [6, 6, 0],
                [0, 6, 0],
                [0, 0, 4],
                [6, 0, 4],
                [6, 6, 4],
                [0, 6, 4],
            ],
            "CityObjects": {
                "b": {
                    "type": "Building",
                    "geometry": [
                        {
                            "type": "MultiSurface",
                            "boundaries": [[[0, 1, 2, 3]], [[4, 5, 6, 7]]],
                        }
                    ],
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "map.json"
            p.write_text(json.dumps(data))
            case, evidence = self.convert(p)
            self.assertEqual(case["geometry"][0]["max_m"][2], 8.0)
            self.assertEqual(evidence["ground_range_m"], 0.0)
            data["vertices"][1][2] = 1
            data["vertices"][2][2] = 1
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "Terrain elevation range"):
                self.convert(p)

    def test_wind_rotates_with_geometry_and_nonfinite_parameters_fail(self):
        c, p = self.convert(rotation_deg=45.0)
        self.assertEqual(c["flow"]["direction_deg_from"], 315.0)
        self.assertEqual(p["source_wind_direction_deg_from"], 270.0)
        for name in ("default_height_m", "level_height_m", "max_ground_range_m"):
            with self.assertRaises(ValueError):
                self.convert(**{name: float("inf")})

    def test_cityjson_parent_containers_and_negative_indices(self):
        data = {
            "type": "CityJSON",
            "vertices": [
                [100, 200, 0],
                [112, 200, 0],
                [112, 212, 0],
                [100, 212, 0],
                [100, 200, 8],
                [112, 200, 8],
                [112, 212, 8],
                [100, 212, 8],
            ],
            "CityObjects": {
                "parent": {
                    "type": "Building",
                    "children": ["part"],
                    "attributes": {"name": "example"},
                },
                "part": {
                    "type": "BuildingPart",
                    "parents": ["parent"],
                    "geometry": [
                        {
                            "type": "MultiSurface",
                            "lod": "1.2",
                            "boundaries": [[[0, 1, 2, 3]], [[4, 5, 6, 7]]],
                        }
                    ],
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "map.json"
            p.write_text(json.dumps(data))
            c, e = self.convert(p)
            self.assertEqual(len(c["geometry"]), 1)
            data["CityObjects"]["part"]["geometry"][0]["boundaries"][0][0][0] = -1
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "vertex index"):
                self.convert(p)

    def test_twelve_direction_padding(self):
        _, p = self.convert(ensemble_clearance=True)
        self.assertEqual(
            p["clearances_H"],
            dict(upstream=15.0, downstream=15.0, lateral=15.0, above_roof=5.0),
        )


if __name__ == "__main__":
    unittest.main()
