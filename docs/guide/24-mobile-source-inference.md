# Source inference and route selection from rides

The source extension implements R2 and R3 of the mobile-measurement plan.
Its observations are local-source concentration increments along idealized
rides through an accepted steady field. A successful synthetic recovery tests
the numerical workflow; it does not validate a bicycle sensor or urban air.

## Setup

Build the checkout and its bounded response driver, then install the optional
study packages. These dependencies are outside the native CFD core.

```sh
cargo build --release --locked
cargo build --release --locked -p cfd-craft --example mobile_response
python -m pip install -r integrations/requirements-mobile.txt
```

## Supply street emissions

First make a local case and `map-provenance.json` with the
[urban converter](22-urban-geometry-particles-vegetation.md). Then supply street
centerlines and a CSV whose columns are `street_id`, `constituent`,
`rate_kg_s_m`, `units`. Rates must be explicit, finite and nonnegative, with
`units=kg/s/m`; no emission factor or traffic rate is inferred.

```sh
python integrations/traffic_sources.py --case mapped/case.json --map-provenance mapped/map-provenance.json --streets streets.geojson --rates rates.csv --height-m 0.3 --output mapped-traffic --binary target/release/cfd-craft
```

The converter reuses the recorded map transform, clips continuous segments,
and records retained/omitted lengths, integrated kg/s, input hashes and all
assumptions. Continuous building intersections reject the affected street.
Native `check` also tests the represented mask: a geometrically clear street
may still be unrepresentable on a coarse grid. Rejections retain diagnostics;
there is no silent source relocation. See the
[traffic-input contract](../../integrations/traffic-sources.md).

## One flow, separate scalar responses

`mobile_response::PreparedFlow` validates the original source/receptor support,
prepares one flow-only case per wind, and requires completed native steady
acceptance. Adoption verifies case/physics/source identities, the actual state
and recomputed native gates. Every source column starts at zero concentration
on the same immutable velocity, pressure, k and epsilon arrays. Their
length-prefixed little-endian f64 SHA-256 is recorded in `summary.frozen_flow`
and recomputed by the independent field checker. The flow is not updated by
a scalar response. This is an explicit frozen-flow initialization API; ordinary
restart still requires its existing exact-case contract.

Transport reuses the native SSPRK2 operator, stable step, mass accounting,
positivity and steady-equation/monitor gates. Only steady `linear_upwind`
transport with empty scalar initial conditions is eligible. MUSCL cannot
produce an exact linear response matrix. Particle bins and fixed leaf sinks
remain linear under their declared fixed coefficients. Failed preparation or
response archives and work counts remain in the report.

For three source groups, one wind uses one accepted flow solve, three cold
scalar columns, and a separate combined-truth scalar solve for verification.
The last solve is not used to construct the columns. Prescribed analytical
flow counts as zero numerical flow solves. All archive identities refer to
the actual producer; memory, iteration and wall-time budgets remain binding.

## Build and test ride responses

[Path receptors and virtual rides](23-mobile-paths-and-virtual-rides.md) supply
the observation operator H: uniform arc-length samples, interpolation in
distance, constant speed and a declared first-order sensor lag. The study
applies exactly the same H to each native source column and the independent
combined truth. A zero initial sensor value makes H linear. The consumed case
supplies the original polyline, preserving corners between concentration
samples. Rows carry wind, route, sample index, time and position.

```sh
python tutorials/mobile_measurements.py run --preset source-response --output runs/mobile-source-response
python tutorials/mobile_measurements.py run --preset canyon --output runs/mobile-canyon
```

Use `--config PLAN.json` for another frozen study. The preset configuration,
noise assumptions and GR error gates are written before any native solve.
Between winds, the driver permits only the wind vector/direction/speed and
case name to differ; source rates, geometry, routes and numerical controls
stay fixed. The demonstration uses three groups, two winds and two training
plus two held-out rides. Native archives, independent audits, stdout/stderr,
partial failures, virtual truth, the matrix and CSV remain under the new output
directory. See [the measured results](../evidence/mobile-measurements.md).

## Coverage, rank and ambiguity

The matrix A maps dimensionless source multipliers q to concentrations in
kg/m3. Each column's explicitly supplied integrated reference kg/s is retained
to convert the fitted multiplier back to an emission rate. Nonnegative least
squares uses training rides only. Held-out rides and the reference station
never enter the fit. Singular values and rank use the declared relative
threshold (default 1e-10), with named nullspace combinations and identical
response groups. A particular nonnegative estimate of a rank-deficient matrix
does not identify individual street rates.

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

## Noise and required passes

The declared covariance of one route/wind pass is
Σ = σ_sensor² I + σ_pass² 11ᵀ. Readout noise is independent; pass-to-pass
scatter is one coherent offset within a pass and independent between passes.
Whitening uses its analytic inverse square root, avoiding quadratic storage
in ride length. Neither random noise nor atmospheric scatter is simulated.
These are planning assumptions, not an inferred error distribution.

For an effective n samples per pass, the variance of its mean is
v = σ_pass² + σ_sensor²/n. To target mean half-width h at Gaussian multiplier z,
the smallest planned count is ceil(v / ((h/z)² − σ_systematic²)), at least one.
An unreachable systematic floor or zero mean with a relative-only target
returns no achievable pass count. Drift, sensor calibration and CFD model
error require separate evidence. `n` is effective independent sample count,
not merely the logger frequency. Planning is reported per ridden street
segment and wind, conditional on its modeled sensor mean.

## Integer route and wind selection

Each binary decision selects an available route/wind observation opportunity,
with riding plus setup time charged against a declared budget. Wind sectors
are opportunities to wait for, not weather the rider can control. For candidate
r, F_r = A_rᵀ Σ_r⁻¹ A_r. The E-optimal objective maximizes the smallest eigenvalue
of Σ_r z_r F_r, so weakly observed source combinations affect the choice.

The implementation uses LP-IP-craft's native mixed integer solver for a bounded
outer approximation: unit-vector cuts provide upper bounds, and eigenvectors
of each returned information matrix add violated cuts. Actual candidate
feasibility, integrality, time cost and eigenvalues are checked independently.
Native solver results, incumbents and bounds are retained even when a limit
or failure prevents certification. Each outer bound is the native solver's
proven master bound (`best_bound`), never the incumbent's objective value; a
master without a finite proven bound stops without certification. `certified`
means convergence within the declared floating-point gap, not an exact
rational proof. The small synthetic campaign additionally checks every binary
pattern independently. Rank of the selected observations is reported
separately.

## Use an observation CSV and compare a station

```sh
python tutorials/mobile_measurements.py fit runs/mobile-source-response/mobile-response-matrix.json observations.csv --train train-near train-far --heldout heldout-mid heldout-reverse --output fitted-rates.json
```

The CSV requires exactly `wind,ride,sample_index,concentration_kg_m3`, matching
the matrix's unique sample identities. Matrix and consumed CSV hashes are
returned with the sensor parameters, frozen-plan hash and native producer
identities. Data must represent the same constituent, source-increment units,
route and observation operator. Arbitrary raw sensor readings need their own
predeclared alignment, calibration and background treatment first.

The report gives steady adjacent-path mean / reference-point concentration
and lagged sensor mean / reference-point concentration per wind. These are
modeled local-increment ratios. Initial sensor lag matters on short rides;
neither ratio is a measured bicycle/station comparison or total ambient PM.
The [unopened-data protocol](../../validation/protocols/mobile-rides.md)
records the decisions needed before V2 can begin. V1's urban OpenFOAM comparison,
V2 measured validation and the previous district/rotation gates remain open.
