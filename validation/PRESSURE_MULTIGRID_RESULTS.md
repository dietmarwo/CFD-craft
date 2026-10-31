# Pressure multigrid results

## Scope and protocol

Baseline: main `bbd191b` (merged PRs #11 and #12), measured 2026-10-31.
Opt-in tensor-linear symmetric geometric multigrid versus the unchanged default
IC(0), solving the same fine pressure equation. No scientific gate was relaxed.
One solver thread on AMD EPYC 9V74; Rust 1.88.0, locked dependencies; the host
exposed 9 CPUs with an 8-CPU quota and 8 GiB memory limit. Native source
fingerprint: `d246dc36db0681182f74601a8bd8c87932283769bc836ea566d0e2a4ea6592d9`.

One warmup and three alternating timed pairs per configuration. Repeated work
and returned fields match for each method. Kernel results below come from the
isolated campaign, with one cold solve and three reused solves per child;
reused time is the median within a child, then across timed children.

## Manufactured pressure kernels

All 40 child records passed the independent manufactured-field and true-residual
bounds. Boundary conditions are wall x/z and periodic y; the cavity retains two
span cells. Nominal tolerance is 1e-11, independent RMS recovery bound 1e-8 and
final true-relative-residual bound 1.01e-10. The table reports milliseconds.

| Grid | IC(0) / MG iterations | Cold IC(0) | Cold MG | Reused IC(0) | Reused MG | Reused speedup |
|---|---:|---:|---:|---:|---:|---:|
| cavity24 | 53 / 6 | 1.437 | 4.639 | 1.292 | 0.928 | 1.39× |
| cavity48 | 102 / 6 | 12.942 | 23.468 | 13.007 | 3.646 | 3.57× |
| cavity96 | 193 / 6 | 100.655 | 118.179 | 102.410 | 16.864 | 6.07× |
| cube24 | 61 / 7 | 22.338 | 161.036 | 19.565 | 13.059 | 1.50× |
| cube48 | 113 / 7 | 413.964 | 1995.427 | 390.576 | 152.088 | 2.57× |

Cold multigrid is slower on every tested kernel. Reuse amortizes hierarchy
construction; a single small solve is not a reason to select it. The observed
6/7 iterations belong to this RHS and are not a general iteration bound.

## Accepted coupled cavity

Both methods keep the canonical numerics, 20000-step/600-second resource bounds,
independent archived-field audit and frozen 0.06 Ghia centerline screen. All 16
child records passed, including warmups. Solver time includes setup and actual
stepping; workflow time additionally includes process/output/checking work.

| Flow-plane grid | Steps (both) | IC(0) PCG work | MG PCG work | IC(0) solver s | MG solver s | Solver speedup | Ghia error (both) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 24² | 2010 | 204,850 | 24,120 | 7.355 | 5.412 | 1.36× | 0.02756134 |
| 48² | 6390 | 1,262,035 | 76,680 | 180.665 | 74.108 | 2.44× | 0.01695144 |

Maximum returned-field differences over the pairs: velocity 2.22e-16 m/s;
pressure 2.22e-15 m²/s², with the same gauge. Predeclared bounds were
1e-8 and 1e-7 respectively. The 0.01 development accuracy target remains unmet;
pressure acceleration does not change donor-cell momentum error. No fresh
OpenFOAM speed ratio or matched-accuracy comparison is claimed.

## Hosted reproduction

The manual `external=pressure` job ran the same campaign on a GitHub runner
(AMD EPYC 7763, 4 CPUs, ubuntu-24.04;
[run 41235330963](https://github.com/dietmarwo/CFD-craft/actions/runs/41235330963))
on the code of commit `646dda3`, which differs from the recorded measurements by
the `CFD-W004` check and an exact (rather than hashed) hierarchy reuse check. All
rows passed; iterations, steps and Ghia errors equal the recorded ones.

| Configuration | IC(0) / MG iterations | IC(0) | MG | Speedup |
|---|---:|---:|---:|---:|
| kernel cavity24, reused ms | 53 / 6 | 1.632 | 0.928 | 1.76× |
| kernel cavity48, reused ms | 102 / 6 | 13.103 | 4.051 | 3.24× |
| kernel cavity96, reused ms | 193 / 6 | 102.44 | 16.087 | 6.37× |
| kernel cube24, reused ms | 61 / 7 | 22.919 | 14.103 | 1.63× |
| kernel cube48, reused ms | 113 / 7 | 378.06 | 130.76 | 2.89× |
| accepted cavity 24², solver s | 204,850 / 24,120 | 7.965 | 5.526 | 1.44× |
| accepted cavity 48², solver s | 1,262,035 / 76,680 | 185.33 | 73.97 | 2.51× |

Cold multigrid solves were again slower than IC(0) on every kernel (0.14–0.84×).
The evidence zip kept its directory entries; all 16 sealed archives verified in
its extracted copy.

## Shape sweep: where multigrid is slower

The kernels above use a smooth manufactured right-hand side on near-isotropic
grids. A separate sweep on another host solved a rough compatible right-hand
side (`sin(0.618 i)`, centered) to a relative tolerance of 1e-10, timing the
second solve, so the hierarchy is reused. One thread. Face weights are 1/dx²
per axis; the ratio is taken between axes of more than two cells, and
`CFD-W004` marks ratios above 25.

| Cells | Domain, m | Weights x/y/z | Ratio | W004 | IC(0) it / ms | MG it / ms |
|---|---|---:|---:|---|---:|---:|
| 96×2×24 | 4×0.1×1 | 576/400/576 | 1 | no | 106 / 9.7 | 10 / 5.0 |
| 48×48×48 | 1×1×0.2 | 2304/2304/57600 | 25 | no | 132 / 379.6 | 19 / 304.4 |
| 64×2×64 | 1×0.1×0.2 | 4096/400/102400 | 25 | no | 96 / 15.7 | 17 / 15.9 |
| 128×2×16 | 100×1×1 | 2/4/256 | 128 | yes | 212 / 17.0 | 42 / 16.9 |
| 64×64×8 | 1×1×0.01 | 4096/4096/640000 | 156 | yes | 199 / 153.5 | 40 / 154.3 |
| 64×2×64 | 1×0.1×0.1 | 4096/400/409600 | 100 | yes | 85 / 13.9 | 34 / 30.9 |
| 64×2×64 | 1×0.1×0.05 | 4096/400/1638400 | 400 | yes | 82 / 13.5 | 68 / 61.0 |
| 48×48×48 | 1×1×0.1 | 2304/2304/230400 | 100 | yes | 151 / 436.8 | 36 / 569.3 |
| 32×32×16 | 1×1×0.05 | 1024/1024/102400 | 100 | yes | 127 / 44.0 | 37 / 71.5 |
| 64×8×64 | 1×1×1 | 4096/64/4096 | 64 | yes | 109 / 87.0 | 36 / 148.7 |
| 64×16×64 | 1×4×1 | 4096/16/4096 | 256 | yes | 162 / 278.9 | 70 / 644.5 |
| 64×8×64 | 1×1×0.2 | 4096/64/102400 | 1600 | yes | 136 / 108.6 | 121 / 505.8 |
| 64×8×64 | 1×1×0.1 | 4096/64/409600 | 6400 | yes | 147 / 116.0 | 231 / 935.9 |

With a rough right-hand side, one cycle costs roughly as much as 5–10 IC(0)
applications. Multigrid was faster only on the near-isotropic shapes; above a
ratio of 25 it was as fast or slower, sometimes with more iterations. In a
separate review test (64×8×64, domain 1×1×0.02 m, x/z ratio 2500), multigrid
exceeded the case default of 1200 PCG iterations and stopped with CFD-E033,
where IC(0) converged in about 200. `check` reports `CFD-W004` for such cases;
semicoarsening or line smoothing is the remedy, and part of the next pressure
work.

## Memory and work attribution

GNU time 1.9 reports the maximum individual process RSS, including waited
descendants, rather than simultaneous aggregate memory. Peak columns below are
maxima across timed children. Hierarchy storage counts retained numeric/index
vector capacities and level records, excluding reporting/cache handles, allocator
overhead, the grid, outer PCG vectors and construction temporaries.

| Kernel | IC(0) peak MiB | MG peak MiB | MG retained MiB | Grid complexity | Operator complexity |
|---|---:|---:|---:|---:|---:|
| cavity24 | 3.07 | 3.50 | 0.48 | 1.328 | 2.267 |
| cavity48 | 5.32 | 6.95 | 2.06 | 1.332 | 2.450 |
| cavity96 | 15.16 | 21.58 | 8.54 | 1.333 | 2.553 |
| cube24 | 11.77 | 17.31 | 6.31 | 1.143 | 2.443 |
| cube48 | 80.14 | 123.70 | 52.68 | 1.143 | 2.601 |

The 48² accepted-run peaks were 21.03 MiB (IC(0)) and 22.70 MiB (MG). The preflight hierarchy/construction allowance is 1024 additional bytes per cell
before the existing 25% margin; it is a conservative budget rather than RSS.

Additional 100-step 48² phase profiles are explicitly incomplete steady runs.
They pass archive/profile/independent checks and compare equivalent fields,
but are not accepted-solution timings. IC(0) used 19162 PCG iterations and MG
1200, with 200 independent true-residual checks each. MG built one five-level
hierarchy (6138 cells/78084 stored entries across levels), made 1200 cycles
and coarse solves, and recorded 29376000 smoothing cell updates. Pressure
projection occupied about 85.0% of the IC(0) profile and 67.2% of the MG profile.

## Verification and reproducibility

- Clean Rust 1.88 release workspace tests: 65 passed; fmt and clippy with warnings denied passed.
- Python suites pass normally and with `-O`, including strict profile fault injection,
  field equivalence/repetition rejection, and process cleanup.
- Independent dense Galerkin matrices, the entire small preconditioner on the
  compatible subspace, manufactured/continuous Poisson and projection checks pass.
- Changed public face coefficients rebuild the hierarchy; masks fail explicitly.
  Cancellation and pressure limits preserve the entire prior state.
- Default IC(0) fields/checkpoints/probes match the merged binary bitwise on
  cavity and masked canyon controls, including legacy checkpoint replay.
  Multigrid restart matches uninterrupted fields/checkpoints/probes bitwise.
- Gaussian refinement, Poiseuille and empty-ABL checks pass with multigrid.
  Empty-ABL U/k/epsilon drift above H is 0.2341%/0.9405%/2.6754%, below the
  unchanged 2%/5%/5% gates. Its known below-H epsilon drift remains about 16.2%.

The measurements froze their observer before the later PID-namespace cleanup
fix. This host exposes ancestor procfs IDs; cleanup now uses namespace-local
NSpid/NSpgid and checks namespace identity. The pre-fix observer and original
failed tests are retained in raw evidence. Measured native executables launch
no subprocesses; kernel and solver timers are internal and unchanged by that
post-child enumeration fix. Raw workflow times retain their original observer
identity. A separate final-observer control validates the complete measurement
path, without replacing the three-pair headline measurements.

Use [the guide](../docs/PRESSURE_MULTIGRID.md) and
`validation/benchmark_pressure.py` to reproduce. The recorded evidence was
archived with `validation/archive_evidence.py`, which keeps directory entries
[rather than copying only files](../docs/iterations/06-archive-investigation.md);
all 69 sealed archives verify in its extracted copy.

## Remaining work

IC(0) remains default. Masked topology/component-preserving coarsening, robust
anisotropy, cheaper hierarchy construction and coarse operator complexity are
next pressure work. Better momentum accuracy and an implicit/steady flow
algorithm remain separate gap-closing steps. The canyon experimental-data gate,
and the native physical-qualification status, are unchanged.
