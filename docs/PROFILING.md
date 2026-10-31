# Native phase profiling and cavity accuracy sweeps

Profiling measures the existing algorithm to establish a baseline for pressure
multigrid and better momentum discretization. Read the
[iteration plan](iterations/17-gap-measurement-plan.md) and the
[baseline results](../validation/GAP_BASELINE.md) for scope and recorded results.

## Profile a real run

```sh
cargo build --release --locked
mkdir -p runs
target/release/cfd-craft profile cases/verification/lid-cavity.json --output runs/profile-cavity
target/release/cfd-craft report runs/profile-cavity/run
python validation/check_profile.py runs/profile-cavity
```

The canonical cavity case runs a transient interval. For a steady measurement,
make a case copy with `run.mode` set to `steady` and `run.threads` to 1. Case
checks and resource limits apply to both commands. `--restart CHECKPOINT` uses
the same verified native restart contract as `run`.

The output path must be new and its parent must exist. An envelope contains:

- `run/`: an ordinary `cfd-craft.manifest/0.1` archive, readable by the existing
  native reporter and independent field checker.
- `profile.json`: `cfd-craft.native-profile/0.1`, containing the summary,
  consumed input/source/state/manifest identities, initial counters and a
  `cfd-craft.phase-profile/0.1` timing record.

The command exits 0 for accepted numerical evidence with all requested artifacts,
2 for incomplete/failed numerical evidence or output omissions, and 1 for an
invalid request or execution/I/O failure. A numerical failure retains its profile
and ordinary archive. A process killed without a chance to write its results
cannot guarantee a final profile.

`check_profile.py` checks the envelope's link to the returned archive, work and
nested time accounting. It runs the independent archived-field audit when
fields are available. Its integrity verdict, native numerical assessment and
independent audit remain distinct. These checks establish consistency; they
do not authenticate a maliciously resealed archive or supply physical validation.

## Interpret time and work

Each phase reports calls, inclusive seconds and exclusive seconds. For example,
`pressure_projection` includes `pressure_solve`, which includes factor/operator
setup. **Add exclusive time only.** The sum is compared with the enclosing
solver and archive-write spans; the request remainder is `unattributed_s`.

`solver_run` includes grid/state setup, timesteps, monitoring and assessment.
`step` includes momentum, pressure, turbulence and scalar subphases. Short
operations such as intermediate allocations remain in their enclosing phase's
exclusive time. The control timer starts after preflight and checkpoint import,
includes thread-pool setup, solver and archive writing, and ends before profile
JSON serialization. The outer workflow measures independent checking and startup.

For `pressure_solve`, `work_units` counts attempted PCG iterations whose operator
work started. `operator_applications` includes those compact products plus
independent face-by-face true-residual checks; those checks have their own count.
`preconditioner_applications` counts IC(0) applications. A factor-setup span occurs
only when construction runs, including a zero-RHS first projection. Timers and
locks occur at phase boundaries; inner iterations update local integer counters.

The ordinary summary's steps/pressure iterations describe retained state.
Profile work includes an unsuccessful step. Subtract `initial_steps` and
`initial_pressure_iterations` for a restarted invocation. A failed projection
can have positive attempted work and zero new retained iterations. Do not divide
failed work by retained steps to estimate step cost.

Profiling consumes wall time. Cases close to a deadline can stop at different
steps. Compare exact fields on fixed work or comfortably accepted runs, and
measure on/off overhead with paired runs before making timing claims.

## Rust API

Given a validated `Case` named `case` in a function returning `cfd_craft::Result`,
use the same solver entry point:

```rust
use cfd_craft::solver::{self, Control};

let control = Control::new(case.run.wall_time_limit_s).with_profiling();
let result = solver::run(&case, &control, None)?;
let timing = control.profile()?.expect("profiling enabled");
println!("{} retained steps", result.state.steps);
println!("{} seconds accounted", timing.accounted_exclusive_s);
```

The caller owns its Rayon pool, producer identity and publication policy.
`Control::profile` without `with_profiling` returns `None`. Custom
`Control::span(Phase)` scopes must finish in nested order; snapshots with active
or incorrectly nested spans return `CFD-B003 profile.active` or `.nesting`.
Stacks are per thread. Concurrent callers can have aggregate exclusive time
exceeding elapsed wall time; the CLI uses serial orchestration.

## Measure cost at a declared accuracy

```sh
python validation/compare_backends.py --grid-sweep \
  --binary target/release/cfd-craft --foam-root runs/openfoam13/runtime/opt/openfoam13 \
  --levels 1 2 --sweep-rounds 3 --accuracy-target 0.01 \
  --native-wall-s 180 --timeout-s 180 --native-max-steps 20000 \
  --foam-iterations 3000 --output runs/accuracy-sweep
```

Install the pinned runtime through the [backend guide](../integrations/OPENFOAM.md).
The sweep keeps one warmup and the requested timed rows for each configuration,
alternating native/OpenFOAM order within each grid block. It adds a native 12²
diagnostic. Supported paired levels 1,2,3 mean 24²,48²,72² in the flow plane.
Native keeps two periodic span cells; OpenFOAM keeps one empty span cell.

Every row retains numerical acceptance, independent evidence, the frozen 0.06
Ghia screen and measured maximum centerline-u error separately. A timeout,
iteration limit or accuracy miss remains in `report.json`. The 0.01 target is a
development objective; existing numerical checks still apply.

Best cost at the target uses configurations whose timed repetitions are all
accepted and repeat their work, producer and sampled profile. Warmups do not
enter medians. If a backend misses the target on every tested grid/budget, its
best cost and the cross-backend ratio are `null`, with an explicit
target-not-reached status. No crossing is extrapolated.

The sweep exits 0 if all rows pass existing numerical/audit/reference checks,
2 when a valid workflow includes unaccepted evidence, and 1 for an invalid
workflow, changed input or inconsistent repeated result. Missing the development
target alone is a recorded outcome and does not invalidate a sweep.

Workflow time includes preparation, a bounded child, archive checks and profile
evaluation. Native solver time is `elapsed_s`; OpenFOAM solver time is its
`foamRun` child time. Separate process time and GNU-time RSS observations are
retained. RSS means maximum individual process RSS, including waited descendants,
rather than simultaneous aggregate memory; it is explicitly unavailable without
GNU time. Inspect timer scopes before comparing the earlier
[comparison](../validation/BACKEND_COMPARISON.md).

The old comparator without `--grid-sweep` retains its three-method, balanced
permutation experiment and fail-on-unaccepted behavior.

For a hosted run, dispatch **CFD checks** with `external=accuracy`. It builds the
release, installs the pinned runtime, runs the 24²/48² sweep and uploads the
complete evidence. Notices show accepted-row counts, medians and unreached
targets. This explicit opt-in is separate from the existing `all` budget.
