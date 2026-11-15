# Agent entry point
<!-- check: rel=1e-4 -->

CFD-craft is a CPU research solver for constant-density incompressible flow
and the dispersion of gases and particles around buildings on uniform
Cartesian grids. A case is one strict JSON file; a run is bounded and reports
why it stopped, what its numerical checks support and an
experimental-validation label. Scripts turn a city map and street data into a
case and turn an accepted run into virtual sensor rides and estimates of
street emissions. An optional adapter runs two generated cases on OpenFOAM
Foundation 13 for cross-checks.

Version 0.1.1 is a research prototype. A numerically accepted run is not an
experimentally validated prediction.

## The run loop

Commands run from the root of a checkout, with the built command on `PATH`
(`cargo build --release --locked`, then
`export PATH="$PWD/target/release:$PATH"`) and the packages of
`requirements-validation.txt` installed. Without a checkout,
`pip install cfd-craft` gives `check` and `simulate` in Python
([chapter 1](guide/01-first-run.md)), but no fields or archives.

1. **Discover.** `cfd-craft describe` prints the schemas, the allowed values
   and the exit codes.
2. **Choose or edit a case.** Start from a committed case under
   [`cases/`](https://github.com/dietmarwo/CFD-craft/blob/main/cases) or
   [`examples/manual/`](https://github.com/dietmarwo/CFD-craft/blob/main/examples/manual);
   write edits to a new file. For a city block, let
   `integrations/urban_map.py` write the case from a map and
   `integrations/traffic_sources.py` add line sources from supplied street
   rates; read their provenance files (assumed heights, dropped buildings,
   omitted streets) before you go on.
3. **Check.** `cfd-craft check CASE` exits 1 on invalid input and prints each
   diagnostic with a `code` and the `path` of the offending field. Read all of
   them, warnings included, and check again after a fix: a parse error is
   reported alone, and the checks that need the grid run only when no other
   error is left.
4. **Bound the run.** Set `run.max_steps`, `run.wall_time_limit_s`,
   `run.threads`, `run.memory_limit_mib` and `output.max_total_mib`. Choose a
   new output directory whose parent exists.
5. **Run.** `cfd-craft run CASE --output NEW_DIR`. Read `termination`,
   `assessment`, every entry of `checks` and `experimental_validation` in
   `summary.json`.
6. **Verify.** `cfd-craft report NEW_DIR` checks the archive against its
   hashes. `python validation/check_fields.py NEW_DIR` recomputes continuity,
   mass balances and receptor values from the stored fields, and also the
   building masks, deposition, vegetation drag and path samples of a case
   that has them.
7. **Derive, only from an accepted run.** `integrations/virtual_ride.py`
   computes a sensor ride along a path receptor;
   `tutorials/mobile_measurements.py` builds a ride response matrix on one
   frozen flow per wind, fits street emissions and selects routes;
   `validation/urban_campaign.py` repeats steps 3 to 6 for twelve wind
   directions. The ride and study tools refuse a run that is not accepted;
   the study and the campaign keep failed rows.

```bash
cfd-craft describe > runs/describe.json
cfd-craft check examples/manual/point-source.json > runs/check.json
cfd-craft run examples/manual/point-source.json --output runs/point > /dev/null
cfd-craft report runs/point > /dev/null
python validation/check_fields.py runs/point > runs/fields-check.json
```

```python
import json

s = json.load(open("runs/point/summary.json"))
print(s["termination"], s["assessment"], s["model_scope"])
print(all(c["passed"] for c in s["checks"]), s["experimental_validation"])
tracer = next(c for c in s["constituents"] if c["id"] == "tracer")
print(f"R_down = {tracer['receptors_kg_m3']['R_down'] * 1e9:.6g} micrograms/m3")
print("fields check passed:", json.load(open("runs/fields-check.json"))["passed"])
```

```text
completed steady_discrete_solution prescribed_flow_passive_transport
True not_validated; see validation/data-inventory.json
R_down = 17.8118 micrograms/m3
fields check passed: True
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## Rules

- Use only the fields that `describe` lists. Do not invent fields from older
  proposals; an unknown field is an error (`CFD-E000`).
- Never weaken a tolerance or a gate after a failure.
- Keep failed and incomplete rows in every report, with their actual work counts.
- `completed` is not `accepted`, and `accepted` is not `validated`. An
  iteration or time limit is incomplete even when some checks pass.
- Exit 0 of `report` means an intact archive, not convergence.
- Look up constituents and receptors by ID, never by position: receptor maps
  are sorted as text (`R10` before `R2`).
- Never write into a run directory, and never reuse one.
- Never turn an earlier saved state of a failed run into a final result.
- Compare settings only with the same source, geometry, sampling and
  numerical-fidelity definitions.
- The canyon cases are illustrative research cases on a coarse grid, not a
  reproduction of a wind-tunnel experiment.
- A campaign or study that finished is not a set of accepted results. Read
  `accepted` of every direction and the checks of every study; a timeout
  stays incomplete even when a mass balance closes.
- Never invent an input that a tool asks for: building heights, emission
  rates, sensor noise and wind frequencies are supplied or reported as
  assumptions. No tool moves a source, a route or a receptor out of a solid.
- A virtual ride is a pass through a steady mean field of the declared
  sources: no turbulence, no background, no measured sensor.
- When a response matrix is rank deficient, report the ambiguous combination
  of streets; do not interpret their individual rates.
- Particle, vegetation and path results carry the same three labels as every
  result. None is experimentally validated, and inference from rides is
  verified on synthetic data of the same model only.

## Machine-readable entry points

| Entry point | What it gives |
|---|---|
| `cfd-craft describe` | JSON with `case_schema`, `result_schema`, `phase_profile_schema`, `exit_codes`, the allowed `physics`, `scalar_advection`, `momentum_advection`, `steady_algorithms`, `pressure_preconditioners`, `geometry_kinds` and `receptor_kinds`, the `path_sampling` limits, the defaults, `limitations` and the build identity |
| `python -m cfd_craft describe` | From the Python package: the same `case_schema` and `result_schema`, the binding's `capabilities` and its build identity. It has no `exit_codes`, value lists or `limitations` |
| `cfd-craft check CASE` | `cfd-craft.check/0.1`: `valid`, `cells`, size estimates and `diagnostics`, each with `code`, `severity` and `path` |
| `summary.json` of a run | `cfd-craft.result/0.1`: `termination`, `assessment`, `checks`, `model_scope`, `experimental_validation`, work counts, receptor values in kg/m3; per constituent also `paths`, `deposited_kg` and `deposition_rate_kg_s`; `particulate_matter`, `vegetation` and `frozen_flow` where they apply |
| `geometry.json` of a run | Cell counts, the mask hash and, per building under `shapes`, exact and represented volume and the narrowest street in cells |
| `map-provenance.json`, `traffic-provenance.json` | `cfd-craft.map-provenance/1`, `cfd-craft.traffic-provenance/1`: input hashes, license, crop, rotation, assumed heights, dropped buildings, kept and omitted street lengths, the exit code of `check` |
| Output of `virtual_ride.py` | `cfd-craft.virtual-ride/0.1`: parameters, times, positions, `steady_field_kg_m3`, `sensor_kg_m3` and the hashes of the run it read |
| `report.json` of the mobile study | `cfd-craft.mobile-study-result/1`: `passed`, `gate_checks`, `inference` (multipliers, rank, ambiguous combinations), `pass_count_planning`, `route_selection` |
| `report.json` of the wind campaign | `cfd-craft.urban-report/1`: one row per direction with `accepted`, and `within_budget` |
| Exit codes | 0 success (valid case, accepted run, intact archive); 1 invalid input or an execution or I/O error; 2 a run without numerical acceptance, or an accepted run that omitted files over its output budget |
| [Diagnostics](diagnostics.md) | Every `CFD-` code with its meaning; the scripts report `CFD-M001` (map), `CFD-M002` (streets), `CFD-M003` (inference), `CFD-M004` (ride) and `CFD-U001` (campaign) |

Generated pages: [case schema](reference/case-schema.md),
[result schema](reference/result-schema.md), [command line](reference/cli.md),
[Python API](reference/python-api.md); also the [result contract](result-contract.md).

## Conventions that cause wrong cases

- Coordinates are east, north, up, in meters. A meteorological wind direction
  is where the wind comes **from**, clockwise from north: 270 blows toward +x.
- Stored pressure is kinematic pressure (m2/s2). In RANS cases the isotropic
  turbulent pressure is absorbed into it.
- A point source declares kg/s, a line source kg/s per meter, a volume source
  kg/s per cubic meter. The solver integrates the represented support and
  rejects sources inside solids.
- Use `linear_upwind` for an exact source-response matrix; the MUSCL limiter
  makes transport nonlinear.
- A steady source needs an open boundary. A closed or fully periodic domain
  with a steady source has no steady solution (`CFD-E020`).
- Give a trace gas its molecular diffusivity (of order 1e-5 m2/s). In RANS
  cases the turbulent diffusivity does the mixing; a large constant hides it.
- Point receptors interpolate from cell centers and reject stencils through a
  wall; volume receptors integrate the exact overlap. A path receptor takes
  east and north coordinates and one height; its samples are at most
  `sample_spacing_m` apart, and a segment through a building is an error.
- A building is a set of whole cells: a cell is solid when its center lies in
  the box or footprint. Read `shapes` in `geometry.json` for the volume error
  and the street width in cells.
- A particle `diameter_m` is in meters (1e-6 is one micrometer). PM2.5 and
  PM10 are sums of whole bins by aerodynamic diameter.
- A vegetation volume is fluid with drag, not a solid. A volume without a
  fluid cell center has no effect and draws no message.
- A converted map is rotated. `flow.direction_deg_from` is in the model
  frame; `map-provenance.json` keeps the map direction and `rotation_deg`.

Units of every field: [units and conventions](reference/units-and-conventions.md).

## Where to find what

| Task | Where |
|---|---|
| Run a first case from Python | [First run](guide/01-first-run.md) |
| Read the files of a run directory | [The files of a run](guide/03-cli-and-archive.md#the-files-of-a-run) |
| Decide whether a result can be used | [Can I trust this result?](guide/04-reading-a-result.md) |
| Budgets, preview, cancellation | [Before you spend compute](guide/07-budgets-preview-cancel.md) |
| Resume a stopped run | [Checkpoint and restart](guide/08-checkpoint-restart.md) |
| Buildings and a street canyon | [Buildings and a street canyon](guide/10-street-canyon.md) |
| Polygon footprints, a map, particles, vegetation, wind-direction campaign | [Urban geometry, particles and vegetation](guide/22-urban-geometry-particles-vegetation.md) |
| Sample along a route, simulate a sensor ride | [Mobile paths and virtual rides](guide/23-mobile-paths-and-virtual-rides.md) |
| Street emissions from rides, passes, routes | [Source inference and route selection from rides](guide/24-mobile-source-inference.md) |
| Many runs, source inference | [Many runs](guide/12-studies.md) |
| Optimization | [Optimization lessons](guide/13-optimization-lessons.md), [optimization jobs](guide/14-optimization-jobs.md) |
| A diagnostic or an unexpected exit | [Troubleshooting](guide/21-troubleshooting.md) |
| Any other task | [How do I …?](how-to.md) |

Chapters 10, 12, 14, 16, 18, 19 and 23 end with a section "A task for an
agent": a bounded task with its budgets and interpretation rules.

## Opt-in numerics

The defaults are donor-cell momentum, explicit pseudo-time and an IC(0)
pressure preconditioner, and they stay. For a steady run, opt in with
`numerics.momentum_advection = limited_upwind`, `steady_algorithm =
implicit_projection`, `pressure_relative_tolerance` 0.1, `max_time_step_s` 100
and, for a two-dimensional problem, one cell on the periodic axis. On the
cavity this reaches the same accepted steady state in far fewer iterations.
`pressure_preconditioner = multigrid` also works with buildings and separate
fluid regions. There it needs fewer pressure iterations but gave no
consistent gain in run time, and it is slower than the default on strongly
anisotropic grids (`CFD-W004`); see
[chapter 22](guide/22-urban-geometry-particles-vegetation.md#multigrid-with-buildings). See
[the implicit recipe](guide/09-opt-in-numerics.md#the-implicit-recipe) and the
[implicit steady results](evidence/implicit-steady.md).

## OpenFOAM backend

- It runs two generated cases (laminar cavity, turbulent backward-facing
  step); it does not translate native cases and runs no dispersion.
- Its archives have their own schema and their own `report`
  (`integrations/openfoam_backend.py report`); do not give them to
  `cfd-craft report`.
- Continuation needs a complete source archive whose stored face flux passes
  the independent gate; failed, timed-out and canceled runs are not eligible.
- Mesh initialization needs an accepted, independently audited, cold-generated
  source; coarse face flux is never copied.
- Code agreement, comparison with measurements and physical qualification are
  separate results; none of them qualifies the native canyon model.

Chapters [15](guide/15-openfoam-first-run.md), [16](guide/16-compare-solvers.md),
[17](guide/17-continuation-and-mapping.md), [18](guide/18-backstep-resolution.md)
and [19](guide/19-refinement-campaign.md) cover it.

## Scope

CFD-craft models uniform Cartesian grids with buildings as boxes or polygon
prisms, laminar flow, one neutral k-epsilon package, optional porous
vegetation, passive gases and particle size classes with settling and
deposition. It does not model terrain, LES, buoyancy, chemistry, stretched
grids or GPU execution. The fcmaes worker has two models: a prescribed-flow
allocation of three sources and a wind-direction objective for a
`neutral_rans` case.

Nothing is experimentally validated; the canyon validation gate (measured
data and a grid study) is open. Four further gates are open for city blocks:
multigrid with buildings has no consistent end-to-end gain; the canyon
rotated by 45 degrees did not pass its grid study; no direction of the
district demonstration converged within its short budget; inference from
rides is verified on synthetic data of the same model only. The
[model cards](model-cards/README.md) state the scope of each component, and
the [evidence index](evidence/README.md#open-gates) lists the gates.

## For contributors

Changing the solver: start at the [developer pages](developer/README.md) and
follow
[`AGENTS.md`](https://github.com/dietmarwo/CFD-craft/blob/main/AGENTS.md).
