# Stage V: momentum verification and donor-cell baseline

Protocol declared 1 November 2026, before the campaign. Base: `f358be6`
(PR #14); this is the first stage of the accuracy/steady-solver plan.
No production Rust stencil, case schema, default, tolerance or acceptance
rule changes in this stage. Implement from analytic equations and the project
plan; do not consult OpenFOAM implementation source.

## Frozen protocol

1. `tests/momentum.rs` evaluates the production momentum RHS with viscosity
   and acceleration set to zero in a test-only helper **after** building the
   valid grid. No production floating-point operations are rearranged.
   Use periodic Taylor–Green velocities `u=sin(X)cos(Z)`,
   `w=-cos(X)sin(Z)`, `X=2πx+φx`, `Z=2πz+φz`. The exact negative advection is
   `(-π sin(2X), 0, -π sin(2Z))` at component face centers.
   Grids are 32, 64, 128, 256 with two periodic span cells. Eight fixed phase
   pairs in radians: (0.137,0.271), (0.419,1.103), (1.337,0.593),
   (2.017,1.771), (2.693,2.291), (3.349,0.887), (4.123,3.517),
   (5.071,4.237). Report L1/L2/L∞ errors and least-squares log(h) slopes
   for the two nonzero components together. The donor-cell mean L1 slope
   must be between 0.8 and 1.2; all errors must be finite and positive.
   A solid-barrier test requires bit-identical near-side RHS after changing
   far-side velocities, plus a near-side sensitivity control.
2. `validation/momentum_accuracy.py` runs translating Taylor–Green vortices
   in a unit periodic box, two span cells, `ν=0.005`, amplitude 0.2,
   uniform offset (0.7,0.2,0.3), phase (0.137,0.271), final time 0.05.
   The exact perturbation decays as `exp(-8π²νt)` and translates with the
   offset. Grids 16,32,64 use fixed maximum dt=0.0005. Repeat grid 64 at
   dt/2 and dt/4; the last time-refinement difference must be below 1% of
   the grid-64 spatial L1 error. Record L1/L2/L∞ orders, actual steps,
   momentum change normalized by initial sum(abs(u))*V, and initial cell
   Peclet numbers. Donor-cell's spatial baseline is expected to be first order.
   Supply a generated checksummed checkpoint through the public restart
   contract and record its identity. Normal numerical/archive audits apply.
3. A periodic transverse velocity step `v(x)` in uniform `u=1`, `w=0`,
   grid 64x2x2, ν=1e-8, `advective_cfl_max=0.45`, runs exactly 1000 steps.
   Its intentional iteration-limit termination is recorded, not called
   transient acceptance. Report extrema, growth and actual timestep/CFL.
4. Extend the external cavity recipe with an explicit bounded grid selector,
   retaining the existing level interface. `--grids 16 24 32 48` means the
   **same** list for both backends, without the native-only 12 diagnostic.
   One warmup and three alternating timed pairs per grid, one solver thread,
   native multigrid, 600 s/20000 steps; reference 180 s/3000 iterations.
   Keep the 0.06 screen and the separate 0.01 objective. Keep every failed row;
   no extrapolated crossing. All recipe files other than mesh size and
   matching sample stations retain the current method and controls.
5. Separately attempt native 96² at 1800 s/80000 steps, same steady equations
   and acceptance tolerances. This extra budget is for self-convergence,
   never a timed cost-at-target sample. Compare accepted centerline profiles
   on fixed 257 physical stations; report errors relative to the 96² profile
   and descriptive slopes. A finite reference is not an exact solution/GCI.
   If this run is incomplete, retain it and mark self-convergence unavailable.
6. Compare default runs with an unmodified-main binary: steady cavity24,
   transient Poiseuille and a masked canyon limited to three steps.
   Require identical fields.json, checkpoint.json, probes.csv, geometry.json,
   case.json, steps and pressure work. Timers/build identities are not fields.

## Checks and hosted reproduction

Rust fmt, all-target clippy with warnings denied, release locked workspace
tests; all Python suites in normal and optimized modes; repository-wide Ruff.
Fixtures run in ordinary numerical CI; `external=momentum` runs the full paired
grid sweep and self-convergence campaign on a hosted runner. New evidence
errors use `CFD-B007 momentum.<field>`; invalid sweep selectors keep CFD-B004
and external recipe selectors keep CFD-X001.

Campaign addendum, before the repeat: one full 32-row local sweep had accepted
timed rows on every grid, but its OpenFOAM-48 warmup failed the existing
`archive.progress` check (a 1250 snapshot was in the sealed file inventory but
absent from the recorded directory list). Retain that entire campaign and its
failure. Repeat the complete identical protocol once, using the fixed binary
and frozen producer files, after builds finish. Do not repair the old archive,
relax its verifier, substitute a timed row for the warmup, or select the faster
campaign. Report the full repeat as the final baseline if its audits pass.

Reference addendum, before continuation: the cold 96² solver returned converged
fields at 21390 steps, but failed while writing executable identity after the
running executable had been replaced during a build. Retain the unsealed run
and its exit-1 failure. Initialize a new run from its unchanged checksummed
native checkpoint through the public restart contract, using the fixed binary.
Require fresh numerical acceptance and independent archive/field checks, and
compare its fields/checkpoint bytes with the predecessor. Record the exact
initial-state provenance and both runs' work/timers; the continuation's timer
is not the cold solve's timer or a cost-at-target sample. Do not repair or
manually seal the original output directory.

Stage V changes measurement capability, not solver performance. P3a is next:
opt-in conservative second-order advection; then P4 implicit diffusion, P5a
implicit steady coupling, conditional P5b local steps, P3b/P5c open/RANS,
P5d scalar transport, with matched-accuracy measurements after each stage.

Final collection addendum: the complete repeat's initial passes did not survive
later re-auditing; three OpenFOAM records subsequently failed. A new collection
check and regression tests now invalidate rows after a late manifest/archive
change. A sequential reproduction also encountered the already documented
cloud anomaly (see 06-archive-investigation.md), so it remains failed. Before
the final attempt, declare the identical numerical/timing protocol under a
fresh temporary directory; pack and round-trip-check the evidence archive there
before copying only the archive. Record filesystem events and scoped processes.
This containment is not a diagnosis or a repair of any old archive.
