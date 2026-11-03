"""F1: the same fixed-emission problem solved by native LP, BiteOpt and GP."""

import copy
import itertools
import json
import subprocess
import time
import numpy as np
import fcmaes_rust
from support import (
    Runs,
    allocation,
    digest,
    native_linear,
    receptor_values,
    require,
    responses,
    source_case,
    write,
)


def vertex_reference(a):
    """Enumerate vertices in (q0,q1,t); no LP implementation is reused."""
    rows = [[r[0] - r[2], r[1] - r[2], -1] for r in a]
    bounds = [-3 * r[2] for r in a]
    rows += [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, -1]]
    bounds += [1.4, -0.1, 1.4, -0.1, 0]
    matrix, rhs = np.array(rows), np.array(bounds)
    feasible = []
    for active in itertools.combinations(range(len(rows)), 3):
        square = matrix[list(active)]
        if abs(np.linalg.det(square)) < 1e-12:
            continue
        point = np.linalg.solve(square, rhs[list(active)])
        if np.all(matrix @ point <= rhs + 1e-8):
            feasible.append(point)
    require(feasible, "no feasible reference vertex")
    point = min(feasible, key=lambda p: p[2])
    return np.array([point[0], point[1], 3 - point[0] - point[1]]), float(point[2])


def gp(args, case, budget):
    setup_start = time.perf_counter()
    root = args.output / "gp"
    root.mkdir()
    node = root / "node"
    actions = []

    def call(*parts):
        command = [str(args.runner.resolve()), "--root", str(node), *map(str, parts)]
        p = subprocess.run(command, capture_output=True, text=True, timeout=600)
        actions.append(
            dict(
                argv=command, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr
            )
        )
        write(root / "actions.json", actions)
        require(p.returncode == 0, f"GP runner failed: {p.stderr[:2000]}")
        return json.loads(p.stdout)

    call("node", "init", "--capacity", "1")
    call("workers", "add", "--id", "cfd", "--executable", args.worker.resolve())
    describe = subprocess.run(
        [str(args.worker.resolve()), "describe"],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    example = next(
        e
        for e in json.loads(describe.stdout)["examples"]
        if e["profile"] == "fcmaes.surrogate/1"
    )
    payload = copy.deepcopy(example["payload"])
    payload.update(
        evaluations=budget,
        runs=1,
        concurrent=1,
        evaluation_threads=1,
        recheck_best=True,
    )
    case_path = root / "case.json"
    write(case_path, case)
    spec = dict(
        schema_version="optimization.job/0.1",
        request_key="cfd-f1-gp-v1",
        worker="cfd",
        payload_schema="fcmaes.surrogate/1",
        resources=dict(cpu_slots=1, outer_workers=1, inner_threads=1),
        limits=dict(wall_time_seconds=540, grace_seconds=2),
        inputs=[dict(name="case", file="case.json", sha256=digest(case_path))],
        payload=payload,
    )
    write(root / "job.json", spec)
    setup_seconds = time.perf_counter() - setup_start
    start = time.perf_counter()
    result = call("run", "--spec", root / "job.json")
    require(
        result.get("state") == "completed"
        and result.get("completed_tasks") == result.get("requested_tasks"),
        "GP job incomplete",
    )
    manifest = call("result", result["directory"])
    write(root / "result.json", manifest)
    work = result["known_work_lower_bound"]
    require(
        work["failed_evaluations"] == 0 and work["cancelled_evaluations"] == 0,
        "GP contains failed solves",
    )
    outcome = manifest["results"][0]["outcome"]
    require(
        outcome.get("x") is not None and outcome.get("objective") is not None,
        "GP has no usable incumbent",
    )
    x = outcome["x"]
    return [x[0], x[1], 3 - sum(x)], dict(
        method="GP",
        setup_seconds=setup_seconds,
        objective=outcome["objective"],
        requested_evaluations=budget,
        work=work,
        search_seconds=time.perf_counter() - start,
        worker_sha256=digest(args.worker),
        runner_sha256=digest(args.runner),
    )


def run(args, report):
    """Build a response matrix; compare equal-domain native solvers and replay."""
    # Prescribed transport is serial; requesting more threads does not parallelize it.
    case = source_case(1)
    runs = Runs(args, report)
    budget = 16 if args.preset == "smoke" else 128
    report["budgets"] = dict(
        requested_search_calls=budget,
        threads=1,
        seed=601,
        concentration_scale_kg_m3=1e-8,
        total_multiplier=3,
        lower=[0.1, 0.1, 0.2],
        upper=[1.4, 1.4, 2.8],
    )
    start = time.perf_counter()
    a = responses(case, runs, "training")
    setup_seconds = time.perf_counter() - start
    write(args.output / "response.json", a)
    rows = np.vstack([np.column_stack([a, -np.ones(len(a))]), [1, 1, 1, 0]])
    x, lp = native_linear(
        [0, 0, 0, 1],
        [0.1, 0.1, 0.2, 0],
        [1.4, 1.4, 2.8, 3 * a.max()],
        rows,
        [-np.inf] * len(a) + [3],
        [0] * len(a) + [3],
    )
    qref, reference = vertex_reference(a)
    require(
        abs(x[3] - reference) <= 1e-7,
        "native LP disagrees with independent vertex optimum",
    )
    lp.update(
        method="LP",
        response_setup_seconds=setup_seconds,
        response_setup_solves=3,
        reference_objective=reference,
        reference_q=qref,
        q=x[:3],
    )
    report["arms"].append(lp)
    trace = []

    def objective(point):
        q = [point[0], point[1], 3 - sum(point)]
        c = allocation(case, q)
        r = runs(c, "bite", "search")
        value = max(receptor_values(r, c)) / 1e-8 if r["accepted"] else float("inf")
        trace.append(dict(q=q, objective=value, accepted=r["accepted"], path=r["path"]))
        return value

    start = time.perf_counter()
    answer = fcmaes_rust.optimize_bite(
        objective, [1, 1], [0.1, 0.1], [1.4, 1.4], seed=601, max_evaluations=budget
    )
    require(
        answer[2] == len(trace) and np.isfinite(answer[1]),
        "Bite work count or incumbent invalid",
    )
    qb = [answer[0][0], answer[0][1], 3 - sum(answer[0])]
    report["arms"].append(
        dict(
            method="BiteOpt",
            q=qb,
            objective=answer[1],
            requested_evaluations=budget,
            actual_evaluations=len(trace),
            search_seconds=time.perf_counter() - start,
        )
    )
    write(args.output / "bite.trace.json", trace)
    qg, gp_row = gp(args, case, budget)
    gp_row["q"] = qg
    report["arms"].append(gp_row)
    for row in report["arms"]:
        q = np.asarray(row["q"])
        c = allocation(case, q)
        replay = runs(c, row["method"] + "-replay", "validation")
        require(replay["accepted"], "selected allocation failed full CFD replay")
        receptors = np.asarray(receptor_values(replay, c)) / 1e-8
        error = float(np.max(np.abs(receptors - a @ q)))
        require(
            error <= 1e-4 * max(1, float(np.max(receptors))),
            "linear superposition replay failed",
        )
        require(
            float(receptors.max()) >= reference - 1e-4,
            "full CFD beat the exact linear optimum beyond tolerance",
        )
        holdout_case = allocation(source_case(1, wind=1.15), q)
        holdout = runs(holdout_case, row["method"] + "-wind", "holdout")
        require(holdout["accepted"], "changed-wind validation failed")
        row.update(
            replay_objective=float(receptors.max()),
            superposition_max_error=error,
            heldout_wind_objective=max(receptor_values(holdout, holdout_case)) / 1e-8,
        )
    report["checks"].append(
        dict(name="LP-vertex-optimum-and-fresh-full-CFD-superposition", passed=True)
    )
    report["interpretation"] = (
        "GP work is additional to full_field_solves. LP pays for three response solves. Fixed linear transport only; changed wind is a separate model."
    )
