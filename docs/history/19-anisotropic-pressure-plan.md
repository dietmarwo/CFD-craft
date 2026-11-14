# Anisotropic pressure acceleration plan

## Baseline and scope

Start from merged main `2ddf17d` (PR #13). Preserve its independent pressure
residual, default IC(0), exact coefficient reuse checks, nonblocking statistics,
anisotropy warning and hosted notices. This is the anisotropy substep of P2;
masked/component-preserving coarsening remains P2b, so this does not complete P2.

The reviewed point smoother can exceed 1200 PCG iterations on 64x8x64 in a
1x1x0.02 m domain while IC(0) converges. Add exact line-block relaxation for
strongly unequal pressure weights, retaining the point path on the isotropic
cavity. Retain tensor interpolation and the Galerkin equation; choose coarsening axes
at setup as described below.
Do not introduce residual-dependent cycles, inner tolerances or relaxed gates.

## Mathematical design

Choose stiff axes from the declared uniform cell spacings at setup. Ignore a
weak two-cell invariant span when deciding whether the coarsened axes are
anisotropic, but include a stiff two-cell axis. Above weight ratio 25, use one
or two stiff axes (within a factor four of the largest). A forward block sweep
solves each principal line matrix exactly against the latest outside-line
values. The backward sweep is its adjoint. Use one forward/backward adjoint block pair on anisotropic levels, with the
dominant stiff direction (or the small joint plane). Isotropic levels retain
the original two-forward/two-back point sweeps. Block diagonals are SPD principal
submatrices; their symmetric Gauss-Seidel composition and positive coarse
inverse give a fixed SPD preconditioner on the compatible subspace.

Preserve weak-axis modes by coarsening stiff axes first. When two stiff
axes have at most 16 cells together, solve their small plane blocks exactly;
this permits remaining weak directions to coarsen after stiff axes reach two
cells. This setup policy is fixed throughout a solve.

Use stored band Cholesky factors and scratch. Fold periodic line ordering to
keep cyclic couplings in a narrow band; derive the actual bandwidth from stored
matrix entries, including duplicate short periodic edges and Galerkin fill.
Retain current gauges, compatibility check, fine PCG product, face correction and
independent true residual. A nonpositive block pivot must fail with a coded
field diagnostic, without a diagonal repair or hidden fallback. Cache identity
must include spacing-dependent selection, and memory estimates must include
line factors/maps. Statistics and profiling must identify line work.

## Tests and predeclared evidence

- Independent dense line-block solves, including odd/periodic/outlet lines and
  two-cell duplicates; full small preconditioner symmetry/positive-energy and
  Galerkin checks; manufactured/continuous pressure and projection tests.
- Preserve cancellation, iteration-limit state retention, compatibility,
  coefficient rebuild, nonblocking statistics and checkpoint contracts.
- Minimum Rust 1.88 and actual stable: fmt, all-target clippy -D warnings and
  locked release workspace tests. Python suites in normal and optimized modes,
  lint/format, independent archived-field audits and unchanged scientific gates.
- Before timings, freeze one warmup plus three balanced timed triplets per
  shape. Compare merged point MG, candidate line MG and IC(0), including failed
  rows, cold/reused time, PCG work, true residual, independent recovery and RSS.
  Include the review's failing 64x8x64, one-stiff-axis wall/open/periodic cases,
  plate anisotropy, odd shapes, stiff two-cell span and isotropic controls.
  Use nominal pressure tol 1e-14 for the ill-conditioned rough kernels, at most 1200 iterations; independent RMS error
  <=1e-8 and true residual <=1.1e-12. No threshold is loosened after failure.
- Coupled anisotropic square cavity: 64x2x12, Re=100, canonical physics and
  numerics. Measure steady convergence and a transient interval to 1 s with
  one warmup and three alternating IC(0)/MG timed pairs, 600 s/20000-step
  bounds, independent archives/fields and velocity/pressure differences
  <=1e-8/1e-7. The transient assessment is interval completion, not steady
  convergence. Stop a configuration after an unaccepted warmup and retain it
  without a timing ratio. Its coarse vertical grid is a throughput fixture;
  steady measurements retain the 0.06 Ghia screen; the standard 24/48 sweep
  separately reports cost at the 0.01 accuracy objective.
- Fresh native/OpenFOAM cavity sweep: multigrid explicitly recorded in the
  native plan, levels 24/48, one warmup and three timed rows, native 600 s,
  20000 steps, OpenFOAM 3000 iterations/180 s, error objective 0.01 and existing
  0.06 screen. Distinguish same-grid configured solver/workflow ratios from
  cost at matched accuracy. An unreached target has no finite accuracy ratio.

## Remaining roadmap

P0 profiling and P1 isotropic pressure MG are merged. P2a is this anisotropy
substep. P2b needs component-preserving masked coarsening, narrow-passage tests,
27k/93k canyon controls and accepted coupled benefit. P2c targets hierarchy
construction/coarse complexity if still material. P3 adds independently verified
higher-order momentum. P4 is a bounded implicit-diffusion go/no-go; P5 is a
dedicated implicit steady method. P6 measures canyon and optimization-campaign
payoff, with the physical model and experimental-data gates kept explicit.
(Status 1 November 2026: P2a, P3, P4 and P5 are done; P2b, P2c and P6 remain;
see the [gap status](../evidence/performance-gap-status.md).)

## Pilot correction before the formal campaign

The initial rough-RHS pilot at 1e-12 met the solver residual gate but missed
the independent 1e-8 pressure-recovery bound on the most stretched grid, for
IC(0) as well as the candidate. Keep those records. The formal ill-conditioned
kernel campaign tightens the common tolerance to 1e-14; the recovery bound
stays 1e-8. This adds algebraic accuracy, rather than relaxing a test.

The pilot also showed divisions while classifying block couplings dominating
the fine sweeps. Precompute outside-block row entries during setup and retain
them in the memory/accounting estimate. Coefficients stay fixed per solve.

The formal candidate caches outside rows and diagonal reciprocals. One exact
block pair replaces two point pairs on anisotropic levels; complete matrix
symmetry/positivity tests cover this fixed SPD composition. Profiling counts
block-level cell visits independently from smoothing updates.

Each rough-kernel child makes one cold and one cached solve; three balanced
timed children provide the reused median, preceded by one warmup per method.
