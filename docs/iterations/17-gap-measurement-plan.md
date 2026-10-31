# Iteration 17: measure the native/OpenFOAM performance gap (P0)

Baseline: merged PR #10, `67599967afde765ba10d947cef5e5a0211549768`.
This is the first implementation stage of the reviewed gap-closing plan.

## Scope and decisions

1. Add opt-in, aggregated native phase profiling. A new `profile` command owns
   a fresh envelope containing `run/` (an ordinary native archive) and a
   separately versioned `profile.json`. The existing case, result and archive
   formats remain readable. Record input/build/archive identities, attempted
   pressure work, committed steps, inclusive/exclusive timings and unattributed
   request time. No per-cell or per-iteration locks/timers.
2. Extend the existing backend comparator with an explicit accuracy-sweep mode.
   Use supported OpenFOAM levels 1..3 (24/48/72), matching native flow-plane
   grids and the existing span treatments. Retain every warmup and timed row,
   including failure/time/iteration limits. Keep workflow success, numerical
   acceptance, the frozen 0.06 screen and a new 0.01 development target distinct.
   Calculate cost at the target only from repeated accepted qualifying runs;
   report an unreached target without an invented ratio.
3. Profile actual evolving native runs and compare profiling on/off and the
   merged baseline in alternating one-thread rounds. Check exact state/archive
   fields and counters, independently audit fields, and report overhead without
   interpreting instrumentation as a solver speedup.

## Validation and declared compute limits

- Core release tests, formatting, all-target Clippy with warnings denied;
  normal and optimized Python contracts and Ruff.
- Profiling: laminar cavity, prescribed scalar transport and a bounded RANS
  canyon; restart, cancellation, failed projection, output preflight and archive
  readers. Preserve partial-work accounting when a step does not commit.
- Reproduce the accepted 24² native/OpenFOAM pair with the old comparator;
  execute a two-grid 24/48 accuracy sweep on the same host. Use one warmup and
  three alternating timed pairs per grid; per-run 180 s native wall budget and
  180 s OpenFOAM allowance, 3000 OpenFOAM outer iterations. Native 12² is an
  additional diagnostic. One profiled 48² run uses the same 180 s budget; a
  separate short-budget run demonstrates censored rows.
- Profile overhead: one warmup and five alternating pairs at 24², plus fixed-work
  scalar and canyon controls. Do not time independent CPU-heavy campaigns at
  the same time. Compiler, CPU, binaries, runtime and consumed cases are retained.
- The 72² campaign is not run; its plan and budget handling are tested.
  Record a 48² timeout rather than increasing its frozen budget.

## Completion and next stage

The profiler must account for nested time without adding it twice, retain
failed attempted work, and leave the solver's numerical results unchanged.
The sweep must retain unsuccessful rows and explicitly show whether each
backend reaches the target on the tested grids. New diagnostics include field
paths. The next numerical stage is P1, a symmetric PCG-compatible multigrid
preconditioner; it is not part of the measurement stage.
