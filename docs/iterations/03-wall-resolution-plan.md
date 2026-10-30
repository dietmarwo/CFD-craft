# Iteration 03: resolve the backstep convergence gate

Date: 29 October 2026. Base: merged PR #3, `4ea88a3`.

## Evidence and decision

PR #3 preserves the delivered backend and strengthens copied-input checks,
environment isolation, archive verification, first-solve residual parsing,
diagnostic codes, residual trends and comparison baselines. A nonconverged
iterate no longer passes the measurement screen. These changes are retained.

The backstep stalls with the first cell in the wall-function buffer layer.
The present SIMPLEC recipe also under-relaxes pressure by 0.2. These are two
different hypotheses, which require controlled comparisons. More iterations
alone are not the proposed fix.

## Implementation

1. Preserve the legacy mesh and numerical settings as named defaults. Add
   explicit `wall-resolved` and `simplec` options for the backstep only.
2. Generate a conforming graded mesh with first-cell heights derived from
   geometric series. Refine all four solid walls, including the vertical step.
   Use k=0, zero wall eddy viscosity and the low-Re omega treatment of the
   existing SST model. Retain the same geometry, Reynolds number, measured
   inlet and unmeasured-inlet assumptions. Do not fit downstream measurements.
3. Add a SIMPLEC profile with pressure relaxation 1 and transport relaxation
   0.7. Keep the nonlinear residual, continuity and experimental thresholds
   unchanged. Compare pressure-coupling and wall-package effects separately.
4. Independently read the actual Cartesian OpenFOAM mesh. Recompute cell
   volumes, local finite-volume divergence from stored phi and first-cell
   distances/y+ from stored wall traction. Check generated geometry against
   represented geometry, not just metadata. This auditor supports the bounded
   generated hexahedral cases; it is not a general unstructured-mesh reader.
5. Supply a bounded comparison/refinement tutorial with numerical, mesh,
   near-wall and measurement verdicts separate. Require local normalized
   divergence <=1e-4 for the new independent audit, and first-cell y+ <=1 for
   the wall-resolved candidate. These are development gates frozen before runs.
6. Run small controlled cases and a refinement series within cloud resources.
   Preserve all failed runs. Numerical acceptance is required before a
   measurement screen; a mesh pair requires the same wall/numerical package.
7. Test geometry/flux corruption, metadata mismatch, options, legacy behavior
   and optimized Python. Run required Rust/Ruff checks, the existing external
   suite and the native analytic/empty-ABL suite. Verify the patch on a clean
   checkout and deliver a ZIP and implementation log.

## Acceptance and limits

The software gate is complete, reproducible generation/execution/audit with
passing regression tests. The scientific target is at least one numerically
accepted, independently audited wall-resolved backstep. A converged mesh pair
is a further target, not permission to conceal a budget or convergence failure.
Do not claim GCI outside an appropriate refinement regime. The original
screening protocol remains unchanged and its broad-target limitations remain.

There are no native RANS/kernel changes, new scalar physics, home-machine,
GPU or MPI requirements. Velocity evidence still does not qualify the native
canyon or concentrations. Physical uncertainty and inlet/model sensitivity
remain separate gates even if numerical convergence is achieved.

## Primary references

- [Foundation 13 low-Re wall condition](https://cpp.openfoam.org/v13/classFoam_1_1nutLowReWallFunctionFvPatchScalarField.html).
- [Resolving the viscous sub-layer](https://doc.cfd.direct/notes/cfd-general-principles/resolving-the-viscous-sub-layer).
- [SIMPLE/SIMPLEC controls](https://www.openfoam.com/documentation/user-guide/6-solving/6.3-solution-and-algorithm-control).
- [Driver--Seegmiller data and boundary definitions](https://tmbwg.github.io/turbmodels/backstep_val.html).

## Review amendment after the bounded trials

The SIMPLEC pressure/transport-relaxation control still stalls. Wall-resolved trials develop
nonfinite residuals, including a cold-start, first-order, strongly damped SIMPLE
reference with tighter pressure solves. These observations do not establish
that either wall resolution or pressure relaxation caused the original stall.
The additional solver trials changed several settings and are exploratory,
not controlled estimates of individual effects.

The delivered `wall-resolved`/`simple` recipe is explicitly experimental: zero
interior velocity, measured inlet, bounded upwind momentum, limited U/k/omega
gradients, PCG/DIC pressure with absolute 1e-12 and zero relative tolerance,
and 0.1 pressure/transport relaxation. The unchanged nonlinear gate remains
1e-7. Remove irrelevant GAMG dictionary entries from this PCG reference.

The software acceptance target is retained. The scientific acceptance target
is **not achieved**. Stop a solve when logged residuals/continuity become
nonfinite; preserve its log, return code and started-iteration count. Do not
postprocess an earlier saved snapshot as a final solution. The refinement
workflow records finer levels as not started when the coarse level is not
accepted, rather than allocating more compute to an unqualified recipe.

Before another mesh campaign, reproduce the instability on the pinned runtime
and compare against an independently maintained Foundation-13 SST backstep
setup, checking pressure/flux initialization and boundary/turbulence treatment.
Only then attempt same-recipe mesh sensitivity. A first-order reference is
not evidence of improved accuracy or performance.
