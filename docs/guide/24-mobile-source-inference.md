# Source inference and route selection from rides
<!-- check: rel=1e-4 -->

Which street emits how much? Rides with a sensor give concentrations along
routes. If a model gives the concentration that each street alone would cause
on each ride, the emission rates can be fitted to the rides. This chapter
builds that table (the response matrix), fits rates, shows which streets the
rides cannot tell apart, estimates how many passes a street needs and selects
routes under a time budget.

Everything here is verified on synthetic data that the same model produced.
A successful recovery tests the numerical workflow. It validates no sensor
and no urban air, and no measured ride has been used.

## Setup

You need a checkout with the command and the example `mobile_response` built,
and the optional Python packages: NumPy, SciPy and LP-IP-craft for the study,
Shapely for the street converter.

```sh
cargo build --release --workspace --locked
cargo build --release --locked -p cfd-craft --example mobile_response
python -m pip install -r integrations/requirements-mobile.txt
```

Every section reads this study of 4 s on the documentation host. It writes
its plan and its acceptance thresholds before the first solve.

```bash
mkdir -p runs
python tutorials/mobile_measurements.py run --preset source-response --output runs/study > /dev/null
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## The smallest study

The preset has three streets (line sources `street-a` to `street-c`), two wind
directions (270 and 250 degrees), two training rides and two held-out rides
that the fit never sees. The true rates are 0.7, 1.3 and 0.4 times the
reference rate of each street.

```python
import json

r = json.load(open("runs/study/report.json"))
fit = r["inference"]
print(r["passed"], r["experimental_validation"])
print([f"{m:.4g}" for m in fit["multipliers"]], fit["estimate_label"])
print(fit["identifiability"]["rank"], fit["heldout_relative_error"] < 1e-3)
print(r["relative_superposition_defect"] < 1e-4)
print(sorted(k for k, passed in r["gate_checks"].items() if passed))
```

```text
True not_validated
['0.7', '1.3', '0.4'] unique_nonnegative_estimate
3 True
True
['ambiguity_reported', 'full_rank_training', 'heldout_recovery', 'rate_recovery', 'route_integer_optimal', 'superposition']
```

The fit recovers the three multipliers from the training rides, the matrix
has full rank 3, and the held-out rides are predicted within the threshold of
1e-3. The study exits 0 when all six checks pass and 2 otherwise; failed
solves and partial results stay in the output directory. The second preset,
`--preset canyon`, does the same in the street canyon of chapter 10;
`--config PLAN.json` runs your own plan.

## One flow, one transport run per street

For each wind the study solves the flow once and accepts it by the usual
steady checks. Then it solves one transport run per street on that frozen
flow, each from zero concentration: the flow is not updated again. A fourth
transport run with all streets at their true rates is the reference; it is
never used to build the matrix. Each run is a normal archive that passes
`validation/check_fields.py`. The checker recomputes a hash of the frozen
velocity, pressure and turbulence fields of each archive, and the study
requires the same hash in all runs of one wind.

The matrix has one row per ride sample and one column per street. A row is
the virtual ride of [chapter 23](23-mobile-paths-and-virtual-rides.md) through
one street's field: constant speed, a first-order sensor that starts at zero.
The matrix maps dimensionless multipliers to kg/m3; the reference rate of each
column converts a fitted multiplier back to kg/s.

Conditions for an exact matrix: steady `linear_upwind` transport, no initial
concentration, and the same flow for all columns (`CFD-E089` otherwise). The
MUSCL scheme is not linear. Particle bins and leaf deposition stay linear.
The Rust interface is `mobile_response::PreparedFlow`
([transport model card](../model-cards/transport.md#frozen-flow-source-responses)).

## Fit your own observations

`fit` takes a response matrix and a CSV with exactly the columns
`wind,ride,sample_index,concentration_kg_m3`, one row per sample of the
matrix. The study wrote such a file from its reference run:

```bash
python tutorials/mobile_measurements.py fit runs/study/mobile-response-matrix.json \
  runs/study/virtual-observations.csv --train train-near train-far \
  --heldout heldout-mid heldout-reverse --output runs/fit.json
python -c "
import json
f = json.load(open('runs/fit.json'))
print([f'{m:.4g}' for m in f['multipliers']], f['individual_rates_unique'])
p = f['input_provenance']
print(len(p['matrix_sha256']), len(p['observations_sha256']))"
```

```text
['0.7', '1.3', '0.4'] True
64 64
```

The fit is a nonnegative least-squares fit on the training rides, weighted by
the declared noise. Held-out rides only test the prediction. The result keeps
the SHA-256 hashes of the matrix and of the CSV it read (second line). Real sensor data must first
be aligned to the samples, calibrated and reduced to the increment above
background, in kg/m3 of the same constituent; the fit does none of that.

## Which streets can be told apart

Two streets with the same response on every ride cannot be separated: only
their sum is known. `identifiability` reports the rank of the matrix and
names the combinations that the rides do not determine.

```python
import sys

sys.path.insert(0, "integrations")
from mobile_inference import identifiability, required_passes

report = identifiability([[1.0, 1.0], [2.0, 2.0]], ["street-a", "street-b"])
print(report["rank"], report["nullity"], report["full_column_rank"])
passes = required_passes(
    1e-8,
    sensor_sigma_kg_m3=2e-10,
    pass_scatter_sigma_kg_m3=1e-9,
    effective_samples_per_pass=5,
    relative_half_width=0.1,
    confidence_z=1.96,
    systematic_sigma_kg_m3=0.0,
)
print(passes["passes"], passes["simulated"])
```

```text
1 1 False
4 False
```

Rank 1 of 2: the fitted rates of the two streets are one of many equally good
answers and must not be read one by one. The rank uses a relative threshold
on the singular values (default 1e-10). The study also adds a copy of
`street-b` on purpose and reports rank 3 of 4.

## How many passes a street needs

The second result above is a planning number. A pass is one ride of a route
in one wind. The noise model has two declared parts: readout noise of the
sensor, independent per sample, and scatter between passes, one offset per
pass. With n effective independent samples per pass the variance of a pass
mean is v = pass scatter² + sensor noise² / n. To know the mean within a half
width h at confidence factor z you need at least
ceil(v / ((h/z)² − systematic²)) passes. A mean of 1e-8 kg/m3 with the values
above needs 4 passes for 10 percent. When the systematic part alone exceeds
the target, no number of passes is enough and the function says so.

No noise is simulated and none is estimated from data. Drift, calibration
error and the error of the CFD model are not reduced by repetition.

## Which routes under a time budget

A candidate is one route in one wind, with its riding and setup time. A wind
direction is an opportunity to wait for, not something the rider controls.
The selection picks the set of candidates within the time budget whose
weakest-determined combination of streets is determined best (an E-optimal
design: it maximizes the smallest eigenvalue of the summed information
matrices).

```python
import json

sel = json.load(open("runs/study/report.json"))["route_selection"]
print(sel["selected"], sel["certified"])
print(f"{sel['riding_time_s']:.4g} of {sel['riding_time_budget_s']:.4g} s")
rank = sel["selected_identifiability"]["rank"]
print(sel["exhaustive_check"]["checked_patterns"], rank)
```

```text
['wind-270:train-near', 'wind-250:train-near'] True
26.67 of 36 s
16 3
```

The mixed-integer solver of LP-IP-craft solves a sequence of bounded linear
models with added cuts. `certified` means that the selection is optimal within
the declared floating-point gap, measured against the solver's proven bound;
it is not an exact proof. Limits and solver failures are kept in the report
and are never certified. For the four candidates here all 16 subsets were
also enumerated.

## Street emissions from map data

`integrations/traffic_sources.py` turns street centerlines and a table of
emission rates into line sources of a case made by the
[map converter](22-urban-geometry-particles-vegetation.md#import-buildings-from-a-map):

```sh
python integrations/traffic_sources.py --case mapped/case.json \
  --map-provenance mapped/map-provenance.json --streets streets.geojson \
  --rates rates.csv --height-m 0.3 --output mapped-traffic
```

The streets are GeoJSON lines in the coordinate system of the buildings. The
CSV has the columns `street_id`, `constituent`, `rate_kg_s_m` and `units`,
where `units` must be `kg/s/m`. The tool invents no rate: no emission factor
and no traffic count is assumed. It reuses the recorded map transformation,
clips streets to the domain and records kept and omitted lengths, the total
in kg/s and the hashes of its inputs. A street that touches a building is
rejected (`CFD-M002`), never moved. See the
[street-emission input contract](../../integrations/traffic-sources.md).

## What this is not

- **Not validated.** Inference and route selection are verified on synthetic
  data from the same model only. The [protocol for measured rides](../../validation/protocols/mobile-rides.md)
  lists what must be fixed before measured data are opened.
- **Not a bike-against-station comparison.** The report gives the ratio of a
  modeled path mean and of a modeled lagged sensor mean to a modeled station
  value. On a short ride the lagged ratio is dominated by the sensor starting
  at zero.
- **Not total concentration.** Rows are increments from the declared streets
  in a steady mean field.
- **Not better than the flow under it.** The open questions of
  [chapter 22](22-urban-geometry-particles-vegetation.md#what-these-results-are-not)
  apply to every matrix built on a district flow.

## Next

- [Mobile evidence record](../evidence/mobile-measurements.md): the measured
  results of both presets.
- [Chapter 12](12-studies.md): source inference from fixed sensors.
