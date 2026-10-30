#!/usr/bin/env python3
"""Boundary tests for external execution. All unit fixtures are synthetic.

Set CFD_OPENFOAM_ROOT for additional real Foundation-13 execution tests. No
synthetic fixture in this file is experimental or solver-validation evidence.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
sys.path.insert(0, str(ROOT / "tutorials"))
sys.path.insert(0, str(ROOT / "validation"))
import openfoam_backend as backend
import openfoam_cases
import backstep_data
import compare_backstep
from external_cfd import mesh_sensitivity


def synthetic_profiles():
    lines = ['variables="ID","y","u","v","uu","vv","uv","uuu","uvv","vuu","vvv"']
    for x in [-4, 1, 4, 6, 10]:
        lines.append(f'zone,t="exp, x/H={x}"')
        for i in range(10):
            lines.append(f"{i} {1.1 + i * 0.5} 1 0 1 1 0 0 0 0 0")
    return "\n".join(lines)


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-external-unit-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def prepared(self):
        path = self.root / "prepared"
        backend.prepare("cavity", 1, 50, path)
        return path

    def process_directory(self):
        path = self.root / "execution"
        (path / "case").mkdir(parents=True)
        return path

    def execute(self, source, seconds=2, max_bytes=1024**2, stop=None):
        return backend.execute(
            [sys.executable, "-c", source],
            os.environ.copy(),
            self.process_directory(),
            "unit",
            time.monotonic() + seconds,
            max_bytes,
            512,
            stop or backend.Stop(),
        )

    def test_prepared_input_corruption_is_rejected(self):
        path = self.prepared()
        with (path / "0/U").open("a") as f:
            f.write("\n//changed\n")
        with self.assertRaisesRegex(ValueError, "CFD-X001 case.inputs"):
            backend.check_prepared(path)

    def test_extra_files_and_symlinks_are_rejected(self):
        path = self.prepared()
        (path / "extra").write_text("not an input")
        with self.assertRaises(ValueError):
            backend.check_prepared(path)
        (path / "extra").unlink()
        (path / "extra").symlink_to(path / "0/U")
        with self.assertRaisesRegex(ValueError, "symlink"):
            backend.check_prepared(path)

    def test_generator_mismatch_is_rejected(self):
        path = self.prepared()
        record = json.loads((path / "case.json").read_text())
        record["generator_sha256"] = "0" * 64
        backend.write_json(path / "case.json", record)
        with self.assertRaisesRegex(ValueError, "generator_sha256"):
            backend.check_prepared(path)

    def test_prepare_requires_measurements_and_bounded_grid(self):
        with self.assertRaisesRegex(ValueError, "CFD-D001 data"):
            backend.prepare("backstep", 1, 100, self.root / "missing")
        with self.assertRaises(ValueError):
            openfoam_cases.build("cavity", 100, 100)

    def test_occupied_directory_is_preserved(self):
        path = self.prepared()
        marker = path / "0/U"
        before = marker.read_bytes()
        with self.assertRaises((FileExistsError, ValueError)):
            backend.prepare("cavity", 1, 50, path)
        self.assertEqual(marker.read_bytes(), before)

    def test_another_openfoam_fork_is_rejected(self):
        root = self.root / "wrong-runtime"
        directory = root / "platforms/linux64GccDPInt32Opt/bin"
        directory.mkdir(parents=True)
        for name in ["blockMesh", "checkMesh", "foamRun", "foamPostProcess"]:
            p = directory / name
            p.write_text(f"#!{sys.executable}\nprint('Using: OpenFOAM-v2312')\n")
            p.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "CFD-X002 runtime.version"):
            backend.runtime(root)

    def test_invalid_runtime_retains_a_failure_archive(self):
        prepared = self.prepared()
        output = self.root / "failed-run"
        result = backend.run(prepared, output, self.root / "not-a-runtime")
        self.assertFalse(result["passed"])
        self.assertEqual(result["execution_status"], "failed")
        self.assertEqual(backend.verify(output)["error"], result["error"])

    def test_zero_process_exit_does_not_supply_numerical_evidence(self):
        self.assertEqual(self.execute("print('done')")["returncode"], 0)
        with self.assertRaisesRegex(ValueError, "no iterations"):
            backend.numerical_assessment(self.root, "done", "cavity")

    def test_archive_versions_cannot_be_changed_by_resealing(self):
        prepared = self.prepared()
        for part in ["manifest.json", "summary.json"]:
            output = self.root / ("version-" + part)
            backend.run(prepared, output, self.root / "missing-runtime")
            value = json.loads((output / part).read_text())
            value["schema_version"] = "unsupported/999"
            backend.write_json(output / part, value)
            manifest = json.loads((output / "manifest.json").read_text())
            if part == "summary.json":
                entries = backend.inventory(output)
                entries.pop("manifest.json")
                entries.pop("complete.json")
                manifest["files"] = entries
            backend.write_json(output / "manifest.json", manifest)
            backend.write_json(
                output / "complete.json",
                {"manifest_sha256": backend.sha256(output / "manifest.json")},
            )
            with self.assertRaisesRegex(ValueError, "schema_version"):
                backend.verify(output)

    def test_failed_process_preserves_its_actual_return_code(self):
        with self.assertRaises(backend.ExecutionError) as failure:
            self.execute("print('failed'); raise SystemExit(7)")
        self.assertEqual(failure.exception.record["returncode"], 7)
        self.assertIn("CFD-X003", str(failure.exception))
        self.assertIn("failed", (self.root / "execution/unit.log").read_text())

    def test_timeout_kills_the_process_group(self):
        child = "import time; from pathlib import Path; time.sleep(0.6); Path('descendant-survived').write_text('alive')"
        source = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
        start = time.monotonic()
        with self.assertRaisesRegex(backend.ExecutionError, "CFD-X004"):
            self.execute(source, seconds=0.3)
        self.assertLess(time.monotonic() - start, 3)
        time.sleep(0.7)
        self.assertFalse((self.root / "execution/case/descendant-survived").exists())

    def test_cancellation_is_distinct_from_timeout(self):
        class TimedStop:
            deadline = time.monotonic() + 0.15

            @property
            def cancelled(self):
                return time.monotonic() >= self.deadline

        with self.assertRaisesRegex(backend.ExecutionError, "CFD-X008"):
            self.execute("import time; time.sleep(30)", stop=TimedStop())

    def test_an_exited_leader_cannot_leave_running_descendants(self):
        child = "import signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(0.6); Path('descendant-survived').write_text('alive')"
        source = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(0.15)"
        self.assertEqual(self.execute(source)["returncode"], 0)
        time.sleep(0.7)
        self.assertFalse((self.root / "execution/case/descendant-survived").exists())

    def test_output_budget_is_enforced(self):
        with self.assertRaisesRegex(backend.ExecutionError, "CFD-X005"):
            self.execute(
                "import sys; sys.stdout.buffer.write(b'x'*5000000); sys.stdout.flush()",
                max_bytes=1024 * 1024,
            )
        self.assertLessEqual(
            (self.root / "execution/unit.log").stat().st_size, 1024 * 1024
        )

    def test_scalar_lists_reject_bad_counts_and_nonfinite_values(self):
        with self.assertRaises(ValueError):
            backend.scalar_value("value nonuniform List<scalar> 2 (1);", "value", 2)
        with self.assertRaises(ValueError):
            backend.scalar_value("value nonuniform List<scalar> 1 (nan);", "value", 1)

    def test_full_returned_velocity_is_checked(self):
        p = self.root / "U"
        p.write_text("internalField nonuniform List<vector> 2 ((0 0 0) (1 nan 0));")
        with self.assertRaisesRegex(ValueError, "CFD-X006 fields.U"):
            backend.internal_values(p, 2, True)
        p.write_text("internalField nonuniform List<vector> 2 ((0 0 0) (1 0 0));")
        self.assertEqual(len(backend.internal_values(p, 2, True)), 6)

    def test_negative_final_turbulence_is_rejected(self):
        (self.root / "3").mkdir()
        backend.write_json(self.root / "case.json", {"metadata": {"cells": 1}})
        for name, value in {
            "U": "(0 0 0)",
            "p": "0",
            "k": "-1",
            "omega": "1",
            "nut": "1",
        }.items():
            (self.root / "3" / name).write_text(f"internalField uniform {value};")
        with self.assertRaisesRegex(ValueError, "fields.k"):
            backend.final_field_checks(self.root, "3", "backstep")

    def test_sample_position_and_nonfinite_values_are_rejected(self):
        path = self.root / "postProcessing/sampleProfiles/3"
        path.mkdir(parents=True)
        f = path / "line.xy"
        metadata = {"expected_samples": {"line": {"axis": "y", "positions": [0.5]}}}
        f.write_text("# y U_x U_y U_z\n0.6 1 0 0\n")
        with self.assertRaisesRegex(ValueError, "position"):
            backend.sample_checks(self.root, "3", metadata, "cavity")
        f.write_text("# y U_x U_y U_z\n0.5 nan 0 0\n")
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            backend.sample_checks(self.root, "3", metadata, "cavity")

    def test_measured_station_and_sample_identities_are_strict(self):
        text = synthetic_profiles()
        self.assertEqual(set(backstep_data.profiles(text)), {-4, 1, 4, 6, 10})
        with self.assertRaisesRegex(ValueError, "duplicate station"):
            backstep_data.profiles(text + "\n" + text)
        with self.assertRaises(ValueError):
            backstep_data.profiles(text.replace("x/H=10", "x/H=11"))
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            backstep_data.profiles(text.replace("1 0 1 1", "nan 0 1 1", 1))

    def test_reference_file_corruption_is_rejected(self):
        for name in backstep_data.FILES:
            (self.root / name).write_text("synthetic data, not measurements")
        with self.assertRaisesRegex(ValueError, "raw SHA-256 mismatch"):
            backstep_data.load(self.root)

    def test_protocol_tolerance_cannot_be_relaxed(self):
        p = json.loads(compare_backstep.PROTOCOL.read_text())
        p["profile_rmse_max_u_ref"] = 100
        backend.write_json(self.root / "relaxed.json", p)
        with self.assertRaisesRegex(ValueError, "protocol.sha256"):
            compare_backstep.assess(self.root, self.root, self.root / "relaxed.json")

    def test_reference_interpolation_never_extrapolates(self):
        with self.assertRaisesRegex(ValueError, "extrapolation"):
            compare_backstep.interpolate([1, 2], [0, 1], [0.5], "test")
        with self.assertRaises(ValueError):
            compare_backstep.interpolate([1, 1], [0, 1], [1], "test")
        self.assertAlmostEqual(
            compare_backstep.interpolate([1, 2], [0, 1], [1.5], "test")[0], 0.5
        )

    def test_reattachment_uses_signed_cf_and_reports_multiple_crossings(self):
        x = np.array([0, 2, 3, 4, 5, 6, 7], dtype=float)
        cf = np.array([0, -1, 1, -1, 1, -1, 1], dtype=float)
        last, all_crossings = compare_backstep.crossing(x, cf)
        self.assertEqual(last, 6.5)
        self.assertEqual(len(all_crossings), 3)
        self.assertIsNone(compare_backstep.crossing(x, np.ones(len(x)))[0])

    def test_failed_meshes_are_not_converged_grid_points(self):
        rows = [
            {"level": 1, "comparison": {"numerical_passed": False}},
            {"level": 2, "comparison": None},
        ]
        result = mesh_sensitivity(rows)
        self.assertFalse(result["assessed"])
        self.assertEqual(result["available_converged_levels"], [])

    def test_mesh_comparison_matches_identities(self):
        sample = {
            "station_x_over_h": 1,
            "sample_id": 1,
            "y_over_h": 0.1,
            "predicted_u_over_u_ref": 0.5,
        }
        row = {
            "numerical_passed": True,
            "paired_velocity_samples": [sample],
            "reattachment": {"predicted_x_over_h": 6},
        }
        other = json.loads(json.dumps(row))
        other["paired_velocity_samples"][0]["sample_id"] = 2
        with self.assertRaisesRegex(
            ValueError, "CFD-D001 mesh_sensitivity.paired_velocity_samples"
        ):
            mesh_sensitivity(
                [{"level": 1, "comparison": row}, {"level": 2, "comparison": other}]
            )


# A synthetic stand-in for the four Foundation-13 programs. It writes logs, fields,
# a patch list and samples in the formats the adapter parses, so run() and verify()
# are exercised end to end without OpenFOAM. Behaviour comes from <root>/mode.
FAKE_PROGRAM = r"""
import json, os, re, sys, time
from pathlib import Path

name = Path(sys.argv[0]).name
root = Path(sys.argv[0]).resolve().parents[3]
mode = (root / "mode").read_text().strip()
args = sys.argv[1:]
if "-help" in args:
    print("Usage: foamRun [OPTIONS]")
    print("Using: OpenFOAM-13 (synthetic test runtime)")
    sys.exit(0)
case = Path(args[args.index("-case") + 1])
print("| Version:  13")
print("Build  : 13-synthetic")
meta = json.loads((case / "case.json").read_text())["metadata"]
cells = meta["cells"]
faces = round(cells**0.5)
if name == "blockMesh":
    mesh = case / "constant/polyMesh"
    mesh.mkdir(parents=True)
    (mesh / "boundary").write_text(
        f"2\n(\nlid {{ type wall; nFaces {faces}; startFace 0; }}\n"
        f"walls {{ type wall; nFaces {3 * faces}; startFace {faces}; }}\n)\n"
    )
elif name == "checkMesh":
    print("Mesh OK.")
elif name == "foamRun":
    print("ENVIRONMENT", " ".join(sorted(os.environ)), "HOME=" + os.environ.get("HOME", ""))
    iterations = 3 if mode == "stalled" else 2
    if mode == "churn":
        # Old snapshots appear and vanish while the adapter measures the output.
        end, i = time.monotonic() + 1.0, 0
        while time.monotonic() < end:
            snapshot = case / str(100 + i % 3)
            snapshot.mkdir(exist_ok=True)
            for j in range(30):
                (snapshot / f"f{j}").write_bytes(b"x" * 64)
            for f in list(snapshot.iterdir()):
                f.unlink()
            snapshot.rmdir()
            i += 1
    for it in range(1, iterations + 1):
        r = 5e-8 if it == iterations and mode != "stalled" else 1e-3
        print(f"Time = {it}s")
        print(f"smoothSolver:  Solving for Ux, Initial residual = {r}, Final residual = 1e-12, No Iterations 3")
        print(f"smoothSolver:  Solving for Uy, Initial residual = {r}, Final residual = 1e-12, No Iterations 3")
        print(f"GAMG:  Solving for p, Initial residual = {r}, Final residual = 1e-12, No Iterations 5")
        # A second pressure solve: OpenFOAM's residualControl uses the first one.
        print("GAMG:  Solving for p, Initial residual = 0.09, Final residual = 1e-12, No Iterations 5")
        print(f"time step continuity errors : sum local = {r * 1e-3}, global = 0, cumulative = 0")
    snapshot = case / str(iterations)
    snapshot.mkdir()
    values = " ".join("(0.1 0 0)" for _ in range(cells))
    (snapshot / "U").write_text(f"internalField nonuniform List<vector> {cells} ({values});\n")
    (snapshot / "p").write_text("internalField uniform 0;\n")
    lid = f"nonuniform List<scalar> {faces} ({' '.join(['1e-3'] * faces)})" if mode == "leak" else "uniform 0"
    (snapshot / "phi").write_text(
        f"boundaryField\n{{\nlid {{ type calculated; value {lid}; }}\n"
        "walls { type calculated; value uniform 0; }\n}\n"
    )
    if mode != "stalled":
        print(f"SIMPLE solution converged in {iterations} iterations")
    if mode == "symlink":
        (case / "link").symlink_to(case / "case.json")
    print("End")
elif name == "foamPostProcess":
    latest = max((p for p in case.iterdir() if re.fullmatch(r"[0-9]+", p.name)), key=lambda p: int(p.name)).name
    for sample, spec in meta["expected_samples"].items():
        out = case / "postProcessing/sampleProfiles" / latest
        out.mkdir(parents=True, exist_ok=True)
        rows = "\n".join(f"{y!r} 0.1 0 0" for y in spec["positions"])
        (out / f"{sample}.xy").write_text(f"# {spec['axis']} U_x U_y U_z\n{rows}\n")
    print("End")
"""


def fake_runtime(root, mode):
    """A runtime directory whose four programs are FAKE_PROGRAM."""
    bin_directory = Path(root) / "platforms/linux64GccDPInt32Opt/bin"
    bin_directory.mkdir(parents=True)
    (Path(root) / "etc").mkdir()
    (Path(root) / "etc/controlDict").write_text("synthetic\n")
    (Path(root) / "mode").write_text(mode)
    for name in ["blockMesh", "checkMesh", "foamRun", "foamPostProcess"]:
        program = bin_directory / name
        program.write_text(f"#!{sys.executable}\n" + FAKE_PROGRAM)
        program.chmod(0o755)
    return Path(root)


def reseal(directory):
    entries = backend.inventory(directory)
    entries.pop("manifest.json")
    entries.pop("complete.json")
    backend.write_json(
        directory / "manifest.json",
        {"schema_version": "cfd-craft.external-archive/0.1", "files": entries},
    )
    backend.write_json(
        directory / "complete.json",
        {"manifest_sha256": backend.sha256(directory / "manifest.json")},
    )


class FakeRuntime(unittest.TestCase):
    """run() and verify() end to end on a synthetic runtime; not solver evidence."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-external-fake-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_fake(self, mode, name="run"):
        prepared = self.root / f"{name}-input"
        backend.prepare("cavity", 1, 50, prepared)
        foam = fake_runtime(self.root / f"{name}-runtime", mode)
        output = self.root / name
        return backend.run(prepared, output, foam, timeout_s=60), output

    def test_a_converged_run_verifies_with_first_solve_residuals(self):
        saved = {k: os.environ.get(k) for k in ["WM_PROJECT_SITE", "FOAM_SIGFPE"]}
        os.environ.update(WM_PROJECT_SITE="/site", FOAM_SIGFPE="0")
        try:
            report, output = self.run_fake("converged")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key)
                else:
                    os.environ[key] = value
        self.assertTrue(report["passed"], report.get("error"))
        self.assertTrue(backend.verify(output)["passed"])
        numerical = report["numerical"]
        self.assertEqual(numerical["iterations"], 2)
        self.assertTrue(numerical["solver_reported_convergence"])
        # The first pressure solve of the last iteration, not the later one at 0.09.
        self.assertEqual(numerical["initial_residuals_final_iteration"]["p"], 5e-8)
        self.assertEqual(numerical["residual_trend"]["p"]["median_last_window"], 5e-8)
        self.assertEqual(
            [c["program"] for c in report["commands"]], backend.PROGRAMS["cavity"]
        )
        # The child sees a fixed environment, not the caller's OpenFOAM settings.
        line = next(
            x
            for x in (output / "solve.log").read_text().splitlines()
            if x.startswith("ENVIRONMENT")
        )
        self.assertNotIn("WM_PROJECT_SITE", line)
        self.assertNotIn("FOAM_SIGFPE", line)
        self.assertIn("HOME=/nonexistent", line)

    def test_a_stalled_run_completes_without_numerical_acceptance(self):
        report, output = self.run_fake("stalled")
        self.assertEqual(report["execution_status"], "completed")
        self.assertFalse(report["passed"])
        self.assertTrue(report["error"].startswith("CFD-X007"))
        self.assertFalse(backend.verify(output)["passed"])

    def test_a_net_boundary_flux_fails_the_balance(self):
        report, output = self.run_fake("leak")
        faces = round(report["case_metadata"]["cells"] ** 0.5)
        self.assertAlmostEqual(
            report["numerical"]["net_flux_m3_s"], faces * 1e-3, delta=1e-12
        )
        self.assertFalse(report["passed"])

    def test_snapshot_deletion_during_a_solve_keeps_every_record(self):
        report, output = self.run_fake("churn")
        self.assertTrue(report["passed"], report.get("error"))
        self.assertEqual(
            [c["program"] for c in report["commands"]], backend.PROGRAMS["cavity"]
        )

    def test_a_symlink_left_by_the_solver_seals_a_failed_archive(self):
        report, output = self.run_fake("symlink")
        self.assertEqual(report["execution_status"], "failed")
        self.assertIn("CFD-X006 archive.symlinks: case/link", report["error"])
        self.assertTrue((output / "complete.json").is_file())
        with self.assertRaisesRegex(ValueError, "symlink rejected"):
            backend.verify(output)

    def test_the_copied_case_is_what_gets_checked(self):
        original = backend.shutil.copytree

        def copy_and_add(source, destination, *args, **kwargs):
            result = original(source, destination, *args, **kwargs)
            if Path(destination).name == "case":
                (Path(destination) / "constant/fvModels").write_text("added\n")
            return result

        backend.shutil.copytree = copy_and_add
        try:
            report, output = self.run_fake("converged")
        finally:
            backend.shutil.copytree = original
        self.assertEqual(report["execution_status"], "failed")
        self.assertIn("CFD-X001 case.inputs", report["error"])

    def test_the_verifier_rejects_inconsistent_archives(self):
        report, output = self.run_fake("converged")

        def mutated(change):
            target = self.root / f"mutated-{len(list(self.root.iterdir()))}"
            backend.shutil.copytree(output, target, symlinks=True)
            change(target)
            reseal(target)
            return target

        def summary(edit):
            def change(target):
                record = json.loads((target / "summary.json").read_text())
                edit(record)
                backend.write_json(target / "summary.json", record)

            return change

        def failed_solver(r):
            r["commands"][2]["returncode"] = 139

        def other_runtime(r):
            r["runtime"]["help"] = "Using: OpenFOAM-v2312"

        def progress(r):
            r["progress"]["started_iterations"] = 3000

        def relabelled(r):
            r["execution_status"] = "timeout"

        def extra_input(target):
            (target / "case/constant/fvModels").write_text("not consumed\n")

        def inputs_as_list(target):
            record = json.loads((target / "case/case.json").read_text())
            record["inputs"] = list(record["inputs"])
            backend.write_json(target / "case/case.json", record)
            summary(
                lambda r: r.update(
                    case_sha256=backend.sha256(target / "case/case.json")
                )
            )(target)

        for change, expected in [
            (summary(failed_solver), "archive.commands"),
            (summary(other_runtime), "archive.runtime"),
            (summary(progress), "archive.progress"),
            (summary(relabelled), "archive.error"),
            (extra_input, "archive.case/constant/fvModels"),
            (inputs_as_list, "CFD-X006 archive: malformed"),
        ]:
            with self.assertRaisesRegex(ValueError, expected):
                backend.verify(mutated(change))

    def test_exit_codes_separate_failed_execution_from_unaccepted_numerics(self):
        prepared = self.root / "cli-input"
        backend.prepare("cavity", 1, 50, prepared)
        script = ROOT / "integrations/openfoam_backend.py"

        def cli(output, foam):
            return subprocess.run(
                [sys.executable, str(script), "run", "--case", str(prepared)]
                + ["--output", str(output), "--foam-root", str(foam)]
                + ["--timeout-s", "60"],
                capture_output=True,
                text=True,
                timeout=120,
            ).returncode

        self.assertEqual(cli(self.root / "cli-missing", self.root / "missing"), 1)
        stalled = fake_runtime(self.root / "cli-runtime", "stalled")
        self.assertEqual(cli(self.root / "cli-stalled", stalled), 2)

    def test_tutorial_errors_are_coded_and_cancellation_stops_downloads(self):
        import external_cfd

        report, output = self.run_fake("converged")
        result = external_cfd.cavity_comparison(
            self.root / "no-binary", output, self.root / "comparison"
        )
        self.assertFalse(result["passed"])
        self.assertTrue(result["error"].startswith("CFD-"), result["error"])
        self.assertTrue((self.root / "comparison/cavity-comparison.json").is_file())

        fetched = []
        original_run, original_fetch = external_cfd.backend.run, external_cfd.fetch

        def cancelled_run(*args, stop, **kwargs):
            stop.cancelled = True
            return {"passed": False, "execution_status": "cancelled"}

        external_cfd.backend.run = cancelled_run
        external_cfd.fetch = fetched.append
        try:
            workflow = external_cfd.workflow(
                self.root / "unused", self.root / "no-binary", self.root / "flow"
            )
        finally:
            external_cfd.backend.run = original_run
            external_cfd.fetch = original_fetch
        self.assertEqual(fetched, [])
        self.assertFalse(workflow["workflow_completed"])


class Installer(unittest.TestCase):
    def test_installer_errors_carry_one_code(self):
        import install_openfoam13

        with tempfile.TemporaryDirectory(prefix="cfd-installer-") as d:
            root = Path(d)
            (root / "occupied").mkdir()
            with self.assertRaisesRegex(ValueError, "^CFD-E062 output"):
                install_openfoam13.install(root / "occupied", root / "missing.deb")
            package = root / "wrong.deb"
            package.write_bytes(b"not the pinned package")
            p = subprocess.run(
                [sys.executable, str(ROOT / "integrations/install_openfoam13.py")]
                + ["--output", str(root / "out"), "--package-file", str(package)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(p.returncode, 1)
            error = json.loads(p.stdout)["error"]
            self.assertEqual(error.count("CFD-"), 1, error)


class Comparison(unittest.TestCase):
    def test_a_failed_numerical_gate_leaves_the_screen_unassessed(self):
        screen = compare_backstep.measurement_screen(False, True)
        self.assertIsNone(screen["measurement_screen_passed"])
        self.assertFalse(screen["passed"])
        self.assertTrue(screen["measurement_screen"].startswith("not_assessed"))
        self.assertTrue(compare_backstep.measurement_screen(True, True)["passed"])

    def test_baselines_and_near_wall_resolution(self):
        inlet = [[0, 1.0, 0.5], [1, 2.0, 1.0]]
        baseline = compare_backstep.no_step_baseline(inlet, np.array([0.5, 1.5, 3.0]))
        np.testing.assert_allclose(baseline, [0.0, 0.75, 1.0])
        metadata = {
            "lower_wall_first_cell_height_h": 1 / 24,
            "reference_speed_m_s": 1.0,
            "height_m": 1.0,
            "reynolds": 36000,
            "turbulence_package": "synthetic",
        }
        x = np.array([2.0, 6.0, 20.0])
        stress = np.array([[-1e-4, 0.0], [4e-4, 0.0], [9e-4, 0.0]])
        resolution = compare_backstep.first_cell_y_plus(metadata, x, stress)
        expected = [0.01 * 36000 / 48, 0.02 * 36000 / 48, 0.03 * 36000 / 48]
        self.assertAlmostEqual(resolution["scored_1_to_12"]["minimum"], expected[0])
        self.assertAlmostEqual(resolution["scored_1_to_12"]["maximum"], expected[1])
        self.assertAlmostEqual(resolution["recovery_12_to_40"]["median"], expected[2])


@unittest.skipUnless(
    os.environ.get("CFD_OPENFOAM_ROOT"), "set CFD_OPENFOAM_ROOT for real backend tests"
)
class RealBackend(unittest.TestCase):
    def test_real_cavity_and_iteration_limit(self):
        with tempfile.TemporaryDirectory(prefix="cfd-real-openfoam-") as d:
            root = Path(d)
            foam = Path(os.environ["CFD_OPENFOAM_ROOT"])
            for iterations, should_pass in [(3000, True), (50, False)]:
                source = root / f"input{iterations}"
                output = root / f"run{iterations}"
                backend.prepare("cavity", 1, iterations, source)
                report = backend.run(source, output, foam, timeout_s=60)
                self.assertEqual(report["passed"], should_pass, report.get("error"))
                self.assertEqual(backend.verify(output)["passed"], should_pass)
                self.assertEqual(report["execution_status"], "completed")
                # Resealing checksums must not hide a corrupted actual returned field.
                time_name = report["numerical"]["final_time_directory"]
                field = output / "case" / time_name / "U"
                text = field.read_text()
                field.write_text(text.replace("internalField", "invalidField", 1))
                with self.assertRaisesRegex(ValueError, "fields.U"):
                    backend.final_field_checks(output / "case", time_name, "cavity")
                entries = backend.inventory(output)
                entries.pop("manifest.json")
                entries.pop("complete.json")
                backend.write_json(
                    output / "manifest.json",
                    {
                        "schema_version": "cfd-craft.external-archive/0.1",
                        "files": entries,
                    },
                )
                backend.write_json(
                    output / "complete.json",
                    {"manifest_sha256": backend.sha256(output / "manifest.json")},
                )
                with self.assertRaisesRegex(ValueError, "fields.U"):
                    backend.verify(output)


if __name__ == "__main__":
    unittest.main()
