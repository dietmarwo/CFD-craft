# Mobile paths and virtual rides
<!-- check: rel=1e-4 -->

A sensor on a bicycle does not stand at one point. It moves through the
concentration field along a route, and it reacts with a delay. This chapter
samples a computed field along a route (a path receptor) and then computes
what an idealized sensor would record on one ride through it (a virtual
ride). At the end you have both for a small plume.

The field is the steady mean concentration from the declared sources. A
virtual ride is therefore a model of the observation, not of the atmosphere:
it contains no turbulent fluctuations, no traffic pulses and no background,
and it is not experimentally validated.

## Setup

You need the `cfd-craft` command and a checkout
([chapter 3](03-cli-and-archive.md)). Path receptors also work in the Python
package. The ride tool `integrations/virtual_ride.py` and the field checker
run from the checkout and need only the Python standard library.

Every section reads this run of `examples/manual/path-ride.json`: a point
source in a uniform wind of 1 m/s toward +x, on 16 x 8 x 8 cells of 0.5 m.

```bash
mkdir -p runs
cfd-craft run examples/manual/path-ride.json --output runs/path-field > /dev/null
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## Declare a path receptor

A path is a receptor of kind `path`. The example case contains this one:

<!-- check: fragment -->
```json
{
  "kind": "path",
  "id": "ride",
  "polyline_m": [[2.0, 1.0], [4.0, 1.0], [6.0, 3.0]],
  "height_m": 2.0,
  "sample_spacing_m": 0.25
}
```

- `polyline_m` lists the corners of the route as east and north coordinates
  in meters. The route may bend and may visit a place twice.
- `height_m` is the constant height above the flat ground.
- `sample_spacing_m` is the largest distance between two samples. The solver
  divides the length of the route into equal intervals no longer than this
  and samples both ends.

The solver never moves or clips a route. A route outside the domain or with
an invalid height or spacing is an error (`CFD-E086`). A route that enters a
building is an error even when all samples lie in the air, and so is a sample
whose interpolation would use a solid cell (`CFD-E087`). A path has at most
4097 corners and 20001 samples, a case at most 50000 path samples
(`CFD-E088`).

## Read the samples and the mean

```python
import json

s = json.load(open("runs/path-field/summary.json"))
tracer = next(c for c in s["constituents"] if c["id"] == "tracer")
ride = tracer["paths"]["ride"]
print(s["termination"], s["assessment"], len(ride["distance_m"]))
print(f"{ride['distance_m'][1]:.4g} {ride['distance_m'][-1]:.4g}")
print(ride["points_m"][0], ride["points_m"][-1])
print([f"{c * 1e9:.4g}" for c in ride["concentrations_kg_m3"][::5]])
mean = ride["mean_kg_m3"]
print(f"{mean * 1e9:.4g}", mean == tracer["receptors_kg_m3"]["ride"])
```

```text
completed steady_discrete_solution 21
0.2414 4.828
[2.0, 1.0, 2.0] [6.0, 3.0, 2.0]
['1.828', '3.676', '9.418', '37.26', '15.66']
14.89 True
```

The route is 4.828 m long. With a spacing of at most 0.25 m it gets 20
intervals of 0.2414 m, so 21 samples. Each constituent has, under
`paths["ride"]`, the sample positions `points_m`, the distance along the route
`distance_m`, the concentrations and their mean. The fourth line shows every
fifth sample in micrograms/m3: the route enters the plume near its end.

The mean (14.89 micrograms/m3) is the average along the route, by the
trapezoid rule over the samples. It also appears in `receptors_kg_m3` and in
`probes.csv` under the id of the path, so everything that works with point
receptors works with a path, for example the response matrix of
[chapter 12](12-studies.md#unit-responses-and-superposition). Each sample
interpolates the cell-center values linearly, as a point receptor does.

## Check the path independently

`validation/check_fields.py` rebuilds every sample position, its interpolation
weights, the test of whole segments against buildings, the concentrations and
the mean from the stored fields, without the solver:

```bash
python validation/check_fields.py runs/path-field > runs/path-check.json
python -c "import json; print(json.load(open('runs/path-check.json'))['passed'])"
```

```text
True
```

## Simulate a ride

The ride tool takes a run directory, a constituent and a path, and needs a
riding speed, the interval between sensor readings and the response time of
the sensor.

```bash
python integrations/virtual_ride.py runs/path-field --constituent tracer --path ride \
  --speed-m-s 3 --sampling-interval-s 0.1 --response-time-s 2 --output runs/ride.json > /dev/null
```

```python
import json

r = json.load(open("runs/ride.json"))
print(len(r["time_s"]), f"{r['time_s'][-1]:.4g} s", r["position_geometry"])
for i in (0, 5, 10, 15, 17):
    field, sensor = r["steady_field_kg_m3"][i] * 1e9, r["sensor_kg_m3"][i] * 1e9
    print(f"{r['time_s'][i]:.4g} s  field {field:.4g}  sensor {sensor:.4g}")
print(r["provenance"]["experimental_validation"])
```

```text
18 1.609 s declared_polyline
0 s  field 1.828  sensor 1.828
0.5 s  field 4.059  sensor 2.095
1 s  field 23.31  sensor 3.888
1.5 s  field 22.04  sensor 9.877
1.609 s  field 15.66  sensor 10.35
not_validated; see validation/data-inventory.json
```

At 3 m/s the ride takes 1.609 s. `steady_field_kg_m3` is what a sensor without
delay would read; `sensor_kg_m3` is the reading of a sensor with a response
time of 2 s. On this short ride the slow sensor reaches less than half of the
peak. Values are in micrograms/m3.

How the tool works:

- **Field.** It accepts only a completed, accepted steady run and checks the
  manifest and the hashes of the consumed case and summary. A transient or
  incomplete run is refused (`CFD-M004`). The output records those hashes, the
  route and all parameters.
- **Motion.** The speed is constant. Positions follow the declared route with
  its corners; the concentration is linear between the path samples.
- **Sensor.** The reading y follows `response_time * dy/dt = concentration - y`,
  a first-order lag. The tool integrates it exactly between samples, so a
  shorter reading interval does not change the values. The last reading is at
  the end of the route, even when the ride time is not a multiple of the
  interval.
- **Start.** The sensor starts at the first field value. `--initial-kg-m3 0`
  starts it at zero instead. `--response-time-s 0`, the default, gives a
  sensor without delay.
- **Bounds.** A ride has at most 200000 readings, and an existing output file
  is never overwritten.

## What a virtual ride is not

- Not a time series of the atmosphere. Variation along the ride is variation
  in space of a steady mean field.
- Not a model of a particular sensor. No commercial sensor is claimed to
  follow the first-order lag without calibration.
- Not validated. The sampling and the lag are verified against analytic
  cases ([mobile evidence record](../evidence/mobile-measurements.md)); no
  measured ride has been compared.
- Not exact superposition by itself. Samples are linear in the field, but the
  field is linear in the sources only with fixed flow and `linear_upwind`
  transport ([chapter 5](05-sources-receptors-transport.md#muscl-is-sharper-and-not-linear)).

## A task for an agent

> Read `docs/ai-context.md`. Add a path receptor to a case whose route stays
> in resolved air; declare height and sample spacing. Run the case, keep the
> archive and run `validation/check_fields.py` on it. Simulate one ride with
> a stated speed, reading interval, response time and start value. Report the
> termination, the assessment, the path mean and the ride, and say that the
> ride is an idealized pass through a steady mean field, not a measurement.

## Next

- [Chapter 24](24-mobile-source-inference.md): infer street emissions from
  rides and plan routes.
- [Chapter 22](22-urban-geometry-particles-vegetation.md): buildings from a
  map, particles and vegetation.
