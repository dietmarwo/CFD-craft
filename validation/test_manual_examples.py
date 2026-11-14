#!/usr/bin/env python3
"""Contract tests of the manual-example runner's OpenFOAM mode and of the links.

No OpenFOAM runtime is needed: the runner's recipes are compared with the
`bash` blocks of guide chapters 15 and 17 that carry the same commands, and a
missing runtime must produce a coded failure report naming each step. The link
test resolves relative links, `blob/main` links and links to the documentation
site.
"""

import contextlib
import io
import json
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(1, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_docs
import external_notices
import manual_examples

ROOT = Path(__file__).resolve().parents[1]
FOAM = "runs/openfoam13/runtime/opt/openfoam13"
CH15 = "docs/guide/15-openfoam-first-run.md"
CH17 = "docs/guide/17-continuation-and-mapping.md"


def guide_commands(page, title):
    """The commands of the `bash` blocks of one section, continuation lines joined.

    Each block's `mkdir -p runs` is the setup of the session directory, not a
    recipe step, and is left out.
    """
    parsed, failures = check_docs.parse((ROOT / page).read_text(encoding="utf-8"))
    if failures:
        raise ValueError(f"{page}: {failures[0]}")
    sections = [s for s in parsed["sections"] if s["title"] == title]
    if len(sections) != 1:
        raise ValueError(f"{page}: no single section `{title}`")
    blocks = [b for b in sections[0]["blocks"] if b["language"] == "bash"]
    commands = []
    for block in blocks:
        for line in block["text"].replace("\\\n", " ").splitlines():
            if line.strip() and line.strip() != "mkdir -p runs":
                commands.append(shlex.split(line))
    return blocks, commands


class Recipes(unittest.TestCase):
    def recorded(self):
        steps = []

        def run(name, argv, timeout=180):
            words = []
            for value in argv:
                value = str(value)
                if value == sys.executable:
                    value = "python"
                elif value.startswith(str(ROOT) + "/"):
                    value = value[len(str(ROOT)) + 1 :]
                words.append(value)
            steps.append((name, words, timeout))

        # The manual's paths, relative to the repository root.
        manual_examples.foam_recipes(run, Path(FOAM), Path("runs"))
        return steps

    def test_the_recipes_are_the_guide_commands_in_order(self):
        steps = [words for _, words, _ in self.recorded()]
        sections = [
            (CH15, "Use the adapter from Python", 1, 1),  # Example 22
            (CH15, "Generate, run and inspect", 1, 3),  # Example 21
            (CH17, "Continue on the same mesh", 1, 2),  # Example 24
            (CH17, "Start a finer mesh", 2, 2),  # Example 25 and its run
        ]
        guide = []
        for page, title, blocks, commands in sections:
            found_blocks, found = guide_commands(page, title)
            self.assertEqual(len(found_blocks), blocks, title)
            self.assertEqual(len(found), commands, title)
            guide += found
        self.assertEqual(len(steps), 8)
        self.assertEqual(steps, guide)
        # Chapter 17 is its own session: its setup repeats the cold run of
        # chapter 15, and both pages run only with the runtime.
        _, setup = guide_commands(CH17, "Setup")
        self.assertEqual(setup, steps[1:3])
        for page in (CH15, CH17):
            parsed, _ = check_docs.parse((ROOT / page).read_text(encoding="utf-8"))
            self.assertIn("openfoam", parsed["flags"], page)
            self.assertIsNone(parsed["none"], page)

    def test_the_runtime_root_is_passed_as_given(self):
        for name, words, timeout in self.recorded():
            if "--foam-root" in words:
                self.assertEqual(words[words.index("--foam-root") + 1], FOAM, name)
            self.assertGreaterEqual(timeout, 600, name)


class Outcome(unittest.TestCase):
    def test_run_and_api_results_are_summarized(self):
        summary = dict(
            passed=False,
            execution_status="completed",
            numerical=dict(
                passed=False,
                iterations=3000,
                solver_reported_convergence=False,
                initial_residuals_final_iteration={"p": 2e-6},
            ),
        )
        expected = dict(
            passed=False,
            execution_status="completed",
            numerical_passed=False,
            iterations=3000,
            solver_reported_convergence=False,
            final_residuals={"p": 2e-6},
        )
        self.assertEqual(manual_examples.outcome(json.dumps(summary)), expected)
        api = dict(passed=False, execution={**summary, "error": "CFD-X007 x"})
        self.assertEqual(
            manual_examples.outcome(json.dumps(api)),
            {**expected, "error": "CFD-X007 x"},
        )
        self.assertIsNone(manual_examples.outcome("not json"))
        self.assertIsNone(manual_examples.outcome("[1]"))


class MissingRuntime(unittest.TestCase):
    def test_every_step_runs_and_each_failure_is_recorded(self):
        with tempfile.TemporaryDirectory(prefix="cfd-manual-foam-") as temp:
            out = Path(temp) / "run"
            done = subprocess.run(
                [
                    sys.executable,
                    ROOT / "validation/manual_examples.py",
                    "--foam-root",
                    Path(temp) / "missing",
                    "--output",
                    out,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(done.returncode, 1, done.stderr)
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(json.loads(done.stdout), report)
            # The steps ran with output paths relative to the working directory.
            self.assertTrue((out / "foam-cavity-input/case.json").is_file())
            self.assertEqual(report["schema_version"], manual_examples.SCHEMA)
            self.assertEqual(report["examples"], "openfoam")
            self.assertIs(report["passed"], False)
            rows = {r["name"]: r for r in report["rows"]}
            self.assertEqual(len(rows), 8)
            self.assertEqual(rows["foam-prepare"]["returncode"], 0)
            failed = [n for n in rows if n != "foam-prepare"]
            self.assertEqual(
                report["error"],
                "CFD-U001 manual.openfoam: failed steps " + ", ".join(failed),
            )
            self.assertTrue(
                rows["foam-api"]["result"]["error"].startswith("CFD-X002 runtime.")
            )
            self.assertEqual(rows["foam-run"]["result"]["execution_status"], "failed")
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                external_notices.manual_examples(report, "manual OpenFOAM recipes")
            text = printed.getvalue()
            self.assertTrue(text.startswith("::notice title=manual OpenFOAM recipes::"))
            for name, row in rows.items():
                self.assertIn(f"{name}: exit {row['returncode']}", text)


def heading_anchors(path):
    """GitHub-style anchors of a Markdown file's headings (without duplicates)."""
    anchors = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"#+ (.*)", line)
        if match:
            text = re.sub(r"[^\w\- ]", "", match.group(1).strip().lower())
            anchors.add(text.replace(" ", "-"))
    return anchors


BLOB = "https://github.com/dietmarwo/CFD-craft/blob/main/"
SITE = "https://dietmarwo.github.io/CFD-craft/"
STUB_MARK = "<!-- stub -->"
SKIPPED = {"runs", "target", ".git", "book"}


def is_stub(path):
    """A permanent stub starts with the marker line `<!-- stub -->`."""
    with path.open(encoding="utf-8") as handle:
        return handle.readline().strip() == STUB_MARK


def site_page(url):
    """The file under `docs/` that a documentation-site URL is built from.

    The site renders `docs/X.md` as `X.html` and a directory's `README.md` as
    its `index.html`; the bare site URL is the landing page `docs/index.md`.
    """
    path = url[len(SITE) :]
    if path in ("", "index.html"):
        return ROOT / "docs/index.md"
    if path.endswith("/"):
        return ROOT / "docs" / path / "README.md"
    if path.endswith("/index.html"):
        return ROOT / "docs" / path[: -len("index.html")] / "README.md"
    if path.endswith(".html"):
        return ROOT / "docs" / (path[: -len(".html")] + ".md")
    return ROOT / "docs" / path


class SiteUrls(unittest.TestCase):
    def test_site_urls_map_to_pages(self):
        self.assertEqual(site_page(SITE), ROOT / "docs/index.md")
        self.assertEqual(site_page(SITE + "index.html"), ROOT / "docs/index.md")
        self.assertEqual(
            site_page(SITE + "guide/11-python.html"), ROOT / "docs/guide/11-python.md"
        )
        self.assertEqual(site_page(SITE + "guide/"), ROOT / "docs/guide/README.md")
        self.assertEqual(
            site_page(SITE + "guide/index.html"), ROOT / "docs/guide/README.md"
        )
        self.assertEqual(
            site_page(SITE + "diagnostics.html"), ROOT / "docs/diagnostics.md"
        )


def resolve(path, target):
    """The local file a link names, or None for a link outside the project."""
    if target.startswith(BLOB):
        return (ROOT / target[len(BLOB) :]).resolve()
    if target.startswith(SITE) or target + "/" == SITE:
        return site_page(target if target.startswith(SITE) else SITE).resolve()
    if target.startswith(("http:", "https:", "mailto:")):
        return None
    return (path.parent / target).resolve() if target else path


class DocumentationLinks(unittest.TestCase):
    def test_relative_links_and_anchors_resolve(self):
        broken = []
        to_stub = []
        stub_problems = []
        checked = 0
        site_links = 0
        files = sorted(
            p
            for p in ROOT.rglob("*.md")
            if not SKIPPED & set(p.relative_to(ROOT).parts)
        )
        self.assertGreater(len(files), 20)
        stubs = {p for p in files if is_stub(p)}
        for path in files:
            text = path.read_text(encoding="utf-8")
            links = re.findall(r"\]\(([^)#\s]*)(#[^)\s]*)?\)", text)
            if path in stubs and not links:
                stub_problems.append(
                    f"{path.relative_to(ROOT)}: no link to the new page"
                )
            for target, anchor in links:
                linked = resolve(path, target)
                if linked is None:
                    continue
                checked += 1
                site_links += target.startswith(SITE)
                name = f"{path.relative_to(ROOT)}: {target}{anchor}"
                if not linked.exists():
                    broken.append(name)
                    continue
                if anchor and linked.suffix == ".md":
                    if anchor[1:] not in heading_anchors(linked):
                        broken.append(name)
                if linked in stubs:
                    if path in stubs:
                        stub_problems.append(f"{name} (a stub links to a stub)")
                    else:
                        to_stub.append(name)
        print(
            f"links checked: {checked} (site: {site_links}), stubs: {len(stubs)}, "
            f"links to stubs: {len(to_stub)}",
            file=sys.stderr,
        )
        self.assertGreater(site_links, 0)
        self.assertEqual(broken, [])
        self.assertEqual(stub_problems, [])
        self.assertEqual(to_stub, [])

    def test_urls_in_code_and_package_metadata_resolve(self):
        """Doc comments, package metadata and scripts name live pages, not stubs."""
        pattern = re.compile(
            "("
            + re.escape(SITE)
            + r"[^\s)\"'>`]*|"
            + re.escape(BLOB)
            + r"[^\s)\"'>`]*)"
        )
        sources = [
            p
            for suffix in ("*.rs", "*.toml", "*.py", "*.yml")
            for p in ROOT.rglob(suffix)
            if not SKIPPED & set(p.relative_to(ROOT).parts)
        ] + sorted((ROOT / ".github/workflows").glob("*.yml"))
        problems = []
        checked = 0
        for path in sorted(set(sources)):
            for url in pattern.findall(path.read_text(encoding="utf-8")):
                target, _, anchor = url.partition("#")
                target = target.rstrip(".,;")
                linked = resolve(path, target)
                checked += 1
                name = f"{path.relative_to(ROOT)}: {url}"
                if not linked.exists():
                    problems.append(name)
                elif linked.suffix == ".md" and is_stub(linked):
                    problems.append(f"{name} (a stub)")
                elif anchor and linked.suffix == ".md":
                    if anchor not in heading_anchors(linked):
                        problems.append(f"{name} (no such heading)")
        print(f"URLs in code and metadata: {checked}", file=sys.stderr)
        self.assertGreater(checked, 10)
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
