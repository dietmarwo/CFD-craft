# Scripts

The Python tools a user calls. Each runs from the root of a checkout as
`python PATH`. This list comes from their argument parsers and exit statements.
Several write files: give each a new `--output`, and read the source of a script
before running it with other arguments.

## Setup

Native scripts need the release binary (`cargo build --release -p cfd-craft-cli`).
The scripts find it at `target/release/cfd-craft`; `--binary` overrides that.
OpenFOAM scripts need `--foam-root`, the Foundation 13 runtime that
[`integrations/install_openfoam13.py`](https://github.com/dietmarwo/CFD-craft/blob/main/integrations/install_openfoam13.py)
stages. The map and street converters need Shapely
(`integrations/requirements-urban.txt`). The mobile study needs the packages
of `integrations/requirements-mobile.txt` and the example binary
`target/release/examples/mobile_response`
(`cargo build --release --locked -p cfd-craft --example mobile_response`).

## Exit codes

A script exits 0 when its checks passed and 1 when they did not or its input was
invalid, unless the table says otherwise. Exit 2 means the work completed without
accepted evidence (the convention of the native CLI). Failures carry a code from
[diagnostics](../diagnostics.md). No exit code sets physical qualification.

## Inspect and export a run

| Script | Arguments | Result |
|---|---|---|
| `validation/export_vtk.py` | `--run DIR --output FILE.vtr [--max-mib 64]` | ParaView rectilinear file from a verified archive with fields. Exits 1 if `FILE` exists or the archive fails the field checks |
| `validation/check_profile.py` | `DIR` | Checks a `cfd-craft profile` directory against its archive; prints the findings |
| `validation/profile_case.py` | `--binary PATH --case CASE --output DIR` | Child-process resource use (KiB, Linux) of one command |

```bash
cfd-craft run cases/verification/periodic-tracer.json --output runs/a > /dev/null
python validation/export_vtk.py --run runs/a --output runs/a.vtr | python -c "import json,sys; print(json.load(sys.stdin)['cells'])"
```

```text
3456
```

## Verification and acceptance

| Script | Arguments | Result |
|---|---|---|
| `validation/run_suite.py` | `--output DIR [--binary PATH] [--preset smoke\|study] [--pressure-preconditioner ic0\|multigrid] [--abl-numerics JSON] [--abl-steady]` | Analytic cases against frozen targets, with a report under `--output` |
| `validation/cavity.py` | `--output DIR [--binary PATH]` | Lid-driven cavity against the Ghia reference; a numerical benchmark, not urban validation |
| `validation/manual_examples.py` | `--output DIR [--binary PATH] [--example-dir DIR] [--foam-root ROOT]` | Runs the native examples; with `--foam-root` also the OpenFOAM ones |
| `validation/check_installed.py` | `--output FILE [--binary PATH]` | Installed-wheel acceptance; run it with `python -I` outside the checkout |

## Measurement

| Script | Arguments | Result |
|---|---|---|
| `validation/benchmark_native.py` | `--baseline PATH --candidate PATH --case CASE --mode setup\|pressure\|momentum\|production\|transport\|steps --output DIR [--rounds 5] [--inner 4] [--steps 8] [--threads 1] [--timeout-s 180]` | Alternating paired probes of two binaries at fixed work |
| `validation/compare_backends.py` | `--foam-root ROOT --output DIR [--binary PATH] [--repeats 1] [--timeout-s 180] [--grid-sweep ...]` | Same-host cavity timing, native against OpenFOAM. Exit 2 in sweep mode when the workflow is valid but a gate failed |

`--grid-sweep` adds `--levels`, `--grids`, `--sweep-rounds`, `--accuracy-target`,
`--native-wall-s`, `--native-max-steps`, `--native-pressure-preconditioner`,
`--native-numerics`, `--native-span` and `--foam-iterations`; read
`validation/compare_backends.py` for their defaults.

## Tutorials

| Script | Arguments | Result |
|---|---|---|
| `tutorials/canyon_study.py` | `--output DIR [--binary PATH] [--preset smoke\|sensitivity\|study]` | Canyon wind, grid, domain and Schmidt sensitivity; failed rows are kept |
| `tutorials/source_inference.py` | `--output DIR [--binary PATH] [--preset smoke\|study]` | Three-source inverse problem with held-out sensors |
| `tutorials/external_cfd.py` | `--foam-root ROOT --output DIR [--binary PATH] [--data PATH] [--preset cavity\|smoke\|study] [--timeout-s 600]` | Both backends and a measurement comparison. Exit 2 for recorded unaccepted evidence, 1 for a workflow error |
| `tutorials/backstep_resolution.py` | `--foam-root ROOT --output DIR [--data PATH] [--preset smoke\|controls\|study] [--timeout-s 900] [--iterations 6000] [--max-stages 1]` | Convergence and mesh-resolution study. Exit codes as above |

## City blocks and mobile measurements

Guide chapters [22](../guide/22-urban-geometry-particles-vegetation.md),
[23](../guide/23-mobile-paths-and-virtual-rides.md) and
[24](../guide/24-mobile-source-inference.md) use these scripts. Each `--output`
must not exist yet.

| Script | Arguments | Result |
|---|---|---|
| `integrations/urban_map.py` | `SOURCE --output DIR --crop XMIN YMIN XMAX YMAX --cell-m M --coordinate-system TEXT --license TEXT --attribution TEXT [--template CASE] [--rotation-deg DEG] [--height-attribute height] [--max-ground-range-m 0.5] [--ensemble-clearance] [--binary PATH]` | Input: building footprints as GeoJSON polygons or CityJSON solids in projected meters. Output: `case.json` with polygon prisms, `check.json` (the report of `cfd-craft check`) and `map-provenance.json` (input hash, license, crop, rotation, assumed heights, dropped buildings). `--template` (default `cases/canyon/wh1-wind270.json`) supplies flow, numerics and budgets. Exit 1 with `CFD-M001` |
| `integrations/traffic_sources.py` | `--case CASE --map-provenance FILE --streets GEOJSON --rates CSV --height-m M --output DIR [--binary PATH] [--street-id-property id] [--street-license TEXT] [--street-attribution TEXT] [--rates-description TEXT]` | Input: a converted case with its provenance, street centerlines in the same coordinates and a CSV with `street_id`, `constituent`, `rate_kg_s_m`, `units`. Output: `case.json` with added line sources, `traffic-provenance.json`, `check.json`, `check.stderr`. Exit 1 with `CFD-M002` and a `diagnostic.json` ([input contract](https://github.com/dietmarwo/CFD-craft/blob/main/integrations/traffic-sources.md)) |
| `validation/urban_campaign.py run` | `CASE --output DIR [--binary PATH] [--run-budget-s 120] [--campaign-budget-s 1200] [--threads 1] [--workers 2] [--map-provenance FILE] [--runner PATH]` | Input: a `neutral_rans` case. Runs the wind directions 0, 30, …, 330 degrees from cold starts. Output: `campaign-plan.json` (written first), one folder `wind-DDD` per direction with the consumed case, the run archive, the independent field check and `result.json`, then `results.json` and `report.json`. Exit 0 when all twelve are accepted within the campaign budget, 2 otherwise. `--runner` sends the directions through `optimization-run` |
| `validation/urban_campaign.py worker` | `JOB [--binary PATH]` | Runs the one direction that a `job.json` of the campaign describes. The campaign and the job launcher `integrations/launch_urban_command.py` call it |
| `integrations/virtual_ride.py` | `RUN_DIR --constituent ID --path ID --speed-m-s V --sampling-interval-s S --output FILE [--response-time-s 0] [--initial-kg-m3 C]` | Input: an accepted steady run archive with a path receptor. Output: a JSON file (`cfd-craft.virtual-ride/0.1`) with times, positions, the field along the ride and the reading of a first-order sensor; prints the number of readings. Exit 1 with `CFD-M004` |
| `tutorials/mobile_measurements.py run` | `--output DIR [--preset source-response\|canyon] [--config PLAN.json] [--binary PATH]` | Runs a source-inference study: per wind one flow, one frozen-flow transport run per source group and one reference run; then the ride response matrix, the fit, pass planning and route selection. Output: `frozen-study-plan.json` (written first), the archives per wind, `mobile-response-matrix.json`, `virtual-observations.csv`, `report.json`. Exit 0 when every check of the plan passes, 2 otherwise, 1 with `CFD-M003` for invalid input. `--binary` is the `mobile_response` example |
| `tutorials/mobile_measurements.py fit` | `MATRIX CSV --train RIDE [RIDE ...] --heldout RIDE [RIDE ...] --output FILE` | Input: a response matrix of `run` and a CSV with `wind,ride,sample_index,concentration_kg_m3`. Output: fitted multipliers, rank and ambiguous combinations, held-out error and the hashes of both inputs. Exit 1 with `CFD-M003` |
| `validation/summarize_urban.py` | `EVIDENCE_DIR --output FILE` | Summarizes the directory layout of the [urban evidence record](../evidence/urban-extension.md): paired default and multigrid runs, district campaigns, failed rows included |

`integrations/mobile_inference.py` is a module, not a command: `identifiability`,
`infer_sources`, `required_passes`, `route_information` and `select_routes`
are the functions behind chapter 24. `integrations/urban_job.py` stages the
campaign directions as jobs of `optimization-run`
([chapter 14](../guide/14-optimization-jobs.md#wind-direction-jobs-for-a-city-block)).

## OpenFOAM backend

`python integrations/openfoam_backend.py COMMAND`:

| Command | Arguments | Exit |
|---|---|---|
| `prepare` | `--case cavity\|backstep --output DIR [--level 1] [--cavity-grid N] [--iterations 3000] [--data PATH] [--mesh-family legacy\|wall-resolved] [--solver-profile legacy\|simplec\|simple]` | 0, or 1 for an invalid request |
| `prepare-restart` | `--source DIR --output DIR [--iterations 6000]` | 0, or 1 for an ineligible source |
| `prepare-mapped` | `--source DIR --level N --output DIR --foam-root ROOT [--iterations 6000] [--data PATH] [--timeout-s 300] [--output-mib 512] [--memory-mib 2048]` | as `prepare-restart` |
| `run` | `--case CASE --output DIR --foam-root ROOT [--timeout-s 600] [--output-mib 256] [--memory-mib 2048]` | 0 accepted; 2 completed, timed out or canceled without accepted evidence; 1 execution failed |
| `report` | `DIR` | as `run` for the archived result; 1 if verification fails |

| Script | Arguments | Result |
|---|---|---|
| `integrations/install_openfoam13.py` | `--output DIR [--package-file DEB]` | Stages the pinned package without root; 1 on failure |
| `integrations/run_jobs.py` | `--runner PATH --output DIR [--binary PATH] [--worker PATH]` | Runs a CFD command and scalar application profiles on a foreground node |

## Release tools

| Script | Arguments | Result |
|---|---|---|
| `scripts/package_version.py` | none | Prints the release version; fails when the three version sources disagree |
| `scripts/check_release.py` | none | Checks crate metadata, licenses and lockfiles before packaging |
| `scripts/generate_reference.py` | `[--binary PATH] [--check]` | Writes the generated pages of this section; `--check` writes nothing and fails when one differs |
| `scripts/generate_cases.py` | none | Rewrites the committed cases under `cases/`; do not run it casually |
