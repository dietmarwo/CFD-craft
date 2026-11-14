# Agent entry point
<!-- check: rel=1e-4 -->

CFD-craft is a CPU research solver for constant-density incompressible flow
and passive-gas dispersion on uniform Cartesian grids. A case is one strict
JSON file; a run is bounded and reports why it stopped, what its numerical
checks support and an experimental-validation label. An optional adapter runs
two generated cases on OpenFOAM Foundation 13 for cross-checks.

Version 0.1.0 is a research prototype. A numerically accepted run is not an
experimentally validated prediction.

## The run loop

Commands run from the root of a checkout, with the built command on `PATH`
(`cargo build --release --locked`, then
`export PATH="$PWD/target/release:$PATH"`) and the packages of
`requirements-validation.txt` installed. Without a checkout,
`pip install cfd-craft` gives `check` and `simulate` in Python
([chapter 1](guide/01-first-run.md)), but no fields or archives.

1. **Discover.** `cfd-craft describe` prints the schemas, the allowed values
   and the exit codes. Use only fields it lists.
2. **Choose or edit a case.** Start from a committed case under
   [`cases/`](https://github.com/dietmarwo/CFD-craft/blob/main/cases) or
   [`examples/manual/`](https://github.com/dietmarwo/CFD-craft/blob/main/examples/manual);
   write edits to a new file.
3. **Check.** `cfd-craft check CASE` exits 1 on invalid input and prints every
   diagnostic with a `code` and the `path` of the offending field. Read all of
   them, warnings included, before you spend compute.
4. **Bound the run.** Set `run.max_steps`, `run.wall_time_limit_s`,
   `run.threads`, `run.memory_limit_mib` and `output.max_total_mib`. Choose a
   new output directory whose parent exists.
5. **Run.** `cfd-craft run CASE --output NEW_DIR`. Read `termination`,
   `assessment`, every entry of `checks` and `experimental_validation` in
   `summary.json`.
6. **Verify.** `cfd-craft report NEW_DIR` checks the archive against its
   hashes. `python validation/check_fields.py NEW_DIR` recomputes continuity,
   mass balances and receptor values from the stored fields.

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

## Machine-readable entry points

| Entry point | What it gives |
|---|---|
| `cfd-craft describe` | JSON with `case_schema`, `result_schema`, `phase_profile_schema`, `exit_codes`, the allowed `physics`, `scalar_advection`, `momentum_advection`, `steady_algorithms` and `pressure_preconditioners`, the defaults, `limitations` and the build identity |
| `python -m cfd_craft describe` | The same description from the Python package |
| `cfd-craft check CASE` | `cfd-craft.check/0.1`: `valid`, `cells`, size estimates and `diagnostics`, each with `code`, `severity` and `path` |
| `summary.json` of a run | `cfd-craft.result/0.1`: `termination`, `assessment`, `checks`, `model_scope`, `experimental_validation`, work counts, receptor values in kg/m3 |
| Exit codes | 0 success (valid case, accepted run, intact archive); 1 invalid input or an execution or I/O error; 2 a run without numerical acceptance, or an accepted run that omitted files over its output budget |
| [Diagnostics](diagnostics.md) | Every `CFD-` code with its meaning |

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
  wall; volume receptors integrate the exact overlap.

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
| Many runs, source inference | [Many runs](guide/12-studies.md) |
| Optimization | [Optimization lessons](guide/13-optimization-lessons.md), [optimization jobs](guide/14-optimization-jobs.md) |
| A diagnostic or an unexpected exit | [Troubleshooting](guide/21-troubleshooting.md) |
| Any other task | [How do I …?](how-to.md) |

Chapters 10, 12, 14, 16, 18 and 19 end with a section "A task for an agent":
a bounded task with its budgets and interpretation rules.

## Opt-in numerics

The defaults are donor-cell momentum, explicit pseudo-time and an IC(0)
pressure preconditioner, and they stay. For a steady run, opt in with
`numerics.momentum_advection = limited_upwind`, `steady_algorithm =
implicit_projection`, `pressure_relative_tolerance` 0.1, `max_time_step_s` 100
and, for a two-dimensional problem, one cell on the periodic axis. On the
cavity this reaches the same accepted steady state in far fewer iterations.
`pressure_preconditioner = multigrid` is rejected for a case with `geometry`
(`CFD-E034`). See
[the implicit recipe](guide/09-opt-in-numerics.md#the-implicit-recipe) and the
[implicit steady results](evidence/implicit-steady.md).

## OpenFOAM backend

- It runs two generated cases (laminar cavity, turbulent backward-facing
  step); it does not translate native cases and runs no dispersion.
- Its archives have their own schema and their own `report`
  (`integrations/openfoam_backend.py report`); do not give them to
  `cfd-craft report`.
- Continuation needs a complete source archive whose stored face flux passes
  the independent gate; failed, timed-out and cancelled runs are not eligible.
- Mesh initialization needs an accepted, independently audited, cold-generated
  source; coarse face flux is never copied.
- Code agreement, comparison with measurements and physical qualification are
  separate results; none of them qualifies the native canyon model.

Chapters [15](guide/15-openfoam-first-run.md), [16](guide/16-compare-solvers.md),
[17](guide/17-continuation-and-mapping.md), [18](guide/18-backstep-resolution.md)
and [19](guide/19-refinement-campaign.md) cover it.

## Scope

Version 0.1.0 models uniform Cartesian grids with box-shaped solids, laminar
flow, one neutral k-epsilon package and passive gas. It does not model
particles, deposition, vegetation, LES, chemistry, stretched grids or GPU
execution. The fcmaes worker supports prescribed-flow, three-source scalar
allocation only. Nothing is experimentally validated; the canyon validation
gate (measured data and a grid study) is open. The
[model cards](model-cards/README.md) state the scope of each component.

## For contributors

Changing the solver: start at the [developer pages](developer/README.md) and
follow
[`AGENTS.md`](https://github.com/dietmarwo/CFD-craft/blob/main/AGENTS.md).
