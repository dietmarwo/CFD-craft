# Stage V: momentum verification and donor-cell baseline

Measured 1 November 2026 against main `f358be6` (merged PR #14).
Stage V changes verification and measurement only. Production Rust numerics,
default serialization, physical models and acceptance thresholds are unchanged.
See the [protocol](../history/20-momentum-verification-plan.md),
[full accuracy/steady plan](../history/accuracy-steady-plan.md) and
[machine-readable reduced evidence](https://github.com/dietmarwo/CFD-craft/blob/main/validation/data/stage-v-donor-cell-baseline.json).

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
steps; OpenFOAM 180 s/3000 iterations. The recorded run used a fresh temporary
directory, started after all builds and the 96² reference had finished, and
recorded filesystem events and process snapshots. All **32 rows pass final
collection**, and its evidence archive verifies **51/51 sealed archives** after
a zip round trip, including the analytic fixtures, default controls and the
accepted 96² reference. Default controls retain IC(0). These medians are not a
speedup comparison with earlier hosts or compiler versions.

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
OpenFOAM's qualifying 24² median is 0.726 s. On the GitHub runner a cold 96²
solve, with no restart, was accepted after 825.9 s (see
[Hosted reproduction](#hosted-reproduction)). This exposes a very large
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
all-target clippy. All 17 Python suites pass in normal and optimized mode
(411 tests per mode). Ruff passes formatting and lint.

Two partial sweeps were invalidated by changed frozen inputs and retained.
A complete sweep failed an OpenFOAM warmup progress check. A complete repeat
initially passed all 32 rows, but later checks rejected three of its OpenFOAM
archives: purged snapshots/directories no longer matched their seals. Those
initial passes are not presented as the final trustworthy baseline.

A new post-campaign collection guard rechecks the manifest and native/external
archive after all child runs, retains `accepted_at_measurement`, and invalidates
late changes before calculating qualifying costs. Two regression tests cover
changed manifests and late archive rejection; the final accuracy-sweep suite
and comparator suites cover them in both Python modes. The subsequent
sequential reproduction still failed (two rows at collection, further changes
at packaging), and remains failed. The older
[cloud archive investigation](../history/06-archive-investigation.md)
already describes this anomaly; its underlying cause remains unknown.

The recorded campaign used the identical numerical and timing protocol in a
fresh temporary directory. It passed collection and the zip round trip there,
and its archive was rechecked after copying (51/51 sealed archives, identical
bytes and CRCs). Filesystem events, process snapshots, the reproduction driver
and the failed attempts are kept with the evidence. This containment is not a
repair of old archives or a diagnosis. No verifier or scientific tolerance was
relaxed. The cold-reference and different-work byte comparison failures remain
recorded above.

## Hosted reproduction

Ordinary Rust CI includes the operator and insulation tests; numerical CI runs
`validation/momentum_accuracy.py`. The manual **external=momentum** job runs the
whole protocol on a GitHub runner: fixtures, the paired sweep, the 96²
reference and the default byte controls against `main` (`f358be6` for this
run; the job now builds `6d33850`). It ran on
the code of commit `9fdc961` (AMD EPYC 9V74, 4 CPUs, ubuntu-24.04;
[run 41302658721](https://github.com/dietmarwo/CFD-craft/actions/runs/41302658721)),
whose solver and fixture code is the code measured above. Every step passed.

- **Fixtures:** identical to the recorded values: vortex orders 0.97390 /
  0.97475 / 0.95906, time-difference order 2.0002 at 4.95e-6 of the spatial
  error, the same momentum drift and no new extrema in the transverse step.
- **Paired sweep:** all 32 rows accepted, the workflow valid, and no row
  rejected at final collection. Ghia errors equal the recorded ones; native
  still misses 0.01 on every paired grid, so the ratio at target stays null.

| Grid | Native solver s | OpenFOAM solver s | Native/OpenFOAM | Native workflow s | OpenFOAM workflow s |
|---|---:|---:|---:|---:|---:|
| 16² | 0.924 | 0.264 | 3.50× | 0.993 | 0.841 |
| 24² | 4.391 | 0.629 | 6.98× | 4.454 | 1.250 |
| 32² | 12.937 | 1.450 | 8.92× | 13.030 | 2.061 |
| 48² | 59.551 | 5.417 | 10.99× | 59.657 | 6.146 |

- **96² reference:** a **cold** solve accepted at **21390 steps** after
  **825.9 s** of solver time, Ghia error **0.00920562**, with no restart. This
  is the clean counterpart of the recorded checkpoint continuation (21420
  steps, 0.00920541). It is still a single diagnostic, not a repeated
  cost-at-target sample: about 1,300 times OpenFOAM's 0.629 s at 24².
- **Self-convergence:** descriptive L1/L2/L∞ slopes 1.2845 / 1.2765 / 1.3558
  against the cold reference, equal to the recorded ones to four digits.
- **Default controls:** steady cavity24, transient Poiseuille and the
  three-step masked canyon are byte-identical to `main` with identical work
  (2010/204850, 2/0, 3/365).
- **Evidence archive:** 51/51 sealed archives verified after the zip round
  trip; no archive records a time directory without files.

## Remaining stages

Stage V provides verification fixtures and a baseline; it delivers no
numerical speedup. Each following stage may require more than one PR.
Done since (1 November 2026): P3a, P3b, P4, P5a, P5c, P5d and M; P5b was not
needed; P2b and P2c remain open
([gap status](performance-gap-status.md)). The table is the plan as recorded.

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
