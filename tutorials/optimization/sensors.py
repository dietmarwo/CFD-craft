"""F2: binary coverage is a different objective from source identifiability."""

import itertools
import numpy as np
from scipy.optimize import nnls
from support import (
    Runs,
    allocation,
    native_linear,
    receptor_values,
    require,
    responses,
    source_case,
    write,
)


def coverage(detection, subset, weights):
    return float(weights @ np.any(detection[list(subset)], axis=0))


def selection(detection, weights, budget=3):
    n, m = detection.shape
    rows = [np.r_[np.ones(n), np.zeros(m)]]
    for j in range(m):
        row = np.zeros(n + m)
        row[:n] = -detection[:, j]
        row[n + j] = 1
        rows.append(row)
    x, result = native_linear(
        np.r_[np.zeros(n), weights],
        np.zeros(n + m),
        np.ones(n + m),
        rows,
        [-np.inf] * (m + 1),
        [budget] + [0] * m,
        kinds=["binary"] * (n + m),
        sense="maximize",
    )
    chosen = list(np.flatnonzero(x[:n] > 0.5))
    exact = [
        (list(s), coverage(detection, s, weights))
        for s in itertools.combinations(range(n), budget)
    ]
    optimum = max(v for _, v in exact)
    require(
        abs(coverage(detection, chosen, weights) - optimum) <= 1e-7,
        "arms.MIP.coverage",
        "MIP differs from exhaustive optimum",
    )
    greedy = []
    for _ in range(budget):
        greedy.append(
            max(
                (i for i in range(n) if i not in greedy),
                key=lambda i: coverage(detection, greedy + [i], weights),
            )
        )
    return chosen, result, exact, greedy


def optimal_subsets(detection, weights, a, budget=3):
    """Every subset of at most `budget` sensors that reaches the coverage optimum.

    Coverage is indifferent to which optimal subset is returned, so the rank and
    conditioning of each one show what the coverage objective leaves to chance.
    """
    n = detection.shape[0]
    optimum = max(
        coverage(detection, s, weights)
        for s in itertools.combinations(range(n), budget)
    )
    rows = []
    for size in range(1, budget + 1):
        for subset in itertools.combinations(range(n), size):
            if abs(coverage(detection, subset, weights) - optimum) > 1e-7:
                continue
            matrix = a[list(subset)]
            rank = int(np.linalg.matrix_rank(matrix))
            rows.append(
                dict(
                    sensors=list(subset),
                    rank=rank,
                    condition_number=(
                        float(np.linalg.cond(matrix))
                        if rank == matrix.shape[1]
                        else None
                    ),
                )
            )
    return optimum, rows


def inversion(a, values, subset, truth):
    matrix = a[list(subset)]
    x, residual = nnls(matrix, np.asarray(values)[list(subset)])
    singular = np.linalg.svd(matrix, compute_uv=False)
    return dict(
        estimate=x,
        residual=residual,
        relative_rate_error=float(np.linalg.norm(x - truth) / np.linalg.norm(truth)),
        rank=int(np.linalg.matrix_rank(matrix)),
        singular_values=singular,
        full_column_rank=bool(np.linalg.matrix_rank(matrix) == matrix.shape[1]),
        nullity=int(matrix.shape[1] - np.linalg.matrix_rank(matrix)),
        condition_number=(
            float(np.linalg.cond(matrix))
            if np.linalg.matrix_rank(matrix) == matrix.shape[1]
            else None
        ),
        observed_subspace_condition_number=float(np.linalg.cond(matrix)),
    )


def run(args, report):
    """Choose three of six sensors; verify all 20 subsets, then invert held-out data."""
    runs = Runs(args, report)
    winds = [0.85, 1.15]
    matrices = [responses(source_case(1, wind), runs, f"wind-{wind}") for wind in winds]
    sources = np.array(
        [[2, 0, 0], [0, 2, 0], [0, 0, 2], [1, 1, 0], [0, 1, 1], [1, 0, 1]]
    )
    concentration = np.column_stack([a @ q for a in matrices for q in sources])
    # Fixed physical concentration threshold + a declared noise allowance, not fitted to outcomes.
    threshold, noise_allowance = 0.22, 0.02
    detection = (concentration >= threshold + noise_allowance).astype(float)
    weights = np.tile([3, 3, 3, 1, 1, 1], len(winds)).astype(float)
    chosen, mip, exhaustive, greedy = selection(detection, weights)
    write(
        args.output / "scenario-matrix.json",
        dict(
            winds=winds,
            sources=sources,
            concentration=concentration,
            detection=detection,
            weights=weights,
            normalized_threshold=threshold,
            normalized_noise_allowance=noise_allowance,
        ),
    )
    write(args.output / "exhaustive.json", exhaustive)
    report["arms"] = [
        dict(
            method="MIP",
            sensors=chosen,
            coverage=coverage(detection, chosen, weights),
            native=mip,
        ),
        dict(
            method="greedy",
            sensors=greedy,
            coverage=coverage(detection, greedy, weights),
        ),
    ]
    report["budgets"] = dict(
        candidate_sensors=6,
        sensor_budget=3,
        training_scenarios=12,
        total_scenario_weight=float(sum(weights)),
        concentration_scale_kg_m3=1e-8,
        noise_seed=812,
        heldout_wind=1.0,
        mismatch_wind=1.3,
    )
    truth = np.array([0.7, 1.3, 0.4])
    base = source_case(1)
    heldout_matrix = responses(base, runs, "holdout-calibration")
    optimum, optimal = optimal_subsets(detection, weights, heldout_matrix)
    write(args.output / "optimal-subsets.json", optimal)
    full = [r for r in optimal if r["condition_number"] is not None]
    report["coverage_optimal_subsets"] = dict(
        optimum=optimum,
        count=len(optimal),
        by_size={
            size: sum(len(r["sensors"]) == size for r in optimal) for size in (1, 2, 3)
        },
        rank_deficient=sum(r["condition_number"] is None for r in optimal),
        full_rank_condition_range=(
            [
                min(r["condition_number"] for r in full),
                max(r["condition_number"] for r in full),
            ]
            if full
            else None
        ),
        interpretation="Every listed subset is coverage-optimal; the MIP and greedy answers are two of them, chosen by solver and index order.",
    )
    rng = np.random.default_rng(812)
    # Wind 1.0 is the calibration wind (in-model); 1.3 is a model mismatch.
    for wind in [1.0, 1.3]:
        c = allocation(source_case(1, wind), truth)
        r = runs(c, f"heldout-{wind}", "holdout")
        require(r["accepted"], f"solves.{r['path']}", "held-out source solve failed")
        data = np.asarray(receptor_values(r, c)) / 1e-8
        noise = rng.uniform(-noise_allowance, noise_allowance, len(data))
        for row in report["arms"]:
            row.setdefault("inversion", []).append(
                dict(
                    wind=wind,
                    truth=truth,
                    noiseless=inversion(heldout_matrix, data, row["sensors"], truth),
                    noisy=inversion(
                        heldout_matrix, data + noise, row["sensors"], truth
                    ),
                    # Physical threshold on the noiseless field; training used
                    # threshold + noise allowance so noisy data stay detected.
                    detection=bool(np.any(data[row["sensors"]] >= threshold)),
                    noise=noise,
                )
            )
    report["checks"].append(
        dict(
            name="bounded-MIP-independent-primal-integrality-and-20-subset-check",
            passed=True,
        )
    )
    report["interpretation"] = (
        "Coverage optimality is verified only for the frozen finite scenario set. Rank, conditioning and held-out inversion errors are reported, never inferred from detection."
    )
