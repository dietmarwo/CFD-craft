#!/usr/bin/env python3
"""Translating Taylor–Green, momentum conservation and a 1000-step stability baseline.

Analytic fields initialize generated, checksummed public-contract checkpoints.
These are verification initial conditions, not evidence of prior physical runs.
Donor-cell's order and nonconservative drift are measured, not corrected here.
"""

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tutorials"))
from common import accepted, run_case, write_report

OFFSET = np.array([0.7, 0.2, 0.3])
PHASE = np.array([0.137, 0.271])
AMPLITUDE = 0.2
VISCOSITY = 0.005
END_TIME = 0.05
DT = 0.0005


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-B007 momentum.{field}: {message}")


def case_for(cells, dt, viscosity=VISCOSITY):
    c = json.loads((ROOT / "cases/verification/poiseuille.json").read_text())
    c["grid"]["cells"] = list(cells)
    c["boundaries"] = dict(x="periodic", y="periodic", z="periodic")
    c["flow"].update(viscosity_m2_s=viscosity, acceleration_m_s2=[0.0] * 3)
    c["numerics"].update(max_time_step_s=dt, pressure_preconditioner="multigrid")
    c["run"].update(threads=1, end_time_s=END_TIME, wall_time_limit_s=120.0)
    return c


def face_coordinates(cells, axis):
    """Periodic native face order: axis, z, y, x; no duplicate endpoint faces."""
    nx, ny, nz = cells
    z, y, x = np.meshgrid(
        (np.arange(nz) + (0.0 if axis == 2 else 0.5)) / nz,
        (np.arange(ny) + (0.0 if axis == 1 else 0.5)) / ny,
        (np.arange(nx) + (0.0 if axis == 0 else 0.5)) / nx,
        indexing="ij",
    )
    return x, y, z


def exact_vortex(cells, time_s):
    values = []
    decay = AMPLITUDE * math.exp(-8 * math.pi**2 * VISCOSITY * time_s)
    for axis in range(3):
        x, _, z = face_coordinates(cells, axis)
        xx = 2 * math.pi * (x - OFFSET[0] * time_s) + PHASE[0]
        zz = 2 * math.pi * (z - OFFSET[2] * time_s) + PHASE[1]
        perturbation = (
            decay * np.sin(xx) * np.cos(zz)
            if axis == 0
            else -decay * np.cos(xx) * np.sin(zz)
            if axis == 2
            else np.zeros_like(x)
        )
        values.append((OFFSET[axis] + perturbation).ravel())
    return np.concatenate(values)


def norms(values):
    values = np.asarray(values, dtype=float)
    require(
        values.size > 0 and np.isfinite(values).all(),
        "norms",
        "finite nonempty array required",
    )
    return dict(
        l1=float(np.mean(np.abs(values))),
        l2=float(np.sqrt(np.mean(values**2))),
        linf=float(np.max(np.abs(values))),
    )


def orders(grids, errors):
    require(
        len(grids) == len(errors) and len(grids) >= 2,
        "orders",
        "paired grid/error records required",
    )
    require(
        all(type(n) is int and n > 0 for n in grids),
        "orders.grids",
        "positive integers required",
    )
    result = {}
    for key in ("l1", "l2", "linf"):
        e = [error[key] for error in errors]
        require(
            all(math.isfinite(v) and v > 0 for v in e),
            "orders.errors",
            "finite positive errors required",
        )
        result[key] = float(
            np.polyfit(np.log(1 / np.array(grids, dtype=float)), np.log(e), 1)[0]
        )
    return result


def momentum_change(initial, final, cells):
    count = math.prod(cells)
    volume = 1.0 / count
    before = np.array(initial).reshape(3, count)
    after = np.array(final).reshape(3, count)
    return [
        dict(
            component=axis,
            initial=float(np.sum(a) * volume),
            final=float(np.sum(b) * volume),
            normalized_change=float(
                abs(np.sum(b - a)) / max(np.sum(np.abs(a)), 1e-300)
            ),
        )
        for axis, (a, b) in enumerate(zip(before, after, strict=True))
    ]


def initialize(binary, case, velocity, output, label, report):
    seed_case = copy.deepcopy(case)
    seed_case["name"] = label + "-seed"
    seed_case["run"]["end_time_s"] = 1e-9
    seed = run_case(binary, seed_case, output / seed_case["name"])
    report["runs"].append(seed)
    require(accepted(seed), label + ".seed", "seed state generation failed")
    wrapper = json.loads((output / seed_case["name"] / "checkpoint.json").read_text())
    state = json.loads(wrapper["payload"])
    require(
        len(state["velocity"]) == len(velocity),
        label + ".initial",
        "face count differs",
    )
    state.update(
        time_s=0.0,
        steps=0,
        monitor_history=[],
        pressure_iterations=0,
        velocity=np.asarray(velocity).tolist(),
        pressure=[0.0] * math.prod(case["grid"]["cells"]),
    )
    wrapper["payload"] = json.dumps(state, separators=(",", ":"), allow_nan=False)
    wrapper["payload_sha256"] = hashlib.sha256(wrapper["payload"].encode()).hexdigest()
    checkpoint = output / (label + "-initial.json")
    checkpoint.write_text(json.dumps(wrapper, allow_nan=False) + "\n")
    return checkpoint


def vortex_trial(binary, output, n, dt, label, report):
    c = case_for([n, 2, n], dt)
    c["name"] = label
    initial = exact_vortex(c["grid"]["cells"], 0)
    checkpoint = initialize(binary, c, initial, output, label, report)
    row = dict(
        grid=n,
        max_dt_s=dt,
        initial_checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
    )
    report["vortices"].append(row)
    run = run_case(binary, c, output / label, restart=checkpoint)
    report["runs"].append(run)
    row.update(accepted=accepted(run), run_directory=label)
    require(row["accepted"], label + ".run", "vortex solve/audit failed")
    final = np.array(
        json.loads((output / label / "fields.json").read_text())["velocity"]
    )
    time_s = run["summary"]["physical_time_s"]
    exact = exact_vortex(c["grid"]["cells"], time_s)
    indices = np.r_[0 : 2 * n * n, 4 * n * n : 6 * n * n]
    row.update(
        error=norms((final - exact)[indices]),
        steps=run["summary"]["steps"],
        solver_s=run["summary"]["elapsed_s"],
        physical_time_s=time_s,
        momentum=momentum_change(initial, final, c["grid"]["cells"]),
        initial_cell_peclet=(OFFSET[0] + AMPLITUDE) / (n * VISCOSITY),
    )
    require(
        row["steps"] == round(END_TIME / dt),
        label + ".steps",
        "stable time cap was not the actual fixed timestep",
    )
    return row, final[indices]


def stability_trial(binary, output, report):
    c = case_for([64, 2, 2], 1.0, viscosity=1e-8)
    c["name"] = "transverse-step"
    c["numerics"]["advective_cfl_max"] = 0.45
    c["run"].update(max_steps=1000, end_time_s=100.0)
    values = []
    for axis in range(3):
        x, _, _ = face_coordinates(c["grid"]["cells"], axis)
        values.append(
            (
                np.ones_like(x)
                if axis == 0
                else ((x < 0.5).astype(float) if axis == 1 else np.zeros_like(x))
            ).ravel()
        )
    initial = np.concatenate(values)
    checkpoint = initialize(binary, c, initial, output, c["name"], report)
    run = run_case(binary, c, output / c["name"], restart=checkpoint)
    report["runs"].append(run)
    summary = run["summary"] or {}
    require(
        run["returncode"] == 2
        and summary.get("termination") == "iteration_limit"
        and summary.get("steps") == 1000
        and run["independent"]["passed"],
        "stability.run",
        "expected an audited 1000-step iteration-limited run",
    )
    velocity = np.array(
        json.loads((output / c["name"] / "fields.json").read_text())["velocity"]
    )
    v = velocity.reshape(3, -1)[1]
    report["stability"] = dict(
        steps=1000,
        termination=summary["termination"],
        numerical_accepted=accepted(run),
        initial_min=0.0,
        initial_max=1.0,
        final_min=float(v.min()),
        final_max=float(v.max()),
        new_extrema=max(0.0, float(-v.min()), float(v.max() - 1.0)),
        final_max_abs_growth=float(np.abs(v).max() - 1.0),
        advective_cfl_max=0.45,
        initial_advective_rate_s_inv=66.0,
        initial_dt_s=0.45 / (66.0 + 2e-8 * (64**2 + 2**2 + 2**2)),
        mean_dt_s=summary["physical_time_s"] / 1000,
        momentum=momentum_change(initial, velocity, c["grid"]["cells"]),
        meaning="baseline at the unchanged cap; intentional work limit is not numerical acceptance",
    )


def campaign(binary, output):
    output = Path(output)
    output.mkdir()
    report = dict(
        schema_version="cfd-craft.momentum-accuracy/0.1",
        passed=False,
        runs=[],
        vortices=[],
        plan=dict(
            grids=[16, 32, 64],
            dt_s=DT,
            time_refinement_dt_s=[DT, DT / 2, DT / 4],
            offset=OFFSET.tolist(),
            amplitude=AMPLITUDE,
            phase=PHASE.tolist(),
            viscosity_m2_s=VISCOSITY,
            final_time_s=END_TIME,
            momentum_change_gate=None,
            future_conservative_gate_per_100_steps=1e-13,
        ),
    )
    write_report(output, report)
    try:
        spatial = [
            vortex_trial(binary, output, n, DT, f"vortex-{n}", report)
            for n in [16, 32, 64]
        ]
        fine, values = spatial[-1]
        time_trials = [
            vortex_trial(binary, output, 64, DT / divisor, f"time-{divisor}", report)
            for divisor in [2, 4]
        ]
        differences = [
            norms(values - time_trials[0][1]),
            norms(time_trials[0][1] - time_trials[1][1]),
        ]
        ratio = differences[-1]["l1"] / fine["error"]["l1"]
        report.update(
            spatial_orders=orders([16, 32, 64], [r[0]["error"] for r in spatial]),
            temporal=dict(
                differences=differences,
                difference_order=math.log(differences[0]["l1"] / differences[1]["l1"])
                / math.log(2),
                fine_difference_over_spatial_error=ratio,
                maximum_ratio=0.01,
            ),
        )
        require(
            ratio < 0.01,
            "temporal",
            "time error is not negligible relative to spatial error",
        )
        stability_trial(binary, output, report)
        report["passed"] = True
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        IndexError,
        ZeroDivisionError,
        subprocess.SubprocessError,
    ) as exc:
        report["error"] = (
            str(exc)
            if str(exc).startswith("CFD-")
            else f"CFD-B007 momentum.campaign: {exc}"
        )
    write_report(output, report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/cfd-craft")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        report = campaign(args.binary.resolve(), args.output)
    except (ValueError, OSError) as exc:
        print(f"CFD-B007 momentum.output: {exc}")
        return 1
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "runs"}, indent=2, allow_nan=False
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
