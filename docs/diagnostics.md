# Diagnostics

`cfd-craft check CASE` prints a `cfd-craft.check/0.1` report on stdout. Each
diagnostic has a code, a severity, a JSON path into the case (for example
`geometry[1]`, `sources[0].rate_kg_s_m`, `numerics.advective_cfl_max`) and a
message. Errors make the case invalid; warnings do not. `run` and `preview`
print the same report and exit 1 when the case is invalid, before any output
directory is created. `preview` checks the coarsened case it runs, then compares
it with the original's cell mask, which it counts without building the original
grid.

The grid, source and receptor checks need the built grid. When the estimated peak
does not fit this host (CFD-W070), they are skipped, so a check never allocates
more than the host can hold.

| Code | Severity | Meaning |
|---|---|---|
| CFD-E000 | error | The file is not a valid case: unknown or duplicate field, wrong type, trailing data. The path points at the element |
| CFD-E001 | error | Unsupported `schema_version` |
| CFD-E002 | error | Empty `name` |
| CFD-E003 | error | A domain length outside 1e-6..1e9 m |
| CFD-E004 | error | An axis with fewer than 2 or more than 4096 cells |
| CFD-E005 | error | `ground_open_top` on x or y |
| CFD-E006 | error | Estimated peak memory above `run.memory_limit_mib`, or more than 1e8 cells |
| CFD-E007 | error | Estimated artifacts above `output.max_total_mib` |
| CFD-E008 | error | Threads, step budget, pressure iterations or monitor window out of range |
| CFD-E009 | error | A time, tolerance or step limit that is not finite and positive |
| CFD-E010 | error | `advective_cfl_max` outside 0..0.45 |
| CFD-E011 | error | Neutral RANS without `ground_open_top` |
| CFD-E012 | error | Invalid flow parameters |
| CFD-E013 | error | Obstacles with prescribed uniform flow |
| CFD-E014 | error | Box ID missing or repeated, or bounds not increasing inside the domain |
| CFD-E015 | error | Constituent ID or diffusivity invalid |
| CFD-E016 | error | Source ID, constituent or declared rate invalid |
| CFD-E017 | error | Source support degenerate or outside the domain |
| CFD-E018 | error | More than one initial condition per constituent, or an undeclared one |
| CFD-E019 | error | Receptor ID missing or repeated |
| CFD-E020 | error | Steady sources without an open boundary to remove their mass |
| CFD-E021 | error | Invalid moving wall |
| CFD-E022 | error | Wall-time limit above seven days or physical horizon above 1e12 s |
| CFD-E023 | error | Laminar flow with `ground_open_top`; its open top exists only in the RANS closure |
| CFD-E024 | error | Prescribed velocity with a normal component at an impermeable boundary |
| CFD-E025 | error | Negative or nonfinite initial concentration |
| CFD-E026 | error | Invalid periodic Gaussian initial condition |
| CFD-E027 | error | Receptor support degenerate or outside the domain |
| CFD-E028 | error | A box contains no cell center, so the grid would not represent it; the path names the box |
| CFD-E030 | error | The geometry leaves no fluid cells |
| CFD-E040 | error | A source intersects a solid cell |
| CFD-E041 | error | A source has no support on the grid |
| CFD-E042 | error | A receptor is empty or samples a solid cell |
| CFD-E043 | error | A steady source in a fluid component without an outlet |
| CFD-E044 | error | The represented source density is not finite |
| CFD-E070 | error | `run` and `preview`: the estimated peak exceeds 80 % of this host's available memory |
| CFD-E072 | error | `preview` only: coarsening changes the solid volume by more than 20 % or the number of fluid components |
| CFD-E073 | error | `preview` only: the original cell mask cannot be counted (more than 1e8 cells, or its 4 bytes per cell do not fit this host), so the preview cannot be compared with it |
| CFD-W001 | warning | A box spans fewer than 10 vertical cells: too coarse for physical interpretation |
| CFD-W002 | warning | RANS blockage ratio above the COST 732 recommendation of 3 % |
| CFD-W003 | warning | RANS domain clearance below the COST 732 recommendation (about 5 H_max upstream, at the sides and above; 15 H_max downstream). Every open, slip or wall side is checked; periodic sides are not |
| CFD-W070 | warning | `check` only: the estimated peak exceeds 80 % of this host's available memory; the grid checks are skipped |

W002 and W003 encode the COST 732 best-practice guideline (Franke et al., 2007) as summarized by secondary sources that cite it. The primary document was not retrieved from its distribution share; `validation/data-inventory.json` records that. They are warnings because best-practice distances depend on the scenario: a wind-tunnel reproduction may use the tunnel's own dimensions.

Codes from a run, a restart or `report`, reported in `summary.json` `error` or on stderr:

| Code | Meaning |
|---|---|
| CFD-E031 | Closed fluid component with an incompatible net flux |
| CFD-E032 | Pressure CG lost positive definiteness |
| CFD-E033 | Pressure iteration limit reached |
| CFD-E050 | Checkpoint dimensions do not match the case |
| CFD-E051 | Nonfinite or invalid state, including concentration in a solid cell |
| CFD-E052 | Velocity divergence |
| CFD-E053 | Negative concentration beyond round-off; no clipping is applied |
| CFD-E054 | Eddy viscosity outside the declared numerical regime |
| CFD-E055 | The time step is not finite and positive |
| CFD-E060 | Checkpoint identity or checksum mismatch |
| CFD-E061 | Fields or checkpoint omitted because they would exceed the output budget; the manifest lists them under `omitted` and the run exits 2. `report` repeats the code on stderr for such an archive and exits 0 |
| CFD-E062 | The output directory already exists |
| CFD-E063 | The output directory cannot be created, for example because its parent does not exist |
| CFD-E064 | `report` rejects the archive; the message names the failed check |
| CFD-E065 | The restart checkpoint cannot be read or parsed, or is larger than half of `run.memory_limit_mib` |
| CFD-E066 | The restart checkpoint lies beyond `run.max_steps` or `run.end_time_s` of the case |

## External backend and reference data

These Python diagnostics carry the code and offending field in the error text.
They belong to the separate external artifact schema. E062/E063 are also used
for occupied/unavailable external output paths. The external tools exit 0 for
an accepted result, 2 for a completed, stopped or verified run without accepted
evidence, and 1 for a failed execution or invalid input
([backend guide](../integrations/OPENFOAM.md)).

| Code | Meaning |
|---|---|
| CFD-X001 | Invalid external case/input identity or execution-limit field, including an iteration limit without a divisor between 50 and 250 (`iterations`) |
| CFD-X002 | Missing/unsupported runtime, version, package identity or installer dependency |
| CFD-X003 | A child command exited unsuccessfully; the actual return code and log are retained |
| CFD-X004 | External execution wall deadline reached |
| CFD-X005 | External output/per-file budget reached |
| CFD-X006 | Invalid mesh, returned field, sample, numerical record or archive checksum |
| CFD-X007 | A completed external solve did not reach its convergence/continuity gate |
| CFD-X008 | External execution cancelled; process group stopped |
| CFD-X009 | A cross-solver comparison exceeds its frozen target |
| CFD-X010 | The solver log shows a numerical breakdown: `execution.solve.residual` for a NaN/Inf residual or continuity value, `execution.solve.continuity` for a reported mean continuity error (`sum local`, in units of U_ref/H) of at least 1. The process group is stopped and the failure archive retained |
| CFD-X011 | The independent Cartesian audit rejects `mesh.*` (points, faces, owner/neighbour order and orientation, boundary ranges, volume, first-cell heights), `fields.phi.*` or `wallShearStress.*` (missing, malformed, nonfinite, or zero traction on a wall); `run.numerical` marks an archive without a final field, which is not assessed |
| CFD-X012 | `initial_state.*`: an ineligible or changed restart source (`source.*`), a receipt that is incomplete or disagrees with the consumed inputs (fields, fixed inputs, metadata, controls, field header times), a runtime or rebuilt mesh that differs from the source (`runtime`, `mesh.*`), a stored face flux that fails the independent local gate (`phi.local_continuity`), or a stage input that cannot be written (`inputs`) |
| CFD-X013 | `comparison.*`: a restart comparison of two archives from different cases, recipes, meshes or runtimes, or without final fields; an invalid `mode` or missing `data`; a run of the fixed-work driver (`source`, `split`, `continuous`) that did not complete with a final field |
| CFD-D001 | Reference/protocol hash, measurement identity, pairing or metric input invalid |
| CFD-X014 | `mapping.*`: in a coarse-to-fine preparation, solve or archive, an unsupported source, level or initialization; changed source bytes or a broken source chain (`source.*`); failed source acceptance or audit; invalid mapped fields; consumed values that no single nearby source cell supplies in every field (`mapper.values`) or replay statistics that differ from the receipt (`mapper.replay`); utility arguments or logs that differ from the receipt (`mapper.*`, `commands`); changed generated boundaries or controls; missing, malformed or unreadable evidence; an exceeded output budget (`output`); or a runtime or rebuilt mesh that differs (`runtime`, `mesh.*`) |
| CFD-X015 | `refinement.*`: unsupported campaign limits or coarse source (`source.*`); a source changed during its checked snapshot (`source.copy.*`, `source.inventory`); a changed or incorrectly bound retained parent (`stages[N].parent.*`); a failed archive checkpoint (`archives.*`, preserving the underlying diagnostic); incompatible mesh-pair inputs, runtimes or observable identities (`pair.*`); or a symlink rejected before CI archive serialization (`archive.*`). No archive is repaired or resealed |
