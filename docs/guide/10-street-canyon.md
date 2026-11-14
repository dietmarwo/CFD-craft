# Buildings and a street canyon
<!-- check: rel=1e-4 -->

At the end of this chapter you have run a street between two buildings with a
turbulence model and a line source, read its warnings, and can say what the
result supports. You need the `cfd-craft` command, a checkout and its Python
requirements ([chapter 3](03-cli-and-archive.md)). The grid of this case is
too coarse for a physical claim: every concentration here is a workflow
example, not a prediction.

## Setup

Commands run from the root of a checkout with `cfd-craft` on `PATH`. Every
section reads this default-numerics run (36 to 47 s on the documentation host):

```bash
mkdir -p runs
cfd-craft run cases/canyon/wh1-wind270.json --output runs/canyon > /dev/null
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## The case: boxes, open top, wind

The case is
[`cases/canyon/wh1-wind270.json`](https://github.com/dietmarwo/CFD-craft/blob/main/cases/canyon/wh1-wind270.json):
18 m x 16 m x 6 m with 18 x 16 x 12 cells of 1 m x 1 m x 0.5 m.

- `geometry` lists solid boxes: two buildings, 1 m wide, 10 m long and 1 m
  high, with a 1 m street between them (W/H = 1). A cell is solid when its
  center lies inside a box. A box that contains no cell center is rejected
  (`CFD-E028`); it never disappears silently.
- `flow.kind` is `neutral_rans`: a neutral atmospheric boundary layer with a
  k-epsilon model and rough walls. The inlet is a logarithmic profile with
  `speed_m_s` (2 m/s) at `reference_height_m` (1 m) over `roughness_m`.
- `flow.direction_deg_from` is the meteorological wind direction: where the
  wind comes from, clockwise from north. 270 blows toward +x, across the street.
- `boundaries.z` is `ground_open_top`: rough ground and a top that carries the
  boundary-layer stress. `neutral_rans` requires it. The `open` sides become
  inlet, outlet or slip faces from the wind direction.
- The source is a line along the street at 0.15 m height: 1e-8 kg/s per meter
  over 10 m, 1e-7 kg/s in total. Four point receptors sit in the street.

## Read the warnings before the result

```bash
cfd-craft check cases/canyon/wh1-wind270.json > runs/canyon-check.json
```

```python
import json
checked = json.load(open("runs/canyon-check.json"))
print(checked["check"]["valid"], checked["check"]["cells"])
print([(d["code"], d["path"]) for d in checked["check"]["diagnostics"]])
print(*(checked["geometry"][k] for k in ("solid_cells", "box_cells", "fluid_components")))
```

```text
True 3456
[('CFD-W001', 'geometry[0]'), ('CFD-W001', 'geometry[1]'), ('CFD-W003', 'domain.size_m[0]'), ('CFD-W003', 'domain.size_m[1]'), ('CFD-W002', 'geometry')]
40 {'east': 20, 'west': 20} 1
```

The case is valid and carries five warnings. `CFD-W001`: each building spans
2 cells in height, fewer than the 10 needed for a physical interpretation.
`CFD-W003`: the clearance between buildings and domain sides is below the
COST 732 best-practice guideline along x and y. `CFD-W002`: the buildings
block more than 3 percent of the cross-section. Warnings do not stop a run;
they say what the result cannot be used for. The last line is what the grid
made of the boxes: 20 solid cells per building, one connected fluid region.

## The result

```python
import json
s = json.load(open("runs/canyon/summary.json"))
print(s["termination"], s["assessment"])
print(s["model_scope"], s["turbulent_floor_events"])
print(s["experimental_validation"])
tracer = next(c for c in s["constituents"] if c["id"] == "tracer")
print({k: f"{v * 1e9:.4g}" for k, v in tracer["receptors_kg_m3"].items()}, "micrograms/m3")
```

```text
completed steady_discrete_solution
neutral_k_epsilon_rough_wall 0
not_validated; see validation/data-inventory.json
{'sensor0': '96.5', 'sensor1': '230.7', 'sensor2': '97.09', 'sensor3': '141'} micrograms/m3
```

The run completed and is numerically accepted: continuity, the momentum and
turbulence equations, the tracer balance and the monitors pass, and no
turbulence floor was hit (one floor event would prevent acceptance). It is
not experimentally validated. The four values are what this model gives on
this grid, where the street is one column of cells. They say nothing about a
real canyon.

## Another wind direction

`cases/canyon/wh1-wind225.json` differs only in `direction_deg_from`: 225, a
south-west wind with components toward +x and +y, oblique to the street.

```bash
cfd-craft run cases/canyon/wh1-wind225.json --output runs/canyon-225 > /dev/null
```

```python
import json
for run in ("canyon", "canyon-225"):
    s = json.load(open(f"runs/{run}/summary.json"))
    values = s["constituents"][0]["receptors_kg_m3"]
    print(run, s["assessment"], [f"{values[k] * 1e9:.4g}" for k in sorted(values)])
```

```text
canyon steady_discrete_solution ['96.5', '230.7', '97.09', '141']
canyon-225 steady_discrete_solution ['28.54', '60.11', '93.7', '19.42']
```

With the oblique wind all four values are lower, and they rise along the
street from `sensor0` to `sensor2`. This shows how to do a direction study; on
this grid the numbers are not a physical result.

## The same steady state faster

The default run takes about 3,800 explicit steps. The opt-in implicit recipe
of [chapter 9](09-opt-in-numerics.md) reaches the same discrete steady state:

```python
import json
case = json.load(open("cases/canyon/wh1-wind270.json"))
case["name"] = "canyon-recipe"
case["numerics"].update(
    steady_algorithm="implicit_projection", pressure_relative_tolerance=0.1, max_time_step_s=100
)
json.dump(case, open("runs/canyon-recipe.json", "w"), indent=2)
```

```bash
cfd-craft run runs/canyon-recipe.json --output runs/canyon-recipe > /dev/null
```

```python
default, recipe = (json.load(open(f"runs/{n}/summary.json")) for n in ("canyon", "canyon-recipe"))
print(recipe["termination"], recipe["assessment"], recipe["steps"] < default["steps"] / 5)
a, b = (r["constituents"][0]["receptors_kg_m3"] for r in (default, recipe))
print(all(abs(b[k] / a[k] - 1) < 1e-4 for k in a))
```

```text
completed steady_discrete_solution True
True
```

The recipe run is accepted by the same checks, and its four sensors equal the
default ones within the tolerance of this page. On the documentation host it
takes about 2 s where the default takes 36 to 47 s. The recipe is opt-in; the
committed measurements and their limits are in
[implicit RANS results](../evidence/implicit-rans.md). A faster run on this
grid is still a run on a grid too coarse for a physical claim.

## Molecular and turbulent diffusivity

`diffusivity_m2_s` of a constituent is its molecular diffusivity. Give a trace
gas its real value, of order 1e-5 m2/s. In a `neutral_rans` case the mixing is
done by the turbulent diffusivity, the eddy viscosity over
`flow.turbulent_schmidt`. A large constant hides the effect of that number.

## All committed scenarios in one study
<!-- check: long -->

`tutorials/canyon_study.py` runs the three committed canyon cases (W/H of 1
and 2, winds from 270 and 225 degrees), audits each archive with the checker
of chapter 3 and writes a report and a figure. It runs two cases at a time
with two threads each and takes about a minute on the documentation host.

```bash
python tutorials/canyon_study.py --preset smoke --output runs/canyons > /dev/null
```

```python
import json
report = json.load(open("runs/canyons/report.json"))
print(report["passed"], report["numerical_accepted"], len(report["runs"]))
print(report["empirical_validation"], report["physical_claim"])
```

```text
True 3 3
blocked_data none
```

```sh
python tutorials/canyon_study.py --preset sensitivity --output runs/canyon-sensitivity
python tutorials/canyon_study.py --preset study --output runs/canyon-study
```

`sensitivity` adds two Schmidt numbers and a longer outlet domain. `study`
also tries two finer grids with the default numerics. In the recorded run
neither finished within its 300 s budget, so there is no grid-convergence
result; the report keeps those rows as incomplete
([native verification](../evidence/native-verification.md)).

## What this result is not

- Not resolved. Each building is one cell wide and two cells high, and the
  street is a single column of cells. No canyon vortex can form on this grid.
- Not grid-converged. No refinement study has finished, and the building-wall
  roughness depends on the cell width, so refining also changes the wall model.
- Not the CODASC wind-tunnel geometry or inflow. The boxes are illustrative.
- Not validated. The measured data could not be obtained, so no comparison
  with experiments exists.

It is evidence that the coupled flow, turbulence and tracer workflow runs,
conserves mass and reaches a steady discrete state
([flow model card](../model-cards/flow.md), [roadmap](../developer/roadmap.md)).

## A task for an agent

Give this to a coding agent that has the checkout:

> Read `docs/ai-context.md` and the flow and transport model cards. Run the
> smoke canyon workflow with no more than its two concurrent processes and two
> solver threads per process. Explain meteorological wind direction, source
> normalization, finite-canyon geometry and receptor support. For each
> scenario show the stopping reason, the independent continuity and mass
> audit, the equation residuals and the receptor values. Keep a timeout or a
> failed numerical check in the report. If capacity permits, run the
> sensitivity preset. Distinguish numerical parameter sensitivity from
> experimental validation. Consult `validation/data-inventory.json` and the
> frozen-protocol requirements before proposing a comparison with measured
> data. Return a compact report with figures and the limits of its
> interpretation. A full resolution study requires a separate explicit
> compute budget.

## Next

- [Chapter 11](11-python.md): the Python binding in depth.
- [Chapter 12](12-studies.md): many runs, response matrices, source inference.
