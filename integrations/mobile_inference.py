"""R3 mobile-source inference and E-optimal route design with native LP-IP-craft.

All uncertainty is conditional on declared linear response/noise assumptions.
No atmospheric scatter is simulated and no measured data are manufactured.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import itertools
import math
import time

import numpy as np
from scipy.optimize import nnls


def require(condition, message):
    if not condition:
        raise ValueError(f"CFD-M003 mobile_inference: {message}")


def plain(value):
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, np.generic):
        return plain(value.item())
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def matrix(value, columns=None):
    a = np.asarray(value, dtype=float)
    require(
        a.ndim == 2 and a.shape[0] > 0 and a.shape[1] > 0 and np.isfinite(a).all(),
        "finite nonempty response matrix required",
    )
    require(
        a.shape[0] <= 1_000_000 and a.shape[1] <= 64 and a.size <= 20_000_000,
        "response matrix work budget exceeded",
    )
    if columns is not None:
        require(
            a.shape[1] == len(columns) and len(set(columns)) == len(columns),
            "source IDs/matrix mismatch",
        )
    return a


def identifiability(response, source_ids, *, relative_rank_tolerance=1e-10):
    a = matrix(response, source_ids)
    require(
        math.isfinite(relative_rank_tolerance) and 0 < relative_rank_tolerance < 1,
        "invalid rank tolerance",
    )
    _, singular, vh = np.linalg.svd(a, full_matrices=a.shape[0] < a.shape[1])
    threshold = (float(singular[0]) if len(singular) else 0.0) * relative_rank_tolerance
    rank = int(np.count_nonzero(singular > threshold))
    nullspace = vh[rank:]
    combinations = []
    for vector in nullspace:
        v = vector / max(np.max(np.abs(vector)), 1e-300)
        combinations.append(
            {
                name: float(coefficient)
                for name, coefficient in zip(source_ids, v, strict=True)
                if coefficient != 0.0
            }
        )
    aliases = []
    used = set()
    for j, name in enumerate(source_ids):
        if j in used:
            continue
        group = [name]
        for k in range(j + 1, len(source_ids)):
            scale = max(
                float(np.linalg.norm(a[:, j])), float(np.linalg.norm(a[:, k])), 1e-300
            )
            if np.linalg.norm(a[:, j] - a[:, k]) <= relative_rank_tolerance * scale:
                group.append(source_ids[k])
                used.add(k)
        if len(group) > 1:
            aliases.append(group)
    return dict(
        rank=rank,
        source_count=a.shape[1],
        full_column_rank=rank == a.shape[1],
        nullity=a.shape[1] - rank,
        singular_values=singular.tolist(),
        relative_rank_tolerance=relative_rank_tolerance,
        condition_number=float(singular[0] / singular[-1])
        if rank == a.shape[1]
        else None,
        named_ambiguous_combinations=combinations,
        identical_response_groups=aliases,
        interpretation="rank is conditional on the declared source columns, samples, wind and numerical tolerance",
    )


def noise_covariance(n, sensor_sigma_kg_m3, pass_scatter_sigma_kg_m3):
    require(
        n > 0
        and math.isfinite(sensor_sigma_kg_m3)
        and sensor_sigma_kg_m3 > 0
        and math.isfinite(pass_scatter_sigma_kg_m3)
        and pass_scatter_sigma_kg_m3 >= 0,
        "invalid noise assumptions",
    )
    require(
        type(n) is int and n <= 2048,
        "explicit covariance budget exceeded; use the rank-one whiten routine",
    )
    return (
        np.eye(n) * sensor_sigma_kg_m3**2
        + np.ones((n, n)) * pass_scatter_sigma_kg_m3**2
    )


def whiten(response, values, rows, sensor_sigma_kg_m3, pass_scatter_sigma_kg_m3):
    """Independent readout noise plus one coherent offset per independent pass.

    Each (wind,receptor) block is one pass. Station values are not inference rows.
    """
    a = matrix(response)
    y = np.asarray(values, dtype=float)
    require(
        y.shape == (len(a),) and len(rows) == len(a) and np.isfinite(y).all(),
        "response/observation dimensions",
    )
    output_a = np.empty_like(a)
    output_y = np.empty_like(y)
    groups = {}
    for i, row in enumerate(rows):
        require(
            row.get("kind") == "ride",
            "only declared ride rows can be used for mobile inference",
        )
        groups.setdefault((row["wind"], row["receptor"]), []).append(i)
    require(
        math.isfinite(sensor_sigma_kg_m3)
        and sensor_sigma_kg_m3 > 0
        and math.isfinite(pass_scatter_sigma_kg_m3)
        and pass_scatter_sigma_kg_m3 >= 0,
        "invalid noise assumptions",
    )
    for indices in groups.values():
        # Sigma=sigma_sensor² I + sigma_pass² 11^T. Its inverse square
        # root has one mean eigenmode and a diagonal orthogonal complement;
        # no sample-by-sample dense covariance or full left SVD is needed.
        group_a = a[indices]
        group_y = y[indices]
        mean_a = group_a.mean(axis=0)
        mean_y = group_y.mean()
        mean_noise = math.hypot(
            sensor_sigma_kg_m3, math.sqrt(len(indices)) * pass_scatter_sigma_kg_m3
        )
        output_a[indices] = (
            group_a - mean_a
        ) / sensor_sigma_kg_m3 + mean_a / mean_noise
        output_y[indices] = (
            group_y - mean_y
        ) / sensor_sigma_kg_m3 + mean_y / mean_noise
    require(
        np.isfinite(output_a).all() and np.isfinite(output_y).all(),
        "noise scale creates nonfinite whitened observations",
    )
    return output_a, output_y


def infer_sources(
    response,
    observations,
    rows,
    source_ids,
    training_rides,
    heldout_rides,
    *,
    sensor_sigma_kg_m3=2e-10,
    pass_scatter_sigma_kg_m3=1e-9,
):
    a = matrix(response, source_ids)
    y = np.asarray(observations, dtype=float)
    require(
        y.shape == (len(a),) and len(rows) == len(a) and np.isfinite(y).all(),
        "observation dimensions/nonfinite value",
    )
    train_names = set(training_rides)
    hold_names = set(heldout_rides)
    require(
        train_names and hold_names and train_names.isdisjoint(hold_names),
        "train/held-out ride IDs must be nonempty and disjoint",
    )
    available = {row["receptor"] for row in rows if row.get("kind") == "ride"}
    require(train_names | hold_names <= available, "unknown train/held-out ride")
    train = [
        i
        for i, row in enumerate(rows)
        if row.get("kind") == "ride" and row["receptor"] in train_names
    ]
    test = [
        i
        for i, row in enumerate(rows)
        if row.get("kind") == "ride" and row["receptor"] in hold_names
    ]
    require(train and test, "no inference/held-out observations")
    aw, yw = whiten(
        a[train],
        y[train],
        [rows[i] for i in train],
        sensor_sigma_kg_m3,
        pass_scatter_sigma_kg_m3,
    )
    fitted, residual = nnls(aw, yw)
    prediction = a @ fitted
    rank = identifiability(aw, source_ids)
    return dict(
        multipliers=fitted.tolist(),
        individual_rates_unique=rank["full_column_rank"],
        estimate_label="unique_nonnegative_estimate"
        if rank["full_column_rank"]
        else "one_nonnegative_solution_ambiguous_rates",
        identifiability=rank,
        training_row_indices=train,
        heldout_row_indices=test,
        training_rides=sorted(train_names),
        heldout_rides=sorted(hold_names),
        weighted_training_residual=float(residual),
        heldout_relative_error=float(
            np.linalg.norm((prediction - y)[test])
            / max(np.linalg.norm(y[test]), 1e-300)
        ),
        prediction_kg_m3=prediction.tolist(),
        noise_assumptions=dict(
            sensor_sigma_kg_m3=sensor_sigma_kg_m3,
            pass_scatter_sigma_kg_m3=pass_scatter_sigma_kg_m3,
            within_pass="independent readout noise plus coherent pass offset",
            between_passes="independent",
            simulated=False,
        ),
        interpretation="conditional linear same-model inference; no posterior or experimental-validation claim",
    )


def required_passes(
    mean_kg_m3,
    *,
    sensor_sigma_kg_m3,
    pass_scatter_sigma_kg_m3,
    effective_samples_per_pass,
    relative_half_width=0.1,
    absolute_half_width_kg_m3=None,
    confidence_z=1.96,
    systematic_sigma_kg_m3=0.0,
    max_passes=1000000,
):
    values = [
        mean_kg_m3,
        sensor_sigma_kg_m3,
        pass_scatter_sigma_kg_m3,
        effective_samples_per_pass,
        relative_half_width,
        confidence_z,
        systematic_sigma_kg_m3,
    ]
    require(
        all(math.isfinite(v) for v in values)
        and sensor_sigma_kg_m3 >= 0
        and pass_scatter_sigma_kg_m3 >= 0
        and effective_samples_per_pass > 0
        and relative_half_width > 0
        and confidence_z > 0
        and systematic_sigma_kg_m3 >= 0,
        "invalid pass-count assumptions",
    )
    require(
        type(max_passes) is int and max_passes > 0,
        "max_passes must be a positive integer",
    )
    target = (
        absolute_half_width_kg_m3
        if absolute_half_width_kg_m3 is not None
        else abs(mean_kg_m3) * relative_half_width
    )
    require(math.isfinite(target) and target >= 0, "invalid uncertainty target")
    variance = (
        pass_scatter_sigma_kg_m3**2 + sensor_sigma_kg_m3**2 / effective_samples_per_pass
    )
    denominator = (target / confidence_z) ** 2 - systematic_sigma_kg_m3**2
    if denominator <= 0:
        return dict(
            passes=None,
            achievable=False,
            reason="zero mean/target or systematic noise floor cannot be reduced by more passes",
            target_half_width_kg_m3=target,
        )
    count = max(1, math.ceil(variance / denominator))
    return dict(
        passes=count if count <= max_passes else None,
        achievable=count <= max_passes,
        reason=None if count <= max_passes else "declared pass budget exceeded",
        target_half_width_kg_m3=target,
        independent_pass_variance_kg2_m6=variance,
        systematic_sigma_kg_m3=systematic_sigma_kg_m3,
        effective_samples_per_pass=effective_samples_per_pass,
        confidence_z=confidence_z,
        simulated=False,
        interpretation="Gaussian independent-pass planning assumption; correlated drift/model error need separate treatment",
    )


def route_information(
    response,
    rows,
    candidates,
    *,
    sensor_sigma_kg_m3=2e-10,
    pass_scatter_sigma_kg_m3=1e-9,
):
    a = matrix(response)
    result = []
    ids = []
    for candidate in candidates:
        require(candidate["id"] not in ids, "duplicate route candidate ID")
        ids.append(candidate["id"])
        idx = [
            i
            for i, row in enumerate(rows)
            if row.get("kind") == "ride"
            and row["wind"] == candidate["wind"]
            and row["receptor"] == candidate["ride"]
        ]
        require(
            idx
            and math.isfinite(candidate["riding_time_s"])
            and candidate["riding_time_s"] > 0,
            "empty route or invalid riding time",
        )
        aw, _ = whiten(
            a[idx],
            np.zeros(len(idx)),
            [rows[i] for i in idx],
            sensor_sigma_kg_m3,
            pass_scatter_sigma_kg_m3,
        )
        result.append(aw.T @ aw)
    return np.asarray(result)


def _native_master(information, costs, budget, cuts, remaining):
    from lp_ip_craft import Model, NativeOptions, Options, solve

    n = len(information)
    rows = [np.r_[costs, 0.0]]
    for direction in cuts:
        rows.append(
            np.r_[-np.einsum("i,rij,j->r", direction, information, direction), 1.0]
        )
    indptr = [0]
    indices = []
    values = []
    for row in rows:
        for i, v in enumerate(row):
            if v != 0:
                indices.append(i)
                values.append(float(v))
        indptr.append(len(indices))
    model = Model(
        objective=[0.0] * n + [1.0],
        lower=[0.0] * (n + 1),
        upper=[1.0] * (n + 1),
        row_lower=[-math.inf] * len(rows),
        row_upper=[budget] + [0.0] * len(cuts),
        indptr=indptr,
        indices=indices,
        values=values,
        kinds=["binary"] * n + ["continuous"],
        sense="maximize",
    )
    result = solve(
        model,
        backend="native",
        options=Options(threads=1),
        backend_options=NativeOptions(
            time_limit_seconds=min(5.0, remaining),
            node_limit=10000,
            iteration_limit=200000,
            component_threads=1,
            tree_threads=1,
            dual_tolerance=1e-9,
            pivot_tolerance=1e-10,
        ),
    )
    if result.status != "optimal" or result.candidate is None:
        failure = ValueError(
            f"CFD-M003 mobile_inference: route MIP stopped as {result.status}; optimum not certified"
        )
        failure.native_result = plain(result)
        raise failure
    x = np.asarray(result.candidate, dtype=float)
    activity = np.asarray(rows) @ x
    require(
        np.isfinite(x).all()
        and np.max(np.abs(x[:n] - np.round(x[:n]))) <= 1e-7
        and np.min(x) >= -1e-7
        and np.max(x) <= 1 + 1e-7
        and activity[0] <= budget + 1e-7
        and np.max(activity[1:]) <= 1e-7,
        "native route candidate failed independent primal/integrality check",
    )
    return x, plain(result)


def select_routes(
    information,
    candidates,
    riding_time_budget_s,
    *,
    max_cuts=64,
    wall_time_limit_s=30.0,
    gap_tolerance=1e-7,
):
    """Maximize lambda_min(sum selected Fisher matrices) by exact integer outer approximation.

    For every unit vector v, t <= sum z_r v^T F_r v. The master provides an
    upper bound; its actual minimum-eigenvalue vector supplies a separating cut.
    No continuous relax-and-round route is returned as an integer optimum.
    """
    f = np.asarray(information, dtype=float)
    require(
        f.ndim == 3
        and f.shape[0] == len(candidates)
        and f.shape[1] == f.shape[2] > 0
        and np.isfinite(f).all(),
        "invalid information matrices",
    )
    require(
        0 < len(candidates) <= 20
        and math.isfinite(riding_time_budget_s)
        and riding_time_budget_s >= 0
        and math.isfinite(wall_time_limit_s)
        and wall_time_limit_s > 0
        and 0 < max_cuts <= 256
        and 0 < gap_tolerance < 1,
        "invalid route work/time budget",
    )
    require(
        np.max(np.abs(f - f.transpose(0, 2, 1))) <= 1e-9 * max(1.0, np.max(np.abs(f)))
        and np.min(np.linalg.eigvalsh(f)) >= -1e-9 * max(1.0, np.max(np.abs(f))),
        "information matrices must be symmetric positive semidefinite",
    )
    require(
        len({c["id"] for c in candidates}) == len(candidates),
        "duplicate route candidate IDs",
    )
    costs = np.array([c["riding_time_s"] for c in candidates], dtype=float)
    require(np.isfinite(costs).all() and np.min(costs) > 0, "invalid riding costs")
    scale = max(float(np.linalg.eigvalsh(f.sum(axis=0))[-1]), 1e-300)
    normalized = f / scale
    cuts = list(np.eye(f.shape[1]))
    trace = []
    started = time.monotonic()
    best_score = -math.inf
    best = []
    certified = False
    for iteration in range(max_cuts):
        remaining = wall_time_limit_s - (time.monotonic() - started)
        if remaining <= 0:
            break
        try:
            x, native = _native_master(
                normalized, costs, riding_time_budget_s, cuts, remaining
            )
        except (ValueError, RuntimeError) as exc:
            trace.append(
                dict(
                    iteration=iteration,
                    error=str(exc),
                    native=getattr(exc, "native_result", None),
                    incumbent_selected=[candidates[i]["id"] for i in best],
                )
            )
            break
        chosen = np.flatnonzero(x[:-1] > 0.5).tolist()
        eigen, vectors = np.linalg.eigh(
            normalized[chosen].sum(axis=0) if chosen else np.zeros_like(normalized[0])
        )
        actual = max(0.0, float(eigen[0]))
        bound = float(x[-1])
        if actual > best_score:
            best_score = actual
            best = chosen
        trace.append(
            dict(
                iteration=iteration,
                selected=[candidates[i]["id"] for i in chosen],
                normalized_lower_bound=actual,
                normalized_upper_bound=bound,
                native=native,
            )
        )
        if bound <= best_score + gap_tolerance:
            certified = True
            break
        direction = vectors[:, 0]
        cuts.append(direction)
    selected = [candidates[i]["id"] for i in best]
    return dict(
        selected_indices=best,
        selected=selected,
        objective="maximize worst source-direction Fisher information (E-optimal)",
        certified=certified,
        minimum_eigenvalue=max(0.0, best_score) * scale
        if best_score > -math.inf
        else None,
        riding_time_s=float(costs[best].sum()),
        riding_time_budget_s=riding_time_budget_s,
        information_scale=scale,
        cuts=len(cuts),
        iterations=trace,
        elapsed_s=time.monotonic() - started,
        normalized_gap_tolerance=gap_tolerance,
        backend="LP-IP-craft native",
        wind_assumption="sectors are available observation opportunities, not controlled weather",
    )


def exhaustive_route_check(information, candidates, budget, max_candidates=16):
    f = np.asarray(information)
    require(
        len(candidates) <= max_candidates, "exhaustive verification budget exceeded"
    )
    best = -math.inf
    chosen = []
    for bits in itertools.product((0, 1), repeat=len(candidates)):
        idx = [i for i, b in enumerate(bits) if b]
        if sum(candidates[i]["riding_time_s"] for i in idx) > budget + 1e-9:
            continue
        eigen = float(
            np.linalg.eigvalsh(f[idx].sum(axis=0) if idx else np.zeros_like(f[0]))[0]
        )
        if eigen > best:
            best = eigen
            chosen = idx
    return dict(
        optimum_minimum_eigenvalue=max(0.0, best),
        selected_indices=chosen,
        checked_patterns=2 ** len(candidates),
    )
