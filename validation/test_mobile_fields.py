"""Real native frozen-flow archives and independently resealed fingerprint faults."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "target/release/examples/mobile_response"


@unittest.skipUnless(BIN.is_file(), "build the native mobile_response example first")
class FrozenFlowFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.campaign = tempfile.TemporaryDirectory(prefix="cfd-frozen-campaign-")
        root = Path(cls.campaign.name)
        case = json.loads((ROOT / "examples/manual/path-ride.json").read_text())
        case["grid"]["cells"] = [8, 4, 1]
        case["flow"] = dict(
            kind="laminar",
            initial_velocity_m_s=[1.0, 0.0, 0.0],
            viscosity_m2_s=1e-3,
            acceleration_m_s2=[0.0, 0.0, 0.0],
        )
        case["numerics"]["monitor_window"] = 10
        case["run"].update(max_steps=4000, wall_time_limit_s=15.0, threads=1)
        case["output"].update(fields=True, checkpoint=False)
        request = dict(
            schema_version="cfd-craft.mobile-response/1",
            case=case,
            groups=[dict(id="street", source_ids=["S0"])],
            truth_multipliers=[1.3],
            campaign_wall_time_limit_s=60.0,
        )
        source = root / "request.json"
        source.write_text(json.dumps(request))
        result = subprocess.run(
            [str(BIN), str(source), str(root / "result")],
            capture_output=True,
            text=True,
            timeout=70,
        )
        if result.returncode:
            cls.campaign.cleanup()
            raise AssertionError(result.stdout + result.stderr)
        report = json.loads((root / "result/report.json").read_text())
        if not report["passed"]:
            cls.campaign.cleanup()
            raise AssertionError(report)
        cls.template = root / "result/column-0"

    @classmethod
    def tearDownClass(cls):
        cls.campaign.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-frozen-fault-")
        self.root = Path(self.temp.name)
        self.archive = self.root / "archive"
        shutil.copytree(self.template, self.archive)

    def tearDown(self):
        self.temp.cleanup()

    def modify(self, filename, callback):
        path = self.archive / filename
        content = json.loads(path.read_text())
        callback(content)
        path.write_text(json.dumps(content))
        manifest = json.loads((self.archive / "manifest.json").read_text())
        manifest["files"][filename] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.archive / "manifest.json").write_text(json.dumps(manifest))
        (self.archive / "complete.json").write_text(
            json.dumps(
                dict(
                    manifest_sha256=hashlib.sha256(
                        (self.archive / "manifest.json").read_bytes()
                    ).hexdigest()
                )
            )
        )

    def audit(self, code, message=None):
        for options in [[], ["-O"]]:
            result = subprocess.run(
                [
                    sys.executable,
                    *options,
                    str(ROOT / "validation/check_fields.py"),
                    str(self.archive),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, code, result.stdout + result.stderr)
            if message:
                self.assertIn(message, result.stdout)

    def test_actual_cold_response_archive_passes_both_python_modes(self):
        self.audit(0)
        record = json.loads((self.archive / "summary.json").read_text())
        self.assertEqual(record["frozen_flow"]["response_flow_updates"], 0)
        self.assertEqual(record["frozen_flow"]["native_flow_solves"], 1)

    def test_resealed_velocity_pressure_k_and_epsilon_changes_break_frozen_identity(
        self,
    ):
        for name in ["velocity", "pressure", "k", "epsilon"]:
            with self.subTest(field=name):
                shutil.rmtree(self.archive)
                shutil.copytree(self.template, self.archive)

                def alter(record):
                    record[name][0] += 1e-9

                self.modify("fields.json", alter)
                self.audit(1, "frozen flow state fingerprint")

    def test_resealed_declared_fingerprint_is_checked_against_stored_arrays(self):
        def alter(record):
            record["frozen_flow"]["flow_state_sha256"] = "f" * 64

        self.modify("summary.json", alter)
        self.audit(1, "frozen flow state fingerprint")

    def test_a_nonzero_flow_update_claim_is_not_a_frozen_response(self):
        def alter(record):
            record["frozen_flow"]["response_flow_updates"] = 1

        self.modify("summary.json", alter)
        self.audit(1, "frozen flow preparation/update evidence")


if __name__ == "__main__":
    unittest.main()
