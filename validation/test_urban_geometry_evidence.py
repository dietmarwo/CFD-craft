"""Independent polygon archive and per-shape evidence tamper controls."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from check_fields import check

ROOT = Path(__file__).resolve().parents[1]


class GeometryEvidenceTests(unittest.TestCase):
    def archive(self, root):
        out = root / "run"
        done = subprocess.run(
            [
                str(ROOT / "target/release/cfd-craft"),
                "run",
                str(ROOT / "cases/verification/polygon-prism.json"),
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(check(out)["passed"])
        return out

    def test_polygon_mask_and_all_shape_evidence_are_recomputed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.archive(Path(tmp))
            geometry = json.loads((out / "geometry.json").read_text())
            self.assertEqual(geometry["shapes"]["concave"]["exact_volume_m3"], 8.0)
            self.assertEqual(
                geometry["shapes"]["concave"]["narrowest_fluid_passage_cells"], 1
            )

    def test_resealed_false_volume_or_passage_is_rejected(self):
        for field in ["exact_volume_m3", "narrowest_fluid_passage_cells"]:
            with tempfile.TemporaryDirectory() as tmp:
                out = self.archive(Path(tmp))
                path = out / "geometry.json"
                value = json.loads(path.read_text())
                value["shapes"]["concave"][field] += 1
                path.write_text(json.dumps(value))
                manifest = json.loads((out / "manifest.json").read_text())
                manifest["files"]["geometry.json"] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
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
                    check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("per-shape", result.stdout)


if __name__ == "__main__":
    unittest.main()
