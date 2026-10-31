#!/usr/bin/env python3
"""Real CLI usage: schema validation, source scaling, replay and failure semantics."""

import argparse
import copy
import json
import math
from pathlib import Path
import subprocess
import sys

import jsonschema

ROOT = Path(__file__).resolve().parents[2]


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-U001 manual.{field}: {message}")


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def workflow(binary, output):
    require(
        not output.exists() and not output.is_symlink(), "output", "new path required"
    )
    output = output.resolve()
    require(binary.is_file(), "binary", "build the native CLI first")
    output.mkdir(parents=True)
    result = dict(passed=False, commands=[], physical_qualification=False)

    def call(label, argv, expected=0):
        run = subprocess.run(
            [str(v) for v in argv], capture_output=True, text=True, timeout=140
        )
        (output / (label + ".stdout.log")).write_text(run.stdout)
        (output / (label + ".stderr.log")).write_text(run.stderr)
        result["commands"].append(dict(label=label, returncode=run.returncode))
        require(
            run.returncode == expected, label + ".exit_code", run.stderr or run.stdout
        )
        return json.loads(run.stdout)

    def cli(label, *args, expected=0):
        return call(label, [binary, *args], expected)

    try:
        schemas = cli("describe", "describe")
        case = json.loads(
            (ROOT / "cases/verification/source-response.json").read_text()
        )
        case["run"]["threads"] = 1
        jsonschema.validate(case, schemas["case_schema"])
        write(output / "source.json", case)
        checked = cli("check", "check", output / "source.json")
        require(checked["check"]["valid"], "check.valid", "case rejected")
        summary = cli(
            "solve", "run", output / "source.json", "--output", output / "base"
        )
        require(
            summary["assessment"] == "steady_discrete_solution",
            "assessment",
            "not accepted",
        )
        jsonschema.validate(summary, schemas["result_schema"])
        verified = cli("report", "report", output / "base")
        require(verified == summary, "report", "summary differs")
        audit = call(
            "audit",
            [sys.executable, ROOT / "validation/check_fields.py", output / "base"],
        )
        require(audit["passed"], "audit", "independent field check failed")
        tracer = next(s for s in summary["constituents"] if s["id"] == "tracer")
        r1 = tracer["receptors_kg_m3"]["R1"]  # IDs, not dictionary positions.
        scaled = copy.deepcopy(case)
        for source in scaled["sources"]:
            source["rate_kg_s_m3"] *= 2
        write(output / "scaled.json", scaled)
        twice = cli(
            "scaled", "run", output / "scaled.json", "--output", output / "scaled"
        )
        require(
            twice["assessment"] == "steady_discrete_solution",
            "scaled.assessment",
            "not accepted",
        )
        twice_r1 = next(s for s in twice["constituents"] if s["id"] == "tracer")[
            "receptors_kg_m3"
        ]["R1"]
        require(
            math.isclose(twice_r1, 2 * r1, rel_tol=1e-6),
            "scaled.R1",
            "linear source response mismatch",
        )
        # Invalid input exits 1 and never creates a solve directory.
        invalid = copy.deepcopy(case)
        invalid["flow"]["invented_solver"] = True
        write(output / "invalid.json", invalid)
        bad = cli("invalid", "check", output / "invalid.json", expected=1)
        require(not bad["check"]["valid"], "invalid", "invalid case accepted")
        require(
            any(d["code"] == "CFD-E000" for d in bad["check"]["diagnostics"]),
            "invalid.diagnostic",
            "parse code missing",
        )
        # Interrupt by work budget, keep the same physical endpoint for restart.
        full = json.loads(
            (ROOT / "cases/verification/periodic-tracer.json").read_text()
        )
        full["run"]["threads"] = 1
        partial = copy.deepcopy(full)
        partial["run"]["max_steps"] = 5
        write(output / "partial.json", partial)
        write(output / "full.json", full)
        stopped = cli(
            "partial",
            "run",
            output / "partial.json",
            "--output",
            output / "partial",
            expected=2,
        )
        require(
            stopped["termination"] == "iteration_limit"
            and stopped["assessment"] == "incomplete",
            "partial",
            "wrong status",
        )
        consistent = cli("partial-report", "report", output / "partial")
        require(
            consistent["assessment"] == "incomplete",
            "partial-report",
            "integrity changed numerical verdict",
        )
        resumed = cli(
            "resume",
            "run",
            output / "full.json",
            "--restart",
            output / "partial/checkpoint.json",
            "--output",
            output / "resumed",
        )
        cold = cli("cold", "run", output / "full.json", "--output", output / "cold")
        require(
            resumed["assessment"]
            == cold["assessment"]
            == "transient_interval_completed",
            "restart.assessment",
            "not accepted",
        )
        require(
            (output / "resumed/fields.json").read_bytes()
            == (output / "cold/fields.json").read_bytes(),
            "restart.fields",
            "states differ",
        )
        preview = cli(
            "preview",
            "preview",
            output / "full.json",
            "--output",
            output / "preview",
            "--factor",
            "2",
        )
        require(
            preview["model_scope"].startswith("preview:"),
            "preview",
            "preview label missing",
        )
        call(
            "vtk",
            [
                sys.executable,
                ROOT / "validation/export_vtk.py",
                "--run",
                output / "base",
                "--output",
                output / "base.vtr",
            ],
        )
        result.update(
            passed=True,
            R1_ug_m3=r1 * 1e9,
            scaled_R1_ug_m3=twice_r1 * 1e9,
            source_total_kg_s=tracer["source_rate_kg_s"],
            resumed_equals_cold=True,
            incomplete_archive_report_exit=0,
        )
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        StopIteration,
        subprocess.SubprocessError,
    ) as exc:
        result["error"] = (
            str(exc)
            if str(exc).startswith("CFD-")
            else f"CFD-U001 manual.execution: {exc}"
        )
    write(output / "report.json", result)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/cfd-craft")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        result = workflow(args.binary.resolve(), args.output)
    except (ValueError, OSError) as exc:
        result = dict(
            passed=False,
            error=str(exc)
            if str(exc).startswith("CFD-")
            else f"CFD-U001 manual.input: {exc}",
        )
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
