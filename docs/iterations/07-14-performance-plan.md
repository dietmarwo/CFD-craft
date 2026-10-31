# Iterations 07–14: native CPU throughput

Declared before implementation on merged PR #7,
`402a15036636d8f48591a2d9b5f4ed203cb5ab91`.
Date: 30 October 2026.

## Baseline review

Keep PR #7's frozen-source, first-manifest, returned-summary and producer checks,
source measurement screening, observation failures as evidence, error precedence,
started-work accounting and split notices. Its actual 12000-iteration fine
backstep is still numerically unaccepted; declining residuals do not imply a
stall or an accepted mesh pair. The source-flux decision and physical-validation
gates remain open and unchanged.

The native roadmap identifies repeated IC(0)-PCG projection and explicit stepping
as the throughput limit. The increments below reduce implementation cost without
a new pressure equation, turbulence closure, advection scheme or convergence
policy. They need serial CPU validation only, not GPU or MPI.

## Eight increments

| Iteration | Target | Proposed implementation | Decisive validation |
|---|---|---|---|
| 07 | Allocation in every PCG preconditioner application | Reuse the preconditioned residual vector; add a bounded, deterministic kernel/fixed-step benchmark | Same pressure solve, independent true residual and allocation-free repeated application |
| 08 | Pointer chasing in IC(0) triangular sweeps | Store lower factors in contiguous row offsets, columns and values | Periodic duplicate faces, masked components, outlets, independent assembled reference |
| 09 | Per-row heap allocation and searches during cold factor setup | Assemble sorted/coalesced lower edges directly into contiguous storage, preserving accumulation order | Cold versus warmed timings; equivalence to the prior factor on odd/even periodic and masked cases |
| 10 | Large face objects, branches and divisions in every PCG multiply | Build compact active pressure-face entries once per solve, retain face accumulation order and the public operator's semantics | Topology/nullspace/projection suite; independent matrix products and true solve residuals |
| 11 | Temporary full-grid/face arrays in projection | Form projection RHS/scales directly and apply pressure gradients without a temporary face vector | Open/closed/masked projection, gauge and compatibility checks, final-field comparison |
| 12 | Repeated neighbor lookups in RANS gradients | Reuse local cell-neighbor indices in production and variable-viscosity terms | Existing wall/ABL tests, unchanged arithmetic and independent empty-ABL gate |
| 13 | Duplicate staggered-face lookup in momentum sampling and viscosity | Share each face-neighbor lookup between advective sampling and viscous coefficients | Laminar/channel/cavity and oblique/canyon RANS fixtures |
| 14 | State copies immediately discarded by SSPRK stages | Build a candidate state only for needed fields, move monitor history only after all fallible checks | Transactional failure/cancellation, scalar mass/positivity/superposition and identical accepted results |

Each increment is a separate commit with its own measurements.
If a proposed change does not help its measured target, retain that negative
finding and revise or replace the implementation before calling it a gain.
Do not reduce accuracy, use fewer required solver iterations, or remove checks.

## Frozen measurement protocol

Use the same compiler, Cargo.lock, release profile, cases, thread allowances,
work counts and output settings for all versions. Build the baseline before
optimizing. Preserve binaries privately with hashes and source identities.

Measure grid setup, cold/warm pressure solves, momentum, production, scalar RHS
and a fixed number of coupled steps through a deterministic Rust probe. Use
moderate masked canyon grids and a periodic transport case; keep each child
below 180 seconds, preserve failures and actual iterations. Warm up once, then
use at least five alternating baseline/candidate measurements for final speed
claims. Record medians and ranges, CPU time and peak RSS where available.
Kernel results are not end-to-end speedups. Include one/four-thread comparisons
where relevant; do not treat this host as a ranking of machines.

Run numerical tests after each affected change. Pressure changes require the
independent assembled operator/reference, disconnected/nullspace and projection
checks. RANS changes require the unchanged empty-ABL check and a model-card
update. Transport/state changes require mass, positivity, unit normalization,
refinement and failed-step atomicity. Final verification also includes the
existing native analytic/order/cavity/SciPy suites and an accepted coarse canyon.

For baseline/final fixed-work comparisons require the same case/physics,
completed work and stopping state, no new floor events, valid finite fields and
independent mass/continuity checks. Compare all retained fields and budgets
with a preregistered relative scale of 1e-11 plus 1e-13 absolute (report exact
agreement too); pressure nullspaces use the same gauges. Tolerances in the
solver and scientific verification suites are unchanged. A speedup that fails
these requirements is rejected.

Update the memory estimate if caches/workspaces raise the bound. Report measured
RSS alongside it; do not trade an unreported memory regression for speed.

## Record

Record the source and binary identities, the frozen cases, every paired
measurement and the test results. Keep the native canyon's physical and model
limits and the external fine backstep gate explicit. Report actual results,
including slower cases, the memory cost and any remaining throughput limits.
