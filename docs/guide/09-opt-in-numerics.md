# Opt-in numerics
<!-- check: rel=1e-4 -->

At the end of this chapter you have switched on second-order momentum
advection, the implicit steady iteration and multigrid, and seen that the
acceptance checks do not move. You need the `cfd-craft` command, a checkout
and its Python requirements ([chapter 3](03-cli-and-archive.md)).

## Setup

Commands run from the root of a checkout with `cfd-craft` on `PATH`. The setup
writes four copies of the steady cavity of [chapter 6](06-flow-cavity.md).
Each copy adds options to the one before it:

```bash
mkdir -p runs
```

```python
import json

case = json.load(open("cases/verification/lid-cavity.json"))
case["run"].update(mode="steady", threads=1)
copies = {
    "second": {"momentum_advection": "limited_upwind", "momentum_limiter": "van_leer"},
    "implicit": {"steady_algorithm": "implicit_projection"},
    "recipe": {"pressure_relative_tolerance": 0.1, "max_time_step_s": 100},
    "recipe-mg": {"pressure_preconditioner": "multigrid"},
}
for name, options in copies.items():
    case["name"] = f"cavity-{name}"
    case["numerics"].update(options)
    if name == "recipe":
        case["grid"]["cells"] = [24, 1, 24]  # one span cell, see chapter 6
    json.dump(case, open(f"runs/{name}.json", "w"), indent=2)
```

The setup also runs the second-order copy (8 to 11 s on the documentation host):

```bash
cfd-craft run runs/second.json --output runs/second > /dev/null
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## The defaults and why they stay

| Field of `numerics` | Default | Opt-in values |
|---|---|---|
| `momentum_advection` | `donor_cell` (first order) | `second_order_upwind`, `limited_upwind` |
| `momentum_limiter` | none | `van_albada`, `van_leer`, `monotonized_central` |
| `steady_algorithm` | `explicit` | `implicit_viscous`, `implicit_projection` |
| `pressure_preconditioner` | `ic0` | `multigrid` |

A case that names none of these fields runs exactly as it did before they
existed, and its hashes and checkpoints stay valid. Every option is part of
the physics hash. The options are opt-in: nothing selects them for you, and a
change of defaults is an open item of the [roadmap](../developer/roadmap.md).

## Second-order momentum advection

`limited_upwind` replaces the first-order donor-cell flux of the momentum
equations with a conservative second-order upwind flux and a slope limiter;
`second_order_upwind` has no limiter. A limiter is required with
`limited_upwind` and not allowed otherwise (`CFD-E037`). The setup's run:

```python
import json

s = json.load(open("runs/second/summary.json"))
print(s["termination"], s["assessment"])
print([check["name"] for check in s["checks"]])
print(f"velocity_max = {s['velocity_max_m_s']:.5g} m/s", s["steps"] > 2000)
```

```text
completed steady_discrete_solution
['local_continuity', 'boundary_volume_balance', 'steady_momentum_equations', 'monitor_stability']
velocity_max = 0.86857 m/s True
```

It is accepted by the same four checks as the default run of chapter 6. The
solution differs: the maximum speed is 0.86857 m/s, against 0.85856 m/s first
order. The committed [matched accuracy](../evidence/matched-accuracy.md)
record gives the difference from the Ghia reference as 0.0276 for the default
and 0.0054 for this scheme on a 24 x 24 grid. It works with all boundary
kinds, buildings and `neutral_rans`, and leaves `numerics.transport` alone.

## Implicit steady iteration

The explicit steady mode marches small time steps. `implicit_projection` takes
one implicit momentum correction and one projection per outer iteration.

```bash
cfd-craft run runs/implicit.json --output runs/implicit > /dev/null
```

```python
import json

explicit = json.load(open("runs/second/summary.json"))
implicit = json.load(open("runs/implicit/summary.json"))
print(implicit["termination"], implicit["assessment"])
print(explicit["steps"] > 2000, implicit["steps"] < 400)
key = "momentum_solver_iterations"
print(key in explicit, key in implicit)
```

```text
completed steady_discrete_solution
True True
False True
```

The implicit run is accepted by the same checks after a few hundred outer
iterations, where the explicit run needs more than 2,000 steps: about 0.5 s
against 8 to 11 s on the documentation host
([implicit steady results](../evidence/implicit-steady.md)). `steps` now
counts outer iterations and `momentum_solver_iterations` the inner iterations
of the momentum solves; an explicit run omits that field. The implicit
algorithms need steady mode (`CFD-E045`) and a computed flow (`CFD-E047`).
`implicit_viscous` treats only viscosity implicitly, for laminar flow.

## The implicit recipe

Two more settings shorten the path to the same steady state: a loose inner
pressure tolerance (`pressure_relative_tolerance` 0.1) and a step cap that no
longer binds (`max_time_step_s` 100).

```bash
cfd-craft run runs/implicit.json --output runs/implicit > /dev/null
cfd-craft run runs/recipe.json --output runs/recipe > /dev/null
```

```python
import json

speeds = []
for name in ("second", "implicit", "recipe"):
    s = json.load(open(f"runs/{name}/summary.json"))
    speeds.append(s["velocity_max_m_s"])
    print(f"{name:8} {s['assessment']}  velocity_max = {speeds[-1]:.5g} m/s")
print((max(speeds) - min(speeds)) / min(speeds) < 1e-4)
```

```text
second   steady_discrete_solution  velocity_max = 0.86857 m/s
implicit steady_discrete_solution  velocity_max = 0.86857 m/s
recipe   steady_discrete_solution  velocity_max = 0.86857 m/s
True
```

All three runs are accepted and agree within the tolerance of this page. The
recipe changes the path of the iteration, not the steady state or the checks.
It takes about 0.1 s on the documentation host. Two cautions: a recipe run
that is stopped early is only loosely divergence free and fails
`check_fields.py`, and the gain is measured on this cavity and the coarse
canyon of chapter 10 ([implicit RANS results](../evidence/implicit-rans.md)).

## Multigrid for the pressure equation

```bash
cfd-craft run runs/recipe.json --output runs/recipe > /dev/null
cfd-craft run runs/recipe-mg.json --output runs/recipe-mg > /dev/null
```

```python
import json

ic0 = json.load(open("runs/recipe/summary.json"))
mg = json.load(open("runs/recipe-mg/summary.json"))
print(mg["assessment"], mg["pressure_iterations"] < ic0["pressure_iterations"])
print(abs(mg["velocity_max_m_s"] / ic0["velocity_max_m_s"] - 1) < 1e-4)
```

```text
steady_discrete_solution True
True
```

`multigrid` preconditions the same pressure equation and needs fewer pressure
iterations for the same result. It costs setup time and memory, so compare
total run times; on this small grid they are equal on the documentation host.
A case with `geometry` is rejected (`CFD-E034`), with no silent fallback. See
[pressure multigrid](../developer/pressure-multigrid.md), also for `CFD-W004`.

## Where the time goes: `profile`

`profile` runs a case like `run` and records the time of each solver phase.

```bash
cfd-craft profile runs/recipe.json --output runs/profile > /dev/null
python validation/check_profile.py runs/profile > runs/profile-check.json
```

```python
import json

checked = json.load(open("runs/profile-check.json"))
for key in ("integrity_passed", "numerical_accepted", "physical_qualification"):
    print(key, checked[key])
timing = json.load(open("runs/profile/profile.json"))["timing"]
print(timing["accounted_exclusive_s"] <= timing["elapsed_s"])
```

```text
integrity_passed True
numerical_accepted True
physical_qualification False
True
```

`runs/profile` holds the ordinary run archive in `run/` and `profile.json`.
Each phase has calls, inclusive and exclusive seconds. Phases nest, so add
exclusive times only. `check_profile.py` ties the profile to its archive and
runs the field audit. `physical_qualification` is always `false`: a timing is
not a validation. See [profiling](../developer/profiling.md).

## With turbulence and a tracer

`implicit_projection` also runs `neutral_rans` cases and constituents
([chapter 10](10-street-canyon.md)). Constituents advance in at most 16
explicit sub-steps per outer iteration and can cover less pseudo-time than the
flow (`scalar_time_s`). Their steady state and its checks are unchanged.

## Next

- [Chapter 10](10-street-canyon.md): buildings, turbulence and a line source.
- [Flow model card](../model-cards/flow.md) and [comparison](../comparison.md).
