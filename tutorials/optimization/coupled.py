"""F3: acceptance-aware coupled cavity design with fidelity and condition replay."""

import json
import math
import time
import numpy as np
import fcmaes_rust
from support import ROOT, Runs, require, write


TARGET = 0.04
FIDELITY = 0.1


def cavity(speed, viscosity, n, threads):
    case = json.loads((ROOT / "cases/verification/lid-cavity.json").read_text())
    case["name"] = "optimization-coupled-cavity"
    case["grid"]["cells"] = [n, 2, n]
    case["flow"]["viscosity_m2_s"] = viscosity
    case["moving_walls"][0]["velocity_m_s"] = [float(speed), 0, 0]
    case["numerics"].update(
        momentum_advection="limited_upwind",
        momentum_limiter="van_leer",
        pressure_preconditioner="multigrid",
        steady_algorithm="implicit_projection",
    )
    case["run"].update(
        mode="steady", max_steps=5000, wall_time_limit_s=30, threads=threads
    )
    return case


def mean_square_speed(velocity, case):
    """Volume mean of |u|^2 from the staggered face-normal velocities.

    The solver stores one normal velocity per face: all x faces, then y, then z
    (the layout validation/check_fields.py checks). Per component, the squared
    face values summed along each grid line and divided by its cell count are
    the trapezoid rule; wall faces carry zero normal velocity. Dividing by a
    third of the face count instead would weight the coarse grid differently
    from the fine one.
    """
    require(not case["geometry"], "case.geometry", "the cavity has no solid cells")
    cells = case["grid"]["cells"]
    velocity = np.asarray(velocity, dtype=float)
    offset, total = 0, 0.0
    for axis in range(3):
        dims = list(cells)
        if case["boundaries"]["xyz"[axis]] != "periodic":
            dims[axis] += 1
        count = math.prod(dims)
        total += float(np.sum(velocity[offset : offset + count] ** 2))
        offset += count
    require(
        offset == len(velocity),
        "fields.velocity",
        f"{len(velocity)} face velocities for {offset} faces",
    )
    return total / math.prod(cells)


def field_objective(folder, case, speed):
    fields = json.loads((folder / "fields.json").read_text())
    energy = mean_square_speed(fields["velocity"], case)
    return ((energy - TARGET) / TARGET) ** 2 + 0.02 * speed**2, energy


def run(args, report):
    """Optimize a bounded lid speed; replay all nominated designs on a finer grid."""
    runs = Runs(args, report)
    coarse, fine = (8, 16) if args.preset == "smoke" else (16, 32)
    budget = 12 if args.preset == "smoke" else 64
    training, holdout = [0.01, 0.015], 0.0125
    numerics = cavity(1.0, training[0], coarse, args.threads)["numerics"]
    # Frozen before any solve. This is a teaching design objective, not physical validation.
    report["budgets"] = dict(
        requested_search_calls=budget,
        coarse=coarse,
        fine=fine,
        training_viscosities=training,
        holdout_viscosity=holdout,
        speed_bounds=[0.6, 1.4],
        threads=args.threads,
        max_steps=5000,
        wall_seconds_per_solve=30,
        residual_tolerance=numerics["steady_residual_tolerance"],
        monitor_tolerance=numerics["steady_monitor_tolerance"],
        maximum_relative_energy_grid_change=FIDELITY,
        target_mean_square_speed=TARGET,
        mean_square_speed="trapezoid volume mean of squared face-normal velocities",
    )
    trace = []

    def evaluate(speed, n, conditions, phase):
        rows = []
        for viscosity in conditions:
            case = cavity(speed, viscosity, n, args.threads)
            r = runs(case, phase, phase)
            if r["accepted"]:
                value, energy = field_objective(args.output / r["path"], case, speed)
            else:
                value, energy = float("inf"), None
            rows.append(
                dict(
                    viscosity=viscosity,
                    objective=value,
                    mean_square_speed=energy,
                    accepted=r["accepted"],
                    path=r["path"],
                )
            )
        row = dict(
            speed=speed,
            grid=n,
            cases=rows,
            objective=max(r["objective"] for r in rows),
            accepted=all(r["accepted"] for r in rows),
            phase=phase,
        )
        trace.append(row)
        write(args.output / "evaluations.json", trace)
        return row

    baseline = evaluate(1.0, coarse, training, "baseline")
    samples = [
        evaluate(float(x), coarse, training, "sampling")
        for x in np.linspace(0.6, 1.4, 5)
    ]
    start = time.perf_counter()
    calls = 0

    def objective(x):
        nonlocal calls
        calls += 1
        return evaluate(float(x[0]), coarse, training, "search")["objective"]

    answer = fcmaes_rust.optimize_bite(
        objective, [1.0], [0.6], [1.4], seed=613, max_evaluations=budget
    )
    require(
        answer[2] == calls,
        "search.actual_evaluations",
        "coupled objective call accounting differs",
    )
    choices = [
        ("fixed", baseline),
        ("sampling", min(samples, key=lambda r: r["objective"])),
    ]
    finite = [r for r in trace if r["phase"] == "search" and r["accepted"]]
    if finite:
        choices.append(("BiteOpt", min(finite, key=lambda r: r["objective"])))
    report["search"] = dict(
        requested_evaluations=budget,
        actual_evaluations=calls,
        seconds=time.perf_counter() - start,
        usable_search_candidates=len(finite),
    )
    for method, row in choices:
        validation = evaluate(row["speed"], fine, training, "fine-replay")
        withheld = evaluate(row["speed"], fine, [holdout], "heldout")
        drift = None
        if row["accepted"] and validation["accepted"]:
            drift = max(
                abs(b["mean_square_speed"] - a["mean_square_speed"])
                / max(b["mean_square_speed"], 1e-12)
                for a, b in zip(row["cases"], validation["cases"], strict=True)
            )
        # The withheld viscosity is a convergence check only: it must be
        # accepted, but its objective is reported, not gated.
        supported = bool(
            drift is not None and drift <= FIDELITY and withheld["accepted"]
        )
        report["arms"].append(
            dict(
                method=method,
                training=row,
                fine=validation,
                holdout=withheld,
                relative_energy_grid_change=drift,
                supported_at_requested_fidelity=supported,
            )
        )
    coarse_ranking = [
        r["method"]
        for r in sorted(report["arms"], key=lambda r: r["training"]["objective"])
    ]
    fine_ranking = [
        r["method"]
        for r in sorted(report["arms"], key=lambda r: r["fine"]["objective"])
    ]
    report.update(
        coarse_ranking=coarse_ranking,
        fine_ranking=fine_ranking,
        ranking_changed=coarse_ranking != fine_ranking,
        # Equal speeds are one design; their order in a ranking is a tie.
        distinct_designs=len({r["training"]["speed"] for r in report["arms"]}),
        supported_designs=sum(
            r["supported_at_requested_fidelity"] for r in report["arms"]
        ),
        interpretation="A completed experiment can support zero designs. Two-grid agreement is a screening gate, not a grid-convergence proof or physical validation.",
    )
    report["checks"].append(
        dict(
            name="bounded-search-all-failures-retained-and-fidelity-replayed",
            passed=True,
        )
    )
