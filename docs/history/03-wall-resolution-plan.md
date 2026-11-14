# Iteration 03: resolve the backstep convergence gate

Date: 29 October 2026. Base: merged PR #3, `4ea88a3`.

## Evidence and decision

The merged external backend has copied-input checks,
environment isolation, archive verification, first-solve residual parsing,
diagnostic codes, residual trends and comparison baselines. A nonconverged
iterate does not pass the measurement screen. These properties are retained.

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
   unchanged. Compare pressure-coupling and mesh/wall-package effects
   separately, in a 2x2 design at level 1.
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
   suite and the native analytic/empty-ABL suite.

## Acceptance and limits

The software gate is complete, reproducible generation/execution/audit with
passing regression tests. The scientific target is at least one numerically
accepted, independently audited wall-resolved backstep. A converged mesh pair
is a further target, not permission to conceal a budget or convergence failure.
Do not claim GCI outside an appropriate refinement regime. The original
screening protocol remains unchanged and its broad-target limitations remain.

There are no native RANS/kernel changes, new scalar physics, GPU or MPI
requirements. Velocity evidence still does not qualify the native
canyon or concentrations. Physical uncertainty and inlet/model sensitivity
remain separate gates even if numerical convergence is achieved.

## Primary references

- [Foundation 13 low-Re wall condition](https://cpp.openfoam.org/v13/classFoam_1_1nutLowReWallFunctionFvPatchScalarField.html).
- [Resolving the viscous sub-layer](https://doc.cfd.direct/notes/cfd-general-principles/resolving-the-viscous-sub-layer).
- [SIMPLE/SIMPLEC controls](https://www.openfoam.com/documentation/user-guide/6-solving/6.3-solution-and-algorithm-control).
- [Driver--Seegmiller data and boundary definitions](https://tmbwg.github.io/turbmodels/backstep_val.html).


## Outcome

The software gate is met. The scientific target is met at level 1: the
`wall-resolved`/`simplec` recipe converges to the unchanged nonlinear gate,
passes the independent local-flux and all-wall y+ audit, and its measurement
screen is assessed. A converged mesh pair is not reached: a level-2 case has
four times the cells of a level-1 solve that took about 50 minutes, so it is
not expected to finish within the 3600 s per-case limit. The first streamwise
spacing had a 140:1 cell-width jump at the step plane and diverged under every
profile tried; with only the spacing changed, the same `simple` recipe became
stable. The legacy-mesh stall is unchanged by the pressure-coupling control.
See the [resolution results](../../validation/RESOLUTION_RESULTS.md).
