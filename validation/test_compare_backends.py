#!/usr/bin/env python3
"""Contract tests of the backend timing comparison; synthetic rows are not evidence."""

import contextlib
import io
import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_backends as cmp

TIMES = {"openfoam-steady": 1.0, "native-steady": 5.0, "native-transient": 10.0}


def row(method, workflow, solver=None, steps=None, profile=None, identity="id"):
    r = dict(
        method=method,
        workflow_s=workflow,
        solver_s=workflow / 2 if solver is None else solver,
        solver_timer="synthetic",
        steps={"openfoam-steady": 696, "native-steady": 2010}.get(method, 4093)
        if steps is None
        else steps,
        cells=1152,
        reference_error=0.02,
        predicted_u=[0.1, 0.2] if profile is None else profile,
        assessment="synthetic",
    )
    r["runtime_identity" if method == "openfoam-steady" else "source_sha256"] = identity
    return r


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-compare-")
        self.root = Path(self.temp.name)
        self.binary = self.root / "cfd-craft"
        self.binary.write_text("synthetic executable")
        self.foam = self.root / "openfoam13"
        self.foam.mkdir()
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def fake(self, adjust=None):
        def runner(method, destination, binary, foam_root, timeout_s):
            destination.mkdir()
            self.calls.append((method, destination.name))
            warm = destination.name.startswith("warmup")
            r = row(
                method, 100.0 if warm else TIMES[method] * (1 + 0.01 * len(self.calls))
            )
            if adjust:
                adjust(r, len(self.calls), destination.name)
            return r

        return runner

    def run_compare(self, runner, output="out", **kwargs):
        return cmp.compare(
            self.binary, self.foam, self.root / output, runner=runner, **kwargs
        )


class Design(Fixture):
    def test_every_method_takes_every_position_equally_often_after_warmups(self):
        r = self.run_compare(self.fake())
        self.assertTrue(r["passed"], r.get("error"))
        self.assertEqual(
            [name for _, name in self.calls[:3]],
            [f"warmup-{m}" for m in cmp.METHODS],
        )
        orders = [tuple(x["order"]) for x in r["rounds"]]
        self.assertEqual(sorted(orders), sorted(itertools.permutations(cmp.METHODS)))
        for method in cmp.METHODS:
            positions = [order.index(method) for order in orders]
            self.assertEqual(sorted(positions), [0, 0, 1, 1, 2, 2])
        # The 100-second warmups do not enter the summary.
        for method in cmp.METHODS:
            self.assertLess(r["summary"][method]["workflow_max_s"], 100)

    def test_repeats_repeat_the_permutations(self):
        r = self.run_compare(self.fake(), repeats=2)
        self.assertTrue(r["passed"], r.get("error"))
        self.assertEqual(len(r["rounds"]), 12)

    def test_summary_and_both_ratios_are_exact(self):
        workflow = {
            "openfoam-steady": [1.0, 2.0, 1.0, 1.0, 4.0, 1.0],
            "native-steady": [5.0, 6.0, 8.0, 5.0, 4.0, 7.0],
            "native-transient": [10.0] * 6,
        }

        def adjust(r, call, name):
            if not name.startswith("warmup"):
                index = int(name[6:8])
                r["workflow_s"] = workflow[r["method"]][index]
                r["solver_s"] = r["workflow_s"] / 4

        r = self.run_compare(self.fake(adjust))
        self.assertTrue(r["passed"], r.get("error"))
        s = r["summary"]["native-steady"]
        self.assertEqual(
            (s["workflow_median_s"], s["workflow_min_s"], s["workflow_max_s"]),
            (5.5, 4.0, 8.0),
        )
        self.assertEqual(s["solver_median_s"], 5.5 / 4)
        ratios = r["native_over_openfoam"]["native-steady"]
        self.assertEqual(ratios["workflow_ratio_of_medians"], 5.5)
        # Per round: 5, 3, 8, 5, 1, 7 -> median 5.
        self.assertEqual(ratios["workflow_median_within_round"], 5.0)
        self.assertEqual(ratios["solver_ratio_of_medians"], 5.5)


class Failures(Fixture):
    def assert_fails(self, adjust, text, output="out"):
        r = self.run_compare(self.fake(adjust), output=output)
        self.assertFalse(r["passed"])
        self.assertIn(text, r["error"])
        self.assertTrue(r["error"].startswith("CFD-"), r["error"])
        self.assertNotIn("summary", r)
        on_disk = json.loads((self.root / output / "report.json").read_text())
        self.assertEqual(on_disk["error"], r["error"])

    def test_work_profile_and_producer_must_repeat(self):
        def steps(r, call, name):
            if name == "round-03-native-steady":
                r["steps"] += 1

        def profile(r, call, name):
            if name == "round-05-openfoam-steady":
                r["predicted_u"] = [0.1, 0.2000001]

        def producer(r, call, name):
            if name == "round-01-native-transient":
                r["source_sha256"] = "other"

        def runtime(r, call, name):
            if name == "round-02-openfoam-steady":
                r["runtime_identity"] = "other"

        for adjust, text in [
            (steps, "CFD-B002 comparison.native-steady.steps"),
            (profile, "comparison.openfoam-steady.predicted_u"),
            (producer, "comparison.native-transient.source_sha256"),
            (runtime, "comparison.openfoam-steady.runtime_identity"),
        ]:
            with self.subTest(text=text):
                self.assert_fails(adjust, text, output=text)

    def test_a_changed_input_fails_the_comparison(self):
        def change(r, call, name):
            if call == 7:
                self.binary.write_text("other executable")

        self.assert_fails(change, "comparison.inputs: cfd-craft changed")

    def test_a_failed_run_is_kept_as_the_error(self):
        def fail(method, destination, *args):
            destination.mkdir()
            if destination.name == "round-00-native-transient":
                cmp.require(False, "native-transient.run", "not accepted")
            return row(method, TIMES[method])

        r = self.run_compare(fail)
        self.assertFalse(r["passed"])
        self.assertEqual(
            r["error"], "CFD-B002 comparison.native-transient.run: not accepted"
        )
        self.assertEqual(len(r["rounds"]), 1)

    def test_limits_and_inputs_are_checked_before_the_output_exists(self):
        for kwargs, text in [
            (dict(repeats=0), "repeats"),
            (dict(repeats=6), "repeats"),
            (dict(repeats=True), "repeats"),
            (dict(timeout_s=0), "timeout_s"),
            (dict(timeout_s=601), "timeout_s"),
            (dict(timeout_s=float("nan")), "timeout_s"),
        ]:
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaisesRegex(ValueError, "CFD-B002 comparison." + text),
            ):
                self.run_compare(self.fake(), **kwargs)
        self.binary.unlink()
        with self.assertRaisesRegex(ValueError, "CFD-B002 comparison.binary"):
            self.run_compare(self.fake())
        self.assertFalse((self.root / "out").exists())

    def test_an_existing_output_is_refused_and_kept(self):
        (self.root / "out").mkdir()
        (self.root / "out/keep").write_text("keep")
        with self.assertRaisesRegex(ValueError, "CFD-E062"):
            self.run_compare(self.fake())
        self.assertEqual((self.root / "out/keep").read_text(), "keep")


class Methods(Fixture):
    def test_native_cases_differ_from_the_repository_case_only_as_declared(self):
        base = json.loads(cmp.CASE.read_text())
        for method, mode in [("native-steady", "steady"), ("native-transient", None)]:
            case = cmp.native_case(method)
            expected = json.loads(cmp.CASE.read_text())
            expected["run"]["threads"] = 1
            if mode:
                expected["run"]["mode"] = mode
            self.assertEqual(case, expected)
        self.assertNotEqual(base["run"].get("mode"), "steady")

    def native_record(self, accepted=True):
        def fake_run(binary, case, destination):
            destination.mkdir()
            nx, ny, nz = case["grid"]["cells"]
            faces = (nx + 1) * ny * nz
            # u rises linearly with height: far from the Ghia profile.
            u = np.repeat((np.arange(nz) + 0.5) / nz, ny * (nx + 1)).tolist()
            (destination / "fields.json").write_text(
                json.dumps({"velocity": u[:faces] + [0.0] * 10})
            )
            summary = dict(
                elapsed_s=1.0,
                steps=10,
                fluid_cells=nx * ny * nz,
                pressure_iterations=5,
                physical_time_s=1.0,
                momentum_residual=1e-6,
                assessment="steady_discrete_solution",
                source_sha256="s",
            )
            return dict(
                returncode=0, summary=summary, independent=dict(passed=accepted)
            )

        return fake_run

    def test_a_native_profile_outside_the_reference_target_fails(self):
        with patch.object(cmp, "run_case", side_effect=self.native_record()):
            with self.assertRaisesRegex(
                ValueError, "CFD-B002 comparison.native-steady.reference_error"
            ):
                cmp.run_method(
                    "native-steady", self.root / "n", self.binary, self.foam, 10
                )

    def test_an_unaccepted_native_run_fails(self):
        with patch.object(cmp, "run_case", side_effect=self.native_record(False)):
            with self.assertRaisesRegex(
                ValueError, "CFD-B002 comparison.native-transient.run"
            ):
                cmp.run_method(
                    "native-transient", self.root / "n", self.binary, self.foam, 10
                )

    def openfoam(self, passed=True, programs=("blockMesh", "checkMesh", "foamRun")):
        record = dict(
            passed=passed,
            error=None if passed else "CFD-X007 numerical",
            commands=[
                dict(program=p, wall_s=0.25 * (i + 1)) for i, p in enumerate(programs)
            ],
            numerical=dict(iterations=696),
            case_metadata=dict(cells=576),
            runtime=dict(version="13"),
        )
        reference = np.loadtxt(
            cmp.ROOT / "validation/ghia-re100-u.csv", delimiter=",", skiprows=1
        )
        y = np.r_[0, reference[:, 0], 1]
        u = np.r_[0, reference[:, 1], 1]
        return [
            patch.object(cmp.backend, "prepare"),
            patch.object(cmp.backend, "run", return_value=record),
            patch.object(cmp.backend, "verify", return_value={}),
            patch.object(cmp, "openfoam_centerline", return_value=(y, u)),
        ]

    def test_the_openfoam_solver_time_is_the_foamrun_process(self):
        with contextlib.ExitStack() as stack:
            for p in self.openfoam():
                stack.enter_context(p)
            r = cmp.run_method(
                "openfoam-steady", self.root / "o", self.binary, self.foam, 10
            )
        self.assertEqual(r["solver_s"], 0.75)
        self.assertEqual(r["steps"], 696)
        self.assertLess(r["reference_error"], 1e-12)
        self.assertTrue((self.root / "o/measurement.json").exists())

    def test_an_unaccepted_or_ambiguous_openfoam_run_fails(self):
        for index, (kwargs, text) in enumerate(
            [
                (dict(passed=False), "openfoam-steady.run"),
                (dict(programs=("foamRun", "foamRun")), "openfoam-steady.commands"),
                (dict(programs=("blockMesh",)), "openfoam-steady.commands"),
            ]
        ):
            with contextlib.ExitStack() as stack:
                for p in self.openfoam(**kwargs):
                    stack.enter_context(p)
                with (
                    self.subTest(text=text),
                    self.assertRaisesRegex(ValueError, "CFD-B002 comparison." + text),
                ):
                    cmp.run_method(
                        "openfoam-steady",
                        self.root / f"o{index}",
                        self.binary,
                        self.foam,
                        10,
                    )


class Notices(Fixture):
    def test_the_ci_notice_states_medians_ratios_and_inputs(self):
        import external_notices

        self.run_compare(self.fake())
        printed = io.StringIO()
        argv = ["notices", str(self.root / "out/report.json"), "cavity backends"]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(printed):
            self.assertEqual(external_notices.main(), 0)
        text = printed.getvalue().replace("%0A", "\n").replace("%3A", ":")
        self.assertIn("::notice title=cavity backends::passed True", text)
        for required in [
            "native-steady: workflow median",
            "steps 2010",
            "native-transient/openfoam: workflow",
            "within-round median",
            "solver ",
            "cases/verification/lid-cavity.json ",
        ]:
            self.assertIn(required, text)


class CommandLine(Fixture):
    def test_exit_code_follows_the_report(self):
        argv = [
            "compare_backends.py",
            "--binary",
            str(self.binary),
            "--foam-root",
            str(self.foam),
            "--output",
            str(self.root / "cli"),
        ]
        for passed, code in [(True, 0), (False, 1)]:
            with (
                self.subTest(passed=passed),
                patch.object(sys, "argv", argv),
                patch.object(cmp, "compare", return_value={"passed": passed}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(cmp.main(), code)
        with (
            patch.object(sys, "argv", argv),
            patch.object(cmp, "compare", side_effect=ValueError("CFD-B002 x")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cmp.main(), 1)


if __name__ == "__main__":
    unittest.main()
