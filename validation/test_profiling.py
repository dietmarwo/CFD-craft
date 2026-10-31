#!/usr/bin/env python3
"""Real CLI profiles and fault injection against returned archives."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from check_profile import check

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "target/release/cfd-craft"


class Profiling(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-profile-")
        self.root = Path(self.temp.name)
        self.case = json.loads(
            (ROOT / "cases/verification/periodic-tracer.json").read_text()
        )
        self.case["grid"]["cells"] = [8, 4, 4]
        self.case["run"]["threads"] = 1
        self.case["run"]["end_time_s"] = 0.2

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, command, out="profile", restart=None):
        path = self.root / "input.json"
        path.write_text(json.dumps(self.case))
        args = [str(BIN), command, str(path), "--output", str(self.root / out)]
        if restart:
            args += ["--restart", str(restart)]
        return subprocess.run(args, capture_output=True, text=True, timeout=20)

    def profile(self):
        p = self.invoke("profile")
        self.assertEqual(p.returncode, 0, p.stderr)
        return self.root / "profile"

    def test_profile_and_plain_return_identical_archived_fields(self):
        plain = self.invoke("run", "plain")
        self.assertEqual(plain.returncode, 0, plain.stderr)
        out = self.profile()
        for name in [
            "fields.json",
            "checkpoint.json",
            "geometry.json",
            "case.json",
            "probes.csv",
        ]:
            self.assertEqual(
                (self.root / "plain" / name).read_bytes(),
                (out / "run" / name).read_bytes(),
            )
        r = check(out)
        self.assertTrue(r["integrity_passed"])
        self.assertTrue(r["numerical_accepted"])
        self.assertTrue(r["independent"]["passed"])
        report = subprocess.run(
            [str(BIN), "report", str(out / "run")], capture_output=True, text=True
        )
        self.assertEqual(report.returncode, 0, report.stderr)
        import jsonschema

        d = json.loads(subprocess.check_output([str(BIN), "describe"]))
        jsonschema.validate(
            json.loads((out / "profile.json").read_text())["timing"],
            d["phase_profile_schema"],
        )

    def test_restart_distinguishes_new_and_cumulative_work(self):
        self.case["run"]["end_time_s"] = 2.0
        self.case["run"]["max_steps"] = 2
        self.assertEqual(self.invoke("run", "seed").returncode, 2)
        self.case["run"]["max_steps"] = 4
        p = self.invoke("profile", restart=self.root / "seed/checkpoint.json")
        self.assertEqual(p.returncode, 2, p.stderr)
        r = check(self.root / "profile")
        self.assertEqual(r["attempted_steps"], 2)
        self.assertEqual(r["retained_new_steps"], 2)
        self.assertFalse(r["numerical_accepted"])

    def test_failed_pressure_attempt_is_retained_in_profile(self):
        self.case = json.loads(
            (ROOT / "cases/verification/lid-cavity.json").read_text()
        )
        self.case["numerics"]["pressure_max_iterations"] = 1
        self.case["run"]["max_steps"] = 1
        self.case["run"]["threads"] = 1
        p = self.invoke("profile")
        self.assertEqual(p.returncode, 2, p.stderr)
        r = check(self.root / "profile")
        self.assertEqual((r["attempted_steps"], r["retained_new_steps"]), (1, 0))
        self.assertEqual(
            (r["attempted_pressure_iterations"], r["retained_new_pressure_iterations"]),
            (1, 0),
        )

    def test_existing_dangling_and_missing_parent_outputs_fail_before_solving(self):
        for kind in ["existing", "dangling", "parent"]:
            out = self.root / kind
            if kind == "existing":
                out.mkdir()
                (out / "keep").write_text("keep")
            elif kind == "dangling":
                out.symlink_to(self.root / "not-created")
            name = kind + "/child" if kind == "parent" else kind
            p = self.invoke("profile", name)
            self.assertEqual(p.returncode, 1, p.stderr)
            self.assertIn("CFD-E06", p.stderr)
        self.assertEqual((self.root / "existing/keep").read_text(), "keep")
        self.assertFalse((self.root / "not-created").exists())

    def test_actual_native_sweep_keeps_an_iteration_limited_row(self):
        import accuracy_sweep as sweep

        row = sweep.run_method(
            "native-steady",
            12,
            self.root / "measurement",
            BIN.resolve(),
            self.root,
            dict(
                native_wall_s=20,
                native_max_steps=1,
                foam_wall_s=20,
                foam_iterations=3000,
            ),
        )
        sweep.validate_row(row)
        self.assertFalse(row["accepted"])
        self.assertFalse(row["numerical_accepted"])
        self.assertTrue(row["independent_passed"])
        self.assertEqual(row["termination"], "iteration_limit")
        self.assertEqual(row["steps"], 1)
        self.assertIsNotNone(row["reference_error"])

    def test_unknown_case_field_does_not_claim_output(self):
        self.case["flow"]["invented"] = True
        p = self.invoke("profile")
        self.assertEqual(p.returncode, 1)
        self.assertIn("CFD-E000", p.stdout)
        self.assertFalse((self.root / "profile").exists())

    def test_checker_rejects_identity_accounting_and_work_corruption(self):
        out = self.profile()
        path = out / "profile.json"
        original = json.loads(path.read_text())

        def corrupted(p, key, value):
            for name in key[:-1]:
                p = p[name]
            p[key[-1]] = value

        mutations = [
            (["source_sha256"], "changed"),
            (["archive_manifest_sha256"], "changed"),
            (["state_sha256"], "changed"),
            (["summary", "steps"], 999),
            (["timing", "schema_version"], "future"),
            (["timing", "accounted_exclusive_s"], 1000),
            (["timing", "phases", "step", "inclusive_s"], -1),
            (["timing", "phases", "step", "calls"], 0),
            (["timing", "phases", "step", "work_units"], True),
            (["timing", "elapsed_s"], float("nan")),
            (["passed"], False),
        ]
        for key, value in mutations:
            with self.subTest(key=key):
                p = copy.deepcopy(original)
                corrupted(p, key, value)
                path.write_text(json.dumps(p))
                with self.assertRaisesRegex(ValueError, "CFD-B003 profile"):
                    check(out)
        path.write_text(json.dumps(original))

    def test_checker_rejects_changed_fields_and_symlink_envelope(self):
        out = self.profile()
        alias = self.root / "alias"
        alias.symlink_to(out, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "profile.output"):
            check(alias)
        fields = out / "run/fields.json"
        fields.write_bytes(fields.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "profile.manifest.files.fields.json"):
            check(out)

    def reseal(self, out, manifest):
        """Rewrite the archive manifest and the two records that name its hash."""
        run = out / "run"
        (run / "manifest.json").write_text(json.dumps(manifest, indent=2))
        digest = hashlib.sha256((run / "manifest.json").read_bytes()).hexdigest()
        marker = json.loads((run / "complete.json").read_text())
        marker["manifest_sha256"] = digest
        (run / "complete.json").write_text(json.dumps(marker))
        envelope = json.loads((out / "profile.json").read_text())
        envelope["archive_manifest_sha256"] = digest
        (out / "profile.json").write_text(json.dumps(envelope))

    def edit(self, out, **changes):
        envelope = json.loads((out / "profile.json").read_text())
        envelope.update(changes)
        (out / "profile.json").write_text(json.dumps(envelope))

    def test_omitted_artifacts_and_the_verdict_are_bound_to_the_archive(self):
        out = self.profile()
        original = (out / "profile.json").read_text()
        for changes, field in [
            (dict(omitted=["fields.json"]), "profile.omitted"),
            (dict(passed=1), "profile.passed"),
            (dict(threads=1.0), "profile.threads"),
            (dict(error="CFD-E033: invented"), "profile.error"),
        ]:
            with self.subTest(changes=changes):
                (out / "profile.json").write_text(original)
                self.edit(out, **changes)
                with self.assertRaisesRegex(ValueError, field):
                    check(out)
        # An archive whose fields were omitted for the output budget: the
        # envelope must not call it a complete accepted result.
        (out / "profile.json").write_text(original)
        manifest = json.loads((out / "run/manifest.json").read_text())
        del manifest["files"]["fields.json"]
        manifest["omitted"]["fields.json"] = "CFD-E061: over the output budget"
        (out / "run/fields.json").unlink()
        self.reseal(out, manifest)
        with self.assertRaisesRegex(ValueError, "profile.omitted"):
            check(out)
        self.edit(out, omitted=["fields.json"])
        with self.assertRaisesRegex(ValueError, "profile.passed"):
            check(out)
        self.edit(out, passed=False)
        result = check(out)
        self.assertTrue(result["integrity_passed"])
        self.assertIsNone(result["independent"])

    def test_attempted_work_of_an_iteration_limited_run_is_all_retained(self):
        self.case["run"]["end_time_s"] = 2.0
        self.case["run"]["max_steps"] = 3
        p = self.invoke("profile")
        self.assertEqual(p.returncode, 2, p.stderr)
        out = self.root / "profile"
        self.assertEqual(
            json.loads((out / "run/summary.json").read_text())["termination"],
            "iteration_limit",
        )
        check(out)
        original = json.loads((out / "profile.json").read_text())
        for phases, field in [
            (["step", "timestep"], "work.steps"),
            (["monitor"], "work.monitor"),
            (["timestep"], "work.steps"),
        ]:
            with self.subTest(phases=phases):
                changed = copy.deepcopy(original)
                for name in phases:
                    changed["timing"]["phases"][name]["calls"] += 1
                (out / "profile.json").write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, field):
                    check(out)
        changed = copy.deepcopy(original)
        changed["initial_steps"] = 1
        (out / "profile.json").write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "work.monitor"):
            check(out)

    def test_an_oversized_counter_is_a_coded_error(self):
        out = self.profile()
        changed = json.loads((out / "profile.json").read_text())
        changed["timing"]["phases"]["step"]["calls"] = 10**400
        (out / "profile.json").write_text(json.dumps(changed))
        done = subprocess.run(
            [sys.executable, ROOT / "validation/check_profile.py", out],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertTrue(done.stdout.startswith("CFD-B003 profile."), done.stdout)
        del changed["timing"]
        (out / "profile.json").write_text(json.dumps(changed))
        done = subprocess.run(
            [sys.executable, ROOT / "validation/check_profile.py", out],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.stdout.strip(), "CFD-B003 profile.timing: missing field")


if __name__ == "__main__":
    unittest.main()
