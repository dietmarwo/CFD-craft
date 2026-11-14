"""Unit tests for scripts/mdbook_links.py (the mdBook link preprocessor)."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mdbook_links", ROOT / "scripts/mdbook_links.py"
)
LINKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LINKS)

BLOB = "https://github.com/dietmarwo/CFD-craft/blob/main/"


class RewriteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in [
            "docs/guide/a.md",
            "docs/guide/b.md",
            "docs/guide/README.md",
            "docs/old.md",
            "docs/images/x.jpg",
            "cases/c.json",
        ]:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        self.listed = {"guide/a.md", "guide/b.md", "guide/README.md", "guide/index.md"}

    def rewrite(self, text):
        return LINKS.rewrite_chapter(text, "guide/a.md", self.root, "docs", self.listed)

    def test_link_between_listed_pages_is_left_alone(self):
        text = "See [b](b.md#part) and ![x](../images/x.jpg)."
        self.assertEqual(self.rewrite(text), text)

    def test_stub_and_outside_file_become_github_urls(self):
        text = "[old](../old.md#h) and [case](../../cases/c.json)"
        expected = f"[old]({BLOB}docs/old.md#h) and [case]({BLOB}cases/c.json)"
        self.assertEqual(self.rewrite(text), expected)

    def test_readme_link_becomes_index_link(self):
        self.assertEqual(self.rewrite("[g](README.md#s)"), "[g](index.md#s)")

    def test_code_and_absolute_links_are_not_touched(self):
        text = "`[o](../old.md)` [w](https://example.org/a.md) [h](#here)\n```\n[o](../old.md)\n```"
        self.assertEqual(self.rewrite(text), text)

    def test_missing_target_fails_with_the_code(self):
        with self.assertRaises(LINKS.SiteError) as caught:
            self.rewrite("[m](missing.md)")
        self.assertIn("CFD-R004 site.link", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
