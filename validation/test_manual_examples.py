#!/usr/bin/env python3
"""Contract tests of the manual-example runner's OpenFOAM mode.

No OpenFOAM runtime is needed: the recipes are compared with the manual's text,
and a missing runtime must produce a coded failure report naming each step.
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
import external_notices
import manual_examples

ROOT = Path(__file__).resolve().parents[1]
FOAM = "runs/openfoam13/runtime/opt/openfoam13"


def manual_commands(numbers):
    """The shell commands of the manual's examples, continuation lines joined."""
    text = (ROOT / "docs/USER_MANUAL.md").read_text()
    commands = []
    for number in numbers:
        section = re.search(
            rf"^### Example {number}:.*?(?=^### |\Z)", text, re.M | re.S
        ).group(0)
        for block in re.findall(r"```sh\n(.*?)```", section, re.S):
            commands += [
                shlex.split(c) for c in block.replace("\\\n", " ").splitlines() if c
            ]
    return commands


class Recipes(unittest.TestCase):
    def recorded(self):
        steps = []
        out = Path("/scratch/manual")

        def run(name, argv, timeout=180):
            words = []
            for value in argv:
                value = str(value)
                if value == sys.executable:
                    value = "python"
                elif value.startswith(str(out) + "/"):
                    value = "runs/" + value[len(str(out)) + 1 :]
                elif value.startswith(str(ROOT) + "/"):
                    value = value[len(str(ROOT)) + 1 :]
                words.append(value)
            steps.append((name, words, timeout))

        manual_examples.foam_recipes(run, Path(FOAM), out)
        return steps

    def test_the_recipes_are_the_manual_commands_in_order(self):
        steps = self.recorded()
        manual = manual_commands([22, 21, 24, 25])
        self.assertEqual(len(manual), 7)
        self.assertEqual([words for _, words, _ in steps[:7]], manual)
        # Example 25 says to run the prepared case as in Example 21.
        name, words, _ = steps[7]
        self.assertEqual(name, "foam-finer-run")
        self.assertEqual(
            words,
            manual[2][:4]
            + ["runs/foam-finer-input"]
            + manual[2][5:-1]
            + ["runs/foam-finer"],
        )

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


if __name__ == "__main__":
    unittest.main()
