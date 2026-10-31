#!/usr/bin/env python3
"""Paired IC(0)/multigrid pressure and accepted cavity measurements.

One unscored pair precedes alternating timed pairs. Failed rows stay in report.json.
Kernel setup/cold and reused solves have separate timers; coupled runs use the
unchanged scientific gates. This is not an OpenFOAM or physical-validation claim.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import time

import numpy as np

import compare_backends as cmp
from check_fields import check as audit
from process_measure import measure

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "cfd-craft.pressure-performance/0.1"
METHODS = ["ic0", "multigrid"]
KERNELS = {
    "cavity24": [24, 2, 24],
    "cavity48": [48, 2, 48],
    "cavity96": [96, 2, 96],
    "cube24": [24, 24, 24],
    "cube48": [48, 48, 48],
}


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-B005 pressure_benchmark.{field}: {message}")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite(value, field, positive=False):
    require(
        type(value) in (int, float)
        and math.isfinite(value)
        and (value > 0 if positive else value >= 0),
        field,
        "invalid finite numeric value",
    )
    return value


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def run_row(binary, probe, shape, method, mode, destination):
    destination.mkdir()
    began = time.monotonic()
    row = dict(method=method, mode=mode, grid=shape, passed=False, error=None)
    try:
        case = cmp.native_case("native-steady")
        case["grid"]["cells"] = shape
        case["run"].update(wall_time_limit_s=600, max_steps=20000)
        if method == "multigrid":
            case["numerics"]["pressure_preconditioner"] = method
        input_file = destination / "input.json"
        write(input_file, case)
        row["input_sha256"] = digest(input_file)
        if mode == "kernel":
            result = destination / "probe.json"
            command = [probe, input_file, "pressure", "4", "1", "1", "json", result]
            row["measurement"] = measure(command, destination / "process", 200)
            require(
                row["measurement"]["returncode"] == 0,
                "kernel.execution",
                "child failed",
            )
            p = json.loads(result.read_text())
            require(p["case"] == case, "kernel.case", "consumed case differs")
            require(
                p["mode"] == "pressure" and p["repetitions"] == 4 and p["threads"] == 1,
                "kernel.work",
                "different work",
            )
            times = p["wall_s"]
            require(len(times) == 4, "kernel.samples", "missing timings")
            for t in times:
                finite(t, "kernel.wall_s", positive=True)
            r = p["result"]
            require(
                type(r["iterations"]) is int and r["iterations"] > 0,
                "kernel.iterations",
                "positive integer required",
            )
            finite(r["true_relative_residual"], "kernel.residual")
            finite(r["rms_manufactured_error"], "kernel.error")
            require(
                r["true_relative_residual"] <= 1.01e-10
                and r["rms_manufactured_error"] <= 1e-8,
                "kernel.accuracy",
                "unchanged recovery bounds failed",
            )
            values = np.asarray(r["values"], dtype=float)
            require(
                values.size == math.prod(shape) and np.isfinite(values).all(),
                "kernel.values",
                "invalid returned pressure",
            )
            # Independent manufactured field, cell ordering and closed gauge.
            nx, ny, nz = shape
            x = (np.arange(nx) + 0.5) / nx
            z = (np.arange(nz) + 0.5) / nz
            exact = (
                np.broadcast_to(
                    np.sin(2 * np.pi * x)[None, None, :]
                    + 0.3 * np.cos(4 * np.pi * z)[:, None, None],
                    (nz, ny, nx),
                )
                .copy()
                .ravel()
            )
            exact -= exact.mean()
            error = float(np.sqrt(np.mean((values - exact) ** 2)))
            require(error <= 1e-8, "kernel.independent_error", "recovery bound failed")
            row.update(
                cold_s=times[0],
                reused_s=statistics.median(times[1:]),
                source_sha256=p["source_sha256"],
                result_sha256=p["result_sha256"],
                iterations=r["iterations"],
                true_relative_residual=r["true_relative_residual"],
                rms_manufactured_error=error,
                hierarchy=p["pressure_multigrid"],
            )
        else:
            archive = destination / "run"
            row["measurement"] = measure(
                [binary, "run", input_file, "--output", archive],
                destination / "process",
                620,
            )
            require(
                row["measurement"]["returncode"] in (0, 2),
                "cavity.execution",
                "child failed",
            )
            summary = json.loads((archive / "summary.json").read_text())
            manifest = json.loads((archive / "manifest.json").read_text())
            consumed = json.loads((archive / "case.json").read_text())
            require(consumed == case, "cavity.case", "consumed case differs")
            require(
                manifest["input_case_sha256"] == digest(input_file)
                and manifest["executable_sha256"] == digest(binary),
                "cavity.producer",
                "input/binary identity differs",
            )
            checked = subprocess.run(
                [binary, "report", archive], capture_output=True, text=True, timeout=30
            )
            row["archive_verified"] = checked.returncode == 0
            independent = audit(archive)
            field = json.loads((archive / "fields.json").read_text())
            predicted, error = cmp.at_ghia_stations(*cmp.native_centerline(case, field))
            row.update(
                numerical_accepted=summary["assessment"] == "steady_discrete_solution",
                independent_check=independent,
                reference_error=error,
                predicted_u=list(map(float, predicted)),
                steps=summary["steps"],
                iterations=summary["pressure_iterations"],
                termination=summary["termination"],
                solver_s=summary["elapsed_s"],
                source_sha256=summary["source_sha256"],
                case_sha256=summary["case_sha256"],
                result_sha256=digest(archive / "fields.json"),
            )
            require(
                row["measurement"]["returncode"] == 0
                and row["numerical_accepted"]
                and row["archive_verified"]
                and independent["passed"]
                and error <= 0.06,
                "cavity.acceptance",
                "numerical/archive/audit/reference gate failed",
            )
        require(not row["measurement"]["outer_timeout"], "execution", "outer timeout")
        require(
            row["input_sha256"] == digest(input_file), "input", "changed during run"
        )
        row["passed"] = True
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        OverflowError,
        AttributeError,
        subprocess.SubprocessError,
    ) as exc:
        row["error"] = str(exc)
    row["workflow_s"] = time.monotonic() - began
    return row


def equivalent_fields(left, right):
    a = json.loads((left / "run/fields.json").read_text())
    b = json.loads((right / "run/fields.json").read_text())
    errors = {}
    for field, bound in [("velocity", 1e-8), ("pressure", 1e-7)]:
        x, y = np.asarray(a[field]), np.asarray(b[field])
        require(
            x.shape == y.shape and np.isfinite(x).all() and np.isfinite(y).all(),
            "equivalence.fields",
            "invalid returned arrays",
        )
        errors[field] = float(np.max(np.abs(x - y)))
        require(
            errors[field] <= bound,
            "equivalence." + field,
            f"field difference {errors[field]} exceeds {bound}",
        )
    return errors


def summarize(rows, mode, rounds):
    groups = {}
    for method in METHODS:
        all_rows = [r for r in rows if r["method"] == method]
        timed = [r for r in all_rows if not r["warmup"]]
        valid = len(timed) == rounds and all(r["passed"] for r in all_rows)
        repeat = (
            valid
            and len(
                {
                    (r["iterations"], r["result_sha256"], r["source_sha256"])
                    for r in all_rows
                }
            )
            == 1
        )
        groups[method] = dict(
            qualifying=bool(valid and repeat),
            accepted=sum(r["passed"] for r in timed),
            timed_rows=len(timed),
        )
        if groups[method]["qualifying"]:
            keys = (
                ["cold_s", "reused_s"]
                if mode == "kernel"
                else ["solver_s", "workflow_s"]
            )
            for key in keys:
                for r in timed:
                    finite(r[key], key, positive=True)
                groups[method][key] = statistics.median(r[key] for r in timed)
            peaks = [r["measurement"]["peak_rss_kib_linux"] for r in timed]
            groups[method]["peak_rss_kib_linux"] = (
                max(peaks) if all(p is not None for p in peaks) else None
            )
            groups[method]["iterations"] = timed[0]["iterations"]
            if mode == "kernel":
                groups[method]["hierarchy"] = timed[0]["hierarchy"]
            else:
                groups[method].update(
                    steps=timed[0]["steps"], reference_error=timed[0]["reference_error"]
                )
    keys = ["cold_s", "reused_s"] if mode == "kernel" else ["solver_s", "workflow_s"]
    ratios = {
        key: groups["ic0"][key] / groups["multigrid"][key]
        if all(g["qualifying"] for g in groups.values())
        else None
        for key in keys
    }
    return dict(groups=groups, ic0_over_multigrid=ratios)


def campaign(binary, probe, output, mode, grids, rounds):
    output.mkdir()
    binary, probe = binary.resolve(), probe.resolve()
    identities = {
        str(p): digest(p)
        for p in [
            binary,
            probe,
            Path(__file__),
            ROOT / "cases/verification/lid-cavity.json",
            ROOT / "validation/ghia-re100-u.csv",
            ROOT / "validation/process_measure.py",
            ROOT / "validation/check_fields.py",
            ROOT / "tutorials/external_cfd.py",
            ROOT / "validation/compare_backends.py",
        ]
    }
    report = dict(
        schema_version=SCHEMA,
        passed=False,
        host=dict(
            platform=platform.platform(),
            machine=platform.machine(),
            processor=platform.processor(),
        ),
        rounds=rounds,
        producer_sha256=identities,
        rows=[],
        results={},
        physical_qualification=False,
        protocol=dict(
            threads=1,
            native_wall_s=600,
            max_steps=20000,
            pressure_tolerance=1e-11,
            kernel_repeats=4,
            velocity_equivalence_bound=1e-8,
            pressure_equivalence_bound=1e-7,
            reference_screen=0.06,
            warmup_pairs=1,
        ),
    )
    write(output / "report.json", report)
    try:
        tasks = []
        if mode in ("kernel", "all"):
            tasks += [("kernel", label, n) for label, n in KERNELS.items()]
        if mode in ("cavity", "all"):
            tasks += [("cavity", f"cavity{g}", [g, 2, g]) for g in grids]
        for kind, label, shape in tasks:
            group = []
            for round_index in range(rounds + 1):
                order = METHODS if round_index % 2 == 0 else list(reversed(METHODS))
                destinations = {}
                for method in order:
                    name = f"{kind}-{label}-r{round_index}-{method}"
                    dest = output / name
                    row = run_row(binary, probe, shape, method, kind, dest)
                    row.update(
                        directory=name, warmup=round_index == 0, round=round_index
                    )
                    report["rows"].append(row)
                    group.append(row)
                    destinations[method] = dest
                    write(output / "report.json", report)
                    print(
                        f"{name}: passed={row['passed']} error={row['error']}",
                        flush=True,
                    )
                if kind == "cavity" and all(r["passed"] for r in group[-2:]):
                    try:
                        errors = equivalent_fields(
                            destinations["ic0"], destinations["multigrid"]
                        )
                        for row in group[-2:]:
                            row["equivalence_max_abs"] = errors
                    except (ValueError, OSError, KeyError, TypeError) as exc:
                        for row in group[-2:]:
                            row.update(passed=False, error=str(exc))
                    write(output / "report.json", report)
            report["results"][kind + "-" + label] = summarize(group, kind, rounds)
            write(output / "report.json", report)
        require(
            identities == {p: digest(p) for p in identities},
            "producer",
            "changed during campaign",
        )
        report["passed"] = all(row["passed"] for row in report["rows"]) and all(
            g["qualifying"]
            for r in report["results"].values()
            for g in r["groups"].values()
        )
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
        report["error"] = str(exc)
    write(output / "report.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/cfd-craft")
    ap.add_argument(
        "--probe", type=Path, default=ROOT / "target/release/examples/performance_probe"
    )
    ap.add_argument("--mode", choices=["kernel", "cavity", "all"], default="all")
    ap.add_argument("--grids", type=int, nargs="+", default=[24, 48])
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        require(1 <= args.rounds <= 20, "rounds", "use 1..20 timed pairs")
        require(
            all(g in (24, 48, 72, 96) for g in args.grids), "grids", "use 24/48/72/96"
        )
        r = campaign(
            args.binary, args.probe, args.output, args.mode, args.grids, args.rounds
        )
    except (ValueError, OSError) as exc:
        print(str(exc))
        return 1
    return 0 if r["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
