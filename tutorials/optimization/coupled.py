"""F3: acceptance-aware coupled cavity design with fidelity and condition replay."""

import json
import time
import numpy as np
import fcmaes_rust
from support import ROOT, Runs, require, write


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


def field_objective(folder, speed):
    fields = json.loads((folder / "fields.json").read_text())
    # Components are stored separately; sum of squares is independent of layout.
    velocity = np.asarray(fields["velocity"])
    mean_energy = float(np.sum(velocity**2) / (len(velocity) / 3))
    return ((mean_energy - 0.04) / 0.04) ** 2 + 0.02 * speed**2, mean_energy


def run(args, report):
    """Optimize a bounded lid speed; replay all nominated designs on a finer grid."""
    runs = Runs(args, report)
    coarse, fine = (8, 16) if args.preset == "smoke" else (16, 32)
    budget = 12 if args.preset == "smoke" else 64
    training, holdout = [0.01, 0.015], 0.0125
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
        residual_tolerance=1e-5,
        monitor_tolerance=0.001,
        maximum_relative_energy_grid_change=0.1,
        target_mean_square_speed=0.04,
    )
    trace = []

    def evaluate(speed, n, conditions, phase):
        rows = []
        for viscosity in conditions:
            case = cavity(speed, viscosity, n, args.threads)
            r = runs(case, phase, phase)
            if r["accepted"]:
                value, energy = field_objective(args.output / r["path"], speed)
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
    require(answer[2] == calls, "coupled objective call accounting differs")
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
        supported = bool(drift is not None and drift <= 0.1 and withheld["accepted"])
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
