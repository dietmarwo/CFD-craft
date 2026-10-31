#!/usr/bin/env python3
"""Same-host timing of the lid-driven cavity with the native solver and OpenFOAM.

Three accepted workflows are timed on one machine, one solver thread each:
the generated OpenFOAM cavity recipe (steady SIMPLE), and the native
`cases/verification/lid-cavity.json` in steady mode and in its transient mode
to 30 s. One unscored warmup per method precedes the timed rounds; the rounds
use every order of the three methods, so each method runs first, second and
last equally often.

Every run must pass its own numerical and independent checks and the frozen
0.06 lid-speed Ghia centerline screen, and each method must repeat its work and
sampled profile exactly in every round. The ratios describe these configured
workflows: the grids, discretizations, pressure algorithms and stopping rules
differ, so they are not equal discrete work.

    python validation/compare_backends.py --foam-root ROOT --output runs/compare
"""

import argparse
import hashlib
import itertools
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tutorials"), str(ROOT / "integrations")]
import openfoam_backend as backend
from common import accepted, run_case
from external_cfd import at_ghia_stations, native_centerline, openfoam_centerline

SCHEMA = "cfd-craft.backend-performance/0.2"
METHODS = ["openfoam-steady", "native-steady", "native-transient"]
REFERENCE_TARGET = 0.06
CASE = ROOT / "cases/verification/lid-cavity.json"
PRODUCERS = [
    Path(__file__),
    CASE,
    ROOT / "tutorials/common.py",
    ROOT / "tutorials/external_cfd.py",
    ROOT / "validation/check_fields.py",
    ROOT / "integrations/openfoam_backend.py",
    ROOT / "integrations/openfoam_cases.py",
    ROOT / "validation/ghia-re100-u.csv",
]


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-B002 comparison.{field}: {message}")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def name(path):
    """Repository-relative name of an input; the file name outside the repository."""
    path = Path(path).resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name


def native_case(method):
    """The repository cavity with one thread; steady mode changes only run.mode."""
    case = json.loads(CASE.read_text())
    case["run"]["threads"] = 1
    if method == "native-steady":
        case["run"]["mode"] = "steady"
    return case


def run_method(method, destination, binary, foam_root, timeout_s):
    """One timed workflow; returns its measurement or raises a coded error.

    The timer encloses preparation, the solve, the independent audit and the
    centerline evaluation. For OpenFOAM it also encloses meshing, the mesh
    check, sampling, the runtime check and archive verification.
    """
    destination.mkdir()
    began = time.monotonic()
    if method == "openfoam-steady":
        backend.prepare("cavity", 1, 3000, destination / "input")
        r = backend.run(
            destination / "input", destination / "run", foam_root, timeout_s=timeout_s
        )
        require(r["passed"], f"{method}.run", f"not accepted: {r.get('error')}")
        checked = backend.verify(destination / "run")
        predicted, error = at_ghia_stations(
            *openfoam_centerline(destination / "run", checked)
        )
        workflow = time.monotonic() - began
        solver = [c["wall_s"] for c in r["commands"] if c["program"] == "foamRun"]
        require(len(solver) == 1, f"{method}.commands", "expected one foamRun")
        row = dict(
            solver_timer="foamRun process wall time (startup, case reading, writing)",
            solver_s=solver[0],
            steps=r["numerical"]["iterations"],
            cells=r["case_metadata"]["cells"],
            assessment="steady; external residual and flux gates passed",
            runtime_identity=hashlib.sha256(
                json.dumps(r["runtime"], sort_keys=True).encode()
            ).hexdigest(),
        )
    else:
        case = native_case(method)
        r = run_case(binary, case, destination / "run")
        require(
            accepted(r),
            f"{method}.run",
            f"not accepted: {(r['summary'] or {}).get('assessment')}",
        )
        field = json.loads((destination / "run/fields.json").read_text())
        predicted, error = at_ghia_stations(*native_centerline(case, field))
        workflow = time.monotonic() - began
        summary = r["summary"]
        row = dict(
            solver_timer="native solver timer (elapsed_s; excludes process start)",
            solver_s=summary["elapsed_s"],
            steps=summary["steps"],
            cells=summary["fluid_cells"],
            pressure_iterations=summary["pressure_iterations"],
            physical_time_s=summary["physical_time_s"],
            momentum_residual=summary["momentum_residual"],
            assessment=summary["assessment"],
            source_sha256=summary["source_sha256"],
        )
        backend.write_json(destination / "native-result.json", r)
    require(
        bool(np.isfinite(error)) and error <= REFERENCE_TARGET,
        f"{method}.reference_error",
        f"{error} exceeds the frozen target {REFERENCE_TARGET}",
    )
    row.update(
        method=method,
        workflow_s=workflow,
        reference_error=error,
        predicted_u=[float(v) for v in predicted],
        run_directory=destination.name,
    )
    backend.write_json(destination / "measurement.json", row)
    return row


def summarize(rounds):
    """Per-method medians and ranges; native/OpenFOAM ratios two ways."""
    summary = {}
    for method in METHODS:
        rows = [
            next(m for m in r["measurements"] if m["method"] == method) for r in rounds
        ]
        require(
            len({r["steps"] for r in rows}) == 1,
            f"{method}.steps",
            "work differs between rounds",
        )
        require(
            all(r["predicted_u"] == rows[0]["predicted_u"] for r in rows),
            f"{method}.predicted_u",
            "profile differs between rounds",
        )
        identity = "runtime_identity" if method == METHODS[0] else "source_sha256"
        require(
            len({r[identity] for r in rows}) == 1,
            f"{method}.{identity}",
            "producer differs between rounds",
        )
        times = [r["workflow_s"] for r in rows]
        solver = [r["solver_s"] for r in rows]
        summary[method] = dict(
            workflow_median_s=statistics.median(times),
            workflow_min_s=min(times),
            workflow_max_s=max(times),
            solver_median_s=statistics.median(solver),
            solver_timer=rows[0]["solver_timer"],
            steps=rows[0]["steps"],
            cells=rows[0]["cells"],
            reference_error=rows[0]["reference_error"],
            assessment=rows[0]["assessment"],
        )
    ratios = {}
    for method in METHODS[1:]:
        within = [
            next(m for m in r["measurements"] if m["method"] == method)["workflow_s"]
            / next(m for m in r["measurements"] if m["method"] == METHODS[0])[
                "workflow_s"
            ]
            for r in rounds
        ]
        ratios[method] = dict(
            workflow_ratio_of_medians=summary[method]["workflow_median_s"]
            / summary[METHODS[0]]["workflow_median_s"],
            workflow_median_within_round=statistics.median(within),
            solver_ratio_of_medians=summary[method]["solver_median_s"]
            / summary[METHODS[0]]["solver_median_s"],
        )
    return summary, ratios


def compare(binary, foam_root, output, repeats=1, timeout_s=180, runner=run_method):
    require(type(repeats) is int and 1 <= repeats <= 5, "repeats", "expected 1..5")
    require(
        type(timeout_s) in (int, float) and 0 < timeout_s <= 600,
        "timeout_s",
        "expected (0,600]",
    )
    for field, path in [("binary", binary), ("foam_root", foam_root)]:
        require(Path(path).exists(), field, f"not found: {path}")
    output = Path(output)
    backend.claim_directory(output)
    inputs = [Path(binary), *PRODUCERS]
    orders = [list(p) for p in itertools.permutations(METHODS)] * repeats
    report = dict(
        schema_version=SCHEMA,
        passed=False,
        plan=dict(
            methods=METHODS,
            orders=orders,
            warmups_per_method=1,
            threads_per_solver=1,
            timeout_s=timeout_s,
            reference_target_lid_speed=REFERENCE_TARGET,
            input_sha256={name(p): digest(p) for p in inputs},
            environment=dict(
                platform=platform.platform(),
                processor=platform.processor(),
                cpu_count=os.cpu_count(),
                python=platform.python_version(),
                OMP_NUM_THREADS=os.environ.get("OMP_NUM_THREADS"),
                OPENBLAS_NUM_THREADS=os.environ.get("OPENBLAS_NUM_THREADS"),
            ),
            meaning="configured, accepted workflows; not equal discrete work or identical stopping rules",
        ),
        warmups=[],
        rounds=[],
        physical_qualification=False,
    )
    path = output / "report.json"
    backend.write_json(path, report)
    try:
        for method in METHODS:
            report["warmups"].append(
                runner(
                    method, output / f"warmup-{method}", binary, foam_root, timeout_s
                )
            )
            backend.write_json(path, report)
        for index, order in enumerate(orders):
            record = dict(round=index, order=order, measurements=[])
            report["rounds"].append(record)
            for method in order:
                record["measurements"].append(
                    runner(
                        method,
                        output / f"round-{index:02d}-{method}",
                        binary,
                        foam_root,
                        timeout_s,
                    )
                )
                backend.write_json(path, report)
        for p in inputs:
            require(
                digest(p) == report["plan"]["input_sha256"][name(p)],
                "inputs",
                f"{name(p)} changed during the comparison",
            )
        report["summary"], report["native_over_openfoam"] = summarize(report["rounds"])
        report["passed"] = True
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        report["error"] = backend.diagnostic(exc, "comparison")
    backend.write_json(path, report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/cfd-craft")
    ap.add_argument("--foam-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--timeout-s", type=float, default=180)
    args = ap.parse_args()
    try:
        report = compare(
            args.binary, args.foam_root, args.output, args.repeats, args.timeout_s
        )
    except (ValueError, OSError) as exc:
        print(str(exc))
        return 1
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in ["passed", "error", "summary", "native_over_openfoam"]
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
