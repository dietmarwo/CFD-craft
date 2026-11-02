# Performance gap: current state and remaining stages

## After P5c, P5d and ten performance iterations (1 November 2026)

The hosted paired sweep with the final implicit recipe
([run 41361132558](https://github.com/dietmarwo/CFD-craft/actions/runs/41361132558),
[performance iterations](PERFORMANCE_ITERATIONS_RESULTS.md)) accepted every row.
At the 0.01 Ghia target (24² for both) native takes **0.111× OpenFOAM's solver
time** (0.0698 against 0.628 s) and 0.119× its workflow time, with error
0.0054 against 0.0090; on every shared grid from 16² to 48² native solves in
0.08–0.11× OpenFOAM's time. The steady RANS canyon with its tracer now runs
with `implicit_projection` (P5c, P5d; [results](IMPLICIT_RANS_RESULTS.md)): the
27k canyon in 57.6 s on one 2.1 GHz thread, 52× faster than the explicit mode,
and the 93k canyon in 615 s. There is no OpenFOAM canyon recipe to compare it
with.

Open: defaults remain donor-cell and explicit until an announced decision; the
predeclared P5c tightening statistic failed for U on one decade (recorded);
the canyon is not grid-converged at 93k; masked multigrid (P2b) would cut the
canyon's remaining IC(0) pressure work.

## Matched accuracy after P3a and P5a (1 November 2026)

With opt-in `limited_upwind`/`van_leer` momentum advection (P3a) and the
`implicit_projection` steady algorithm (P5a), the hosted paired sweep
([matched-accuracy results](MATCHED_ACCURACY_RESULTS.md), run 41345659321)
accepted all 32 rows. Both backends first reach 0.01 Ghia error at 24², where
native takes **0.74× OpenFOAM's solver time** (0.549 against 0.743 s) and 0.45×
its workflow time, with error 0.0054 against 0.0090. From 24² up native is faster
and more accurate on every shared grid (0.51× solver time at 48²). Before these
stages, native needed 96² and about 826 s to reach the target.

Defaults are unchanged. Open work at that time: the implicit algorithm for
RANS (P5c) and scalar transport (P5d), which the canyon needs (both done since;
see the section above), and a decision on defaults.
Details: [second-order momentum](SECOND_ORDER_MOMENTUM_RESULTS.md) and
[implicit steady](IMPLICIT_STEADY_RESULTS.md) results.

## Stage V accuracy baseline (1 November 2026)

Stage V, the first stage of the [accuracy/steady-solver plan](../docs/ACCURACY_STEADY_PLAN.md),
adds verification without changing production numerics. Read the
[Stage V results](MOMENTUM_VERIFICATION_RESULTS.md) for the exact protocol and
retained failures. The recorded 16/24/32/48 sweep passed all 32 rows at final
collection, and its evidence archive verified all 51 sealed archives after a
zip round trip. The [hosted reproduction](MOMENTUM_VERIFICATION_RESULTS.md#hosted-reproduction)
repeated the sweep on a GitHub runner with the same errors and all rows
accepted, at native/OpenFOAM solver ratios of 3.50–10.99×.

| Grid | Native Ghia error | OpenFOAM Ghia error | Native steps / OpenFOAM iterations | Native solver s | OpenFOAM solver s | Native/OpenFOAM |
|---|---:|---:|---:|---:|---:|---:|
| 16² | 0.03802453 | 0.01875367 | 1020 / 375 | 1.070 | 0.314 | 3.41× |
| 24² | 0.02756134 | 0.00896632 | 2010 / 696 | 5.202 | 0.726 | 7.16× |
| 32² | 0.02351448 | 0.00870380 | 3240 / 1102 | 15.039 | 1.493 | 10.07× |
| 48² | 0.01695144 | 0.00707998 | 6390 / 2132 | 71.613 | 6.179 | 11.59× |

These configured-recipe timings (recording host, Rust 1.88.0) do not measure a
change in solver performance. The donor-cell operator order is 0.997; the translating
vortex L1 order is 0.974, with independently negligible time error.

A separately budgeted **96²** same-scheme reference reaches Ghia error
**0.00921**. On the GitHub runner a cold solve was accepted at 21390 steps
after **825.9 s** of solver time. On the recording host the cold solve
converged but failed during archive writing, and an accepted checkpoint
continuation supplied the reference after about 1076 s of accumulated solver
work; both are documented. Neither is a repeated cost-at-target timing sample.
The shared paired sweep still has no native qualifying grid, so its formal
`native_over_openfoam_at_target` remains null. Native reaches the accuracy
objective in this diagnostic, but the cost deficit remains very large.

**Next:** P3a conservative second-order laminar advection, then P4 implicit
viscous correction and P5a implicit steady projection. P5b is conditional;
P3b/P5c extend open boundaries/RANS and P5d adds scalar transport. M repeats
matched-accuracy measurement after each stage. P2b/P2c remain separate pressure
work. No defensible percentage of the full gap closed follows from this
verification-only stage.

## Pressure stage P2a

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

## Same-host comparison, 31 October 2026

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
P1 isotropic multigrid, P2a, P3 (P3a/P3b), P4, P5 (P5a, P5c, P5d; P5b was not
needed) and the matched-accuracy measurement M are complete; their rows are
kept below as the record of what was asked. Open: P2b, P2c, P6 and a decision
on defaults.

| Next stage | Scope | Evidence required before calling it complete |
|---|---|---|
| P2b: masked multigrid | Component-preserving aggregation/interpolation; one nullspace/gauge per sealed component; anchored components; thin passages and disconnected pockets. Extend the current rejection only with verified support | Independent masked `-DG`/Galerkin/reference solves; full preconditioner symmetry/positive-energy tests; no merging across solid barriers; changed coefficients/topology/cancellation/restart controls. Accepted 27k/93k canyon comparisons, field equivalence and an actual coupled benefit; preserve budget failures |
| P2c: setup and hierarchy cost | Profile cold hierarchy construction and coarse operator growth. Reduce assembly/scratch/transfer overhead where measured, retaining the fixed SPD cycle | Cold/reused work and memory, operator/grid complexity, exact field/reference controls. Require an end-to-end gain for representative repeated and one-off workloads; iteration counts alone are insufficient |
| P3: momentum accuracy per cost (done) | Independently verified higher-order momentum advection with explicit boundary/conservation treatment. Keep a selectable baseline and frozen physical model | Manufactured spatial/temporal order, periodic and wall/outlet conservation, bounded stability regime, Ghia cost-versus-error refinement. A native run must actually reach the declared 0.01 target before a matched-accuracy ratio can be reported |
| P4: implicit diffusion decision (done) | Bounded laminar implicit momentum diffusion trial after profiling its attainable benefit. Treat turbulent/scalar extensions separately | Independent diffusion/time-order tests, boundary and energy checks, linear-solver residuals, accepted coupled cost at equal error. The earlier approximately 1.68 stability-headroom estimate is a ceiling under assumptions, not a promised speedup; stop if overhead removes the benefit |
| P5: a dedicated steady algorithm (done) | Reduce explicit pseudo-time work with a documented steady momentum/pressure coupling; maintain a consistent residual and fixed point | Independent steady equation residuals, conservation and gauge checks, baseline-equivalent converged fields, cavity grid/error sweep and masked/RANS controls. Compare complete convergence, not cost per outer iteration |
| P6: canyon and optimization payoff | Replay representative canyon and optimizer campaigns using experiment-craft/optimization-jobs, frozen budgets, cached converged flows and held-out scenarios where appropriate | Accepted 27k/93k refinement, model-card and empty-ABL gates, reproducible worker/job identities and failed jobs, budget-matched best-so-far outcomes and fine-grid replay. Experimental-data acquisition/model qualification remains a separate prerequisite for physical claims |

P3–P5 were done before P2b, as recommended, because the accuracy deficit was
visible on unmasked cavities; the cost-at-equal-accuracy comparison is now
reported. The recommended next pressure stage is P2b.

All listed CPU implementation and small/medium validation work can run in
cloud CI; many-core and GPU studies remain lower priority. The opt-in
`external=anisotropy` selector runs the hosted anisotropy campaign; its GitHub
run is recorded in the [anisotropy results](ANISOTROPIC_PRESSURE_RESULTS.md#hosted-reproduction).

## What parity would mean

Use the same physical problem, domain, boundary conditions and declared error
objective; independently accepted fields; repeatable complete-run time and
memory on the same host. Report setup, solver and outer workflow separately.
The native steady algorithm (explicit SSPRK2 by default, opt-in
`implicit_projection`) and the pinned OpenFOAM
Foundation 13 SIMPLEC/GAMG recipe use different discrete schemes and stopping
norms. A same-grid configured timing ratio describes those recipes. A
matched-accuracy ratio additionally requires both methods to reach the error
target. Neither is experimental validation of urban dispersion.

Repeated matched-accuracy costs on the cavity now exist (runs 41345659321 and
41361132558); they describe the laminar cavity and these recipes, not the
canyon, for which there is no OpenFOAM recipe.
Pressure-kernel speedups and coarse-grid throughput retain their own scope.
