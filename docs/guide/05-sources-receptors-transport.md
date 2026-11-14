# Sources, receptors and transport
<!-- check: rel=1e-4 -->

At the end of this chapter you can declare emissions and sensors in the right
units and choose a transport scheme knowingly. You need a checkout and the
Python binding (`python -m pip install cfd-craft`); all runs are short.

## Setup

Run the blocks from the root of a checkout. They read the point-source case of
[chapter 1](01-first-run.md) and two cases from `cases/verification/`. Each has
one constituent, so the blocks take `constituents[0]`.

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## Three kinds of source, three rate units

| `kind` | Fields | Rate field and unit | Total emission |
|---|---|---|---|
| `point` | `point_m` | `rate_kg_s`, kg/s | the declared rate |
| `line` | `from_m`, `to_m` | `rate_kg_s_m`, kg/s per meter | rate times line length |
| `volume` | `min_m`, `max_m` | `rate_kg_s_m3`, kg/s per m3 | rate times box volume |

A line or volume rate is a density, not a total: 5e-8 kg/s/m over 2 m emits
1e-7 kg/s, and so does 5e-8 kg/s/m3 in a 1 m x 2 m x 1 m box. Save these two
objects as `line-source.json` and `volume-source.json`. The block after them
puts each in place of the point source and runs it.

<!-- check: fragment -->
<!-- file: line-source.json -->
```json
{"kind": "line", "id": "S_line", "constituent": "tracer",
 "from_m": [1, 1, 2], "to_m": [1, 3, 2], "rate_kg_s_m": 5e-8}
```

<!-- check: fragment -->
<!-- file: volume-source.json -->
```json
{"kind": "volume", "id": "S_volume", "constituent": "tracer",
 "min_m": [1, 1, 1], "max_m": [2, 3, 2], "rate_kg_s_m3": 5e-8}
```

```python
import copy
import json
import cfd_craft as cfd

case = json.load(open("examples/manual/point-source.json"))
sources = {"point": case["sources"][0]}
for kind in ("line", "volume"):
    sources[kind] = json.load(open(f"{kind}-source.json"))
for kind, source in sources.items():
    variant = copy.deepcopy(case)
    variant["sources"] = [source]
    valid = cfd.check(variant)["valid"]
    tracer = cfd.simulate(variant)["constituents"][0]
    r_down = tracer["receptors_kg_m3"]["R_down"] * 1e9
    print(f"{kind:6} {valid} {tracer['source_rate_kg_s']:.3g} kg/s, {r_down:.6g}")
```

```text
point  True 1e-07 kg/s, 17.8118
line   True 1e-07 kg/s, 15.8814
volume True 1e-07 kg/s, 14.472
```

The columns are validity, the integrated rate the solver used
(`source_rate_kg_s`) and `R_down` in micrograms/m3. Equal total emission does
not make different source shapes the same problem.

## Point and volume receptors

```python
import json
import cfd_craft as cfd

case = json.load(open("examples/manual/point-source.json"))
case["receptors"].append({"kind": "point", "id": "P_mid", "point_m": [5.5, 2.0, 2.0]})
tracer = cfd.simulate(case)["constituents"][0]
for name, value in tracer["receptors_kg_m3"].items():
    print(f"{name} = {value * 1e9:.6g} micrograms/m3")
```

```text
P_mid = 30.3316 micrograms/m3
R_down = 17.8118 micrograms/m3
```

A `point` receptor interpolates between the eight surrounding cell centers. A
`volume_average` receptor weights each cell by its exact overlap with a box.
`P_mid` sits on the plume axis in the middle of `R_down` and reads higher than
the box average. Neither kind bounds the peak concentration. A source or
receptor in a solid cell is rejected, not moved ([chapter 10](10-street-canyon.md)).

## Double the rate, double the concentration

With `numerics.transport` set to `linear_upwind` and a fixed flow, the
concentration is linear in the source strengths. `source-response.json` has
three volume sources of 1e-7 kg/s/m3 in boxes of 0.64 m3, 1.92e-7 kg/s in all:

```python
import json
import cfd_craft as cfd

case = json.load(open("cases/verification/source-response.json"))
values = []
for factor in (1, 2):
    for source in case["sources"]:
        source["rate_kg_s_m3"] = 1e-7 * factor
    result = cfd.simulate(case)
    tracer = result["constituents"][0]
    values.append(tracer["receptors_kg_m3"]["R1"])
    print(result["assessment"], f"{tracer['source_rate_kg_s']:.6g} kg/s")
print(f"R1 ratio = {values[1] / values[0]:.6g}")
```

```text
steady_discrete_solution 1.92e-07 kg/s
steady_discrete_solution 3.84e-07 kg/s
R1 ratio = 2
```

Linearity makes response matrices work ([chapter 12](12-studies.md)).

## MUSCL is sharper and not linear

`linear_upwind` is first-order upwind and smears a plume; `muscl` adds a
limited second-order slope. Run each with one source, another one, and both:

```python
import copy
import json
import cfd_craft as cfd

case = json.load(open("examples/manual/point-source.json"))
first = case["sources"][0]
second = dict(first, id="S1", point_m=[2.0, 1.5, 2.5])
for scheme in ("linear_upwind", "muscl"):
    values = []
    for sources in ([first], [second], [first, second]):
        variant = copy.deepcopy(case)
        variant["numerics"]["transport"] = scheme
        variant["sources"] = sources
        tracer = cfd.simulate(variant)["constituents"][0]
        values.append(tracer["receptors_kg_m3"]["R_down"])
    defect = abs(values[2] - values[0] - values[1]) / values[2]
    print(f"{scheme:13} R_down = {values[0] * 1e9:.6g}  sum holds: {defect < 1e-6}")
```

```text
linear_upwind R_down = 17.8118  sum holds: True
muscl         R_down = 18.1504  sum holds: False
```

The MUSCL value is higher: with less numerical diffusion, more tracer stays
near the plume axis, where the receptor is. The last column tests whether the
run with both sources equals the sum of the single runs within 1e-6. With
`muscl` it does not: the limiter is nonlinear
([transport model card](../model-cards/transport.md)).

## A steady source needs a way out

```python
import json
import cfd_craft as cfd

case = json.load(open("examples/manual/point-source.json"))
case["boundaries"]["x"] = "periodic"
report = cfd.check(case)
print(report["valid"], [(d["code"], d["path"]) for d in report["diagnostics"]])
```

```text
False [('CFD-E020', 'run.mode')]
```

A source that emits forever into a box with no outlet has no steady state, so
the case is rejected at `run.mode`. It needs an `open` boundary downstream.

## A release that is not steady

A fixed amount of tracer in a closed box is a transient problem: here a
Gaussian cloud of 1e-6 kg in a fully periodic box, for 2 s.

```python
import json
import cfd_craft as cfd

result = cfd.simulate(json.load(open("cases/verification/periodic-tracer.json")))
tracer = result["constituents"][0]
print(result["termination"], result["assessment"])
print(f"mass {tracer['mass_kg']:.6g} kg, emitted {tracer['emitted_kg']:.6g} kg")
print(abs(tracer["relative_budget_defect"]) < 1e-9)
```

```text
completed transient_interval_completed
mass 1e-06 kg, emitted 0 kg
True
```

Every constituent carries a mass budget: mass in the domain, emitted mass,
inflow, outflow and their defect. Nothing is emitted or leaves here, so the
mass stays at 1e-6 kg. Negative concentrations are never clipped: they fail.

## Next

- [Chapter 6](06-flow-cavity.md): a flow that the solver computes.
- [Chapter 12](12-studies.md): response matrices and source inference.
