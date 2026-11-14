#!/usr/bin/env python3
"""Contract tests of the documentation check `scripts/check_docs.py`.

Each test writes small pages into a temporary checkout and runs the checker on
them, or calls its comparison and parsing functions directly. A fake
`cfd-craft` in the temporary checkout answers `check`, so no build and no
network are needed. The tests use explicit unittest assertions and behave the
same under `python -O`.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_docs  # noqa: E402

SENTENCE = (
    "Outputs on this page are real. The documentation check compares "
    "floating-point numbers with a relative tolerance of 1e-4; everything else "
    "must match exactly."
)
# Rejects a case that contains the string "bad"; accepts every other case.
FAKE_BINARY = """#!/bin/sh
if [ "$1" != check ]; then exit 3; fi
if grep -q '"bad"' "$2"; then
  echo '{"check": {"diagnostics": [{"severity": "error", "code": "CFD-E000", "path": "case.bad"}]}}'
  exit 2
fi
echo '{"check": {"diagnostics": []}}'
"""
FENCE = "```"


def page(body):
    """A page from an indented literal, with ``` written as FENCE."""
    return textwrap.dedent(body).lstrip("\n")


class Checkout:
    """A temporary checkout with pages, a fake binary and a ledger."""

    def __init__(self, test):
        self.directory = tempfile.TemporaryDirectory(prefix="cfd-docs-test-")
        test.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        binary = self.root / "target/release/cfd-craft"
        binary.parent.mkdir(parents=True)
        binary.write_text(FAKE_BINARY, encoding="utf-8")
        binary.chmod(0o755)
        (self.root / "docs").mkdir()
        (self.root / "examples").mkdir()
        (self.root / "examples/data.txt").write_text("from the checkout\n")
        (self.root / "examples/tool.py").write_text("print('tool')\n")

    def write(self, name, text, counts=True):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if counts:
            self.count(name)
        return name

    def count(self, name):
        """Record the page's own blocks as its ledger entry."""
        ledger = self.ledger()
        parsed, _ = check_docs.parse((self.root / name).read_text(encoding="utf-8"))
        ledger[name] = check_docs.ledger(parsed)
        self.write_ledger(ledger)

    def ledger(self):
        path = self.root / check_docs.COUNTS_FILE
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))["pages"]

    def write_ledger(self, pages):
        check_docs.write_counts(self.root / check_docs.COUNTS_FILE, pages)

    def run(self, *arguments, timeout=120):
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_docs.py"), "--root"]
            + [str(self.root)]
            + [str(argument) for argument in arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=self.root,
            check=False,
        )
        try:
            report = json.loads(done.stdout)
        except ValueError:
            report = None
        return done.returncode, report, done.stderr


class CheckerCase(unittest.TestCase):
    def setUp(self):
        self.checkout = Checkout(self)

    def check(self, text, *arguments, name="docs/page.md"):
        self.checkout.write(name, page(text))
        return self.checkout.run(*arguments, name)

    def passes(self, text, *arguments):
        code, report, errors = self.check(text, *arguments)
        self.assertEqual(code, 0, errors)
        self.assertIs(report["passed"], True)
        return report["pages"][0]

    def fails(self, text, field, *arguments, line=None):
        code, report, errors = self.check(text, *arguments)
        self.assertEqual(code, 1, errors)
        self.assertIs(report["passed"], False)
        prefix = f"CFD-R003 docs.{field}: docs/page.md:"
        if line is not None:
            prefix += f"{line}:"
        found = [f for f in report["pages"][0]["failures"] if f.startswith(prefix)]
        self.assertTrue(found, f"no {prefix} in {report['pages'][0]['failures']}")
        return report["pages"][0]


class Fences(CheckerCase):
    def test_python_and_bash_run_and_text_is_compared(self):
        record = self.passes(f"""
            # Page

            {FENCE}python
            print("hello", 2 + 2)
            {FENCE}
            {FENCE}text
            hello 4
            {FENCE}

            {FENCE}bash
            echo "$((6 * 7))"
            {FENCE}
            {FENCE}text
            42
            {FENCE}
            """)
        self.assertEqual((record["python"], record["bash"], record["text"]), (1, 1, 2))

    def test_tilde_fences_are_accepted(self):
        record = self.passes("""
            # Page

            ~~~bash
            echo tilde
            ~~~
            ~~~text
            tilde
            ~~~
            """)
        self.assertEqual(record["text"], 1)

    def test_a_block_without_or_with_an_unknown_info_string_fails(self):
        self.fails(f"# Page\n\n{FENCE}\necho x\n{FENCE}\n", "fence", line=3)
        self.fails(f"# Page\n\n{FENCE}console\necho x\n{FENCE}\n", "fence", line=3)

    def test_an_unclosed_fence_fails(self):
        self.fails(f"# Page\n\n{FENCE}bash\necho x\n", "fence", line=3)

    def test_an_indented_fence_in_a_list_is_run(self):
        text = (
            f"# Page\n\n1. A step:\n\n   {FENCE}python\n   import sys\n"
            f"   if True:\n       sys.exit(3)\n   {FENCE}\n"
        )
        record = self.fails(text, "python", line=5)
        self.assertEqual(record["python"], 0)
        ok = f"# Page\n\n- A step:\n\n    {FENCE}bash\n    echo ok\n    {FENCE}\n"
        self.assertEqual(self.passes(ok)["bash"], 1)

    def test_a_failing_block_fails_and_stops_its_section(self):
        record = self.fails(
            f"""
            # Page

            ## One

            {FENCE}bash
            exit 4
            {FENCE}

            {FENCE}bash
            echo never
            {FENCE}

            ## Two

            {FENCE}bash
            echo runs
            {FENCE}
            """,
            "bash",
            line=5,
        )
        self.assertEqual(record["bash"], 1)

    def test_bash_runs_with_errexit_nounset_and_pipefail(self):
        for body in ("false\necho after", 'echo "$UNSET_NAME"', "false | true"):
            self.fails(f"# Page\n\n{FENCE}bash\n{body}\n{FENCE}\n", "bash", line=3)

    def test_an_expected_exit_is_written_in_the_block(self):
        record = self.passes(f"""
            # Page

            {FENCE}bash
            bash -c 'exit 2' || echo "exit $?"
            {FENCE}
            {FENCE}text
            exit 2
            {FENCE}
            """)
        self.assertEqual(record["text"], 1)
        self.fails(
            f"""
            # Page

            {FENCE}bash
            bash -c 'exit 2' || echo "exit $?"
            {FENCE}
            {FENCE}text
            exit 1
            {FENCE}
            """,
            "text",
        )

    def test_a_python_exception_fails(self):
        self.fails(
            f"# Page\n\n{FENCE}python\nraise ValueError('x')\n{FENCE}\n", "python"
        )
        self.fails(f"# Page\n\n{FENCE}python\nif True\n{FENCE}\n", "python", line=3)

    def test_text_needs_a_runnable_block_directly_before_it(self):
        self.fails(f"# Page\n\n{FENCE}text\nalone\n{FENCE}\n", "text", line=3)
        self.fails(
            f"# Page\n\n{FENCE}json\n{{}}\n{FENCE}\n{FENCE}text\nx\n{FENCE}\n",
            "text",
            line=6,
        )
        # Two text blocks: the second has no runnable block before it.
        self.fails(
            f"# Page\n\n{FENCE}bash\necho a\n{FENCE}\n{FENCE}text\na\n{FENCE}\n"
            f"{FENCE}text\na\n{FENCE}\n",
            "text",
            line=9,
        )

    def test_the_line_count_must_agree_and_trailing_space_is_ignored(self):
        self.passes(
            f"# Page\n\n{FENCE}bash\necho 'a  '\n{FENCE}\n{FENCE}text\na\n{FENCE}\n"
        )
        self.fails(
            f"# Page\n\n{FENCE}bash\necho a; echo b\n{FENCE}\n{FENCE}text\na\n{FENCE}\n",
            "text",
        )

    def test_sh_is_parsed_and_its_scripts_must_exist(self):
        record = self.passes(f"""
            # Page

            {FENCE}sh
            python examples/tool.py --output ROOT
            pip install something-that-is-never-installed
            {FENCE}
            """)
        self.assertEqual((record["sh"], record["bash"]), (1, 0))
        self.fails(f"# Page\n\n{FENCE}sh\nif then fi (\n{FENCE}\n", "sh", line=3)
        self.fails(f"# Page\n\n{FENCE}sh\npython examples/gone.py\n{FENCE}\n", "sh")

    def test_toml_is_parsed(self):
        self.passes(f'# Page\n\n{FENCE}toml\n[dependencies]\na = "1"\n{FENCE}\n')
        self.fails(f"# Page\n\n{FENCE}toml\n[dependencies\n{FENCE}\n", "toml", line=3)

    def test_rust_is_bound_to_a_compiled_file_in_order(self):
        self.checkout.write(
            "examples/lib.rs", "fn a() {}\n// x\nfn b() {}\nfn c() {}\n", counts=False
        )
        marker = "<!-- check: fragment of examples/lib.rs -->"
        self.passes(
            f"# Page\n\n{marker}\n{FENCE}rust\nfn a() {{}}\n// skipped\nfn c() {{}}\n{FENCE}\n"
        )
        self.fails(
            f"# Page\n\n{marker}\n{FENCE}rust\nfn c() {{}}\nfn a() {{}}\n{FENCE}\n",
            "rust",
        )
        self.fails(f"# Page\n\n{FENCE}rust\nfn a() {{}}\n{FENCE}\n", "rust", line=3)
        self.passes(
            f"# Page\n\n<!-- check: none: a sketch -->\n{FENCE}rust\nfn z() {{}}\n{FENCE}\n"
        )

    def test_mermaid_is_not_run(self):
        record = self.passes(
            f"# Page\n\n{FENCE}mermaid\nnot valid at all ((\n{FENCE}\n"
        )
        self.assertEqual(record["not_run"], 0)

    def test_json_is_strict(self):
        self.passes(f'# Page\n\n{FENCE}json\n{{"a": 1}}\n{FENCE}\n')
        self.fails(f'# Page\n\n{FENCE}json\n{{"a": 1, "a": 2}}\n{FENCE}\n', "json")
        self.fails(f'# Page\n\n{FENCE}json\n{{"a": NaN}}\n{FENCE}\n', "json")
        self.fails(f"# Page\n\n{FENCE}json\n{{'a': 1}}\n{FENCE}\n", "json")

    def test_a_case_is_sent_to_check_and_a_fragment_is_not(self):
        good = '{"schema_version": "cfd-craft.case/0.1", "x": "good"}'
        bad = '{"schema_version": "cfd-craft.case/0.1", "x": "bad"}'
        record = self.passes(f"# Page\n\n{FENCE}json\n{good}\n{FENCE}\n")
        self.assertEqual((record["json"], record["cases"]), (1, 1))
        failed = self.fails(f"# Page\n\n{FENCE}json\n{bad}\n{FENCE}\n", "json", line=3)
        self.assertIn("CFD-E000 case.bad", failed["failures"][0])
        record = self.passes(
            f"# Page\n\n<!-- check: fragment -->\n{FENCE}json\n{bad}\n{FENCE}\n"
        )
        self.assertEqual(record["cases"], 0)

    def test_a_file_marker_writes_the_block_for_later_blocks(self):
        self.checkout.write(
            "examples/case.json", '{"b": [1, 2], "a": 1}\n', counts=False
        )
        record = self.passes(f"""
            # Page

            <!-- file: runs/case.json = examples/case.json -->
            {FENCE}json
            {{"a": 1, "b": [1, 2]}}
            {FENCE}

            {FENCE}bash
            cat runs/case.json
            {FENCE}
            {FENCE}text
            {{"a": 1, "b": [1, 2]}}
            {FENCE}
            """)
        self.assertEqual(record["text"], 1)
        self.fails(
            f'# Page\n\n<!-- file: x.json = examples/case.json -->\n{FENCE}json\n{{"a": 2}}\n{FENCE}\n',
            "json",
        )
        self.fails(
            f'# Page\n\n<!-- file: ../x.json -->\n{FENCE}json\n{{"a": 2}}\n{FENCE}\n',
            "marker",
        )

    def test_a_raw_url_of_the_repository_reads_the_checkout(self):
        record = self.passes(f"""
            # Page

            {FENCE}python
            import urllib.request

            url = "{check_docs.RAW_URL}examples/data.txt"
            print(urllib.request.urlopen(url).read().decode().strip())
            {FENCE}
            {FENCE}text
            from the checkout
            {FENCE}
            """)
        self.assertEqual(record["text"], 1)


class Markers(CheckerCase):
    def test_unknown_misplaced_and_malformed_markers_fail(self):
        self.fails("# Page\n\n<!-- check: sometimes -->\n\nText.\n", "marker", line=3)
        self.fails(
            f"# Page\n\nText.\n\n<!-- check: long -->\n{FENCE}bash\necho\n{FENCE}\n",
            "marker",
            line=5,
        )
        self.fails(
            "# Page\n\n## A\n\n<!-- check: none: x -->\n\nText.\n", "marker", line=5
        )
        self.fails("# Page\n\n<!-- check none: x -->\n", "marker", line=3)
        self.fails("# Page\n\n<!-- check: none -->\n", "marker", line=3)
        self.fails(
            f"# Page\n\n<!-- check: fragment of x.rs -->\n{FENCE}json\n{{}}\n{FENCE}\n",
            "marker",
        )
        self.fails(
            f"# Page\n\n<!-- check: fragment -->\n{FENCE}bash\necho\n{FENCE}\n",
            "marker",
        )
        # Other comments are prose.
        self.passes("<!-- stub -->\n# Page\n\n<!-- a note for writers -->\n")

    def test_a_marker_given_twice_fails(self):
        self.fails(
            "# Page\n\n<!-- check: rel=1e-4 -->\n<!-- check: rel=1e-5 -->\n",
            "marker",
            line=4,
        )
        self.fails(
            "# Page\n\n## A\n\n<!-- check: long -->\n<!-- check: long -->\n", "marker"
        )
        self.fails(
            f"# Page\n\n<!-- check: none: a -->\n<!-- check: none: b -->\n"
            f"{FENCE}bash\necho\n{FENCE}\n",
            "marker",
            line=4,
        )
        self.fails(
            "# Page\n\n<!-- check: timeout=5 -->\n<!-- check: timeout=6 -->\n", "marker"
        )

    def test_none_needs_a_reason_and_is_reported(self):
        record = self.passes(
            f"# Page\n\nThe problem:\n\n<!-- check: none: a problem statement -->\n"
            f"{FENCE}text\n"
            f"minimize 1.5 x\n{FENCE}\n"
        )
        self.assertEqual(
            record["unchecked"], [dict(line=6, reason="a problem statement")]
        )
        record = self.passes(
            f"# Page\n\n<!-- check: none: record of past runs -->\n\n"
            f"{FENCE}bash\nexit 1\n{FENCE}\n"
        )
        self.assertEqual(
            record["unchecked"], [dict(line=1, reason="record of past runs")]
        )
        self.assertEqual(record["bash"], 0)

    def test_long_is_skipped_only_in_smoke_mode(self):
        text = f"""
            # Page

            ## Quick

            {FENCE}bash
            echo quick
            {FENCE}

            ## Slow

            <!-- check: long -->

            {FENCE}bash
            exit 9
            {FENCE}
            {FENCE}text
            not compared in smoke mode
            {FENCE}
            """
        record = self.passes(text, "--smoke")
        self.assertEqual((record["bash"], record["not_run"], record["text"]), (1, 1, 0))
        self.fails(text, "bash")
        # Syntax and script paths are still checked when a block is not run.
        self.fails(
            f"# Page\n\n<!-- check: long -->\n\n{FENCE}bash\nif then (\n{FENCE}\n",
            "bash",
            "--smoke",
        )
        self.fails(
            f"# Page\n\n<!-- check: long -->\n\n{FENCE}bash\npython examples/gone.py\n{FENCE}\n",
            "bash",
            "--smoke",
        )

    def test_openfoam_runs_with_the_runtime_linked_where_pages_name_it(self):
        text = f"""
            # Page

            <!-- check: openfoam -->

            {FENCE}bash
            cat runs/openfoam13/runtime/opt/openfoam13/marker
            {FENCE}
            """
        record = self.passes(text)
        self.assertEqual((record["bash"], record["not_run"]), (0, 1))
        runtime = self.checkout.root / "runtime"
        runtime.mkdir()
        (runtime / "marker").write_text("installed\n")
        self.assertEqual(self.passes(text, "--foam-root", runtime)["bash"], 1)
        self.fails(text, "bash", "--foam-root", self.checkout.root / "missing")

    def test_jobs_run_with_the_runner_linked_where_pages_name_it(self):
        runner = self.checkout.root / "optimization-run"
        runner.write_text("#!/bin/sh\necho runner\n")
        runner.chmod(0o755)
        text = f"""
            # Page

            ## Setup

            {FENCE}bash
            mkdir -p runs
            {FENCE}

            ## Jobs

            <!-- check: jobs -->

            {FENCE}bash
            ../optimization-jobs/target/release/optimization-run
            {FENCE}
            {FENCE}text
            runner
            {FENCE}
            """
        self.assertEqual(self.passes(text)["not_run"], 1)
        self.assertEqual(self.passes(text, "--runner", runner)["text"], 1)

    def test_timeout_markers_limit_blocks_of_their_scope(self):
        record = self.fails(
            f"""
            # Page

            <!-- check: timeout=1 -->

            {FENCE}bash
            sleep 30
            {FENCE}
            """,
            "bash",
            line=5,
        )
        self.assertIn("no end after 1 s", record["failures"][0])
        text = f"""
            # Page

            <!-- check: timeout=60 -->

            ## Fast

            <!-- check: timeout=1 -->

            {FENCE}python
            import time

            time.sleep(30)
            {FENCE}

            ## Patient

            {FENCE}bash
            sleep 2
            echo slept
            {FENCE}
            """
        record = self.fails(text, "python", "--timeout", "1.5", line=9)
        self.assertEqual(len(record["failures"]), 1)
        self.assertEqual(record["bash"], 1)
        for bad in ("timeout=0", "timeout=-1", "timeout=inf", "timeout=x"):
            self.fails(f"# Page\n\n<!-- check: {bad} -->\n", "marker", line=3)

    def test_the_tolerance_marker_and_sentence_go_together(self):
        self.passes(f"# Page\n\n<!-- check: rel=1e-4 -->\n\n{SENTENCE}\n")
        self.passes(
            f"# Page\n\n<!-- check: rel=1e-5 -->\n\n{SENTENCE.replace('1e-4', '1e-5')}\n"
        )
        self.fails("# Page\n\n<!-- check: rel=1e-4 -->\n\nNo sentence.\n", "marker")
        self.fails(f"# Page\n\n{SENTENCE}\n", "marker")
        self.fails(f"# Page\n\n<!-- check: rel=1e-3 -->\n\n{SENTENCE}\n", "marker")
        self.fails("# Page\n\n## A\n\n<!-- check: rel=1e-4 -->\n", "marker")

    def test_a_float_needs_a_declared_tolerance_even_when_not_run(self):
        text = f"""
            # Page

            <!-- check: long -->

            {FENCE}bash
            echo 1.5
            {FENCE}
            {FENCE}text
            1.5
            {FENCE}
            """
        self.fails(text, "text", "--smoke", line=8)


class Sessions(CheckerCase):
    def test_sections_start_from_the_setup_and_not_from_each_other(self):
        record = self.passes(f"""
            # Page

            ## Setup

            {FENCE}bash
            echo made > runs/setup.txt
            {FENCE}

            {FENCE}python
            setup_variable = 1
            {FENCE}

            ## First

            {FENCE}bash
            cat runs/setup.txt
            echo first > runs/first.txt
            {FENCE}
            {FENCE}text
            made
            {FENCE}

            {FENCE}python
            shared = "within one section"
            print("setup_variable" in globals())
            {FENCE}
            {FENCE}text
            False
            {FENCE}

            {FENCE}python
            print(shared)
            {FENCE}
            {FENCE}text
            within one section
            {FENCE}

            ## Second

            {FENCE}bash
            cat runs/setup.txt
            test ! -e runs/first.txt && echo isolated
            {FENCE}
            {FENCE}text
            made
            isolated
            {FENCE}

            {FENCE}python
            print("shared" in globals())
            {FENCE}
            {FENCE}text
            False
            {FENCE}
            """)
        self.assertEqual((record["bash"], record["python"], record["text"]), (3, 4, 5))

    def test_no_variable_or_directory_carries_between_bash_blocks(self):
        self.passes(f"""
            # Page

            {FENCE}bash
            export CARRIED=1
            cd runs
            {FENCE}

            {FENCE}bash
            echo "${{CARRIED:-unset}}" "$(basename "$PWD")"
            {FENCE}
            {FENCE}text
            unset section-00
            {FENCE}
            """)

    def test_sessions_have_the_checkout_directories_and_an_empty_stdin(self):
        self.passes(f"""
            # Page

            {FENCE}bash
            cat examples/data.txt
            ls runs | wc -l
            cat
            {FENCE}
            {FENCE}text
            from the checkout
            0
            {FENCE}
            """)

    def test_setup_must_be_the_first_section_and_a_failing_setup_stops(self):
        self.fails("# Page\n\n## Intro\n\n## Setup\n", "setup")
        record = self.fails(
            f"# Page\n\n## Setup\n\n{FENCE}bash\nexit 1\n{FENCE}\n\n## A\n\n"
            f"{FENCE}bash\necho a\n{FENCE}\n",
            "bash",
        )
        self.assertEqual(record["bash"], 0)


class Comparison(unittest.TestCase):
    DECLARED = dict(rel=1e-4, abs=0.0)

    def agrees(self, shown, actual, declared=DECLARED):
        try:
            check_docs.compare(shown, actual, declared, 1)
        except check_docs.Failure:
            return False
        return True

    def test_floats_agree_within_the_relative_tolerance(self):
        self.assertTrue(self.agrees("R = 17.8118 ug", "R = 17.81180001 ug"))
        self.assertTrue(self.agrees("R = 17.8118 ug", "R = 17.8134 ug"))
        self.assertFalse(self.agrees("R = 17.8118 ug", "R = 17.8140 ug"))
        self.assertTrue(self.agrees("x 1.92e-07", "x 1.92001e-07"))
        self.assertFalse(self.agrees("x 1.92e-07", "x 1.93e-07"))
        self.assertTrue(self.agrees("x -2.5", "x -2.50001"))
        self.assertFalse(self.agrees("x -2.5", "x 2.5"))

    def test_the_bound_uses_the_larger_magnitude_and_the_absolute_part(self):
        # |1 - 1.0001| = 1e-4 <= 1e-4 * 1.0001
        self.assertTrue(self.agrees("1.0", "1.0001"))
        self.assertFalse(self.agrees("1.0", "1.00011"))
        self.assertFalse(self.agrees("0.0", "1e-30"))
        self.assertTrue(self.agrees("0.0", "1e-30", dict(rel=1e-4, abs=1e-20)))
        self.assertTrue(self.agrees("0.0", "-0.0"))

    def test_identical_literals_agree_even_beyond_float_range(self):
        self.assertTrue(self.agrees("big 1e999", "big 1e999"))
        self.assertFalse(self.agrees("big 1e999", "big 2e999"))

    def test_integers_and_text_must_be_identical(self):
        self.assertFalse(self.agrees("steps 400", "steps 401"))
        self.assertFalse(self.agrees("count 1", "count 1.0"))
        self.assertFalse(self.agrees("count 1.0", "count 1"))
        self.assertFalse(self.agrees("R_down = 1.5", "R_up = 1.5"))
        self.assertFalse(self.agrees("a 1.5 b", "a 1.5 c"))

    def test_digits_in_words_hashes_versions_and_schema_names_are_text(self):
        self.assertFalse(self.agrees("cfd-craft.result/0.1", "cfd-craft.result/0.2"))
        self.assertFalse(self.agrees("version 0.1.0", "version 0.1.1"))
        self.assertFalse(self.agrees("sha ab12.5c", "sha ab12.6c"))
        self.assertFalse(self.agrees("R_down2", "R_down3"))
        self.assertFalse(self.agrees("x/H = 1", "x/H = 4"))
        self.assertEqual(check_docs.NUMBER.findall("cfd-craft.case/0.1 v0.1.0"), [])

    def test_a_float_without_a_declared_tolerance_fails(self):
        self.assertFalse(self.agrees("x 1.5", "x 1.5000001", None))
        self.assertTrue(self.agrees("exit 2", "exit 2", None))

    def test_tolerance_markers(self):
        self.assertEqual(check_docs.tolerance("rel=1e-4", 1)["rel"], 1e-4)
        self.assertEqual(check_docs.tolerance("rel=1e-5 abs=1e-9", 1)["abs"], 1e-9)
        for bad in ("rel=2e-4", "rel=0", "rel=nan", "rel=1e-4 abs=inf", "abs=1"):
            with self.assertRaises(check_docs.Failure):
                check_docs.tolerance(bad, 1)


class Counts(unittest.TestCase):
    def setUp(self):
        self.checkout = Checkout(self)
        self.text = page(f"""
            # Page

            {FENCE}bash
            echo a
            {FENCE}
            {FENCE}text
            a
            {FENCE}
            {FENCE}json
            {{}}
            {FENCE}

            ## Later

            <!-- check: long -->

            {FENCE}python
            print("b")
            {FENCE}
            """)

    def test_the_ledger_counts_blocks_by_class(self):
        parsed, failures = check_docs.parse(self.text)
        self.assertEqual(failures, [])
        self.assertEqual(
            check_docs.ledger(parsed),
            dict(run=1, text=1, json=1, long=dict(run=1, text=0)),
        )

    def test_a_page_without_an_entry_fails(self):
        self.checkout.write("docs/page.md", self.text, counts=False)
        self.checkout.write_ledger({})
        code, report, errors = self.checkout.run("docs/page.md")
        self.assertEqual(code, 1, errors)
        self.assertIn("no entry in the ledger", report["pages"][0]["failures"][0])

    def test_fewer_blocks_than_the_ledger_fail_in_every_mode(self):
        self.checkout.write("docs/page.md", self.text)
        for mode in ([], ["--smoke"]):
            code, _, errors = self.checkout.run(*mode, "docs/page.md")
            self.assertEqual(code, 0, errors)
        # The first block and its output move from the always-run class into
        # a long section: the page still passes on its own, the ledger fails it.
        first = f"{FENCE}bash\necho a\n{FENCE}\n{FENCE}text\na\n{FENCE}\n"
        moved = (
            self.text.replace(first, "")
            + "\n## Moved\n\n<!-- check: long -->\n\n"
            + first
        )
        self.checkout.write("docs/page.md", moved, counts=False)
        for mode in ([], ["--smoke"]):
            code, report, errors = self.checkout.run(*mode, "docs/page.md")
            self.assertEqual(code, 1, errors)
            self.assertIn("CFD-R003 docs.counts: docs/page.md:0: run:", errors)

    def test_write_counts_writes_only_when_the_pages_pass(self):
        self.checkout.write("docs/page.md", self.text, counts=False)
        code, report, errors = self.checkout.run("--write-counts", "docs/page.md")
        self.assertEqual(code, 0, errors)
        self.assertIs(report["counts_written"], True)
        self.assertEqual(
            self.checkout.ledger()["docs/page.md"],
            dict(run=1, text=1, json=1, long=dict(run=1, text=0)),
        )
        self.checkout.write(
            "docs/bad.md", f"# Bad\n\n{FENCE}bash\nexit 1\n{FENCE}\n", counts=False
        )
        code, report, _ = self.checkout.run("--write-counts", "docs/bad.md")
        self.assertEqual(code, 1)
        self.assertIs(report["counts_written"], False)
        self.assertNotIn("docs/bad.md", self.checkout.ledger())

    def test_the_default_set_and_its_ledger(self):
        write = self.checkout.write
        write("README.md", "# Readme\n", counts=False)
        write("python/README.md", "# Binding\n", counts=False)
        write("docs/index.md", "# Index\n", counts=False)
        write("docs/guide/01.md", self.text, counts=False)
        write("docs/old.md", "<!-- stub -->\n# Old\n\nThis page moved.\n", counts=False)
        write("docs/history/plan.md", f"# Plan\n\n{FENCE}\nx\n{FENCE}\n", counts=False)
        write("docs/SUMMARY.md", "# Summary\n", counts=False)
        write(
            "docs/reference/schema.md",
            f"# Schema\n\n<!-- check: none: {check_docs.GENERATED} -->\n",
            counts=False,
        )
        expected = [
            "README.md",
            "python/README.md",
            "docs/guide/01.md",
            "docs/index.md",
        ]
        self.assertEqual(check_docs.default_pages(self.checkout.root), expected)
        code, report, errors = self.checkout.run("--smoke", "--write-counts")
        self.assertEqual(code, 0, errors)
        self.assertEqual(sorted(self.checkout.ledger()), sorted(expected))
        code, report, errors = self.checkout.run("--smoke")
        self.assertEqual(code, 0, errors)
        self.assertEqual([p["page"] for p in report["pages"]], expected)
        # A page that leaves the default set fails until the ledger is rewritten.
        (self.checkout.root / "docs/index.md").unlink()
        code, report, errors = self.checkout.run("--smoke")
        self.assertEqual(code, 1, errors)
        self.assertEqual(report["missing_from_set"], ["docs/index.md"])
        # A new page without an entry fails.
        self.checkout.run("--smoke", "--write-counts")
        write("docs/new.md", "# New\n", counts=False)
        code, report, errors = self.checkout.run("--smoke")
        self.assertEqual(code, 1, errors)
        self.assertIn("CFD-R003 docs.counts: docs/new.md:0:", errors)

    def test_a_ledger_of_another_kind_is_refused(self):
        self.checkout.write("docs/page.md", "# Page\n", counts=False)
        (self.checkout.root / check_docs.COUNTS_FILE).write_text('{"pages": {}}')
        code, _, errors = self.checkout.run("docs/page.md")
        self.assertEqual(code, 1)
        self.assertIn("CFD-R003 docs.counts", errors)


if __name__ == "__main__":
    unittest.main()
