# Performance gap: current state and remaining iterations

## Current pressure stage

Stage P2a, anisotropic unmasked pressure multigrid, builds on main `2ddf17d`
(merged PR #13). Fixed symmetric principal line/small-plane
solves and stiff-axis semicoarsening replace point smoothing only where the
spacing policy selects them. Default IC(0), isotropic point arithmetic, the
fine pressure operator and independent numerical gates are retained. See
the [implementation design](../docs/PRESSURE_MULTIGRID.md),
[plan](../docs/iterations/19-anisotropic-pressure-plan.md) and
[measured anisotropy results](ANISOTROPIC_PRESSURE_RESULTS.md).

Pressure acceleration reduces cost per projection. It does not improve the
donor-cell momentum discretization, increase the explicit stability limit,
reduce the number of pseudo-time steps by design, or establish physical model
validity. The prescribed-flow optimization worker bypasses pressure, so its
fitness evaluations gain nothing directly from this change.

## How close native is now

Fresh same-host, one-thread comparison of **opt-in native multigrid** and the
pinned OpenFOAM Foundation 13 SIMPLEC/GAMG cavity recipe, measured 2026-10-31.
One warmup plus three alternating timed pairs at 24²/48²; a native 12²
diagnostic is retained. All 20 child records passed numerical/archive/field
checks and the existing 0.06 Ghia screen. This screen is distinct from the
**0.01 accuracy objective**. Native limits are 600 s/20000 steps; OpenFOAM
limits are 3000 iterations/180 s. Rust stable 1.99.1; AMD EPYC 9V74, one solver
thread, 8-CPU/8-GiB cgroup. Native phase profiling is enabled. Pressure uses
its unchanged case tolerance (1e-10); the 1e-14 kernel tolerance is not imposed
on flow cases.

| Flow-plane grid | Native solver s | OpenFOAM solver s | Native/OpenFOAM solver | Native workflow s | OpenFOAM workflow s | Native/OpenFOAM workflow |
|---|---:|---:|---:|---:|---:|---:|
| 24² | 4.732 | 0.727 | 6.51× | 4.799 | 1.343 | 3.57× |
| 48² | 65.003 | 5.570 | 11.67× | 65.106 | 6.336 | 10.28× |

These are configured-recipe ratios on the same **flow-plane** grid, not identical
algorithms/cell counts or matched-accuracy results. Native retains two span
cells (1152/4608 total); OpenFOAM's 2D empty-boundary recipe has one (576/2304).
Native solver time is `elapsed_s`; OpenFOAM solver time is the recorded solver
process wall time. Workflow includes startup, preparation/output and independent
checking. Native stores and evolves the extra span layer. Memory medians are
about 20.8/25.3 MiB native versus 115.1/116.4 MiB OpenFOAM at 24²/48², complete
process RSS measured by GNU time; these are neither peak campaign memory nor
identical-mesh memory ratios.

| Flow-plane grid | Native Ghia error | OpenFOAM Ghia error | Native steps / OpenFOAM iterations | Reaches 0.01: native / OpenFOAM |
|---|---:|---:|---:|---|
| 24² | 0.02756134 | 0.00896632 | 2010 / 696 | no / yes |
| 48² | 0.01695144 | 0.00707998 | 6390 / 2132 | no / yes |

Error is the frozen maximum absolute centerline-velocity difference at Ghia
Re=100 stations, normalized by lid speed. OpenFOAM reaches 0.01 already at 24²
(0.727 s solver, 1.343 s workflow). Native has not reached it through 48².
Therefore the report's `native_over_openfoam_at_target` is **null**, and a
finite equal-accuracy speed ratio cannot be claimed.

The standard 24²/48² cavities retain point arithmetic and the previous errors
and stopping steps. P2a does **not** close their isotropic gap;
its benefit is the newly supported anisotropic pressure regime. In the separate
64x2x12 anisotropic coupled test, the candidate is **1.41×** faster than IC(0)
for accepted steady convergence (23.632 -> 16.751 s), and **1.64×** for transient
interval completion (1.546 -> 0.942 s). That coarse vertical grid misses the
0.01 target too. Kernel gains of up to 38.15× over old point MG must not be
presented as whole-simulator or OpenFOAM speedups.

To reproduce, build release/locked and run
`python validation/compare_backends.py --grid-sweep --native-pressure-preconditioner multigrid --levels 1 2 --sweep-rounds 3 --native-wall-s 600 --native-max-steps 20000 --foam-iterations 3000 --timeout-s 180 --accuracy-target 0.01 --foam-root PATH --output NEW_DIR`.
The raw report stores the frozen plan, exact inputs, builds, runtime/executable
identities, all rows and profiles. Foundation package
`openfoam13_20260407_amd64.deb` has SHA-256
`9a491909372dd3de79d6fa8980d7fe6c9c1624da49cd14d61675ecacf4fdbcc2`.

## Remaining work, in recommended order

These are work packages; each may take several changes. P0 instrumentation,
P1 isotropic multigrid and P2a are complete; P2a is not all of P2.

| Next iteration | Scope | Evidence required before calling it complete |
|---|---|---|
| P2b: masked multigrid | Component-preserving aggregation/interpolation; one nullspace/gauge per sealed component; anchored components; thin passages and disconnected pockets. Extend the current rejection only with verified support | Independent masked `-DG`/Galerkin/reference solves; full preconditioner symmetry/positive-energy tests; no merging across solid barriers; changed coefficients/topology/cancellation/restart controls. Accepted 27k/93k canyon comparisons, field equivalence and an actual coupled benefit; preserve budget failures |
| P2c: setup and hierarchy cost | Profile cold hierarchy construction and coarse operator growth. Reduce assembly/scratch/transfer overhead where measured, retaining the fixed SPD cycle | Cold/reused work and memory, operator/grid complexity, exact field/reference controls. Require an end-to-end gain for representative repeated and one-off workloads; iteration counts alone are insufficient |
| P3: momentum accuracy per cost | Independently verified higher-order momentum advection with explicit boundary/conservation treatment. Keep a selectable baseline and frozen physical model | Manufactured spatial/temporal order, periodic and wall/outlet conservation, bounded stability regime, Ghia cost-versus-error refinement. A native run must actually reach the declared 0.01 target before a matched-accuracy ratio can be reported |
| P4: implicit diffusion decision | Bounded laminar implicit momentum diffusion trial after profiling its attainable benefit. Treat turbulent/scalar extensions separately | Independent diffusion/time-order tests, boundary and energy checks, linear-solver residuals, accepted coupled cost at equal error. The earlier approximately 1.68 stability-headroom estimate is a ceiling under assumptions, not a promised speedup; stop if overhead removes the benefit |
| P5: a dedicated steady algorithm | Reduce explicit pseudo-time work with a documented steady momentum/pressure coupling; maintain a consistent residual and fixed point | Independent steady equation residuals, conservation and gauge checks, baseline-equivalent converged fields, cavity grid/error sweep and masked/RANS controls. Compare complete convergence, not cost per outer iteration |
| P6: canyon and optimization payoff | Replay representative canyon and optimizer campaigns using experiment-craft/optimization-jobs, frozen budgets, cached converged flows and held-out scenarios where appropriate | Accepted 27k/93k refinement, model-card and empty-ABL gates, reproducible worker/job identities and failed jobs, budget-matched best-so-far outcomes and fine-grid replay. Experimental-data acquisition/model qualification remains a separate prerequisite for physical claims |

P3 can start in parallel with P2b because the current accuracy deficit is already
visible on unmasked cavities. The recommended next pressure iteration is P2b;
the highest-priority prerequisite for an honest OpenFOAM **cost at equal
accuracy** comparison is P3. Do not postpone the accuracy work until every
pressure optimization is exhausted.

All listed CPU implementation and small/medium validation work can run in
cloud CI; many-core and GPU studies remain lower priority. The opt-in
`external=anisotropy` selector runs the hosted anisotropy campaign; its GitHub
run is recorded in the [anisotropy results](ANISOTROPIC_PRESSURE_RESULTS.md#hosted-reproduction).

## What parity would mean

Use the same physical problem, domain, boundary conditions and declared error
objective; independently accepted fields; repeatable complete-run time and
memory on the same host. Report setup, solver and outer workflow separately.
The native SSPRK2 explicit pseudo-time algorithm and the pinned OpenFOAM
Foundation 13 SIMPLEC/GAMG recipe use different discrete schemes and stopping
norms. A same-grid configured timing ratio describes those recipes. A
matched-accuracy ratio additionally requires both methods to reach the error
target. Neither is experimental validation of urban dispersion.

There is no defensible percentage of the full gap closed while one method
does not reach the declared error objective. Pressure-kernel speedups and
coarse-grid throughput are useful progress, with their scope retained.
