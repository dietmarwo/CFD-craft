"""Campaign contract controls: cold cases, direction frames and failed rows."""

import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "urban_campaign", ROOT / "validation/urban_campaign.py"
)
campaign = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(campaign)


class UrbanCampaignTests(unittest.TestCase):
    def base(self):
        return json.loads((ROOT / "cases/canyon/wh1-wind270.json").read_text())

    def test_twelve_cold_cases_and_compass_transform(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "campaign"
            plan = campaign.prepare(
                self.base(),
                out,
                run_budget_s=1,
                campaign_budget_s=100,
                threads=1,
                workers=2,
                map_rotation_deg=23.0,
            )
            self.assertEqual(len(plan["jobs"]), 12)
            self.assertEqual(plan["direction_frame"], "model_local_meteorological_from")
            for relative in plan["jobs"]:
                job = json.loads((out / relative).read_text())
                case = json.loads(((out / relative).parent / "case.json").read_text())
                self.assertEqual(job["initialization"], "cold")
                self.assertNotIn("restart", job)
                self.assertEqual(
                    job["geographic_direction_deg_from"],
                    (job["direction_deg_from"] - 23) % 360,
                )
                self.assertEqual(case["run"]["wall_time_limit_s"], 1)

    def test_campaign_budget_exhaustion_retains_all_twelve_failed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "campaign"
            plan = campaign.prepare(
                self.base(),
                out,
                run_budget_s=10,
                campaign_budget_s=0.01,
                threads=1,
                workers=2,
            )
            report = campaign.run(plan, out, ROOT / "target/release/cfd-craft")
            self.assertEqual(len(report["rows"]), 12)
            self.assertEqual(report["failed"], 12)
            self.assertTrue(
                all(r["error"] == "campaign_budget_exhausted" for r in report["rows"])
            )

    def test_invalid_budgets_and_prescribed_wind_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for budget in [-1, math.nan, math.inf]:
                with self.assertRaises(ValueError):
                    campaign.prepare(
                        self.base(),
                        Path(tmp) / "out",
                        run_budget_s=budget,
                        campaign_budget_s=1,
                        threads=1,
                        workers=1,
                    )

    def test_actual_worker_retains_native_invalid_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "campaign"
            base = self.base()
            base["grid"]["cells"][0] = 0
            plan = campaign.prepare(
                base, out, run_budget_s=1, campaign_budget_s=100, threads=1, workers=2
            )
            # Use a subprocess because worker installs its own hard memory cap.
            import subprocess, sys

            folder = (out / plan["jobs"][0]).parent
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "validation/urban_campaign.py"),
                    "worker",
                    str(folder / "job.json"),
                ],
                check=True,
                timeout=10,
            )
            row = json.loads((folder / "result.json").read_text())
            self.assertFalse(row["accepted"])
            self.assertEqual(row["exit_code"], 1)
            self.assertEqual(row["error"], "no_native_archive")


if __name__ == "__main__":
    unittest.main()
