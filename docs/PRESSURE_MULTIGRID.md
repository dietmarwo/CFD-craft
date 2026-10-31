# Symmetric pressure multigrid

`numerics.pressure_preconditioner` selects `ic0` (default) or `multigrid`.
Multigrid currently accepts unmasked Cartesian cases. A geometry mask is a case
error (`CFD-E034`), with no automatic fallback. Laminar and neutral-RANS pressure
use the same constant-density operator; no flow, scalar or turbulence model is
changed. Prescribed-flow runs bypass pressure and gain no acceleration from this
selection. Unequal spacings are correct algebraically, but the point smoother
and full coarsening are not robust to strong anisotropy: when face weights 1/dx²
differ by more than 25 between axes of more than two cells, `check` warns
(`CFD-W004`). Such cases were slower than IC(0), and extreme ones can stop at the
pressure iteration limit (`CFD-E033`); see the
[shape sweep](../validation/PRESSURE_MULTIGRID_RESULTS.md#shape-sweep-where-multigrid-is-slower).

## Use it

Create an explicit case copy and retain it with the result:

```sh
mkdir -p runs
python - <<'PY'
import json
from pathlib import Path
c = json.loads(Path('cases/verification/lid-cavity.json').read_text())
c['run']['mode'] = 'steady'
c['run']['threads'] = 1
c['run']['wall_time_limit_s'] = 600
c['numerics']['pressure_preconditioner'] = 'multigrid'
Path('runs/cavity-multigrid.json').write_text(json.dumps(c, indent=2))
PY
target/release/cfd-craft check runs/cavity-multigrid.json
target/release/cfd-craft profile runs/cavity-multigrid.json --output runs/cavity-multigrid
target/release/cfd-craft report runs/cavity-multigrid/run
python validation/check_profile.py runs/cavity-multigrid
```

The preconditioner is part of the normalized numerics and checkpoint compatibility
hash. Changing it starts a new run. An omitted selection and an explicit `ic0`
normalize identically to the old schema: old case/checkpoint hashes remain valid.
The result/archive schemas and ordinary output layout are unchanged.

In Rust, set the case **before** building its grid or calling `solver::run`:

```rust
use cfd_craft::case::PressurePreconditioner;
case.numerics.pressure_preconditioner = PressurePreconditioner::Multigrid;
let grid = cfd_craft::grid::Grid::build(&case)?;
// pressure::solve/project on this grid use the selected preconditioner.
// After its first pressure solve:
let stats = cfd_craft::pressure::multigrid_stats(&grid);
```

`describe` exposes the case enum, supported preconditioners and explicit default.
Its legacy `pressure` string continues to name the default IC(0)/PCG path.

## Equation and hierarchy

The fine equation remains `A p = b`, with `A = -D G`, the original shared face
weights and outlet correction equal to zero. Each closed component has a
compatibility check and a mean-zero gauge. The compact fine PCG product and the
independent final face-by-face residual use current grid coefficients, including
duplicate two-cell periodic faces. The final tolerance remains
`10 * pressure_relative_tolerance + 1e-12`, relative to the compatible RHS.

The hierarchy groups consecutive cells in pairs along each axis; an odd last
group has one cell. Directions with at most two cells are retained, so the two
span layers of the cavity keep separate coarse degrees of freedom. Coarse
centers are the pair's mean location. Transfers are tensor products of linear
interpolation between centers, periodic across a wrapped boundary and clamped
at a nonperiodic edge. Each row sums to one. Interpolation of an anchored case
need not itself satisfy a boundary derivative: the unchanged fine operator
supplies the boundary equation through Galerkin projection.

Restriction is exactly the transpose of prolongation, `R = P^T`, and
`A_c = P^T A P`. The pressure inner product on the uniform fine grid differs
from Euclidean only by a common cell-volume scalar. Coarse equations use sums,
not volume averages; they are not rediscretized Laplacians on wider cells.

Construction transfers symmetric edge energies and outlet contributions. It
stores symmetric off-diagonals and transfers row sums separately to preserve
closed constants; rounding is at floating-point assembly precision. Coarse
couplings can have either sign: treating every coarse edge as a positive physical
face would be incorrect. Coarse diagonal positivity follows from Galerkin, not
from an assumption that every coarse off-diagonal is negative.

Every application starts from zero and uses exactly:

1. Two forward Gauss–Seidel sweeps.
2. A residual, transpose restriction and one recursive coarse correction.
3. Linear prolongation and two backward Gauss–Seidel sweeps.

At at most 32 cells, dense Cholesky solves the anchored system directly. For a
closed system, one pressure value is removed before factoring; compatible RHSs
are solved and the mean-zero gauge restored. A single closed coarse cell has no
remaining unknown. A nonpositive pivot produces `CFD-E035`, without modifying
the equation or silently switching methods. There is no inner Krylov solve,
inner stopping tolerance, residual-dependent cycle count or correction scaling.

## Why ordinary PCG is appropriate

PCG requires a fixed symmetric positive preconditioner on the solved subspace
([PETSc's requirement](https://petsc.org/release/manualpages/KSP/KSPCG/)). Here:

- Tensor interpolation has full column rank: each one-dimensional interpolation
  has a strictly dominant submatrix formed from a distinct nearest fine sample
  for each coarse center. Tensor products preserve that rank. It preserves
  constants, so Galerkin retains precisely the closed constant nullspace; an
  outlet makes the coarse system anchored.
- The direct coarse inverse is positive and symmetric, restricted to the
  compatible closed subspace when necessary.
- Backward sweeps are the adjoints of the forward sweeps. A paired forward/back
  Gauss–Seidel correction has positive symmetrization `F^T D F`, with positive
  diagonal `D`; inserting a positive coarse correction and repeating paired
  smoothing preserves positivity and symmetry. Mean-zero projections are
  orthogonal and only remove the known constant mode.
- All work and coefficients are fixed within each outer solve.

These are the mathematical conditions. Tests also assemble the entire small
preconditioner and Cholesky-factor its compatible-subspace matrix; such finite
checks supplement the argument. This cycle differs from the standalone,
potentially nonsymmetric/scaled GAMG settings in the OpenFOAM recipe. No
OpenFOAM or other separately licensed solver code is copied into the core.

## Reuse, memory and profiling

One grid cache owns the hierarchy and reusable RHS, residual and correction
vectors. A mutex holds it for a pressure solve, so concurrent callers sharing a
grid serialize these solves. Cloned grids safely share the cache. The cache keeps
the grid size, gauge and every interior or outlet face's cells and pressure
weight from its build (32 bytes per such face, not counted in `allocated_bytes`)
and compares them exactly before each solve; any changed public face coefficient
rebuilds the hierarchy. Changing topology should rebuild the grid. No cycle
allocates inside PCG; setup allocations are separate.

`pressure::multigrid_stats` reads a separate copy of the statistics and never
waits for a running solve, so a `Control::with_poll` callback may call it. A poll
callback must not itself run a pressure solve on the same grid or a clone of it:
that solve would wait for the running one.

Case preflight adds 1024 bytes per cell before the existing 25% safety margin
for the hierarchy and its construction peak. This conservative allowance differs
from `allocated_bytes`, which counts retained numeric/index vector capacities and level
records, excludes reporting/cache handles and allocator overhead and excludes the grid/outer PCG vectors.
The stats list per-level cells and nonzeros (including diagonals and stored
duplicate fine entries). Sum them relative to the fine level to inspect grid
and operator complexity. Process peak RSS includes the complete child and is
reported separately when GNU time is available.

Profiling records `pressure_multigrid_setup` only when construction is attempted.
The `pressure_solve.multigrid` object counts hierarchy builds, maximum hierarchy
dimensions/storage, cycles, coarse solves and cell updates for smoothing,
residuals, restriction and prolongation. Each coarse solve belongs to one
cycle. Nonterminal cell updates satisfy smoothing = 4 × residual, and
restriction = prolongation = residual. These are cell visits, not floating-point
operation or transfer-nonzero counts. The existing fine operator and PCG work
counters keep their meanings. The profile checker validates both sets, including
failure paths. IC(0) profiles retain their previous serialized shape.

## Reproduce comparisons

```sh
cargo build --release --locked --examples
python validation/run_suite.py --pressure-preconditioner multigrid --output runs/verify-multigrid
python validation/benchmark_pressure.py --mode kernel --output runs/pressure-kernels
python validation/benchmark_pressure.py --mode cavity --grids 24 48 --output runs/pressure-cavity
```

Each campaign uses one thread, one warmup and three alternating timed pairs.
Kernels repeat one cold setup/solve plus three reused solves in each child.
Nominal pressure tolerance is 1e-11; the independent manufactured RMS gate is
1e-8 and the true residual gate is 1.01e-10. Cold/reused timers exclude JSON and
hashing. Coupled runs use the existing cavity numerics, 600 s/20000-step bounds,
independent archived-field audit and frozen Ghia screen. Returned velocity and
pressure equivalence bounds are 1e-8 and 1e-7 respectively, with the same gauge.
The opt-in verification suite also runs the unchanged Poiseuille and empty-ABL
gates (and scalar Gaussian refinement) with the selected preconditioner.
Rows, failures, input/producer identities, work, fields and RSS are retained;
nonrepeating or unaccepted groups have no speedup ratio. Setup and solver/workflow
times have distinct scopes. The baseline IC(0) probe runner is unchanged.

The opt-in **CFD checks** selector `external=pressure` runs this native campaign
and packages evidence with directory entries and archive round-trip checks.
See [recorded results](../validation/PRESSURE_MULTIGRID_RESULTS.md) and the
[plan](iterations/18-pressure-multigrid-plan.md). No timing threshold is imposed
in ordinary CI. Masked-grid multigrid, robust anisotropy, momentum accuracy and
implicit/steady flow algorithms remain separate follow-ups. This change alone
does not qualify a canyon model or establish OpenFOAM parity.
