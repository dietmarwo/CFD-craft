# Mobile paths and virtual rides

A bicycle sensor moves through a spatial field and has its own response time.
The source extension can sample the native field along a flat-ground route,
then generate an idealized pass through that **steady mean local-source
increment**. This is an observation model. It does not generate atmospheric
fluctuations, traffic pulses, background pollution or experimental validation.

## Setup

Build this source checkout and put its command on `PATH`; commands below run
from the checkout root, with a fresh output directory.

```sh
cargo build --release --locked
export PATH="$PWD/target/release:$PATH"
```

## Declare a path receptor

A path uses local east/north coordinates in meters and a constant height above
flat ground. Its `sample_spacing_m` is a maximum spacing: the solver divides
the complete arc length into `ceil(length / spacing)` equal intervals and
includes both endpoints. Samples keep route order, including a repeated visit
to the same location on a loop.

<!-- check: none: JSON receptor fragment, exercised by examples/manual/path-ride.json -->
```json
{
  "kind": "path",
  "id": "ride",
  "polyline_m": [[2.0, 1.0], [4.0, 1.0], [6.0, 3.0]],
  "height_m": 2.0,
  "sample_spacing_m": 0.25
}
```

Every sample uses the existing linear cell-center interpolation, with the
same strict rejection of any positive-weight solid cell. Entire geometric
segments are also traversed on the represented mask: a segment crossing a
building is rejected even if its endpoints and all coarse sample positions
are in fluid. The solver does not clip a route or relocate a measurement.

Paths are capped at 4097 vertices and 20001 samples each, and a case at 50000
total path samples. The memory and output preflight includes their weights and
result arrays. Invalid coordinates/height/spacing use `CFD-E086`, solid
crossings or stencils `CFD-E087`, and sample-budget violations `CFD-E088`.

## Read the samples and mean

For each constituent, `summary.constituents[i].paths["ride"]` contains
`points_m`, `distance_m`, `concentrations_kg_m3` and `mean_kg_m3`. The path mean
is normalized arc-length trapezoidal quadrature over those samples. The same
mean appears in `receptors_kg_m3["ride"]` and `probes.csv`, so existing source
response matrices continue to work. Individual samples are also linear
observations. Exact source superposition still requires fixed flow/diffusivity
and `linear_upwind`; adding a path does not make MUSCL linear.

The independent `validation/check_fields.py` checker reconstructs all sample
positions, interpolation weights, whole-segment supports, concentrations and
means. Its checks remain active under `python -O`. Numerical fixtures verify
Gaussian-plume sampling refinement, short-path/thin-volume agreement,
reversal, superposition, solid rejection and returned-field agreement.
The Gaussian fixture checks interpolation of a prescribed analytic plume; it
is not a new validation of the full flow/transport model.

## Generate a virtual ride

From a source checkout, start with the complete example. Use a fresh output
directory and a new result filename.

```bash
mkdir -p runs
cfd-craft run examples/manual/path-ride.json --output runs/path-field
python validation/check_fields.py runs/path-field
python integrations/virtual_ride.py runs/path-field --constituent tracer --path ride --speed-m-s 3 --sampling-interval-s 0.1 --response-time-s 2 --output runs/virtual-ride.json
```

The tool requires an accepted completed steady field and checks the manifest
and consumed case/summary hashes. The output records those identities, route,
constituent, speed, interval, response time, assumed initial sensor value and
experimental-validation label. An incomplete or transient field is rejected;
consuming a transient solution as a static mean would need a separate model.

The sensor obeys `tau * dy/dt = concentration - y`. Concentration is linear
between the recorded arc-length samples, riding speed is constant, and the
first-order sensor equation is integrated exactly on each linear interval.
The numerical output interval therefore does not add sensor-integration error.
The final endpoint is included even if the ride duration is not an integer
multiple of the requested interval. Original polyline corners determine
positions, rather than chords between coarse observation samples.

With `--response-time-s 0`, the sensor follows that sampled field immediately.
Otherwise, its initial value defaults to the first field sample; use
`--initial-kg-m3 0` to model a sensor initially at zero local increment.
Changing the starting assumption changes the startup response. The analytic
step and ramp tests verify this lag model. No particular commercial sensor is
claimed to follow it without calibration. Rides are capped at 200000 output
samples and do not overwrite an existing output file.

For an agent: choose a route that remains in resolved fluid, declare the
height, sample spacing and sensor assumptions, keep the native field audit,
and compare route coverage or source inference using the recorded samples.
Treat variation along the route as spatial variation in a mean field.
