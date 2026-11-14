# Compute a flow
<!-- check: rel=1e-4 -->

At the end of this chapter you have computed a velocity and pressure field,
steady and transient, and compared it with a published numerical reference.
You need the `cfd-craft` command, a checkout and its Python requirements
([chapter 3](03-cli-and-archive.md)).

## Setup

Commands run from the root of a checkout with `cfd-craft` on `PATH`. The case
is the lid-driven cavity at Reynolds number 100,
`cases/verification/lid-cavity.json`. It is committed as a transient case.
This block writes a steady copy on one thread and checks it:

```bash
mkdir -p runs
```

```python
import json

case = json.load(open("cases/verification/lid-cavity.json"))
case["name"] = "cavity-steady"
case["run"]["mode"] = "steady"
case["run"]["threads"] = 1
json.dump(case, open("runs/cavity-steady.json", "w"), indent=2)
```

```bash
cfd-craft check runs/cavity-steady.json > runs/cavity-steady.check.json
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## The case: walls, a moving lid, one periodic direction

Until now the wind was prescribed. Here `flow.kind` is `laminar`: the solver
computes velocity and pressure of an incompressible fluid with constant
viscosity. These are the fields of the case that matter:

```python
import json

case = json.load(open("runs/cavity-steady.json"))
for key in ("domain", "grid", "boundaries", "flow", "moving_walls"):
    print(key, "=", json.dumps(case[key]))
```

```text
domain = {"size_m": [1.0, 1.0, 1.0]}
grid = {"cells": [24, 2, 24]}
boundaries = {"x": "wall", "y": "periodic", "z": "wall"}
flow = {"kind": "laminar", "initial_velocity_m_s": [0.0, 0.0, 0.0], "viscosity_m2_s": 0.01, "acceleration_m_s2": [0.0, 0.0, 0.0]}
moving_walls = [{"axis": 2, "upper": true, "velocity_m_s": [1.0, 0.0, 0.0]}]
```

- The box is 1 m x 1 m x 1 m. x and z end in no-slip walls. y is periodic, so
  the flow is two-dimensional in the x-z plane, with z up.
- `moving_walls` makes the upper z wall (`axis` 2, `upper` true) slide at
  1 m/s along x. This is the lid.
- With a lid speed of 1 m/s, a box of 1 m and `viscosity_m2_s` of 0.01, the
  Reynolds number is 100.
- The grid has 24 x 2 x 24 uniform cells.

Velocity components are stored on cell faces and pressure in cell centers (a
staggered grid). Pressure is kinematic pressure, p / rho, in m2/s2.

## Run to a steady state

```bash
cfd-craft run runs/cavity-steady.json --output runs/cavity-steady > /dev/null
```

```python
import json

s = json.load(open("runs/cavity-steady/summary.json"))
print(s["termination"], s["assessment"], s["model_scope"])
print([check["name"] for check in s["checks"]])
print(f"velocity_max = {s['velocity_max_m_s']:.6g} m/s")
print(s["steps"] > 1000, s["pressure_iterations"] > s["steps"])
```

```text
completed steady_discrete_solution incompressible_laminar
['local_continuity', 'boundary_volume_balance', 'steady_momentum_equations', 'monitor_stability']
velocity_max = 0.858562 m/s
True True
```

The run is numerically accepted. For a flow, the steady checks are continuity,
the boundary balance, the residual of the momentum equations and the stability
of the monitored values.

With the default numerics a steady run marches explicit time steps until those
checks pass. It needs about 2,000 steps here, each with a pressure solve, and
takes 6 to 8 s on the documentation host. `run.end_time_s` does not bound a
steady run; `run.max_steps` and `run.wall_time_limit_s` do. The
`physical_time_s` of a steady result is pseudo-time, not a physical duration.
[Chapter 9](09-opt-in-numerics.md) shows opt-in numerics that reach the same
state in far fewer iterations.

## Transient mode completes an interval

The committed case has `run.mode` set to `transient` and `run.end_time_s` to
30. A transient run integrates exactly that physical interval and ends as
`completed / transient_interval_completed` when the conservation checks pass.
It does not test whether the flow has stopped changing. That is your
judgment, or a steady run. The next section runs the committed transient
case.

## Compare with a numerical reference

Ghia, Ghia and Shin (1982) tabulate the horizontal velocity on the vertical
centerline of this cavity. `validation/cavity.py` runs the committed case,
interpolates the computed profile to their stations and reports the largest
difference in units of the lid speed. It takes 14 to 21 s on the
documentation host.

```bash
python validation/cavity.py --output runs/cavity-ghia > /dev/null
```

```python
import json

report = json.load(open("runs/cavity-ghia/report.json"))
print(report["passed"], report["grid"], report["target_max"])
print(f"largest difference = {report['maximum_centerline_absolute_error']:.4g}")
```

```text
True [24, 2, 24] 0.06
largest difference = 0.02755
```

The difference is below the fixed limit of 0.06 for this coarse grid. The
reference is itself a numerical solution on a fine grid, so this is a
numerical verification of the flow solver. It is not an experiment and says
nothing about street canyons. The script also writes `cavity.png` with both
profiles. The default momentum scheme is first order. The committed
[matched accuracy](../evidence/matched-accuracy.md) record reports 0.0276 for
it and 0.0054 for the opt-in second-order scheme of chapter 9, in steady mode
on a 24 x 24 grid.

## What the pressure step does

Each step first advances the velocity without the new pressure and then
projects it: a pressure equation is solved so that the corrected face
velocities are divergence free. The same discrete divergence and gradient are
used in the equation and in the correction. A region of fluid that no open
boundary touches, like this cavity, determines pressure only up to a
constant; the solver fixes the mean to zero in each such region. The pressure
equation is solved by conjugate gradients with an incomplete Cholesky
preconditioner, to `numerics.pressure_relative_tolerance`.

A result records the pressure work (`pressure_iterations`) and, as separate
checks, the continuity of the final face velocities and the balance of the
boundary fluxes. The pressure solver can also be tested alone on the grid of
a case. `verify` builds a known pressure field, applies the operator and
solves for the field again:

```bash
cfd-craft verify cases/verification/pressure.json \
  | python -c "import json, sys; v = json.load(sys.stdin); print(v['fixture'], v['passed'])"
```

```text
pressure_discrete_recovery True
```

`verify` exits 0 when the fixture passes and 2 when it fails. It tests the
pressure solve on that grid, not the flow of the case.

## Two-dimensional runs

A periodic axis may have a single cell. The faces along that axis then join a
cell to itself and carry no flux, so the run is two-dimensional:

```python
import json

case = json.load(open("runs/cavity-steady.json"))
case["name"] = "cavity-2d"
case["grid"]["cells"] = [24, 1, 24]
json.dump(case, open("runs/cavity-2d.json", "w"), indent=2)
```

```bash
cfd-craft run runs/cavity-2d.json --output runs/cavity-2d \
  | python -c "import json, sys; s = json.load(sys.stdin); print(s['assessment'], f\"{s['velocity_max_m_s']:.6g}\")"
```

```text
steady_discrete_solution 0.858562
```

The maximum speed agrees with the two-cell run above to the printed digits,
at about half the work. Every other axis needs at least two cells.

## Next

- [Chapter 7](07-budgets-preview-cancel.md): estimate, bound and stop a run
  before you spend compute on it.
- [Chapter 9](09-opt-in-numerics.md): the defaults used here are first order
  and explicit; the opt-in choices are faster and more accurate on this case.
- [Flow model card](../model-cards/flow.md): what the flow model assumes.
