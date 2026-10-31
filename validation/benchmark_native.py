#!/usr/bin/env python3
"""Alternating paired native probes with fixed work and checked numerical results."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import statistics
import subprocess
import time

import numpy as np


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-B001 benchmark.{field}: {message}")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare(a, b, field="result"):
    """Counts/structure match exactly; finite floating values retain the frozen bound."""
    if isinstance(a, bool) or isinstance(b, bool):
        require(type(a) is type(b) and a == b, field, "boolean differs")
        return 0.0
    if type(a) is int and type(b) is int:
        require(a == b, field, "integer work/count differs")
        return 0.0
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        require(math.isfinite(a) and math.isfinite(b), field, "nonfinite value")
        error = abs(a - b)
        require(error <= 1e-13 + 1e-11 * max(abs(a), abs(b)), field, "value differs")
        return error
    if isinstance(a, dict) and isinstance(b, dict):
        require(a.keys() == b.keys(), field, "keys differ")
        return max((compare(a[k], b[k], field + "." + k) for k in a), default=0.0)
    if isinstance(a, list) and isinstance(b, list):
        require(len(a) == len(b), field, "length differs")
        if a and all(type(x) in (int, float) for x in a + b):
            left, right = np.asarray(a), np.asarray(b)
            require(
                np.isfinite(left).all() and np.isfinite(right).all(),
                field,
                "nonfinite array",
            )
            error = abs(left - right)
            require(
                np.all(error <= 1e-13 + 1e-11 * np.maximum(abs(left), abs(right))),
                field,
                "array differs",
            )
            return float(np.max(error))
        return max(
            (
                compare(x, y, f"{field}[{i}]")
                for i, (x, y) in enumerate(zip(a, b, strict=True))
            ),
            default=0.0,
        )
    require(type(a) is type(b) and a == b, field, "value/type differs")
    return 0.0


def compare_reports(a, b):
    for key in [
        "schema_version",
        "case_sha256",
        "case",
        "mode",
        "repetitions",
        "requested_steps",
        "threads",
        "cells",
        "faces",
    ]:
        require(a[key] == b[key], "compare." + key, "work or input identity differs")
    for side, row in [("baseline", a), ("candidate", b)]:
        require(
            row["schema_version"] == "cfd-craft.native-performance/0.1",
            side + ".schema",
            "unsupported",
        )
        require(
            len(row["wall_s"]) == row["repetitions"]
            and all(
                type(v) in (int, float) and math.isfinite(v) and v > 0
                for v in row["wall_s"]
            ),
            side + ".wall_s",
            "invalid timing samples",
        )
    error = compare(a["result"], b["result"])
    return {
        "passed": True,
        "exact_result": a["result_sha256"] == b["result_sha256"]
        and a["result"] == b["result"],
        "maximum_absolute_difference": error,
    }


def measure(binary, case, mode, inner, steps, threads, output, timeout_s):
    command = [
        str(Path(binary).resolve()),
        str(Path(case).resolve()),
        mode,
        str(inner),
        str(steps),
        str(threads),
        "json",
        str(output / "probe.json"),
    ]
    output.mkdir()

    def child_limits():
        resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024**3, 1024**3))

    began = time.monotonic()
    timed_out = False
    cancelled = False
    with (
        (output / "stdout.log").open("w") as stdout,
        (output / "stderr.log").open("w") as stderr,
    ):
        process = subprocess.Popen(
            command,
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"),
            start_new_session=True,
            preexec_fn=child_limits,
        )
        try:
            while True:
                pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                if time.monotonic() - began >= timeout_s:
                    timed_out = True
                    break
                time.sleep(0.02)
        except KeyboardInterrupt:
            cancelled = True
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if process.returncode is None:
                _, status, usage = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
    record = {
        "command": command,
        "return_code": process.returncode,
        "timeout": timed_out,
        "cancelled": cancelled,
        "child_wall_s": time.monotonic() - began,
        "child_cpu_s": usage.ru_utime + usage.ru_stime,
        "peak_rss_kib_linux": usage.ru_maxrss,
        "resource_scope": "entire fresh child including fixture and JSON I/O; not a production memory estimate",
    }
    (output / "process.json").write_text(json.dumps(record, indent=2) + "\n")
    require(
        not timed_out and not cancelled and process.returncode == 0,
        "child",
        f"failed; retained {output.name}",
    )
    report = json.loads((output / "probe.json").read_text())
    return report, record


def run_pair(
    baseline,
    candidate,
    case,
    mode,
    rounds,
    inner,
    steps,
    threads,
    output,
    timeout_s=180,
):
    for field, value, high in [
        ("rounds", rounds, 20),
        ("inner", inner, 1000),
        ("steps", steps, 1000),
        ("threads", threads, 64),
    ]:
        require(
            type(value) is int and 1 <= value <= high, field, "integer outside bounds"
        )
    require(
        type(timeout_s) in (int, float)
        and math.isfinite(timeout_s)
        and 0 < timeout_s <= 180,
        "timeout_s",
        "expected (0,180]",
    )
    require(
        mode in ["setup", "pressure", "momentum", "production", "transport", "steps"],
        "mode",
        "unsupported",
    )
    output = Path(output)
    require(not output.exists(), "output", "fresh path required")
    output.mkdir()
    binaries = {"baseline": Path(baseline), "candidate": Path(candidate)}
    identities = {k: sha(v) for k, v in binaries.items()}
    case_sha = sha(case)
    report = {
        "schema_version": "cfd-craft.paired-performance/0.1",
        "passed": False,
        "case_file_sha256": case_sha,
        "binary_sha256": identities,
        "mode": mode,
        "rounds": rounds,
        "inner_repetitions": inner,
        "steps": steps,
        "threads": threads,
        "samples": [],
        "physical_qualification": False,
        "runner_sha256": sha(__file__),
    }
    # Persist identities and requested work before launching either executable.
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    try:
        source_ids = {}
        # First pair warms filesystem/process startup; it is not a timing sample.
        for index in range(-1, rounds):
            reports = {}
            order = (
                ["baseline", "candidate"]
                if index % 2 == 0
                else ["candidate", "baseline"]
            )
            for label in order:
                require(
                    sha(binaries[label]) == identities[label] and sha(case) == case_sha,
                    "identity." + label,
                    "binary or case changed",
                )
                run, usage = measure(
                    binaries[label],
                    case,
                    mode,
                    inner,
                    steps,
                    threads,
                    output
                    / f"{'warmup' if index < 0 else f'round-{index:02d}'}-{label}",
                    timeout_s,
                )
                require(
                    sha(binaries[label]) == identities[label] and sha(case) == case_sha,
                    "identity." + label,
                    "binary or case changed during execution",
                )
                require(
                    sha(__file__) == report["runner_sha256"],
                    "runner",
                    "benchmark producer changed",
                )
                require(
                    label not in source_ids
                    or run["source_sha256"] == source_ids[label],
                    "source." + label,
                    "compiled producer changed",
                )
                source_ids[label] = run["source_sha256"]
                reports[label] = run
                if index >= 0:
                    times = run["wall_s"]
                    warm = (
                        times[1:]
                        if mode in ["pressure", "steps"] and len(times) > 1
                        else times
                    )
                    report["samples"].append(
                        {
                            "round": index,
                            "side": label,
                            "order": order,
                            "cold_s": times[0],
                            "warm_median_s": statistics.median(warm),
                            "kernel_wall_s": times,
                            "source_sha256": run["source_sha256"],
                            "result_sha256": run["result_sha256"],
                            **usage,
                        }
                    )
            checked = compare_reports(reports["baseline"], reports["candidate"])
            if index >= 0:
                report.setdefault("comparisons", []).append(checked)
            (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        report["summary"] = {}
        for label in binaries:
            samples = [
                s["warm_median_s"] for s in report["samples"] if s["side"] == label
            ]
            cold = [s["cold_s"] for s in report["samples"] if s["side"] == label]
            report["summary"][label] = {
                "median_s": statistics.median(samples),
                "minimum_s": min(samples),
                "maximum_s": max(samples),
                "cold_median_s": statistics.median(cold),
            }
        report["speedup"] = (
            report["summary"]["baseline"]["median_s"]
            / report["summary"]["candidate"]["median_s"]
        )
        report["passed"] = True
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        IndexError,
        subprocess.SubprocessError,
    ) as exc:
        report["error"] = (
            str(exc)
            if str(exc).startswith("CFD-")
            else "CFD-B001 benchmark.record: " + str(exc)
        )
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--case", type=Path, required=True)
    ap.add_argument(
        "--mode",
        choices=["setup", "pressure", "momentum", "production", "transport", "steps"],
        required=True,
    )
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--inner", type=int, default=4)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--timeout-s", type=float, default=180)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        report = run_pair(
            args.baseline,
            args.candidate,
            args.case,
            args.mode,
            args.rounds,
            args.inner,
            args.steps,
            args.threads,
            args.output,
            args.timeout_s,
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc))
        return 1
    print(
        json.dumps(
            {k: report.get(k) for k in ["passed", "speedup", "summary", "error"]},
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
