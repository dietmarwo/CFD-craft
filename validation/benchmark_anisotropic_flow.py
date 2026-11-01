#!/usr/bin/env python3
"""Accepted anisotropic cavity workflows, with steady and transient verdicts distinct."""

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import time

import benchmark_pressure as bp
import compare_backends as cmp
from check_fields import check as audit
from process_measure import measure

ROOT = Path(__file__).resolve().parents[1]
METHODS = ["ic0", "multigrid"]


def run_row(binary, mode, method, destination):
    destination.mkdir()
    began = time.monotonic()
    row = dict(mode=mode, method=method, valid=False, accepted=False)
    try:
        case = cmp.native_case("native-steady")
        case["grid"]["cells"] = [64, 2, 12]
        case["run"].update(
            mode=mode, end_time_s=1.0, wall_time_limit_s=600, max_steps=20000
        )
        if method == "multigrid":
            case["numerics"]["pressure_preconditioner"] = method
        input_file = destination / "input.json"
        bp.write(input_file, case)
        archive = destination / "run"
        row["input_sha256"] = bp.digest(input_file)
        row["measurement"] = measure(
            [binary, "run", input_file, "--output", archive],
            destination / "process",
            620,
        )
        bp.require(
            row["measurement"]["returncode"] in (0, 2)
            and not row["measurement"]["outer_timeout"],
            "anisotropic.execution",
            "child failed",
        )
        summary = json.loads((archive / "summary.json").read_text())
        manifest = json.loads((archive / "manifest.json").read_text())
        bp.require(
            json.loads((archive / "case.json").read_text()) == case,
            "anisotropic.case",
            "consumed case differs",
        )
        bp.require(
            manifest["input_case_sha256"]
            == row["input_sha256"]
            == bp.digest(input_file)
            and manifest["executable_sha256"] == bp.digest(binary),
            "anisotropic.producer",
            "input/binary identity differs",
        )
        verified = subprocess.run(
            [binary, "report", archive], capture_output=True, text=True, timeout=30
        )
        bp.require(
            verified.returncode in (0, 2),
            "anisotropic.archive",
            "archive does not verify",
        )
        try:
            checked = audit(archive)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            checked = dict(passed=False, error=str(exc))
        expected = (
            "steady_discrete_solution"
            if mode == "steady"
            else "transient_interval_completed"
        )
        accepted = (
            summary["assessment"] == expected
            and row["measurement"]["returncode"] == 0
            and checked["passed"]
        )
        row.update(
            valid=True,
            numerical_accepted=accepted,
            independent_check=checked,
            solver_s=summary["elapsed_s"],
            steps=summary["steps"],
            iterations=summary["pressure_iterations"],
            termination=summary["termination"],
            assessment=summary["assessment"],
            physical_time_s=summary["physical_time_s"],
            result_sha256=bp.digest(archive / "fields.json"),
            source_sha256=summary["source_sha256"],
            numerical_error=summary.get("error"),
        )
        if mode == "steady" and accepted:
            field = json.loads((archive / "fields.json").read_text())
            _, error = cmp.at_ghia_stations(*cmp.native_centerline(case, field))
            row.update(reference_error=error, reference_screen_passed=error <= 0.06)
            accepted = accepted and error <= 0.06
        row["accepted"] = accepted
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        AttributeError,
        OverflowError,
        subprocess.SubprocessError,
    ) as exc:
        row.update(error=str(exc), valid=False)
    row["workflow_s"] = time.monotonic() - began
    return row


def campaign(binary, output, rounds=3, modes=("steady", "transient")):
    binary = Path(binary).resolve()
    output = Path(output)
    output.mkdir()
    sources = [
        binary,
        Path(__file__),
        ROOT / "validation/benchmark_pressure.py",
        ROOT / "validation/compare_backends.py",
        ROOT / "validation/check_fields.py",
        ROOT / "validation/process_measure.py",
        ROOT / "tutorials/external_cfd.py",
        ROOT / "validation/ghia-re100-u.csv",
        ROOT / "cases/verification/lid-cavity.json",
    ]
    identities = {str(p): bp.digest(p) for p in sources}
    report = dict(
        schema_version="cfd-craft.anisotropic-flow/0.1",
        completed=False,
        workflow_valid=False,
        plan=dict(
            grid=[64, 2, 12],
            modes=list(modes),
            rounds=rounds,
            warmups=1,
            wall_s=600,
            max_steps=20000,
            transient_end_s=1.0,
            velocity_equivalence_bound=1e-8,
            pressure_equivalence_bound=1e-7,
            steady_ghia_screen=0.06,
            producer_sha256=identities,
            meaning="same discrete equations; transient interval completion is not a steady result",
        ),
        rows=[],
        results={},
    )
    bp.write(output / "report.json", report)
    for mode in modes:
        rows = []
        stopped = False
        for index in range(-1, rounds):
            destinations = {}
            order = METHODS if index % 2 == 0 else list(reversed(METHODS))
            for method in order:
                bp.require(
                    identities == {str(p): bp.digest(p) for p in sources},
                    "anisotropic.inputs",
                    "changed during campaign",
                )
                name = f"{mode}-{'warmup' if index < 0 else index}-{method}"
                dest = output / name
                row = run_row(binary, mode, method, dest)
                row.update(directory=name, warmup=index < 0, round=index)
                destinations[method] = dest
                rows.append(row)
                report["rows"].append(row)
                bp.write(output / "report.json", report)
                print(
                    name,
                    row["accepted"],
                    row.get("solver_s"),
                    row.get("error"),
                    flush=True,
                )
            if all(r["accepted"] for r in rows[-2:]):
                try:
                    errors = bp.equivalent_fields(
                        destinations["ic0"], destinations["multigrid"]
                    )
                    for r in rows[-2:]:
                        r["equivalence_max_abs"] = errors
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    for r in rows[-2:]:
                        r.update(accepted=False, equivalence_error=str(exc))
            if index < 0 and not all(r["accepted"] for r in rows):
                stopped = True
                break
        groups = {}
        for method in METHODS:
            all_rows = [r for r in rows if r["method"] == method]
            timed = [r for r in all_rows if not r["warmup"]]
            qualified = len(timed) == rounds and all(r["accepted"] for r in all_rows)
            if qualified:
                qualified = (
                    len(
                        {
                            (
                                r["steps"],
                                r["iterations"],
                                r["result_sha256"],
                                r["source_sha256"],
                            )
                            for r in all_rows
                        }
                    )
                    == 1
                )
            group = dict(qualifying=qualified, timed_rows=len(timed))
            if qualified:
                group.update(
                    solver_s=statistics.median(r["solver_s"] for r in timed),
                    workflow_s=statistics.median(r["workflow_s"] for r in timed),
                    steps=timed[0]["steps"],
                    iterations=timed[0]["iterations"],
                    reference_error=timed[0].get("reference_error"),
                )
            groups[method] = group
        ratio = {
            key: groups["ic0"][key] / groups["multigrid"][key]
            if all(g["qualifying"] for g in groups.values())
            else None
            for key in ["solver_s", "workflow_s"]
        }
        report["results"][mode] = dict(
            groups=groups,
            ic0_over_multigrid=ratio,
            stopped_after_unaccepted_warmup=stopped,
        )
        bp.write(output / "report.json", report)
    report.update(
        completed=True,
        workflow_valid=all(r["valid"] for r in report["rows"]),
        passed=all(
            g["qualifying"]
            for result in report["results"].values()
            for g in result["groups"].values()
        ),
    )
    bp.require(
        identities == {str(p): bp.digest(p) for p in sources},
        "anisotropic.inputs",
        "changed during campaign",
    )
    bp.write(output / "report.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/cfd-craft")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument(
        "--modes",
        choices=["steady", "transient"],
        nargs="+",
        default=["steady", "transient"],
    )
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        bp.require(1 <= args.rounds <= 5, "anisotropic.rounds", "use 1..5")
        bp.require(
            len(set(args.modes)) == len(args.modes),
            "anisotropic.modes",
            "distinct modes required",
        )
        r = campaign(args.binary, args.output, args.rounds, args.modes)
    except (ValueError, OSError) as exc:
        print(str(exc))
        return 1
    return 1 if not r["workflow_valid"] else 0 if r["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
