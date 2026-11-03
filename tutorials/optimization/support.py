"""Bounded CFD runs and native LP/MIP models for the optimization lessons."""

import argparse
import copy
from dataclasses import asdict, is_dataclass
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tutorials"))
from common import receptor_values, run_case  # noqa: E402


def require(condition, field, message):
    """Fail a lesson check with CFD-T001 and the offending record path."""
    if not condition:
        raise ValueError(f"CFD-T001 optimization.{field}: {message}")


def plain(value):
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, np.generic):
        return plain(value.item())
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plain(value), indent=2, allow_nan=False) + "\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def steady(record):
    return (
        record.get("returncode") == 0
        and record.get("summary") is not None
        and record["summary"]["assessment"] == "steady_discrete_solution"
        and record.get("independent") is not None
        and record["independent"]["passed"]
    )


class Runs:
    def __init__(self, args, report):
        self.args, self.report = args, report
        report["solves"] = []

    def __call__(self, case, label, phase):
        folder = self.args.output / f"{len(self.report['solves']):04d}-{label}"
        start = time.perf_counter()
        try:
            result = run_case(self.args.binary, case, folder)
        except (subprocess.TimeoutExpired, OSError, ValueError) as error:
            result = dict(
                returncode=None,
                summary=None,
                independent=None,
                wall_s=time.perf_counter() - start,
                error=str(error),
                path=folder.name,
            )
        result.update(phase=phase, accepted=steady(result))
        self.report["solves"].append(result)
        write(self.args.output / "summary.json", self.report)
        return result


def source_case(threads=1, wind=1.0):
    case = json.loads((ROOT / "cases/verification/source-response.json").read_text())
    case["run"]["threads"] = threads
    case["flow"]["velocity_m_s"][0] = wind
    require(
        case["numerics"]["transport"] == "linear_upwind",
        "case.numerics.transport",
        "superposition needs linear transport",
    )
    return case


def allocation(case, q):
    candidate = copy.deepcopy(case)
    for source, multiplier in zip(candidate["sources"], q, strict=True):
        source["rate_kg_s_m3"] *= float(multiplier)
    return candidate


def responses(case, runs, label):
    columns = []
    for i in range(3):
        unit = allocation(case, np.eye(3)[i])
        record = runs(unit, f"{label}-unit-{i}", "response_setup")
        require(
            record["accepted"],
            f"solves.{record['path']}",
            "unit response solve was not accepted",
        )
        columns.append(receptor_values(record, unit))
    return np.asarray(columns).T / 1e-8


def native_linear(
    c, lower, upper, rows, row_lower, row_upper, kinds=None, sense="minimize"
):
    from lp_ip_craft import Model, NativeOptions, Options, solve

    matrix = np.asarray(rows)
    indices, values, indptr = [], [], [0]
    for row in matrix:
        for i, value in enumerate(row):
            if value != 0:
                indices.append(i)
                values.append(float(value))
        indptr.append(len(indices))
    model = Model(
        objective=list(c),
        lower=list(lower),
        upper=list(upper),
        row_lower=list(row_lower),
        row_upper=list(row_upper),
        indptr=indptr,
        indices=indices,
        values=values,
        kinds=kinds or ["continuous"] * len(c),
        sense=sense,
    )
    start = time.perf_counter()
    result = solve(
        model,
        backend="native",
        options=Options(threads=1),
        backend_options=NativeOptions(
            time_limit_seconds=30,
            node_limit=10000,
            iteration_limit=200000,
            component_threads=1,
        ),
    )
    require(
        result.status == "optimal" and result.candidate is not None,
        "native.status",
        f"native linear solve ended {result.status}",
    )
    x = np.asarray(result.candidate)
    activity = matrix @ x
    violation = max(
        0.0,
        float(np.max(np.asarray(lower) - x)),
        float(np.max(x - np.asarray(upper))),
        float(np.max(np.asarray(row_lower) - activity)),
        float(np.max(activity - np.asarray(row_upper))),
    )
    require(
        violation <= 1e-7,
        "native.primal_violation",
        "native candidate failed the independent primal check",
    )
    if kinds:
        require(
            np.max(np.abs(x - np.round(x))) <= 1e-7,
            "native.candidate",
            "MIP integrality check failed",
        )
    return x, dict(
        status=result.status,
        objective=float(np.dot(c, x)),
        primal_violation=violation,
        elapsed_seconds=time.perf_counter() - start,
        result=plain(result),
    )


def main(chapter, function):
    parser = argparse.ArgumentParser(description=function.__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--preset", choices=["smoke", "study"], default="smoke")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument(
        "--binary", type=Path, default=ROOT / "target/release/cfd-craft"
    )
    parser.add_argument(
        "--worker",
        type=Path,
        default=ROOT
        / "integrations/fcmaes-cfd-worker/target/release/fcmaes-cfd-worker",
    )
    parser.add_argument(
        "--runner",
        type=Path,
        default=ROOT.parent / "optimization-jobs/target/release/optimization-run",
    )
    args = parser.parse_args()
    require(1 <= args.threads <= 8, "threads", "threads must be in 1..8")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(
        schema_version="cfd-craft.optimization-tutorial/0.1",
        chapter=chapter,
        preset=args.preset,
        state="running",
        passed=False,
        checks=[],
        arms=[],
    )
    start = time.perf_counter()
    try:
        sources = sorted(Path(__file__).parent.glob("*.py")) + [
            ROOT / "tutorials/common.py",
            ROOT / "validation/check_fields.py",
            ROOT / "cases/verification/source-response.json",
            ROOT / "cases/verification/lid-cavity.json",
        ]
        report["source_sha256"] = {
            p.relative_to(ROOT).as_posix(): digest(p) for p in sources
        }
        report["binary_sha256"] = digest(args.binary)
        report["versions"] = {
            name: importlib.metadata.version(name)
            for name in ["fcmaes-rust", "lp-ip-craft", "numpy", "scipy"]
        }
        function(args, report)
        require(
            all(c["passed"] for c in report["checks"]),
            "checks",
            "tutorial gate failed",
        )
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        report["state"] = "complete"
        report["total_seconds"] = time.perf_counter() - start
        solves = report.get("solves", [])
        report["work"] = dict(
            full_field_solves=len(solves),
            accepted=sum(r["accepted"] for r in solves),
            failed=sum(not r["accepted"] for r in solves),
            steps=sum((r.get("summary") or {}).get("steps", 0) for r in solves),
            pressure_iterations=sum(
                (r.get("summary") or {}).get("pressure_iterations", 0) for r in solves
            ),
        )
        write(args.output / "summary.json", report)
    print(
        json.dumps(
            {k: report[k] for k in ["chapter", "passed", "total_seconds"]}
            | {"error": report.get("error")}
        )
    )
    return 0 if report["passed"] else 1
