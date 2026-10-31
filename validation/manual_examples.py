#!/usr/bin/env python3
"""Execute the manual's native CLI, Python and compiled Rust examples."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-U001 manual.{field}: {message}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/cfd-craft")
    ap.add_argument(
        "--example-dir", type=Path, default=ROOT / "target/release/examples"
    )
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    out = args.output.absolute()
    report = dict(passed=False, rows=[], physical_qualification=False)
    claimed = False
    try:
        require(
            not out.exists() and not out.is_symlink(),
            "output",
            "fresh directory required",
        )
        for p in [
            args.binary,
            *[
                args.example_dir / n
                for n in [
                    "manual_library",
                    "manual_control",
                    "manual_checkpoint",
                    "manual_archive",
                ]
            ],
        ]:
            require(p.is_file(), "binary", f"build first: {p}")
        out.mkdir(parents=True)
        claimed = True

        def run(name, argv):
            result = subprocess.run(
                [str(v) for v in argv],
                capture_output=True,
                text=True,
                timeout=180,
                env={**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"},
            )
            (out / (name + ".stdout.log")).write_text(result.stdout)
            (out / (name + ".stderr.log")).write_text(result.stderr)
            report["rows"].append(dict(name=name, returncode=result.returncode))
            require(
                result.returncode == 0,
                name + ".exit_code",
                result.stderr or result.stdout,
            )
            return json.loads(result.stdout)

        for mode, flags in [("normal", []), ("optimized", ["-O"])]:
            value = run(
                "python-" + mode,
                [
                    sys.executable,
                    *flags,
                    ROOT / "examples/manual/cli_workflow.py",
                    "--binary",
                    args.binary.resolve(),
                    "--output",
                    out / mode,
                ],
            )
            require(
                value["passed"] and value["resumed_equals_cold"],
                "python." + mode,
                "workflow failed",
            )
        for name in ["manual_library", "manual_control", "manual_checkpoint"]:
            argv = [args.example_dir.resolve() / name]
            if name == "manual_checkpoint":
                argv.append(out / "library-checkpoint.json")
            value = run(name, argv)
            require(value["passed"], name, "example failed")
            if name == "manual_library":
                require(
                    abs(value["source_total_kg_s"] - 1.92e-7) <= 1e-19,
                    name + ".source_total_kg_s",
                    "volume-rate units differ",
                )
            if name == "manual_checkpoint":
                require(
                    value["same_state_as_cold"] and value["initial_state_id_differs"],
                    name + ".replay",
                    "restart evidence differs",
                )
        for label, accepted in [("base", True), ("partial", False)]:
            value = run(
                "archive-" + label,
                [args.example_dir.resolve() / "manual_archive", out / "normal" / label],
            )
            require(
                value["archive_consistent"]
                and value["numerically_accepted"] is accepted,
                "archive." + label,
                "integrity conflated with assessment",
            )
        point = ROOT / "examples/manual/point-source.json"
        run("point-check", [args.binary.resolve(), "check", point])
        solved = run(
            "point-run",
            [args.binary.resolve(), "run", point, "--output", out / "point-source"],
        )
        require(
            solved["assessment"] == "steady_discrete_solution",
            "point-source.assessment",
            "not accepted",
        )
        run("point-report", [args.binary.resolve(), "report", out / "point-source"])
        audit = run(
            "point-audit",
            [sys.executable, ROOT / "validation/check_fields.py", out / "point-source"],
        )
        require(audit["passed"], "point-source.audit", "field check failed")
        tracer = next(s for s in solved["constituents"] if s["id"] == "tracer")
        report["point_source_ug_m3"] = tracer["receptors_kg_m3"]["R_down"] * 1e9
        report["passed"] = True
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        StopIteration,
        subprocess.SubprocessError,
    ) as exc:
        report["error"] = (
            str(exc)
            if str(exc).startswith("CFD-")
            else f"CFD-U001 manual.execution: {exc}"
        )
    if claimed:
        (out / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n"
        )
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
