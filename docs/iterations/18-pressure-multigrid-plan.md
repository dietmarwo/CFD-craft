# Symmetric pressure multigrid plan

## Baseline and objective

Start from main `bbd191b` (PRs #11 and #12). Preserve the stricter profile and
measurement contracts, process-group cleanup, 600 s hosted native accuracy
budget and evidence ZIP round-trip checks including empty directories.
Pressure occupied 78–88% of the recorded native solver time. This change targets
that equation before changing momentum, pseudo-time stepping or scientific gates.

## Implementation boundary

Add `numerics.pressure_preconditioner: "multigrid"` as an explicit opt-in;
`"ic0"` remains the default. Omitted/default selections retain the previous
normalized case and checkpoint hash. Refuse masks with a coded field diagnostic,
without an implicit fallback. Support closed, periodic and outlet unmasked grids,
odd dimensions, two-cell periodic directions and unequal spacings. Robust
anisotropy and masked coarsening are later work.

Build a geometric hierarchy with tensor linear interpolation,
its Euclidean transpose as restriction, and exact Galerkin coarse operators.
Uniform fine cell volume is a common scalar in the pressure inner product;
coarse equations use aggregate sums, without an inconsistent volume average.
Preserve directions with at most two cells on every level. Use two forward Gauss–Seidel pre-sweeps and their two backward adjoint post-sweeps,
one recursive V-cycle and a dense Cholesky solve at at most 32 coarse cells.
For closed systems solve a gauge-reduced coarse matrix and restore mean zero;
a single collapsed closed cell has no remaining unknown. No inner tolerance,
residual-dependent work or correction scaling is allowed inside ordinary PCG.

Cache the hierarchy and scratch storage for a valid operator, identify current
face coefficients at every solve, and rebuild after coefficient changes. Reuse
all cycle buffers without allocation in PCG iterations. Keep the fine PCG
operator, compatibility check, independent face-by-face residual, correction,
nullspace gauge and numerical acceptance unchanged. Record setup, hierarchy size
and actual multilevel work in opt-in profiling. Account for setup memory in
case preflight; distinguish allocated hierarchy storage from process peak RSS.

## Validation before measurement

- Assemble independent -D G matrices, prolongation matrices and P^T A P;
  check hierarchy entries, nullspace/anchor preservation and pressure solutions.
- Check preconditioner linearity, adjoint symmetry and positive eigenvalues on
  anchored systems and the compatible closed subspace. Explain the SPD argument;
  finite tests supplement it.
- Exercise analytical/manufactured pressure, projection, incompatible RHS,
  cancellation, pressure iteration limits and changed public face coefficients.
- Retain IC(0) exact-output controls and restart/hash behavior; test schema and
  mask rejection, profile counters and independent archived-field checks.
- Run fmt, clippy with warnings denied, release workspace tests, Python lint and
  relevant Python checks in normal and optimized modes.

## Predeclared measurements

One thread, same host/compiler, one warmup and three alternating timed pairs.
Pressure kernels use the existing manufactured RHS, nominal tolerance 1e-11 and
10000 iteration bound on cavity 24/48/96 and unmasked 24^3/48^3 grids; the first
solve includes hierarchy construction and subsequent solves reuse it. Compare
solutions to the manufactured field, not iteration-count equality between
algorithms. Require RMS pressure error <=1e-8 and true relative residual
<=1.01e-10; repeated work/results for each configuration must agree.

Accepted coupled measurements use steady Re=100 cavity 24 and 48, max_steps
20000, wall budget 600 s per run, otherwise the unchanged canonical numerics.
Keep both returned fields, all failed rows, solver/workflow times, source/case
identities and peak RSS when available. Independently audit each archive and
apply the existing Ghia screen. Compare velocity with absolute max <=1e-8 and
pressure <=1e-7 (same gauge); report actual stopping steps and sampled reference
error. These are preconditioner-equivalence bounds, not weaker scientific gates.
Do not claim target accuracy, masked-grid improvement or OpenFOAM parity from
this experiment. Repeating the external CFD campaign is a separate cost/error
measurement after native pressure evidence is sound.

## Prototype decision

The first piecewise-constant prototype passed the small-matrix and projection
checks but reduced cavity-48 PCG iterations only from 102 to 50 and made reused
pressure solves slower. Linear interpolation with immediate span collapse also
left weakly coupled span modes unresolved. Tensor linear transfers with short
axes retained reduced this manufactured case to 6 iterations in a preliminary
run. The final paired campaign measures this design, including its more costly
setup and retained storage. The initial observations are retained separately.
