"""Tests of scripts/generate_reference.py. No network; needs the release binary."""

from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/generate_reference.py"
BINARY = ROOT / "target/release/cfd-craft"
PAGES = [
    "docs/reference/case-schema.md",
    "docs/reference/result-schema.md",
    "docs/reference/python-api.md",
    "docs/reference/cli.md",
]


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--binary", str(BINARY), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )


class GenerateReference(unittest.TestCase):
    def setUp(self):
        self.assertTrue(BINARY.is_file(), "build target/release/cfd-craft first")
        self.saved = {p: (ROOT / p).read_bytes() for p in PAGES}
        self.addCleanup(self.restore)

    def restore(self):
        for page, data in self.saved.items():
            (ROOT / page).write_bytes(data)

    def test_check_passes_on_committed_pages(self):
        done = run("--check")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_changed_page_fails_with_code_and_name(self):
        for page in PAGES:
            with self.subTest(page=page):
                path = ROOT / page
                if page.endswith("cli.md"):
                    # Text outside the generated blocks is hand-written.
                    changed = self.saved[page].replace(
                        b"| 0 | success", b"| 0 | changed", 1
                    )
                    self.assertNotEqual(changed, self.saved[page])
                else:
                    changed = self.saved[page] + b"\nchanged\n"
                path.write_bytes(changed)
                done = run("--check")
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("CFD-R002", done.stderr)
                self.assertIn(page, done.stderr)
                for other in PAGES:
                    if other != page:
                        self.assertNotIn(other, done.stderr)
                path.write_bytes(self.saved[page])

    def test_missing_page_fails(self):
        page = ROOT / "docs/reference/case-schema.md"
        page.unlink()
        done = run("--check")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("docs/reference/case-schema.md", done.stderr)

    def test_generation_twice_is_identical(self):
        self.assertEqual(run().returncode, 0)
        first = {p: (ROOT / p).read_bytes() for p in PAGES}
        self.assertEqual(run().returncode, 0)
        second = {p: (ROOT / p).read_bytes() for p in PAGES}
        self.assertEqual(first, second)
        self.assertEqual(first, self.saved)

    def test_generated_text_has_no_identity(self):
        for page in PAGES:
            text = self.saved[page].decode("utf-8")
            self.assertNotIn("/home/", text, page)
            self.assertIsNone(re.search(r"[0-9a-f]{64}", text), page)
            self.assertIsNone(
                re.search(r"\b20[0-9]{2}-[0-9]{2}-[0-9]{2}\b", text), page
            )

    def test_missing_binary_is_a_coded_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--check",
                    "--binary",
                    str(Path(tmp) / "absent"),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("CFD-R002 reference.binary", done.stderr)

    def test_missing_catalog_code_fails(self):
        catalog = ROOT / "docs/diagnostics.md"
        original = catalog.read_bytes()
        self.addCleanup(catalog.write_bytes, original)
        catalog.write_bytes(original.replace(b"CFD-E066", b"CFD-E0xx"))
        done = run("--check")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("reference.diagnostics", done.stderr)
        self.assertIn("CFD-E066", done.stderr)

    def test_cli_page_keeps_hand_written_text(self):
        text = self.saved["docs/reference/cli.md"].decode("utf-8")
        for name in ("usage", "exit-codes"):
            self.assertEqual(text.count(f"<!-- begin generated: {name} -->"), 1)
            self.assertEqual(text.count(f"<!-- end generated: {name} -->"), 1)
        for command in (
            "describe",
            "check",
            "run",
            "profile",
            "preview",
            "report",
            "verify",
        ):
            self.assertIn(f"\n## {command}\n", text)


if __name__ == "__main__":
    unittest.main()
