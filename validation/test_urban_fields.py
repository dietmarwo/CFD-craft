#!/usr/bin/env python3
"""Independent aerosol/canopy archive audits and resealed tamper controls."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from check_fields import check

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "target/release/cfd-craft"


class UrbanFields(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-urban-fields-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_case(self, fixture):
        out = self.root / fixture
        result = subprocess.run(
            [
                str(BIN),
                "run",
                str(ROOT / "cases/verification" / f"{fixture}.json"),
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(check(out)["passed"])
        return out

    def alter(self, out, name, callback):
        path = out / name
        record = json.loads(path.read_text())
        callback(record)
        path.write_text(json.dumps(record))
        manifest = json.loads((out / "manifest.json").read_text())
        manifest["files"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (out / "manifest.json").write_text(json.dumps(manifest))
        (out / "complete.json").write_text(
            json.dumps(
                {
                    "manifest_sha256": hashlib.sha256(
                        (out / "manifest.json").read_bytes()
                    ).hexdigest()
                }
            )
        )

    def assert_rejected(self, out, message):
        for options in [[], ["-O"]]:
            result = subprocess.run(
                [
                    sys.executable,
                    *options,
                    str(ROOT / "validation/check_fields.py"),
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(message, result.stdout)

    def test_particle_and_canopy_fixtures_pass_under_python_optimized(self):
        for fixture in [
            "particle-settling",
            "particle-steady-column",
            "vegetation-leaf-decay",
            "vegetation-balance",
        ]:
            out = self.run_case(fixture)
            result = subprocess.run(
                [
                    sys.executable,
                    "-O",
                    str(ROOT / "validation/check_fields.py"),
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_forged_cumulative_deposition_cannot_close_a_false_budget(self):
        out = self.run_case("vegetation-leaf-decay")

        def alter_state(record):
            record["budgets"][0]["deposited_kg"]["vegetation"] += 1e-6

        def alter_summary(record):
            record["constituents"][0]["deposited_kg"]["vegetation"] += 1e-6

        self.alter(out, "fields.json", alter_state)
        self.alter(out, "summary.json", alter_summary)
        self.assert_rejected(out, "independent mass accounting")

    def test_forged_leaf_rate_is_rejected_from_stored_fields(self):
        out = self.run_case("vegetation-leaf-decay")

        def alter(record):
            record["constituents"][0]["deposition_rate_kg_s"]["vegetation"] *= 1.2

        self.alter(out, "summary.json", alter)
        self.assert_rejected(out, "vegetation deposition rate")

    def test_forged_extra_deposition_surface_is_rejected(self):
        out = self.run_case("vegetation-leaf-decay")

        def alter(record):
            record["constituents"][0]["deposition_rate_kg_s"]["walls"] = 1e-6

        self.alter(out, "summary.json", alter)
        self.assert_rejected(out, "unknown deposition surface")

    def test_forged_deposition_of_a_passive_gas_is_rejected(self):
        out = self.run_case("periodic-tracer")

        def alter(record):
            record["constituents"][0]["deposition_rate_kg_s"] = {"ground": 1e-6}

        self.alter(out, "summary.json", alter)
        self.assert_rejected(out, "passive gas has particle deposition")

    def test_forged_drag_work_is_rejected_from_staggered_fields(self):
        out = self.run_case("vegetation-balance")

        def alter(record):
            record["vegetation"]["drag_power_per_density_m5_s3"] *= 1.2

        self.alter(out, "summary.json", alter)
        self.assert_rejected(out, "canopy drag power")

    def test_forged_pm_sum_is_rejected(self):
        out = self.run_case("vegetation-leaf-decay")

        def alter(record):
            record["particulate_matter"]["PM2.5"]["mass_kg"] *= 1.2

        self.alter(out, "summary.json", alter)
        self.assert_rejected(out, "PM bin mass sum")


if __name__ == "__main__":
    unittest.main()
