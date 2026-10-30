#!/usr/bin/env python3
"""End-to-end boundaries and independent checker fault injection."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "target/release/cfd-craft"


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cfd-boundaries-")
        self.root = Path(self.tmp.name)
        self.case = json.loads(
            (ROOT / "cases/verification/periodic-tracer.json").read_text()
        )
        self.case["grid"]["cells"] = [8, 4, 4]
        self.case["run"]["end_time_s"] = 0.2

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, *args):
        return subprocess.run(
            [str(BIN), *map(str, args)], capture_output=True, text=True, timeout=20
        )

    def save(self):
        p = self.root / "case.json"
        p.write_text(json.dumps(self.case))
        return p

    def run_case(self):
        p = self.invoke("run", self.save(), "--output", self.root / "out")
        self.assertEqual(p.returncode, 0, p.stderr)
        return self.root / "out"

    def canyon(self):
        case = json.loads((ROOT / "cases/canyon/wh1-wind270.json").read_text())
        case["grid"]["cells"] = [18, 16, 12]
        return case

    def diagnostics(self, p):
        return [
            (d["code"], d["path"]) for d in json.loads(p.stdout)["check"]["diagnostics"]
        ]

    def reseal(self, out):
        manifest = json.loads((out / "manifest.json").read_text())
        for name in manifest["files"]:
            manifest["files"][name] = hashlib.sha256(
                (out / name).read_bytes()
            ).hexdigest()
        (out / "manifest.json").write_text(json.dumps(manifest))
        (out / "complete.json").write_text(
            json.dumps(
                dict(
                    manifest_sha256=hashlib.sha256(
                        (out / "manifest.json").read_bytes()
                    ).hexdigest()
                )
            )
        )

    def checker(self, out, flag):
        return subprocess.run(
            [sys.executable, *flag, str(ROOT / "validation/check_fields.py"), str(out)],
            capture_output=True,
            text=True,
        )

    def test_describe_schemas_cover_case_and_result(self):
        import jsonschema

        p = self.invoke("describe")
        self.assertEqual(p.returncode, 0)
        schemas = json.loads(p.stdout)
        jsonschema.Draft7Validator.check_schema(schemas["case_schema"])
        jsonschema.validate(self.case, schemas["case_schema"])
        out = self.run_case()
        jsonschema.validate(
            json.loads((out / "summary.json").read_text()), schemas["result_schema"]
        )

    def test_unknown_fields_rejected(self):
        self.case["flow"]["algorithm"] = "invented"
        p = self.invoke("check", self.save())
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn("panicked", p.stderr)

    def test_memory_rejected_before_allocation(self):
        self.case["run"]["memory_limit_mib"] = 1
        p = self.invoke("check", self.save())
        self.assertEqual(p.returncode, 1)
        self.assertIn(("CFD-E006", "run.memory_limit_mib"), self.diagnostics(p))

    def test_invalid_input_has_one_exit_code_and_a_report(self):
        self.case["numerics"]["advective_cfl_max"] = 0.9
        out = self.root / "never"
        for p in [
            self.invoke("check", self.save()),
            self.invoke("run", self.save(), "--output", out),
        ]:
            self.assertEqual(p.returncode, 1, p.stderr)
            self.assertIn(
                ("CFD-E010", "numerics.advective_cfl_max"), self.diagnostics(p)
            )
        self.assertFalse(out.exists())

    def test_parse_errors_carry_a_code_and_path(self):
        self.case["receptors"][0]["extra"] = 1
        p = self.invoke("check", self.save())
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.diagnostics(p), [("CFD-E000", "receptors[0]")])

    def test_each_problem_names_its_element(self):
        self.case = self.canyon()
        # "we" is a prefix of "we st"; the error must name the empty box, not box "we".
        self.case["geometry"][0]["id"] = "we"
        self.case["geometry"].append(
            dict(id="we st", min_m=[10.0, 3.0, 0.0], max_m=[10.01, 13.0, 1.0])
        )
        self.case["receptors"].append(
            dict(kind="point", id="inside", point_m=[5.5, 8.0, 0.4])
        )
        p = self.invoke("check", self.save())
        self.assertEqual(p.returncode, 1)
        self.assertIn(("CFD-E028", "geometry[2]"), self.diagnostics(p))
        del self.case["geometry"][2]
        p = self.invoke("check", self.save())
        self.assertEqual(p.returncode, 1)
        self.assertIn(("CFD-E042", "receptors[4]"), self.diagnostics(p))
        warnings = [d for d in self.diagnostics(p) if d[0] == "CFD-W001"]
        self.assertEqual(
            warnings, [("CFD-W001", "geometry[0]"), ("CFD-W001", "geometry[1]")]
        )

    def test_missing_output_parent_fails_before_solving(self):
        self.case = self.canyon()
        start = time.monotonic()
        p = self.invoke("run", self.save(), "--output", self.root / "missing" / "out")
        self.assertEqual(p.returncode, 1)
        self.assertIn("CFD-E063", p.stderr)
        self.assertIn("parent directory", p.stderr)
        # The canyon solve takes tens of seconds; the refusal must come first.
        self.assertLess(time.monotonic() - start, 5.0)

    def test_output_estimate_counts_constituents(self):
        self.case["grid"]["cells"] = [32, 32, 32]
        self.case["output"]["max_total_mib"] = 10
        base = self.case["constituents"][0]
        for i in range(15):
            self.case["constituents"].append(dict(base, id=f"extra{i}"))
        p = self.invoke("check", self.save())
        self.assertEqual(p.returncode, 1)
        self.assertIn(("CFD-E007", "output.max_total_mib"), self.diagnostics(p))

    def invoke_limited(self, address_space, *args):
        """Runs the CLI with a capped address space, so an allocation it cannot make aborts."""
        import resource

        def cap():
            resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))

        return subprocess.run(
            [str(BIN), *map(str, args)],
            capture_output=True,
            text=True,
            timeout=20,
            preexec_fn=cap,
        )

    def test_host_memory_refusal_comes_before_allocation(self):
        self.case = self.canyon()
        self.case["grid"]["cells"] = [4000, 4000, 6]
        self.case["run"]["memory_limit_mib"] = 10**8
        self.case["output"].update(fields=False, checkpoint=False)
        self.case["receptors"] = []
        report = json.loads(self.invoke("check", self.save()).stdout)["check"]
        try:
            info = Path("/proc/meminfo").read_text().split("MemAvailable:")[1]
            available = int(info.split()[0]) / 1024
        except (OSError, IndexError, ValueError):
            self.skipTest("this host does not report available memory")
        if report["estimated_peak_mib"] <= 0.8 * available:
            self.skipTest("this host could hold the large case")
        cap = 1 << 30
        start = time.monotonic()
        p = self.invoke_limited(cap, "check", self.save())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(("CFD-W070", "run.memory_limit_mib"), self.diagnostics(p))
        self.assertNotIn("geometry", json.loads(p.stdout))
        out = self.root / "never"
        p = self.invoke_limited(cap, "run", self.save(), "--output", out)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn(("CFD-E070", "run.memory_limit_mib"), self.diagnostics(p))
        self.assertFalse(out.exists())
        self.assertLess(time.monotonic() - start, 10.0)

    def slot(self):
        """A closed box with a sealed slot: two fluid regions at 64 cells per axis,
        one when coarsened by 4."""
        boxes = [
            ("a", [4, 4, 4], [12, 12, 8]),
            ("b", [4, 4, 8.5], [12, 12, 12]),
            ("s1", [4, 4, 7], [5, 12, 9.5]),
            ("s2", [11, 4, 7], [12, 12, 9.5]),
            ("s3", [5, 4, 7], [11, 5, 9.5]),
            ("s4", [5, 11, 7], [11, 12, 9.5]),
        ]
        case = json.loads((ROOT / "cases/verification/lid-cavity.json").read_text())
        case.update(
            name="slot",
            domain=dict(size_m=[16.0, 16.0, 16.0]),
            grid=dict(cells=[64, 64, 64]),
            boundaries=dict(x="wall", y="wall", z="wall"),
            flow=dict(
                kind="laminar", initial_velocity_m_s=[0.0] * 3, viscosity_m2_s=0.01
            ),
            geometry=[dict(id=i, min_m=lo, max_m=hi) for i, lo, hi in boxes],
            constituents=[],
            sources=[],
            initial_conditions=[],
            receptors=[],
        )
        case["run"].update(mode="transient", end_time_s=0.02, max_steps=2, threads=1)
        case["numerics"]["max_time_step_s"] = 0.01
        case["output"].update(fields=False, checkpoint=False)
        return case

    def test_preview_prints_the_report_for_invalid_input(self):
        self.case["run"]["threads"] = 0
        out = self.root / "never"
        p = self.invoke("preview", self.save(), "--output", out)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn(("CFD-E008", "run.threads"), self.diagnostics(p))
        self.assertFalse(out.exists())

    def test_preview_keeps_the_original_topology(self):
        self.case = self.slot()
        # Over its own memory budget the original is still compared, not built.
        for budget in [1024, 100]:
            self.case["run"]["memory_limit_mib"] = budget
            out = self.root / f"slot-{budget}"
            p = self.invoke("preview", self.save(), "--output", out, "--factor", 4)
            self.assertEqual(p.returncode, 1, (budget, p.stderr))
            errors = [d for d in self.diagnostics(p) if d[0].startswith("CFD-E")]
            self.assertEqual(errors, [("CFD-E072", "grid.cells")])
            self.assertIn("from 2 to 1", p.stdout)
            self.assertFalse(out.exists())
        p = self.invoke("preview", self.save(), "--output", self.root / "slot-2")
        self.assertIn(p.returncode, (0, 2), p.stdout)

    def test_preview_refuses_an_original_it_cannot_count(self):
        self.case = self.slot()
        self.case["geometry"] = [dict(id="block", min_m=[4, 4, 0], max_m=[12, 12, 12])]
        self.case["grid"]["cells"] = [4096, 4096, 8]
        out = self.root / "never"
        p = self.invoke("preview", self.save(), "--output", out, "--factor", 32)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn(("CFD-E073", "grid.cells"), self.diagnostics(p))
        self.assertFalse(out.exists())

    def test_preview_runs_the_coarse_case(self):
        self.case = self.canyon()
        self.case["grid"]["cells"] = [36, 32, 24]
        self.case["run"]["max_steps"] = 5
        out = self.root / "preview"
        p = self.invoke("preview", self.save(), "--output", out)
        self.assertEqual(p.returncode, 2, p.stderr)
        summary = json.loads(p.stdout)
        self.assertTrue(summary["model_scope"].startswith("preview: "))
        case = json.loads((out / "case.json").read_text())
        self.assertEqual(case["grid"]["cells"], [18, 16, 12])
        self.assertEqual(case["name"], self.case["name"] + "-preview")
        self.assertEqual(self.invoke("report", out).returncode, 0)

    def test_output_estimate_bounds_receptor_artifacts(self):
        size = self.case["domain"]["size_m"]
        self.case["receptors"] = [
            dict(
                kind="point",
                id=f"receptor-{i}",
                point_m=[
                    size[0] * (i % 97 + 0.5) / 97,
                    size[1] * (i // 97 % 61 + 0.5) / 61,
                    size[2] / 2,
                ],
            )
            for i in range(20000)
        ]
        self.case["output"].update(fields=True, checkpoint=True, max_total_mib=1000)
        report = json.loads(self.invoke("check", self.save()).stdout)["check"]
        out = self.run_case()
        written = sum(f.stat().st_size for f in out.iterdir()) / 1048576
        self.assertLessEqual(written, report["estimated_output_mib"])
        self.case["output"]["max_total_mib"] = int(written)
        p = self.invoke("check", self.save())
        self.assertEqual(p.returncode, 1)
        self.assertIn(("CFD-E007", "output.max_total_mib"), self.diagnostics(p))

    def test_report_repeats_omitted_artifacts(self):
        out = self.run_case()
        (out / "fields.json").unlink()
        manifest = json.loads((out / "manifest.json").read_text())
        del manifest["files"]["fields.json"]
        manifest["omitted"]["fields.json"] = "CFD-E061: over the output budget"
        (out / "manifest.json").write_text(json.dumps(manifest))
        self.reseal(out)
        p = self.invoke("report", out)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("CFD-E061", p.stderr)
        self.assertIn("fields.json", p.stderr)
        p = self.invoke("report", self.root / "missing")
        self.assertEqual(p.returncode, 1)
        self.assertIn("CFD-E064", p.stderr)

    def test_closed_stdout_is_not_a_crash(self):
        read, write = os.pipe()
        os.close(read)
        try:
            p = subprocess.run([str(BIN), "describe"], stdout=write, timeout=20)
        finally:
            os.close(write)
        self.assertEqual(p.returncode, 0)

    def test_report_rejects_inconsistent_archives(self):
        out = self.run_case()
        self.assertEqual(self.invoke("report", out).returncode, 0)
        (out / "notes.txt").write_text("unlisted")
        self.assertNotEqual(self.invoke("report", out).returncode, 0)
        (out / "notes.txt").unlink()
        case = json.loads((out / "case.json").read_text())
        case["constituents"][0]["diffusivity_m2_s"] *= 2
        (out / "case.json").write_text(json.dumps(case))
        self.reseal(out)
        p = self.invoke("report", out)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("does not describe case.json", p.stderr)

    def test_unbounded_initialization_rejected(self):
        self.case["initial_conditions"][0]["sigma_m"][0] = 1e200
        self.assertNotEqual(self.invoke("check", self.save()).returncode, 0)

    def test_occupied_output_preserved(self):
        out = self.root / "out"
        out.mkdir()
        (out / "sentinel").write_text("keep")
        p = self.invoke("run", self.save(), "--output", out)
        self.assertEqual(p.returncode, 1)
        self.assertIn("CFD-E062", p.stderr)
        self.assertEqual((out / "sentinel").read_text(), "keep")

    def test_null_and_nonfinite_input_rejected(self):
        for value in [None, float("nan"), float("inf")]:
            self.case["numerics"]["max_time_step_s"] = value
            self.assertNotEqual(self.invoke("check", self.save()).returncode, 0)

    def test_report_rejects_tampered_artifact(self):
        out = self.run_case()
        (out / "fields.json").write_text("{}")
        self.assertNotEqual(self.invoke("report", out).returncode, 0)

    def test_report_requires_completion_marker(self):
        out = self.run_case()
        (out / "complete.json").unlink()
        self.assertNotEqual(self.invoke("report", out).returncode, 0)

    def test_checkpoint_corruption_rejected(self):
        out = self.run_case()
        p = out / "checkpoint.json"
        p.write_text(p.read_text()[:-3])
        self.assertNotEqual(
            self.invoke(
                "run", self.save(), "--restart", p, "--output", self.root / "resume"
            ).returncode,
            0,
        )

    def test_independent_checker_survives_optimization(self):
        out = self.run_case()
        for flag in [[], ["-O"]]:
            p = subprocess.run(
                [
                    sys.executable,
                    *flag,
                    str(ROOT / "validation/check_fields.py"),
                    str(out),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p.returncode, 0, p.stdout)
        state = json.loads((out / "fields.json").read_text())
        state["concentrations"][0][0] += 1.0
        (out / "fields.json").write_text(json.dumps(state))
        manifest = json.loads((out / "manifest.json").read_text())
        manifest["files"]["fields.json"] = hashlib.sha256(
            (out / "fields.json").read_bytes()
        ).hexdigest()
        (out / "manifest.json").write_text(json.dumps(manifest))
        (out / "complete.json").write_text(
            json.dumps(
                dict(
                    manifest_sha256=hashlib.sha256(
                        (out / "manifest.json").read_bytes()
                    ).hexdigest()
                )
            )
        )
        # Rehashing defeats the integrity check; the independent physics check must still reject it.
        for flag in [[], ["-O"]]:
            p = subprocess.run(
                [
                    sys.executable,
                    *flag,
                    str(ROOT / "validation/check_fields.py"),
                    str(out),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(p.returncode, 0)

    def test_independent_checker_rejects_resealed_omissions(self):
        def drop_scalars(fields, summary):
            fields["concentrations"] = []
            fields["budgets"] = []

        def scale_receptor(fields, summary):
            summary["constituents"][0]["receptors_kg_m3"]["R1"] *= 100

        def nan_face(fields, summary):
            fields["velocity"][3] = math.nan

        def triple_velocity(fields, summary):
            fields["velocity"] = [3 * v for v in fields["velocity"]]

        def drop_rate(fields, summary):
            del summary["constituents"][0]["source_rate_kg_s"]

        def inflate_speed_scale(fields, summary):
            summary["velocity_max_m_s"] = 1e5
            fields["velocity"][0] += 1e-3

        for mutate in [
            drop_scalars,
            scale_receptor,
            nan_face,
            triple_velocity,
            drop_rate,
            inflate_speed_scale,
        ]:
            out = self.root / mutate.__name__
            p = self.invoke("run", self.save(), "--output", out)
            self.assertEqual(p.returncode, 0, p.stderr)
            fields = json.loads((out / "fields.json").read_text())
            summary = json.loads((out / "summary.json").read_text())
            mutate(fields, summary)
            (out / "fields.json").write_text(json.dumps(fields))
            (out / "summary.json").write_text(json.dumps(summary))
            self.reseal(out)
            for flag in [[], ["-O"]]:
                p = self.checker(out, flag)
                self.assertNotEqual(p.returncode, 0, (mutate.__name__, p.stdout))
                self.assertFalse(json.loads(p.stdout)["passed"])

    def test_independent_checker_rejects_resealed_rans_fields(self):
        self.case = self.canyon()
        self.case["run"]["max_steps"] = 5
        out = self.root / "rans"
        p = self.invoke("run", self.save(), "--output", out)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(self.checker(out, []).returncode, 0)
        fields = json.loads((out / "fields.json").read_text())
        fields["k"] = [-v for v in fields["k"]]
        (out / "fields.json").write_text(json.dumps(fields))
        self.reseal(out)
        for flag in [[], ["-O"]]:
            self.assertNotEqual(self.checker(out, flag).returncode, 0)

    def test_independent_checker_rejects_mass_in_solid_cells(self):
        self.case = self.canyon()
        self.case["run"]["max_steps"] = 5
        out = self.root / "solid"
        p = self.invoke("run", self.save(), "--output", out)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(self.checker(out, []).returncode, 0)
        fields = json.loads((out / "fields.json").read_text())
        values = fields["concentrations"][0]
        # Cell (5, 8, 0) lies inside box west; total mass is unchanged by the move.
        solid = (0 * 16 + 8) * 18 + 5
        fluid = max(range(len(values)), key=values.__getitem__)
        values[solid], values[fluid] = 0.999 * values[fluid], 0.001 * values[fluid]
        (out / "fields.json").write_text(json.dumps(fields))
        self.reseal(out)
        for flag in [[], ["-O"]]:
            p = self.checker(out, flag)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("solid cell", p.stdout)

    def test_independent_checker_rejects_a_wrong_source_strength(self):
        self.case = self.canyon()
        self.case["run"]["max_steps"] = 5
        out = self.root / "rate"
        p = self.invoke("run", self.save(), "--output", out)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(self.checker(out, []).returncode, 0)
        case = json.loads((out / "case.json").read_text())
        source = case["sources"][0]
        rate = next(k for k in source if k.startswith("rate_"))
        source[rate] *= 1.1
        (out / "case.json").write_text(json.dumps(case))
        self.reseal(out)
        for flag in [[], ["-O"]]:
            p = self.checker(out, flag)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("emission normalization", p.stdout)

    def test_launcher_forwards_a_signal_that_arrives_while_starting(self):
        work = self.root / "work"
        work.mkdir()
        solver = self.root / "solver.py"
        solver.write_text(
            "import json, os, signal, sys, time\n"
            "def stop(*_):\n"
            "    json.dump(dict(termination='cancelled'), open('simulation/summary.json', 'w'))\n"
            "    sys.exit(2)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            "os.mkdir('simulation')\n"
            "time.sleep(30)\n"
            "json.dump(dict(termination='completed'), open('simulation/summary.json', 'w'))\n"
        )
        wrapper = (
            "import os, runpy, signal, subprocess, sys\n"
            "real = subprocess.Popen\n"
            "def popen(*a, **k):\n"
            "    os.kill(os.getpid(), signal.SIGTERM)\n"
            "    return real(*a, **k)\n"
            "subprocess.Popen = popen\n"
            "sys.argv = sys.argv[1:]\n"
            "runpy.run_path(sys.argv[0], run_name='__main__')\n"
        )
        launcher = ROOT / "integrations/launch_command.py"
        stub = self.root / "solver"
        stub.write_text(f'#!/bin/sh\nexec {sys.executable} {solver} "$@"\n')
        stub.chmod(0o755)
        start = time.monotonic()
        p = subprocess.run(
            [sys.executable, "-c", wrapper, str(launcher), str(stub)],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=40,
        )
        # The launcher survives the signal and stops the solver instead of waiting for it.
        self.assertNotEqual(p.returncode, -signal.SIGTERM, p.stderr)
        self.assertLess(time.monotonic() - start, 20.0)
        summary = work / "summary.json"
        if summary.exists():
            self.assertEqual(
                json.loads(summary.read_text())["termination"], "cancelled"
            )

    def test_wall_time_retains_failure_evidence(self):
        self.case = json.loads((ROOT / "cases/canyon/wh1-wind270.json").read_text())
        self.case["grid"]["cells"] = [18, 16, 12]
        self.case["run"]["wall_time_limit_s"] = 1e-6
        out = self.root / "timeout"
        p = self.invoke("run", self.save(), "--output", out)
        self.assertEqual(p.returncode, 2, p.stderr)
        summary = json.loads((out / "summary.json").read_text())
        self.assertEqual(summary["termination"], "wall_time_limit")
        self.assertEqual(summary["assessment"], "incomplete")
        self.assertEqual(self.invoke("report", out).returncode, 0)

    def test_pressure_failure_is_not_success(self):
        self.case = json.loads((ROOT / "cases/canyon/wh1-wind270.json").read_text())
        self.case["grid"]["cells"] = [18, 16, 12]
        self.case["numerics"]["pressure_max_iterations"] = 1
        out = self.root / "pressure-failure"
        p = self.invoke("run", self.save(), "--output", out)
        self.assertEqual(p.returncode, 2, p.stderr)
        summary = json.loads((out / "summary.json").read_text())
        self.assertEqual(summary["assessment"], "incomplete")
        self.assertIn("pressure", summary["error"])

    def test_sigterm_retains_cancelled_summary(self):
        self.case = json.loads((ROOT / "cases/canyon/wh1-wind270.json").read_text())
        self.case["grid"]["cells"] = [18, 16, 12]
        out = self.root / "cancel"
        p = subprocess.Popen(
            [str(BIN), "run", str(self.save()), "--output", str(out)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.15)
        p.send_signal(signal.SIGTERM)
        stdout, stderr = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2, (stdout, stderr))
        summary = json.loads((out / "summary.json").read_text())
        self.assertEqual(summary["termination"], "cancelled")

    def test_unfrozen_experimental_protocol_cannot_pass(self):
        from compare_experiment import evaluate

        with self.assertRaises(ValueError):
            evaluate(dict(status="blocked_data"), "absent", "absent")

    def test_spatial_comparison_matches_sample_ids(self):
        from compare_experiment import evaluate

        obs = self.root / "obs.csv"
        pred = self.root / "pred.csv"
        obs.write_text(
            "case_id,wall,sample_id,observed_c_plus\nc,A,1,1\nc,A,2,2\nc,B,3,3\n"
        )
        pred.write_text(
            "case_id,wall,sample_id,predicted_c_plus\nc,A,1,1\nc,A,2,2\nc,B,3,3\n"
        )
        protocol = dict(
            status="frozen",
            pairing="wall taps paired in space, not arc maxima",
            observation_sha256=hashlib.sha256(obs.read_bytes()).hexdigest(),
            required_sample_ids=[["c", "A", "1"], ["c", "A", "2"], ["c", "B", "3"]],
            thresholds=dict(
                abs_fb_max=0.01, nmse_max=0.01, fac2_min=1.0, nmae_max=0.01
            ),
        )
        self.assertTrue(evaluate(protocol, obs, pred)["passed"])
        pred.write_text("case_id,wall,sample_id,predicted_c_plus\nc,A,1,1\n")
        with self.assertRaises(ValueError):
            evaluate(protocol, obs, pred)

    def test_iteration_limit_is_incomplete(self):
        self.case["run"]["max_steps"] = 1
        out = self.root / "limited"
        p = self.invoke("run", self.save(), "--output", out)
        self.assertEqual(p.returncode, 2)
        self.assertEqual(
            json.loads((out / "summary.json").read_text())["assessment"], "incomplete"
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--binary", type=Path, default=BIN)
    args, other = ap.parse_known_args()
    BIN = args.binary.resolve()
    unittest.main(argv=[sys.argv[0], *other])
