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
