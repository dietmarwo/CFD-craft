# Urban geometry, particles and vegetation

This chapter describes the unreleased source extension to 0.1.1. Build from
this checkout; installed 0.1.1 packages do not contain these additions.
Every feature is opt-in. The defaults and normalized case hashes of the
committed gas cases are preserved. These are verified numerical models with
**unvalidated urban physics**; read the [urban evidence](../evidence/urban-extension.md)
before using a district result. A completed time interval or intact archive
is not a steady solution.

## Polygon buildings and roughness

`geometry` keeps the original `id`, `min_m`, `max_m` boxes. Adding `footprint_m`
turns one entry into a vertical polygon prism. Coordinates are local metric x/y;
the x/y bounds must match the polygon bounds, and the z bounds give its height.
Supply 3–2048 vertices without a repeated closing vertex. Concave simple
polygons work; holes, crossing edges and zero area are rejected (`CFD-E084`).

<!-- check: fragment -->
```json
{"geometry":[{"id":"building","min_m":[10,10,0],"max_m":[18,18,8],
"footprint_m":[[10,10],[18,10],[18,14],[14,14],[14,18],[10,18]]}],
"building_roughness_m":0.01,"geometry_min_passage_cells":3}
```

The mask is cell-center based, with lower bounds inclusive and upper bounds
exclusive. It uses the same wall faces and pressure operator as boxes. There
are no cut cells, terrain or body-fitted native walls. `geometry.json.shapes`
records exact and represented volume, signed volume error, contained cells,
and the narrowest horizontal fluid run from each shape to another solid.
Exterior clearances are excluded from that street-width measure. A vanished
shape is still an error (`CFD-E028`), and an underresolved street is a warning
(`CFD-W011`). Passing these checks does not establish geometric accuracy.

`building_roughness_m` is an optional positive aerodynamic z0, independent of
cell width, for non-ground wall functions. The ground retains `flow.roughness_m`.
Omitting it reproduces the old grid-dependent non-ground wall recipe; supplying
it changes the physics hash. The empty-ABL fixture remains required. The
[flow model card](../model-cards/flow.md) gives the wall treatment and its limits.

## Masked pressure multigrid

`numerics.pressure_preconditioner = multigrid` now accepts building masks and
multiple fluid components. The masked path groups only face-connected cells
inside each geometric bin. Coarsening cannot connect across a solid barrier.
Each sealed component retains a separate gauge; outlets anchor their own
components. The fine equation, projection and independently recomputed residual
are unchanged. See the [developer page](../developer/pressure-multigrid.md).

For steady neutral-RANS work, create an explicit case copy with the opt-in
implicit recipe. The source extension deliberately keeps the defaults:

<!-- check: fragment -->
```json
{"numerics":{"steady_algorithm":"implicit_projection",
"momentum_advection":"limited_upwind","momentum_limiter":"van_albada",
"pressure_preconditioner":"multigrid","pressure_relative_tolerance":0.1,
"max_time_step_s":100}}
```

This is a fragment, not a complete case. The recipe is a way to reach a checked
steady fixed point, not an unsteady physical time integrator. A loose inner
pressure tolerance can leave incomplete iterates outside the independent
continuity gate. Keep those runs as failures. Kernel iteration reductions alone
do not establish an end-to-end speedup.

## Convert a map

The optional converter requires Shapely; the native solver has no new dependency.
Use projected metric GeoJSON polygons or CityJSON surfaces/solids. Reproject
longitude/latitude first. For CityGML, first use
[citygml-tools](https://github.com/citygml4j/citygml-tools) to convert to CityJSON;
for OSM, export footprints to GeoJSON and reproject with GDAL or QGIS, retaining
the ODbL attribution and explicit height assumptions. The converter never
silently interprets degrees as meters.

```sh
python -m pip install -r integrations/requirements-urban.txt
python integrations/urban_map.py integrations/fixtures/urban-synthetic.geojson \
  --crop 90 190 145 245 --cell-m 2 --coordinate-system 'local metric synthetic' \
  --license 'CC0-1.0 synthetic fixture' --attribution 'CFD-craft synthetic fixture' \
  --output runs/converted-district
```

The tool crops, rotates by the dominant building-edge direction (or an explicit
angle), simplifies, merges touching footprints **only at equal height**, drops
shapes whose minimum rotated-rectangle width or height is below two cells,
adds COST 732 clearances, writes the case and runs native `check`. Dropped
shapes and every height fallback are recorded. Heights come from the named
attribute, then levels times a declared level height, then the declared default.
These are assumptions, not measurements. Inspect them before running.

CityJSON parent containers defer to their BuildingPart children, inheriting
attributes. When several positive LoDs are present, the lowest positive LoD is
used for a single prism approximation; surfaces from different LoDs are not
mixed. GeometryInstance/templates are refused. Footprint holes require external
decomposition. Conservative lower-half projected surface elevations screen
sloping bases; unknown or nonflat ground can be rejected. Supplied nonfinite
coordinates, transforms, elevations and invalid indices are errors.

`map-provenance.json` contains the exact consumed source-file SHA-256, declared
license/credit, crop, rotation, coordinate system, translation, height and
flat-ground assumptions, discarded shapes and native check status. The tool
refuses a sampled building-base ground range above `--max-ground-range-m` (default 0.5 m). This is a screen of available elevations, not proof of level terrain between buildings. It does
not implement terrain. Empty or unsupported geometry must be resolved at the
source. Geographic wind direction is rotated with the buildings; provenance
keeps both source and local wind directions.

Default clearances are 5H upstream/lateral/above roofs and 15H downstream.
Use `--ensemble-clearance` for 15H on every horizontal side before rotating
through twelve directions. Clearances alone do not prove domain independence.

## Particle bins and leaves

A gas constituent is unchanged. A particle constituent adds `particle`:

<!-- check: fragment -->
```json
{"id":"fine","diffusivity_m2_s":0.000015,"particle":{
"diameter_m":0.000002,"density_kg_m3":1500,
"ground_deposition_velocity_m_s":0.001,"roof_deposition_velocity_m_s":0.001}}
```

Settling is a declared Stokes–Cunningham formula at a reference atmosphere or
an explicit supplied speed. Formula evaluation rejects Reynolds numbers outside
its stated range. Vertical drift is conservative, and the stability limit
includes drift and explicit loss rates. Ground and upward-facing roofs collect
settling plus the declared additional deposition velocity; vertical walls do
not collect particles in this model. Bins have one representative spherical
size, without chemistry, coagulation or resuspension.

`particulate_matter` reports PM2.5/PM10 sums using slip-corrected aerodynamic
diameter. A bin is wholly included or excluded; there is no within-bin size
integration or regulatory measurement-response model. `deposited_kg` stores
cumulative mass by ground, roof and vegetation; `deposition_rate_kg_s` is the
instantaneous rate. The mass budget includes initial mass, emissions, boundary
inflow/outflow, airborne mass and deposition. Checkpoints preserve these ledgers.
The [transport model card](../model-cards/transport.md) states the full equations.

A vegetation volume is a porous **fluid** region, not a solid mask:

<!-- check: fragment -->
```json
{"vegetation":[{"id":"trees","min_m":[20,20,0],"max_m":[28,28,6],
"leaf_area_density_m2_m3":0.5,"drag_coefficient":0.2,
"leaf_deposition_velocity_m_s":0.001,"turbulence_closure":"green1992"}]}
```

Drag is Cd·LAD·|U|·U, with an implicit nonnegative loss in the steady momentum
correction. `green1992` and `sanz2003` select two published canopy source-term
coefficient sets. They retain the ambient neutral-RANS coefficients; these are
source-model alternatives, not reproductions of all assumptions of the original
papers. Leaf collection is LAD·v_leaf·C for particles; gas is unaffected.
Overlapping volumes add. Zero LAD leaves the complete numerical State bytes
unchanged, including the empty-ABL terms; case/physics hashes still describe
the declared input and therefore differ when a zero-LAD entry is added.

`summary.vegetation` reports the instantaneous discrete work and force of the
applied staggered drag, per unit air density, and fluid coverage. Work is a rate,
not a cumulative energy history. The independent field checker recomputes it.
Active-drag transient momentum currently has verified **first-order** time
accuracy; the gas SSPRK2 second-order fixture does not apply to it.

## Twelve cold directions

The campaign writes its plan before execution and keeps a job, consumed case,
stdout/stderr, native archive, profile, independent audit and result for every
direction, including rejected and timed-out rows. Each direction starts cold;
neighboring-direction restarts are not supported. The worker can run locally or through the existing optimization-jobs trusted
command protocol with `--runner PATH/optimization-run`. That route stages hashed
inputs, records the runner manifest and collects the complete native archive in
a ZIP (64MiB per collected file limit).

```sh
python validation/urban_campaign.py run runs/converted-district/case.json \
  --map-provenance runs/converted-district/map-provenance.json \
  --output runs/district-rose --run-budget-s 120 --campaign-budget-s 1200 \
  --threads 1 --workers 2
```

The directions 0,30,…,330 are **model-local** meteorological directions from.
When map provenance is supplied, each job also reports the geographic direction
`(local − map_rotation) mod 360`. Equal directions are not a climatological wind
probability distribution. Supply actual wind frequencies for a later weighted
study. Concentrations are increments from the declared local sources under
neutral flow, not ambient total PM or short turbulent peaks.

An accepted row needs steady native checks and an independent archived-field
audit. A timeout remains incomplete even if a mass ledger closes. Hard worker
address-space limits and process-group cleanup bound runaway jobs; the RSS
field is a sampled observed peak, not a guaranteed exact process maximum.

The optional fcmaes worker adds `app.cfd.wind-direction` for optimization of the
same cold, single-constituent receptor objective. It propagates solver failures;
it does not turn an incomplete value into an optimizer score. The trusted-command
campaign is the path that retains full native fields and independent audits.

## Follow the gates

Run both resolutions on one direction with identical physical footprints,
sources, canopy and domain. Report sensitivity, not grid convergence, unless
the full convergence evidence exists. Separately importing each grid can drop
different buildings and must not be called a grid-only comparison.

The current exploratory measurements do not qualify a practical neighborhood
study. The [evidence page](../evidence/urban-extension.md) preserves the failed
rotation, convergence and budget rows. The conditional GPU experiment is not
triggered merely by a large grid; a million-cell target and a measured dominant
pressure bottleneck are both required. OpenFOAM code comparison and measured
urban data remain separate validation work.
