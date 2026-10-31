#!/usr/bin/env python3
"""Execute the manual's native CLI, Python and compiled Rust examples.

With --foam-root, execute the manual's OpenFOAM recipes (Examples 21, 22, 24 and
25, and the run of the mapped case) instead. Every step must exit 0; each row
of report.json records the step's exit code and the result fields that say
what happened.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


SCHEMA = "cfd-craft.manual-examples/0.1"


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-U001 manual.{field}: {message}")


def outcome(stdout):
    """The fields of a printed JSON result that say what happened, or None."""
    try:
        value = json.loads(stdout)
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    execution = value.get("execution")
    run = execution if isinstance(execution, dict) else value
    numerical = run.get("numerical")
    numerical = numerical if isinstance(numerical, dict) else {}
    found = dict(
        passed=value.get("passed"),
        error=value.get("error") or run.get("error"),
        execution_status=run.get("execution_status"),
        numerical_passed=numerical.get("passed"),
        iterations=numerical.get("iterations"),
        solver_reported_convergence=numerical.get("solver_reported_convergence"),
        final_residuals=numerical.get("initial_residuals_final_iteration"),
    )
    return {k: v for k, v in found.items() if v is not None}


def foam_recipes(run, root, out):
    """The manual's OpenFOAM recipes in order, with the same arguments.

    Steps after a failure still run, so one execution shows every failing step;
    a step that needs a failed step's output fails as well.
    """
    adapter = [sys.executable, ROOT / "integrations/openfoam_backend.py"]
    steps = [
        (
            "foam-api",
            [
                sys.executable,
                ROOT / "examples/manual/openfoam_api.py",
                "--foam-root",
                root,
                "--output",
                out / "manual-foam",
            ],
        ),
        (
            "foam-prepare",
            [*adapter, "prepare", "--case", "cavity", "--level", "1"]
            + ["--iterations", "3000", "--output", out / "foam-cavity-input"],
        ),
        (
            "foam-run",
            [*adapter, "run", "--case", out / "foam-cavity-input", "--foam-root", root]
            + ["--timeout-s", "180", "--output", out / "foam-cavity"],
        ),
        ("foam-report", [*adapter, "report", out / "foam-cavity"]),
        (
            "foam-continuation-prepare",
            [*adapter, "prepare-restart", "--source", out / "foam-cavity"]
            + ["--iterations", "3000", "--output", out / "foam-continuation-input"],
        ),
        (
            "foam-continuation-run",
            [*adapter, "run", "--case", out / "foam-continuation-input"]
            + ["--foam-root", root, "--timeout-s", "180"]
            + ["--output", out / "foam-continuation"],
        ),
        (
            "foam-finer-prepare",
            [*adapter, "prepare-mapped", "--source", out / "foam-cavity"]
            + ["--level", "2", "--iterations", "3000", "--foam-root", root]
            + ["--output", out / "foam-finer-input"],
        ),
        (
            "foam-finer-run",
            [*adapter, "run", "--case", out / "foam-finer-input", "--foam-root", root]
            + ["--timeout-s", "180", "--output", out / "foam-finer"],
        ),
    ]
    failed = []
    for name, argv in steps:
        try:
            run(name, argv, timeout=900)
        except ValueError:
            failed.append(name)
    require(not failed, "openfoam", "failed steps " + ", ".join(failed))


def native_examples(run, args, out, report):
    """The native CLI, Python cookbook, Rust examples and the point source."""
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
            value["archive_consistent"] and value["numerically_accepted"] is accepted,
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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/cfd-craft")
    ap.add_argument(
        "--example-dir", type=Path, default=ROOT / "target/release/examples"
    )
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument(
        "--foam-root",
        type=Path,
        help="Foundation-13 runtime root: run the OpenFOAM recipes instead",
    )
    args = ap.parse_args()
    out = args.output.absolute()
    report = dict(
        schema_version=SCHEMA,
        examples="openfoam" if args.foam_root else "native",
        passed=False,
        rows=[],
        physical_qualification=False,
    )
    claimed = False
    try:
        require(
            not out.exists() and not out.is_symlink(),
            "output",
            "fresh directory required",
        )
        native = [
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
        ]
        for p in [] if args.foam_root else native:
            require(p.is_file(), "binary", f"build first: {p}")
        out.mkdir(parents=True)
        claimed = True

        def run(name, argv, timeout=180):
            result = subprocess.run(
                [str(v) for v in argv],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"},
            )
            (out / (name + ".stdout.log")).write_text(result.stdout)
            (out / (name + ".stderr.log")).write_text(result.stderr)
            row = dict(name=name, returncode=result.returncode)
            found = outcome(result.stdout)
            if found is not None:
                row["result"] = found
            report["rows"].append(row)
            detail = (found or {}).get("error") or result.stderr or result.stdout
            require(
                result.returncode == 0,
                name + ".exit_code",
                f"{result.returncode}: {detail.strip()[-400:]}",
            )
            return json.loads(result.stdout)

        if args.foam_root:
            foam_recipes(run, args.foam_root, out)
        else:
            native_examples(run, args, out, report)
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
    return finish(report, out, claimed)


def finish(report, out, claimed):
    if claimed:
        (out / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n"
        )
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
