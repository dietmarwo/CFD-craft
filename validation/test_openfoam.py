#!/usr/bin/env python3
"""Boundary tests for external execution. All unit fixtures are synthetic.

Set CFD_OPENFOAM_ROOT for additional real Foundation-13 execution tests. No
synthetic fixture in this file is experimental or solver-validation evidence.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
sys.path.insert(0, str(ROOT / "tutorials"))
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
        with self.assertRaisesRegex(ValueError, "identity"):
            mesh_sensitivity(
                [{"level": 1, "comparison": row}, {"level": 2, "comparison": other}]
            )


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
