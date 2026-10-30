# Iteration 03: backstep resolution and independent audit

Work date: 29 October 2026; cloud execution: 30 October UTC. Base:
`4ea88a3286225a7c14f30e7bf7388419dbc804a6`, merged PR #3. The earlier
[external results](EXTERNAL_RESULTS.md) remain the record of that merged
baseline. The [plan and review amendment](../docs/iterations/03-wall-resolution-plan.md)
describe this iteration's targets and the unmet scientific target.

## Result

The independent mesh/local-flux auditor, fail-fast guard and gated study are
implemented and tested. **No wall-resolved backstep is numerically accepted.**
No new experimental-validation, mesh-independence, accuracy or performance
claim follows from this iteration.

| Actual run | Cells | Execution and numerical result | Independent audit / interpretation |
|---|---:|---|---|
| Final cavity, Re=100 | 576 | Converged at iteration 696; numerical gate passed | Local max(abs(div(phi)))*H/U = 4.05294e-9, below 1e-4; volume 0.1 m3 |
| Legacy mesh, SIMPLEC pressure-relaxation control | 22656 | 6000 iterations, 277.45 s; numerical gate failed | Local divergence 3.54708e-5 passes the separate audit, but p initial residual is 0.00168726 and explicit solver convergence is absent |
| Final wall-resolved/simple reference | 47616 | Nonfinite residuals at started iteration 700, stopped after 322.10 s within a 420 s budget | CFD-X010; no final field assessment, wall-y+ verdict or measurement comparison |
| Requested wall-resolved levels 2 and 3 | 190464 / 428544 | Not started | `coarser_level_not_accepted`; no accepted mesh pair or GCI |

The pressure control's last-window medians remain approximately 0.001758 for p,
0.000195 for k and 0.000237 for omega, close to the preceding window. Its
relative boundary-flux imbalance is only 4.9021e-10. Small boundary imbalance
and passing independent continuity do not establish momentum/turbulence
convergence. The measurement screen remains not assessed (null).

Eight earlier wall-resolved pilots explored SIMPLEC/SIMPLE, GAMG/PCG, tighter
linear solves, cold start, first-order advection, less aggressive grading,
gradient limiting and damping. Seven stopped on nonfinite output. The initial
pilot, started before the new guard existed, timed out at 900 s with nonfinite
output. They are retained as failed exploratory evidence, not isolated causal
tests of each setting. The delivered first-order, damped recipe also failed.

## Independent corruption check

Starting from the actual returned cavity archive, add 0.01 m3/s to its first
internal face flux, then recompute the archive's checksums and completion
marker. The global boundary budget is unchanged and the original archive
consistency/numerical-summary verifier still passes. The independent auditor
rejects the altered field: maximum local normalized divergence is 57.6,
against 1e-4. This deliberate synthetic corruption demonstrates a missing
local check; it is not an experimental dataset or physical-validation result.

The actual Foundation-13 `blockMesh` output is also tested against every
claimed first-cell distance on the 47616-cell recipe, including the step wall,
with represented volume 48.2 m3. Correct generated distances do not establish
y+ <=1 without an accepted flow and stored wall traction.

## Software verification and reproduction

On the pinned Foundation 13 package `20260407`, build `13-441953dfbb42`, f64,
32-bit labels, serial, Ubuntu 24.04 x86_64:

- Required Rust formatting, Clippy with warnings denied and 32 release tests pass.
- Ruff formatting and lint checks pass.
- All 35 native CLI tests pass in normal and optimized Python.
- All 38 existing external tests and 16 resolution tests pass in both modes,
  including actual runtime tests; synthetic fixtures remain labeled as such.
- Native Gaussian/Poiseuille/empty-ABL verification passes unchanged targets.
  Gaussian observed order is 2.3233; H..5H relative U/k/epsilon drift is
  0.2341% / 0.9405% / 2.6754%, against 2% / 5% / 5%. Below-H drift remains
  reported and ungated.

```sh
python tutorials/backstep_resolution.py --preset study --iterations 6000 \
  --timeout-s 420 --foam-root ROOT --data VERIFIED_DATA --output NEW_OUTPUT
```

The study returns exit 2, `workflow_completed=true`, `passed=false`; it has
accounted for all requested rows, including explicitly skipped finer cases.
The ZIP delivery includes the exact inputs, source identities, logs, complete
selected archives, partial pilot evidence and software-test logs. OpenFOAM
binaries and raw measurements are not redistributed. Archived original command
paths identify the cloud execution; reproduce in fresh directories.

Before spending another mesh budget, isolate this instability against an
independently maintained Foundation-13 SST backstep setup, including
pressure/flux initialization and wall/inlet turbulence treatment. Retain the
frozen numerical and experimental targets. Once a stable recipe passes, run
the same package on successively finer meshes, then examine inlet/model
sensitivity. The native Rust physics and native canyon validation gates are
unchanged; this work needs no owner workstation.
