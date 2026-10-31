#!/usr/bin/env python3
"""Balanced rough-pressure comparison; incomplete and inaccurate rows stay visible."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics

import numpy as np
from process_measure import measure

ROOT = Path(__file__).resolve().parents[1]
METHODS = ["ic0", "point_mg", "candidate_mg"]
SHAPES = {
    "isotropic": ([24, 2, 24], [1.0, 1.0, 1.0], "wall"),
    "near-isotropic": ([96, 2, 24], [4.0, 0.1, 1.0], "wall"),
    "threshold25": ([64, 2, 64], [1.0, 0.1, 0.2], "wall"),
    "thin100": ([64, 2, 64], [1.0, 0.1, 0.1], "wall"),
    "thin400": ([64, 2, 64], [1.0, 0.1, 0.05], "wall"),
    "cube100": ([48, 48, 48], [1.0, 1.0, 0.1], "wall"),
    "slab100": ([32, 32, 16], [1.0, 1.0, 0.05], "wall"),
    "plate64": ([64, 8, 64], [1.0, 1.0, 1.0], "wall"),
    "plate256": ([64, 16, 64], [1.0, 4.0, 1.0], "wall"),
    "thin1600": ([64, 8, 64], [1.0, 1.0, 0.2], "wall"),
    "thin6400": ([64, 8, 64], [1.0, 1.0, 0.1], "wall"),
    "review-stretched": ([64, 8, 64], [1.0, 1.0, 0.02], "wall"),
    "odd": ([33, 5, 17], [1.0, 1.0, 0.1], "wall"),
    "periodic": ([31, 5, 17], [0.05, 1.0, 1.0], "periodic"),
    "outlet": ([33, 5, 17], [1.0, 1.0, 0.1], "open"),
    "stiff-two-cell": ([32, 2, 32], [1.0, 0.001, 1.0], "wall"),
    "long-domain": ([128, 2, 16], [100.0, 1.0, 1.0], "wall"),
    "short-stiff-axis": ([64, 64, 8], [1.0, 1.0, 0.01], "wall"),
}
SCHEMA = "cfd-craft.anisotropy-performance/0.1"
TOL = 1e-14
REPEATS = 2


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-B006 pressure_suite.{field}: {message}")


def number(value, field, integer=False, positive=False):
    try:
        valid = (
            (type(value) is int if integer else type(value) in (int, float))
            and math.isfinite(value)
            and (value > 0 if positive else value >= 0)
        )
    except OverflowError:
        valid = False
    require(valid, field, "invalid finite numeric value")
    return value


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def case_for(label, method):
    n, size, boundary = SHAPES[label]
    c = json.loads((ROOT / "cases/verification/lid-cavity.json").read_text())
    c["grid"]["cells"] = n
    c["domain"]["size_m"] = size
    c["boundaries"]["x"] = boundary
    c["run"].update(threads=1, memory_limit_mib=2048)
    c["numerics"].update(pressure_relative_tolerance=TOL, pressure_max_iterations=1200)
    c["moving_walls"] = []
    if boundary == "open":
        c["flow"]["initial_velocity_m_s"] = [1.0, 0.0, 0.0]
    if method != "ic0":
        c["numerics"]["pressure_preconditioner"] = "multigrid"
    return c


def audit_probe(p, case):
    require(
        p["schema_version"] == "cfd-craft.anisotropic-pressure/0.1",
        "schema",
        "unsupported",
    )
    require(p["case"] == case, "case", "consumed case differs")
    require(
        type(p["threads"]) is int and p["threads"] == 1,
        "threads",
        "different thread count",
    )
    require(
        p["repetitions"] == REPEATS
        and type(p["repetitions"]) is int
        and p["tolerance"] == TOL
        and type(p["max_iterations"]) is int
        and p["max_iterations"] == 1200,
        "limits",
        "different requested work",
    )
    require(type(p["passed"]) is bool, "passed", "boolean required")
    source = p["source_sha256"]
    require(
        type(source) is str
        and len(source) == 64
        and all(c in "0123456789abcdef" for c in source),
        "source",
        "invalid source fingerprint",
    )
    samples = p["samples"]
    require(
        type(samples) is list and 1 <= len(samples) <= REPEATS,
        "samples",
        "missing samples",
    )
    complete = len(samples) == REPEATS and all(s["error"] is None for s in samples)
    require(p["passed"] == complete, "passed", "completion verdict differs")
    for sample in samples:
        number(sample["wall_s"], "sample.wall_s", positive=True)
        phase = sample["profile"]["phases"]["pressure_solve"]
        for key in [
            "work_units",
            "operator_applications",
            "preconditioner_applications",
            "true_residual_checks",
        ]:
            number(phase[key], "sample." + key, integer=True)
        require(
            phase["operator_applications"]
            == phase["work_units"] + phase["true_residual_checks"],
            "work",
            "operator accounting differs",
        )
        if sample["error"] is None:
            number(sample["iterations"], "iterations", integer=True, positive=True)
            require(
                sample["iterations"] == phase["work_units"],
                "work",
                "iteration accounting differs",
            )
            number(sample["true_relative_residual"], "true_residual")
            number(sample["rms_error"], "rms_error")
    row = dict(
        valid=True,
        accepted=False,
        numerical_completed=complete,
        source_sha256=source,
        attempted_iterations=[
            s["profile"]["phases"]["pressure_solve"]["work_units"] for s in samples
        ],
        errors=[s["error"] for s in samples if s["error"] is not None],
        hierarchy=p["hierarchy"],
    )
    if not complete:
        # A pre-failure successful sample is not the returned final pressure.
        return row
    require(
        len({s["iterations"] for s in samples}) == 1
        and len({s["result_sha256"] for s in samples}) == 1,
        "repetitions",
        "results/work differ",
    )
    values = np.asarray(p["result"]["values"], dtype=float)
    count = math.prod(case["grid"]["cells"])
    require(
        values.shape == (count,) and np.isfinite(values).all(),
        "values",
        "invalid returned pressure",
    )
    i = np.arange(count, dtype=float)
    exact = np.sin(0.73 * i) + 0.3 * np.cos(0.17 * i)
    if case["boundaries"]["x"] != "open":
        exact -= exact.mean()
    error = float(np.sqrt(np.mean((values - exact) ** 2)))
    residual = max(s["true_relative_residual"] for s in samples)
    passed = (
        error <= 1e-8
        and residual <= 1.1e-12
        and all(s["rms_error"] <= 1e-8 for s in samples)
    )
    row.update(
        accepted=passed,
        independent_rms_error=error,
        true_relative_residual=residual,
        iterations=samples[-1]["iterations"],
        result_sha256=p["result"]["result_sha256"],
        cold_s=samples[0]["wall_s"],
        reused_s=samples[1]["wall_s"],
    )
    if not passed:
        row["errors"].append("independent recovery/residual bound missed")
    require(
        type(row["result_sha256"]) is str
        and len(row["result_sha256"]) == 64
        and all(c in "0123456789abcdef" for c in row["result_sha256"]),
        "result",
        "invalid result fingerprint",
    )
    require(
        all(s["result_sha256"] == row["result_sha256"] for s in samples),
        "result",
        "sample/final identity differs",
    )
    return row


def summary(rows, rounds):
    groups = {}
    for method in METHODS:
        all_rows = [r for r in rows if r["method"] == method]
        timed = [r for r in all_rows if not r["warmup"]]
        qualifying = len(timed) == rounds and all(
            r.get("accepted", False) for r in all_rows
        )
        if qualifying:
            qualifying = (
                len(
                    {
                        (r["iterations"], r["result_sha256"], r["source_sha256"])
                        for r in all_rows
                    }
                )
                == 1
            )
        group = dict(
            qualifying=qualifying,
            accepted=sum(r.get("accepted", False) for r in timed),
            rows=len(timed),
        )
        if qualifying:
            for key in ["cold_s", "reused_s"]:
                group[key] = statistics.median(r[key] for r in timed)
            group.update(
                iterations=timed[0]["iterations"],
                rms_error=max(r["independent_rms_error"] for r in timed),
                hierarchy=timed[0]["hierarchy"],
            )
            peaks = [r["measurement"]["peak_rss_kib_linux"] for r in timed]
            group["peak_rss_kib_linux"] = (
                max(peaks) if all(v is not None for v in peaks) else None
            )
        groups[method] = group
    ratios = {
        method: groups[method]["reused_s"] / groups["candidate_mg"]["reused_s"]
        if groups[method]["qualifying"] and groups["candidate_mg"]["qualifying"]
        else None
        for method in ["ic0", "point_mg"]
    }
    return dict(groups=groups, reused_speedup=ratios)


def campaign(baseline, candidate, output, labels, rounds):
    baseline, candidate = Path(baseline).resolve(), Path(candidate).resolve()
    output = Path(output)
    output.mkdir()
    producers = [
        baseline,
        candidate,
        Path(__file__),
        ROOT / "validation/process_measure.py",
        ROOT / "cases/verification/lid-cavity.json",
    ]
    identities = {str(p): digest(p) for p in producers}
    report = dict(
        schema_version=SCHEMA,
        completed=False,
        workflow_valid=False,
        candidate_passed=False,
        plan=dict(
            labels=labels,
            rounds=rounds,
            warmups=1,
            inner_solves=REPEATS,
            tolerance=TOL,
            max_iterations=1200,
            rms_recovery_bound=1e-8,
            true_residual_bound=1.1e-12,
            producer_sha256=identities,
            host=platform.platform(),
            meaning="rough manufactured pressure, not accepted flow; baseline core main plus the shared probe and an unused empty line.rs source marker",
        ),
        rows=[],
        results={},
    )
    write(output / "report.json", report)
    for label in labels:
        block = []
        for index in range(-1, rounds):
            order = (
                METHODS if index < 0 else METHODS[index % 3 :] + METHODS[: index % 3]
            )
            for method in order:
                name = f"{label}-{'warmup' if index < 0 else index}-{method}"
                dest = output / name
                dest.mkdir()
                row = dict(
                    shape=label,
                    method=method,
                    warmup=index < 0,
                    round=index,
                    directory=name,
                    valid=False,
                    accepted=False,
                )
                try:
                    require(
                        identities == {str(p): digest(p) for p in producers},
                        "producer",
                        "changed during campaign",
                    )
                    case = case_for(label, method)
                    input_file = dest / "input.json"
                    write(input_file, case)
                    result = dest / "probe.json"
                    exe = baseline if method == "point_mg" else candidate
                    row["input_sha256"] = digest(input_file)
                    row["measurement"] = measure(
                        [exe, input_file, str(REPEATS), str(TOL), "1200", result],
                        dest / "process",
                        200,
                    )
                    require(
                        row["measurement"]["returncode"] == 0
                        and not row["measurement"]["outer_timeout"],
                        "execution",
                        "probe did not return a measurement",
                    )
                    p = json.loads(result.read_text())
                    row.update(audit_probe(p, case))
                    require(
                        row["input_sha256"] == digest(input_file),
                        "input",
                        "changed during child",
                    )
                except (
                    ValueError,
                    OSError,
                    KeyError,
                    TypeError,
                    AttributeError,
                    OverflowError,
                ) as exc:
                    row.update(valid=False, error=str(exc))
                report["rows"].append(row)
                block.append(row)
                write(output / "report.json", report)
                print(
                    name,
                    row["accepted"],
                    row.get("errors", row.get("error")),
                    flush=True,
                )
        report["results"][label] = summary(block, rounds)
        write(output / "report.json", report)
    report.update(
        completed=True,
        workflow_valid=all(r["valid"] for r in report["rows"]),
        candidate_passed=all(
            g["groups"]["candidate_mg"]["qualifying"]
            for g in report["results"].values()
        ),
    )
    if identities != {str(p): digest(p) for p in producers}:
        report.update(
            workflow_valid=False,
            error="CFD-B006 pressure_suite.producer: changed during campaign",
        )
    write(output / "report.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline-probe", type=Path, required=True)
    ap.add_argument(
        "--candidate-probe",
        type=Path,
        default=ROOT / "target/release/examples/pressure_probe",
    )
    ap.add_argument("--shapes", nargs="+", choices=list(SHAPES), default=list(SHAPES))
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        require(1 <= args.rounds <= 5, "rounds", "use 1..5 timed repetitions")
        require(
            len(set(args.shapes)) == len(args.shapes),
            "shapes",
            "distinct shapes required",
        )
        r = campaign(
            args.baseline_probe,
            args.candidate_probe,
            args.output,
            args.shapes,
            args.rounds,
        )
    except (ValueError, OSError) as exc:
        print(str(exc))
        return 1
    return 1 if not r["workflow_valid"] else 0 if r["candidate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
