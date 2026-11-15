# Urban geometry, particles and vegetation
<!-- check: rel=1e-4 -->

A real street is not two boxes and a gas. Buildings have footprints from a
map, traffic emits particles of several sizes that settle and stick to
surfaces, and hedges and trees slow the wind and collect particles. This
chapter adds each of these to the street canyon of
[chapter 10](10-street-canyon.md), one optional field at a time. A case that
uses none of the fields runs exactly as before.

These models are numerically verified and not experimentally validated: the
tests show that the equations are solved as written, not that a city behaves
this way. The [urban evidence record](../evidence/urban-extension.md) lists
what was measured and what failed.

## Setup

You need the `cfd-craft` command, the Python package `cfd_craft` and a
checkout ([chapter 3](03-cli-and-archive.md)). The case fields of this chapter
work in both. The map converter and the campaign script run from the checkout;
the converter needs Shapely
(`python -m pip install -r integrations/requirements-urban.txt`).

Every section starts from `runs/block.json`: the canyon of chapter 10 with the
opt-in implicit recipe of [chapter 9](09-opt-in-numerics.md#the-implicit-recipe),
so a run takes 2 to 5 s on the documentation host. `runs/block/` holds its
result.

```bash
mkdir -p runs
```

```python
import json

case = json.load(open("cases/canyon/wh1-wind270.json"))
case["name"] = "block"
case["numerics"].update(
    steady_algorithm="implicit_projection",
    pressure_relative_tolerance=0.1,
    max_time_step_s=100,
)
json.dump(case, open("runs/block.json", "w"), indent=2)
```

```bash
cfd-craft run runs/block.json --output runs/block > /dev/null
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## A building with a polygon footprint

A `geometry` entry with `footprint_m` is a prism: a polygon in the horizontal
plane between the heights `min_m[2]` and `max_m[2]`. Without `footprint_m` the
entry is the box of chapter 10. Save this building with one slanted wall as
`east.json`; the next block puts it in place of the east box.

<!-- check: fragment -->
<!-- file: east.json -->
```json
{"id": "east", "min_m": [7.0, 3.0, 0.0], "max_m": [9.0, 13.0, 1.0],
 "footprint_m": [[7.0, 3.0], [9.0, 3.0], [8.4, 13.0], [7.0, 13.0]]}
```

```python
import json

case = json.load(open("runs/block.json"))
case["geometry"][1] = json.load(open("east.json"))
case["geometry_min_passage_cells"] = 2
json.dump(case, open("runs/prism.json", "w"), indent=2)
```

```bash
cfd-craft check runs/prism.json > runs/prism-check.json
```

```python
checked = json.load(open("runs/prism-check.json"))
east = checked["geometry"]["shapes"]["east"]
print(checked["check"]["valid"], east["solid_cells"])
print(east["exact_volume_m3"], east["represented_volume_m3"], east["volume_error_m3"])
print(east["narrowest_fluid_passage_cells"])
print(sorted({d["code"] for d in checked["check"]["diagnostics"]}))
```

```text
True 36
17.0 18.0 1.0
1
['CFD-W001', 'CFD-W002', 'CFD-W003', 'CFD-W011']
```

The grid stays Cartesian. A cell is solid when its center lies inside the
footprint, so a slanted wall becomes a staircase. `check` and `geometry.json`
say what that costs, per shape: the prism has 17 m3, its 36 solid cells hold
18 m3, and the narrowest street next to it is 1 cell wide. The case asks for
at least 2 cells (`geometry_min_passage_cells`), so `check` adds the warning
`CFD-W011`. A shape without any cell center is an error (`CFD-E028`); a
building is never dropped silently.

- A footprint has 3 to 2048 vertices in meters, in either direction, without
  repeating the first vertex at the end. Concave footprints work.
- `min_m` and `max_m` must equal the bounds of the polygon in x and y.
- Holes, crossing edges and zero area are rejected (`CFD-E084`). Split a
  courtyard building into simple polygons.
- A cell center exactly on a slanted edge belongs to the footprint whose
  interior lies on the +x side of that edge. Two footprints that share an
  edge therefore leave no gap and do not overlap.

**Wall roughness.** By default the roughness length of building walls is the
smaller of the ground roughness and 0.001 cell widths, so it changes with the
grid. `building_roughness_m` sets it in meters, independent of the grid, for
`neutral_rans` flow (`CFD-E085`); the ground keeps `flow.roughness_m`. Setting
it changes the physics hash and the result. Neither wall treatment is
validated against measurements ([flow model card](../model-cards/flow.md)).

## Multigrid with buildings

The opt-in multigrid preconditioner of
[chapter 9](09-opt-in-numerics.md#multigrid-for-the-pressure-equation) also
works with buildings and with several separate fluid regions. Save these
`numerics` fields as `recipe.json`: the implicit recipe plus multigrid.

<!-- check: fragment -->
<!-- file: recipe.json -->
```json
{"steady_algorithm": "implicit_projection", "pressure_relative_tolerance": 0.1,
 "max_time_step_s": 100, "pressure_preconditioner": "multigrid"}
```

```python
import json
import cfd_craft as cfd

case = json.load(open("cases/canyon/wh1-wind270.json"))
case["numerics"].update(json.load(open("recipe.json")))
ic0, mg = json.load(open("runs/block/summary.json")), cfd.simulate(case)
print(mg["assessment"], mg["pressure_iterations"] < ic0["pressure_iterations"])
a, b = (s["constituents"][0]["receptors_kg_m3"] for s in (ic0, mg))
print(all(abs(b[k] / a[k] - 1) < 1e-4 for k in a))
```

```text
steady_discrete_solution True
True
```

Both runs solve the same pressure equation to the same checks, so the result
does not change. Fewer iterations are not a faster run. On canyon grids with
equal cell widths multigrid needed about 3 to 6 times fewer pressure
iterations than the default `ic0`, but the whole runs took about the same
time: `ic0` time over multigrid time was 1.05 at 27,648 cells, 0.94 at 93,312
cells and 0.91 on a 37,500-cell block (below 1, `ic0` was faster). With
strongly unequal cell widths (`CFD-W004`) multigrid was slower, because its
path for buildings has no line smoothing. The default stays `ic0`
([measurements](../evidence/urban-extension.md)).

## Import buildings from a map
<!-- check: long -->

`integrations/urban_map.py` converts building footprints to a case with
prisms. It reads GeoJSON polygons or CityJSON solids in a projected coordinate
system in meters and refuses longitude and latitude: reproject first, for
example with GDAL or QGIS. Convert CityGML to CityJSON with
[citygml-tools](https://github.com/citygml4j/citygml-tools). For
OpenStreetMap, export the footprints to GeoJSON and keep the ODbL attribution.

```bash
python integrations/urban_map.py integrations/fixtures/urban-synthetic.geojson \
  --crop 90 190 145 245 --cell-m 4 --coordinate-system 'local metric synthetic' \
  --license 'CC0-1.0 synthetic fixture' --attribution 'CFD-craft synthetic fixture' \
  --output runs/district
```

```python
import json

case = json.load(open("runs/district/case.json"))
p = json.load(open("runs/district/map-provenance.json"))
print(case["grid"]["cells"], case["domain"]["size_m"])
print([(g["id"], g["max_m"][2]) for g in case["geometry"]])
print([(a["id"], a["height_method"]) for a in p["assumptions"]])
print(p["rotation_deg"], p["dropped"], p["check_exit_code"])
```

```text
[54, 32, 14] [216.0, 128.0, 56.0]
[('building-0', 8.0), ('building-1', 8.0), ('building-2', 9.0)]
[('a', 'attribute'), ('b', 'levels'), ('c', 'default'), ('touching', 'attribute')]
0.0 [] 0
```

The converter crops the map to `--crop` (xmin ymin xmax ymax) and rotates it
so that the dominant building edges follow the grid (`--rotation-deg` sets the
angle). It merges footprints that touch and have equal height (here `a` and
`touching`) and adds clearance: 5 building heights upstream, to the sides and
above the roofs, 15 downstream; `--ensemble-clearance` gives 15 on every side
for a study of several wind directions. It writes `case.json`, `check.json`
(the report of `cfd-craft check`) and `map-provenance.json`, and exits 1 with
`CFD-M001` when the input or the check fails. Inspect before you run the case:

- **Heights** come from the attribute named by `--height-attribute`, else from
  a level count times a level height, else from a default. The provenance
  records the method per building. These are assumptions, not measurements.
- **Dropped buildings.** A building narrower or lower than two cells is left
  out and listed under `dropped`.
- **Flat ground.** There is no terrain. Input whose building base heights
  differ by more than `--max-ground-range-m` (default 0.5 m) is refused, and
  so are holes in footprints and CityJSON geometry templates.
- **Wind.** The wind direction is rotated with the buildings; the provenance
  keeps the map direction and the model direction.
- **Budgets and numerics** are copied from `--template` (default: the canyon
  case of chapter 10 with 64 MiB of output). A finer grid needs a template
  with larger budgets: with `--cell-m 2` this example fails `check` with
  `CFD-E007`.

## Particle size classes

A constituent with `particle` is a size class (a bin) of spherical particles
with one diameter and one density. It settles and deposits. A constituent
without `particle` is a gas as before. Save this bin as `coarse.json`:

<!-- check: fragment -->
<!-- file: coarse.json -->
```json
{"id": "coarse", "diffusivity_m2_s": 1.5e-5, "particle": {
 "diameter_m": 5e-6, "density_kg_m3": 1500.0,
 "ground_deposition_velocity_m_s": 0.001, "roof_deposition_velocity_m_s": 0.001}}
```

The block adds a 1 micrometer bin `fine` and a 20 micrometer bin `grit`
without extra deposition velocity, and gives each bin the traffic source.

```python
import json
import cfd_craft as cfd

case = json.load(open("runs/block.json"))
traffic = case["sources"][0]
bins = [json.load(open("coarse.json"))]
for name, diameter in (("fine", 1e-6), ("grit", 2e-5)):
    particle = {"diameter_m": diameter, "density_kg_m3": 1500.0}
    bins.append({"id": name, "diffusivity_m2_s": 1.5e-5, "particle": particle})
case["constituents"] = bins
case["sources"] = [dict(traffic, id=b["id"], constituent=b["id"]) for b in bins]
s = cfd.simulate(case)
print(s["termination"], s["assessment"])
for c in s["constituents"]:
    rate = c["deposition_rate_kg_s"]
    print(
        c["id"],
        f"{c['settling_velocity_m_s']:.4g} m/s",
        f"{c['aerodynamic_diameter_m'] * 1e6:.4g} um",
        f"{c['receptors_kg_m3']['sensor1'] * 1e9:.4g}",
        f"{rate['ground']:.4g} {rate['roof']:.4g}",
    )
for name, pm in sorted(s["particulate_matter"].items()):
    print(name, f"{pm['receptors_kg_m3']['sensor1'] * 1e9:.4g}")
```

```text
completed steady_discrete_solution
coarse 0.001165 m/s 6.143 um 223.2 3.922e-09 1.578e-10
fine 5.26e-05 m/s 1.242 um 230.6 9.791e-11 3.963e-12
grit 0.0182 m/s 24.52 um 185.7 2.83e-08 1.039e-09
PM10 453.8
PM2.5 230.6
```

Each line gives the settling speed, the aerodynamic diameter, the
concentration at `sensor1` in micrograms/m3 and the deposition rates on the
ground and on roofs in kg/s. All bins emit the same 1e-7 kg/s; the larger the
particle, the more is deposited and the less reaches the sensor.

- **Settling** follows the Stokes law with the Cunningham slip correction for
  air at 293.15 K and 101325 Pa. The formula holds up to a particle Reynolds
  number of 0.1; beyond it `check` fails (`CFD-E081`) and you give
  `settling_velocity_m_s` yourself.
- **Deposition.** Ground and upward-facing roofs take the settling flux plus
  the declared deposition velocity. Vertical walls collect nothing.
  `deposited_kg` is the accumulated mass per surface, `deposition_rate_kg_s`
  the current rate; the mass balance and the checkpoint include both.
- **PM2.5 and PM10.** `particulate_matter` adds the bins whose aerodynamic
  diameter (that of a sphere of density 1000 kg/m3 with the same settling
  speed) is at most 2.5 or 10 micrometers. A bin counts completely or not at
  all: PM2.5 is `fine`, PM10 is `fine` plus `coarse`, `grit` is in neither.
- **Closed domains.** A steady particle source may have deposition as its only
  way out; a gas still needs an open boundary (`CFD-E020`).

The values are concentration increments from the declared sources: no
background, chemistry, coagulation or resuspension, and not what a regulatory
PM monitor reports. The [transport model card](../model-cards/transport.md)
has the equations.

## Hedges and trees

A `vegetation` entry is a box of porous fluid, not a solid: air flows through
it and loses momentum, and particles stick to the leaves. Save this hedge
behind the east building as `hedge.json`:

<!-- check: fragment -->
<!-- file: hedge.json -->
```json
{"id": "hedge", "min_m": [9.0, 3.0, 0.0], "max_m": [10.0, 13.0, 1.0],
 "leaf_area_density_m2_m3": 2.0, "drag_coefficient": 0.2,
 "leaf_deposition_velocity_m_s": 0.005, "turbulence_closure": "green1992"}
```

```python
import json
import cfd_craft as cfd

case = json.load(open("runs/block.json"))
case["constituents"][0]["particle"] = {"diameter_m": 1e-6, "density_kg_m3": 1500.0}
case["vegetation"] = [json.load(open("hedge.json"))]
s = cfd.simulate(case)
v = s["vegetation"]
print(s["assessment"], v["volume_fluid_cells"], v["validation"])
print(f"{v['drag_power_per_density_m5_s3']:.4g}")
rate = s["constituents"][0]["deposition_rate_kg_s"]
print({k: f"{x:.4g}" for k, x in sorted(rate.items())})
```

```text
steady_discrete_solution {'hedge': 20} verified_numerics_unvalidated_physics
0.5386
{'ground': '9.753e-11', 'roof': '3.966e-12', 'vegetation': '4.749e-10'}
```

The hedge covers 20 fluid cells. Its leaves take 4.7e-10 kg/s of the 1e-7 kg/s
emitted, more than ground and roofs together.

- **Drag.** `leaf_area_density_m2_m3` (LAD) is leaf area per volume of canopy.
  The drag acceleration is -Cd LAD |U| U with `drag_coefficient` Cd.
  Overlapping volumes add. Prescribed flow cannot respond to drag: use Cd 0
  there (`CFD-E083`).
- **Turbulence.** `turbulence_closure` selects the canopy terms of the
  k-epsilon model: `green1992` (default) or `sanz2003`, the set of Sanz
  (2003) as tabulated by Viana Parente Lopes, Palma and Silva Lopes (2021),
  who list it under Katul et al. (2004). The other model constants do not
  change ([flow model card](../model-cards/flow.md#porous-vegetation)).
- **Leaf deposition** removes LAD times `leaf_deposition_velocity_m_s` times
  the concentration of a particle bin. A gas is not affected.
- `summary.vegetation` reports the drag work rate and the drag force, both per
  unit air density, and the fluid cells of each volume.

Limits: a volume that contains no fluid cell center is accepted without a
message and has no effect; only `volume_fluid_cells` shows 0 (a building in
that situation is `CFD-E028`). Drag in a transient run is first-order accurate
in time. There is no heat, shading, season or leaf size.

## One case, twelve wind directions

`validation/urban_campaign.py` runs a case for the wind directions 0, 30, …,
330 degrees. Each direction starts cold with its own time budget, and each is
kept, also one that failed or timed out: the consumed case, the run archive,
the independent field check and the result.

```sh
python validation/urban_campaign.py run runs/district/case.json \
  --map-provenance runs/district/map-provenance.json \
  --output runs/district-rose --run-budget-s 120 --campaign-budget-s 1200 \
  --threads 1 --workers 2
```

The script exits 0 only when all twelve directions are accepted within the
campaign budget, and 2 otherwise. A direction is accepted when its run is a
steady discrete solution and its stored fields pass
`validation/check_fields.py`. Directions are in the rotated model frame; with
`--map-provenance` each row also gives the map direction. Twelve equal
directions are not a wind climate: weight them with measured frequencies in
your own analysis. `--runner` sends the directions through `optimization-run`
([chapter 14](14-optimization-jobs.md#wind-direction-jobs-for-a-city-block)).

## What these results are not

- **Not validated.** No particle, canopy or building result here has been
  compared with measurements.
- **Not shown to be independent of grid orientation.** In the recorded study
  of a canyon rotated by 45 degrees the coarse rotated case was rejected and
  both finer runs timed out; no rotation error is known.
- **Not a qualified district workflow.** In the recorded Delft demonstration
  (183,260 cells, 45 s per direction) none of the twelve directions converged
  within its budget. A completed campaign is not twelve accepted fields.
- **Not total air quality.** Concentrations are increments from the declared
  sources in neutral mean flow, without background or short peaks.

When you compare two grids, convert the map once and refine the same
footprints; importing each grid separately can drop different buildings.

## Next

- [Chapter 23](23-mobile-paths-and-virtual-rides.md): sample the field along a
  route and simulate a sensor ride.
- [Urban evidence record](../evidence/urban-extension.md): every measurement
  and failed row behind this chapter.
