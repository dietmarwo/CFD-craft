# The case file
<!-- check: rel=1e-4 -->

At the end of this chapter you can read every group of a case, change a case
safely and look up the allowed fields yourself. You need the Python binding of
[chapter 1](01-first-run.md): `python -m pip install cfd-craft`.

## Setup

Save the case of chapter 1 as `point-source.json` in an empty directory:

<!-- file: point-source.json = examples/manual/point-source.json -->
```json
{
  "schema_version": "cfd-craft.case/0.1",
  "name": "manual-point-source",
  "domain": {"size_m": [8.0, 4.0, 4.0]},
  "grid": {"cells": [16, 8, 8]},
  "boundaries": {"x": "open", "y": "periodic", "z": "periodic"},
  "flow": {"kind": "prescribed_uniform", "velocity_m_s": [1.0, 0.0, 0.0]},
  "geometry": [],
  "constituents": [{"id": "tracer", "diffusivity_m2_s": 0.05}],
  "initial_conditions": [],
  "sources": [{"kind": "point", "id": "S0", "constituent": "tracer",
    "point_m": [1.0, 2.0, 2.0], "rate_kg_s": 1e-7}],
  "receptors": [{"kind": "volume_average", "id": "R_down",
    "min_m": [5.0, 1.0, 1.0], "max_m": [6.0, 3.0, 3.0]}],
  "numerics": {
    "transport": "linear_upwind", "max_time_step_s": 0.1,
    "advective_cfl_max": 0.4, "pressure_relative_tolerance": 1e-10,
    "pressure_max_iterations": 1200, "steady_residual_tolerance": 1e-5,
    "steady_monitor_tolerance": 0.001, "monitor_window": 30
  },
  "run": {"mode": "steady", "end_time_s": 2.0, "max_steps": 2000,
    "wall_time_limit_s": 120.0, "threads": 1, "memory_limit_mib": 256},
  "output": {"fields": true, "checkpoint": true, "max_total_mib": 16}
}
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## The groups of a case

Nothing outside the case file configures the solver. Its top-level fields are:

| Fields | What they hold |
|---|---|
| `schema_version`, `name` | Version of the case format; a label copied into the result |
| `domain`, `grid` | Lengths of the box in meters; three cell counts |
| `boundaries` | One condition per axis: `periodic`, `open`, `wall`, `slip` or, for z, `ground_open_top` |
| `flow`, `moving_walls` | Prescribed, laminar or neutral-RANS flow; moving lids |
| `geometry` | Solid boxes (buildings), each with an ID |
| `constituents`, `initial_conditions` | Passive gases with their diffusivity; their starting concentration |
| `sources`, `receptors` | Where mass enters and where concentration is reported, each with an ID |
| `numerics` | Schemes, time step limit, tolerances, monitor window |
| `run` | Mode (`steady` or `transient`), endpoint, and the budgets for steps, wall time, threads and memory |
| `output` | Whether fields and a checkpoint are kept; the output budget |

The six lists (`moving_walls`, `geometry`, `constituents`,
`initial_conditions`, `sources`, `receptors`) are empty when omitted, and the
opt-in numerics of [chapter 9](09-opt-in-numerics.md) have defaults. Every
other field is required. The [case schema](../reference/case-schema.md) lists
each field with its type, default and meaning.

## Units and coordinates

Every quantity has one unit, and the field name carries it. Nothing is
converted silently. This case uses:

| Field | Unit or convention |
|---|---|
| `size_m`, `point_m`, `min_m`, `max_m` | meters; x east, y north, z up |
| `velocity_m_s` | m/s |
| `diffusivity_m2_s` | m2/s |
| `rate_kg_s` | kg/s |
| `end_time_s`, `max_time_step_s`, `wall_time_limit_s` | seconds |
| `receptors_kg_m3` (in the result) | kg/m3; multiply by 1e9 for micrograms/m3 |

The grid is uniform: the cell size is the domain length divided by the cell
count, here 8 m / 16 = 0.5 m along x and 4 m / 8 = 0.5 m along y and z. There
is no mesh file and no mesh generator. The full table is in
[units and conventions](../reference/units-and-conventions.md).

## Change a case without touching the original

Load the case, change a copy, give the copy a new name and check it. Here one
copy has half the source rate and another has only a smaller step budget.

```python
import copy
import json
import cfd_craft as cfd

def r_down(result):
    tracer = next(c for c in result["constituents"] if c["id"] == "tracer")
    return tracer["receptors_kg_m3"]["R_down"]

case = json.load(open("point-source.json"))
half = copy.deepcopy(case)
half["name"] = "point-half-rate"
half["sources"][0]["rate_kg_s"] *= 0.5
budget = copy.deepcopy(case)
budget["name"] = "point-other-budget"
budget["run"]["max_steps"] = 1000
print(cfd.check(half)["valid"], cfd.check(budget)["valid"])
base, changed, same = (cfd.simulate(c) for c in (case, half, budget))
print(changed["assessment"])
print(f"ratio = {r_down(changed) / r_down(base):.6g}")
print(changed["physics_sha256"] == base["physics_sha256"])
print(same["physics_sha256"] == base["physics_sha256"])
```

```text
True True
steady_discrete_solution
ratio = 0.5
False
True
```

Half the rate gives half the concentration, and the run is numerically
accepted. Every result carries `physics_sha256`, a hash of the physical
problem: grid, flow, sources, receptors and numerics. A changed source is a
different problem (`False`). A changed budget is not (`True`): `name`, `run`
and `output` are not part of the hash, which is what lets a checkpoint continue
under another budget ([chapter 8](08-checkpoint-restart.md)).

## A wrong field is an error

A field name from another CFD package is not accepted, and nothing is ignored.
The coordinate of a point source is `point_m`. Rename it to `position_m`:

```python
import json
import cfd_craft as cfd

bad = json.load(open("point-source.json"))
bad["sources"][0]["position_m"] = bad["sources"][0].pop("point_m")
report = cfd.check(bad)
print(report["valid"], [(d["code"], d["path"]) for d in report["diagnostics"]])
try:
    cfd.simulate(bad)
except cfd.CfdError as error:
    print("CfdError", [(d["code"], d["path"]) for d in error.diagnostics])
```

```text
False [('CFD-E000', 'sources[0]')]
CfdError [('CFD-E000', 'sources[0]')]
```

`check` returns the diagnostic; `simulate` raises `CfdError` with the same
diagnostics and never starts, so a typo cannot run silently with a default.
Each diagnostic has a `code`, a `severity`, the `path` of the offending element
and a `message`. Use code and path in programs; the message is for people and
here names the allowed fields. All codes: [diagnostics](../diagnostics.md).

## Find the allowed fields

`describe` returns the schemas of the installed version, generated from the
types the solver uses.

```python
import cfd_craft as cfd

described = cfd.describe()
schema = described["case_schema"]
definitions = schema["definitions"]
print([kind["properties"]["kind"]["enum"][0] for kind in definitions["Flow"]["oneOf"]])
print(definitions["Advection"]["enum"])
print("termination" in described["result_schema"]["properties"])
```

```text
['prescribed_uniform', 'laminar', 'neutral_rans']
['linear_upwind', 'muscl']
True
```

These are the three flow kinds, the two schemes of `numerics.transport`, and a
test that the result schema describes the summary. Both are JSON Schema
(draft-07): with the `jsonschema` package, `jsonschema.validate(case, schema)`
checks names and types in your own tool. Ranges, units, geometry and budgets
are checked only by `check`.

## Next

- [Chapter 3](03-cli-and-archive.md): the command line and the files of a run.
- [Chapter 5](05-sources-receptors-transport.md): sources, receptors, schemes.
