#!/usr/bin/env python3
"""The evidence zip keeps directory entries and re-verifies the extracted copy."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_evidence as evidence

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "target/release/cfd-craft"
# External archives only: any existing file stands in for the native reporter.
STAND_IN = Path(sys.executable)


def external_archive(directory, saved):
    """A sealed external archive whose progress names its saved time directories."""
    (directory / "case").mkdir(parents=True)
    for name in saved:
        (directory / "case" / name).mkdir()
    (directory / "case/0/U").write_text("initial\n")
    (directory / "manifest.json").write_text(
        json.dumps({"schema_version": "cfd-craft.external-archive/0.1"})
    )
    (directory / "summary.json").write_text(json.dumps({"saved": saved}))
    (directory / "complete.json").write_text("{}")


def progress_verify(directory):
    """Stands in for backend.verify: the progress check lists numeric directories."""
    recorded = json.loads((Path(directory) / "summary.json").read_text())["saved"]
    found = sorted(p.name for p in (Path(directory) / "case").iterdir() if p.is_dir())
    if found != sorted(recorded):
        raise ValueError("CFD-X006 archive.progress: summary differs")
    return {"passed": True}


class EmptyDirectories(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-evidence-test-")
        self.root = Path(self.temp.name)
        self.tree = self.root / "sweep"
        # An old time directory without files, as recorded at sealing.
        external_archive(self.tree / "row/run", ["0", "500", "2132"])

    def tearDown(self):
        self.temp.cleanup()

    def test_an_empty_recorded_directory_survives_and_still_verifies(self):
        with patch.object(evidence.backend, "verify", side_effect=progress_verify):
            report = evidence.round_trip(self.tree, self.root / "e.zip", STAND_IN)
            self.assertTrue(report["round_trip_identical"], report)
            self.assertEqual((report["archives"], report["verified"]), (1, 1))
            with zipfile.ZipFile(self.root / "e.zip") as z:
                self.assertIn("sweep/row/run/case/500/", z.namelist())
            # A file-only copy, as an artifact upload makes, loses the directory.
            files_only = self.root / "files-only"
            for path in self.tree.rglob("*"):
                if path.is_file():
                    target = files_only / path.relative_to(self.tree)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
            rows = evidence.verify_tree(files_only, STAND_IN)
            self.assertFalse(rows[0]["verified"])
            self.assertIn("archive.progress", rows[0]["error"])

    def test_a_failing_original_stays_failing_in_the_copy(self):
        (self.tree / "row/run/case/500").rmdir()
        with patch.object(evidence.backend, "verify", side_effect=progress_verify):
            report = evidence.round_trip(self.tree, self.root / "e.zip", STAND_IN)
        self.assertTrue(report["round_trip_identical"])
        self.assertEqual(report["verified"], 0)
        self.assertEqual(report["failed"][0]["archive"], "row/run")

    def test_symlinks_existing_outputs_and_unknown_archives_are_rejected(self):
        (self.tree / "link").symlink_to(self.tree / "row")
        with self.assertRaisesRegex(ValueError, r"CFD-B004 sweep\.archive\.link:"):
            evidence.pack(self.tree, self.root / "e.zip")
        (self.tree / "link").unlink()
        (self.root / "taken.zip").write_text("")
        with self.assertRaisesRegex(ValueError, r"sweep\.archive\.output:"):
            evidence.pack(self.tree, self.root / "taken.zip")
        (self.tree / "row/run/manifest.json").write_text('{"schema_version": "x"}')
        rows = evidence.verify_tree(self.tree, STAND_IN)
        self.assertIn("sweep.archive.schema", rows[0]["error"])

    def test_a_missing_reporter_or_an_empty_tree_is_an_error(self):
        with self.assertRaisesRegex(ValueError, r"sweep\.archive\.binary:"):
            evidence.round_trip(self.tree, self.root / "e.zip", self.root / "none")
        self.assertFalse((self.root / "e.zip").exists())
        (self.root / "empty").mkdir()
        with self.assertRaisesRegex(ValueError, r"sweep\.archive\.archives:"):
            evidence.round_trip(self.root / "empty", self.root / "f.zip", STAND_IN)

    def test_the_same_failure_compares_equal_and_a_lossy_copy_does_not(self):
        broken = self.tree / "broken"
        broken.mkdir()
        (broken / "complete.json").write_text("{}")
        (self.tree / "report.json").write_text("{}")
        with patch.object(evidence.backend, "verify", side_effect=progress_verify):
            report = evidence.round_trip(self.tree, self.root / "e.zip", STAND_IN)
            self.assertTrue(report["round_trip_identical"], report)
            self.assertIn("<tree>", report["failed"][0]["error"])
            real = zipfile.ZipFile.extractall

            def lossy(archive, path):
                real(archive, path)
                (Path(path) / "sweep/report.json").unlink()

            with patch.object(zipfile.ZipFile, "extractall", lossy):
                report = evidence.round_trip(self.tree, self.root / "g.zip", STAND_IN)
            self.assertFalse(report["round_trip_identical"])
            self.assertFalse(report["tree_identical"])
            self.assertEqual(report["missing_in_copy"], ["report.json"])

    def test_a_root_with_parent_components_writes_safe_member_names(self):
        (self.tree / "row/sub").mkdir()
        with patch.object(evidence.backend, "verify", side_effect=progress_verify):
            report = evidence.round_trip(
                self.tree / "row/sub/../..", self.root / "e.zip", STAND_IN
            )
        self.assertTrue(report["round_trip_identical"], report)
        with zipfile.ZipFile(self.root / "e.zip") as z:
            self.assertTrue(all(n.startswith("sweep") for n in z.namelist()))


@unittest.skipUnless(BINARY.is_file(), "build the release CLI first")
class NativeArchives(unittest.TestCase):
    def test_native_archives_are_checked_by_the_reporter(self):
        with tempfile.TemporaryDirectory(prefix="cfd-evidence-native-") as temp:
            temp = Path(temp)
            case = json.loads(
                (ROOT / "cases/verification/periodic-tracer.json").read_text()
            )
            case["grid"]["cells"] = [4, 4, 4]
            case["run"]["max_steps"] = 2
            (temp / "case.json").write_text(json.dumps(case))
            tree = temp / "tree"
            tree.mkdir()
            done = subprocess.run(
                [BINARY, "run", temp / "case.json", "--output", tree / "native"],
                capture_output=True,
                text=True,
            )
            self.assertIn(done.returncode, (0, 2), done.stderr)
            report = evidence.round_trip(tree, temp / "a.zip", BINARY)
            self.assertEqual((report["archives"], report["verified"]), (1, 1))
            self.assertTrue(report["round_trip_identical"])
            summary = tree / "native/summary.json"
            summary.write_text(summary.read_text().replace('"steps"', '"steps" '))
            report = evidence.round_trip(tree, temp / "b.zip", BINARY)
            self.assertEqual(report["verified"], 0)
            self.assertTrue(report["round_trip_identical"])

    def test_the_command_line_exits_one_without_an_identical_round_trip(self):
        with tempfile.TemporaryDirectory(prefix="cfd-evidence-cli-") as temp:
            done = subprocess.run(
                [
                    sys.executable,
                    ROOT / "validation/archive_evidence.py",
                    Path(temp) / "missing",
                    Path(temp) / "e.zip",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(done.returncode, 1)
            self.assertIn(
                "CFD-B004 sweep.archive.source", json.loads(done.stdout)["error"]
            )


if __name__ == "__main__":
    unittest.main()
