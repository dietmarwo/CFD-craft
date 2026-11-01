# Stage V: momentum verification and donor-cell baseline

Measured 1 November 2026 against main `f358be6` (merged PR #14).
This iteration changes verification and measurement. Production Rust numerics,
default serialization, physical models and acceptance thresholds are unchanged.
See the [protocol](../docs/iterations/20-momentum-verification-plan.md),
[full accuracy/steady plan](../docs/ACCURACY_STEADY_PLAN.md) and
[machine-readable reduced evidence](data/stage-v-donor-cell-baseline.json).

## Analytic verification

The production donor-cell operator has mean L1 order **0.99723** over
eight prescribed phase offsets and grids 32/64/128/256. The test-only helper
zeros viscosity/forcing after grid construction; production arithmetic is not
refactored. The solid-barrier insulation test and near-side sensitivity control
pass.

| Phase | L1 order | L2 order | L∞ order |
|---|---:|---:|---:|
| 1 | 0.99781 | 0.99795 | 0.99793 |
| 2 | 0.99748 | 0.99791 | 0.99808 |
| 3 | 0.99680 | 0.99778 | 0.99722 |
| 4 | 0.99693 | 0.99779 | 0.99757 |
| 5 | 0.99775 | 0.99798 | 0.99777 |
| 6 | 0.99707 | 0.99764 | 0.99752 |
| 7 | 0.99644 | 0.99766 | 0.99642 |
| 8 | 0.99755 | 0.99788 | 0.99817 |

The translating Taylor–Green vortex, with nonzero uniform drift, recovers
L1/L2/L∞ orders **0.97390 / 0.97475 / 0.95906**.
Time refinement gives order 2.00022; its last L1 difference is
4.95e-06 of the grid-64 spatial error (gate 0.01).
The fixture therefore exposes advection's first-order error independently of
the existing second-order viscous-shear test.

| Grid | Velocity L1 error | L2 error | L∞ error | Largest normalized component-momentum drift, 100 steps |
|---|---:|---:|---:|---:|
| 16² | 0.00470947 | 0.00583871 | 0.01294304 | 0.0018038913 |
| 32² | 0.00241471 | 0.00299092 | 0.00674135 | 0.00096546842 |
| 64² | 0.00122074 | 0.00151168 | 0.00342471 | 0.00049480891 |

Momentum drift is a recorded baseline, not a newly weakened conservation gate.
The current advective donor-cell form is not conservative; P3a's shared fluxes
must meet its separate 1e-13-per-100-step gate. The transverse step has no new
extrema after 1000 steps at CFL cap 0.45; final range is
[0.42350959, 0.57649041]. Its deliberate iteration limit
is recorded as incomplete numerical acceptance, rather than called an accepted
transient interval.

## Paired backend sweep

AMD EPYC 9V74, 8-CPU cgroup, one solver thread; Rust 1.88.0, Python 3.12.14,
pinned OpenFOAM Foundation 13 package from the existing adapter. One warmup
plus three alternating timed pairs per grid. Native multigrid, 600 s/20000
steps; OpenFOAM 180 s/3000 iterations. The final run used a fresh private
temporary path after the producer builds and 96² reference had finished;
lightweight filesystem-event logging and scoped process snapshots were recorded.
All **32 rows pass final collection**, and the transferred immutable ZIP verifies
**51/51 sealed archives**, including analytic fixtures, default controls and
the accepted 96² reference. Default controls retain IC(0). These local medians
are not a speedup comparison with earlier hosted/compiler versions.

| Grid | Native Ghia error | OpenFOAM Ghia error | Native steps / OpenFOAM iterations | Native solver s | OpenFOAM solver s | Native/OpenFOAM |
|---|---:|---:|---:|---:|---:|---:|
| 16² | 0.03802453 | 0.01875367 | 1020 / 375 | 1.070 | 0.314 | 3.41× |
| 24² | 0.02756134 | 0.00896632 | 2010 / 696 | 5.202 | 0.726 | 7.16× |
| 32² | 0.02351448 | 0.00870380 | 3240 / 1102 | 15.039 | 1.493 | 10.07× |
| 48² | 0.01695144 | 0.00707998 | 6390 / 2132 | 71.613 | 6.179 | 11.59× |

Native computes two span cells, OpenFOAM one. Native `elapsed_s` excludes
startup/output; OpenFOAM's solver-process time includes its startup/output.
The native and SIMPLEC stopping norms also differ. These are configured
same-flow-plane-grid ratios, not equal-work or equal-accuracy ratios.

OpenFOAM reaches 0.01 on 24²; native misses it on every grid in the paired list.
The paired report's `native_over_openfoam_at_target` remains **null**.

## Native 96² self-reference and the first observed target crossing

A separately budgeted native 96² cold solve reached the steady checks at
**21390 steps**, residual 9.9253791e-06, after **1074.45 s** of
solver work. It then exited 1 writing executable identity, because an active
executable had been replaced during a build. Its directory remains unsealed;
no manifest or completion marker was manufactured.

A fresh run used that unchanged checksummed checkpoint through the public
restart contract and the fixed candidate executable. It recomputed acceptance,
passed the independent archive/field audit and finished at **21420 steps**,
residual **9.7918938e-06**, Ghia error **0.00920541**.
The normal restart advances to the next monitor window: 30 extra steps,
360 pressure iterations and 1.574 s. The predecessor/continuation byte
comparison failed and is retained: maximum velocity change
2.31e-07, pressure change
6.59e-08. These are different-work states; this is
not claimed as a same-step restart-identity pass. Default same-work controls
below are unchanged and pass.

Thus native **can reach the 0.01 objective at 96²**, with approximately
**1076.02 s (17.9 minutes) of accumulated solver work** in this diagnostic chain.
OpenFOAM's qualifying 24² median is 0.726 s. This exposes a very large
accuracy-per-cost deficit, but a failed cold archive plus one continuation is
not a repeated matched-accuracy benchmark. The 96² reference is excluded from
the paired cost-at-target calculation; its 1.574-second continuation timer
must never be presented as the full solve cost.

Against this accepted same-scheme 96² centerline on 257 fixed stations,
descriptive L1/L2/L∞ slopes over 16/24/32/48 are
1.28448 / 1.27649 / 1.35582.
A finite reference and this interpolation-based observable do not establish
asymptotic order or a GCI.

## Controls, checks and retained failures

Default steady cavity24, transient Poiseuille and a three-step masked canyon
match unmodified main byte for byte in fields, checkpoints, probes, geometry
and consumed case, with identical steps and pressure work (2010/204850,
2/0, and 3/365 respectively). The canyon work limit is not called convergence.
Rust 1.88.0 and 1.99.1 each pass all 77 release workspace tests, fmt and strict
all-target clippy. All 17 Python suites pass in normal and optimized mode;
the final new-suite rerun has five tests per mode. Ruff 0.16.9 passes formatting
and lint. Initial local Rust-1.88 link failures disappeared after cleaning the
package's build artifacts; no source or compiler flags were changed to pass.

Two partial sweeps were invalidated by changed frozen inputs and retained.
A complete sweep failed an OpenFOAM warmup progress check. A complete repeat
initially passed all 32 rows, but later checks rejected three of its OpenFOAM
archives: purged snapshots/directories no longer matched their seals. Those
initial passes are not presented as the final trustworthy baseline.

A new post-campaign collection guard rechecks the manifest and native/external
archive after all child runs, retains `accepted_at_measurement`, and invalidates
late changes before calculating qualifying costs. Two regression tests cover
changed manifests and late archive rejection; the final accuracy-sweep suite
passes 18 tests per Python mode, and the comparator 15 per mode. The subsequent
sequential reproduction still failed (two rows at collection, further changes
at packaging), and remains failed. The older
[cloud archive investigation](../docs/iterations/06-archive-investigation.md)
already describes this anomaly; its underlying cause remains unknown.

The final campaign used the identical numerical/timing protocol under a fresh
private temporary path. It passed collection and ZIP round-trip tests there;
only the immutable ZIP was transferred back and rechecked (51/51 sealed
archives, exact ZIP bytes and CRCs). Filesystem events, scoped process snapshots,
the reproduction driver and immutable nested failed-attempt evidence are kept.
This containment is not a repair of old archives or a diagnosis. No verifier
or scientific tolerance was relaxed. Cold-reference and different-work byte
comparison failures remain recorded above.

## Hosted reproduction

Ordinary Rust CI includes the operator and insulation tests; numerical CI runs
`validation/momentum_accuracy.py`. Dispatch `CFD checks` with
**external=momentum** for the full paired sweep, separately budgeted 96²
reference and main/candidate byte controls. The job builds both executables
before measurement and preserves complete directory entries in its evidence
zip. This job was **wired but not run on GitHub in this task**. Local evidence
and hosted reproduction are distinct.

## Remaining iterations

Stage V is implemented and locally exercised, including retained deviations
and the accepted checkpoint-based finite reference. It delivers no numerical
speedup. Each following stage may require more than one PR.

| Stage | Remaining implementation and exit evidence |
|---|---|
| P3a — next | Opt-in conservative second-order laminar advection; unlimited and limited candidates; operator/vortex order, conservation, extrema/stability, wall/solid closure, default/restart controls and accepted cavity sweep. Keep only schemes that pass. |
| P4 | Delta-form implicit viscous correction in steady pseudo-time; same fixed point under stricter residual checks, unchanged acceptance, restart and complete-run cost. |
| P5a | Uniform-step implicit steady momentum/projection; choose inner solver by predeclared pilot. Must reduce solver time by at least 2× versus the better explicit/P4 method with selected P3a advection. |
| P5b — conditional | Consistent local pseudo-time and face-weighted projection only if P5a misses its cost gate; independent pressure-operator and nullspace tests. |
| P3b + P5c | Open-boundary closures and RANS, empty-ABL check, same fixed point, zero floor events, accepted 27k/93k canyons and updated model card. |
| P5d | Scalar transport with implicit flow: declared substeps, implicit transport or a verified frozen-flow workflow; mass, positivity, units and refinement checks. |
| M — after each stage | Repeated same-host cost at the declared error, both backends on the shared list, unchanged checks and all failures retained; add a qualifying native grid to the paired protocol when needed. |
| Separate pressure work | P2b masked multigrid and P2c setup/hierarchy costs. They do not block P3a. |
