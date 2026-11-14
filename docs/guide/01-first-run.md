# First run
<!-- check: rel=1e-4 -->

At the end of this chapter you have one numerically accepted result and one
concentration with a unit, computed from Python. You need Python 3.10 or newer
and nothing else: no checkout and no Rust.

## Setup

Install the Python binding (wheels for Linux x86_64, Windows x64 and macOS):

```sh
python -m pip install cfd-craft
```

Save this case as `point-source.json` in an empty directory. It is the whole input.

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

The box is 8 m x 4 m x 4 m with 16 x 8 x 8 = 1,024 cells. The wind is
prescribed (1 m/s along x), so no flow is computed. A point source emits
1e-7 kg/s of a passive tracer at (1, 2, 2) m. The box-shaped receptor `R_down`
averages the concentration from x = 5 m to 6 m, downstream of the source. The
run is steady: it stops when the concentration no longer changes. This is a
synthetic example, not a calibrated pollution scenario.

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## Check the case

`check` validates a case and counts its cells without solving anything.

```python
import json
import cfd_craft as cfd

case = json.load(open("point-source.json"))
report = cfd.check(case)
print(report["valid"], report["cells"], len(report["diagnostics"]))
```

```text
True 1024 0
```

The case is valid, with 1,024 cells and no diagnostics. Check before every run.

## Run it

`simulate` solves the case in this process and returns a summary dictionary.

```python
import json
import cfd_craft as cfd

case = json.load(open("point-source.json"))
result = cfd.simulate(case)
for key in ("termination", "assessment", "experimental_validation"):
    print(result[key])
```

```text
completed
steady_discrete_solution
not_validated; see validation/data-inventory.json
```

These three fields answer three different questions. Read all three before you
use a number; [chapter 4](04-reading-a-result.md) shows them on runs that stop
early.

- `termination`: why the run stopped. `completed` means it reached its goal,
  not a step limit, a time limit or a cancellation.
- `assessment`: what the numerical checks support. `steady_discrete_solution`
  means the discrete equations on this grid are solved, so the run is
  numerically accepted.
- `experimental_validation`: whether the model was compared with measurements
  for this use. In version 0.1.0 no result is.

## Read a receptor

Concentrations are in kg/m3. Multiply by 1e9 for micrograms/m3.

```python
import json
import cfd_craft as cfd

result = cfd.simulate(json.load(open("point-source.json")))
tracer = next(c for c in result["constituents"] if c["id"] == "tracer")
value = tracer["receptors_kg_m3"]["R_down"]
print(f"R_down = {value * 1e9:.6g} micrograms/m3")
```

```text
R_down = 17.8118 micrograms/m3
```

Look up a constituent by its `id` and a receptor by its ID, never by position:
the receptor map is sorted as text, so `R10` comes before `R2`. A `null`
(`None` in Python) means "not available in this context", not zero.

## The same from the shell

The package installs a small command that prints the same report and summary
as JSON.

```bash
python -m cfd_craft check point-source.json > check.json
python -m cfd_craft simulate point-source.json > summary.json
echo "exit $?"
```

```text
exit 0
```

Exit 0 means a valid case or an accepted run, 1 invalid input, 2 a run that is
not numerically accepted. Fields and archives need the `cfd-craft` command.

## Next

- [Chapter 2](02-case-file.md): what is in the case file and how to change it.
- [Chapter 3](03-cli-and-archive.md): the `cfd-craft` command and run archives.
