# Bounded mapped refinement: actual results

30 October 2026. Source patch base: merged PR #6, `06bf8b5d894e5252a5b04d14ff04cda06e010bb8`.

## Outcome

The short local level-2 backstep proof **did not supply accepted fine-grid evidence**. Its exact stopping reason
is `stage_limit`. Workflow collection completed:
`True`. Scientific pass: `False`.
Physical qualification remains **false**.

The final fine field was not numerically accepted, so the coarse/fine observable comparison was not assessed. Two levels do not provide a GCI. These are results of an external
backstep experiment; the native canyon and passive-gas qualification gates are
unchanged.

## Source and declared work

The complete accepted cold level-1 source was recovered from GitHub run
[41106074755](https://github.com/dietmarwo/CFD-craft/actions/runs/41106074755),
artifact 13008679534. Its downloaded ZIP matched GitHub's published SHA-256:
`34ff3df6f86741413aed94a4ffd5c34498de1bba8ce47f2191553d8445931322`.
It passes the current archive verifier, independent audit and frozen measurement
screen. Its exact runtime matches the local pinned runtime. The retained source
manifest is `d90c70c78997c3de30b658cea631fd873fcbad5f2f02ea8793def42750c5284a`.

The source has 48896 cells and 18412 historical iterations; those are not new
local work. The target has 195584 cells. Before execution the amended local proof froze at most
2 stages of 400 iterations,
450 seconds per execution, preparation
180 seconds, 1024 MiB
per-stage output and 4096 MiB child address space.
Two longer host sessions had disappeared without returning or sealing fields,
even with heartbeat monitoring. The plan amendment reduces work to fit a
sustained local session; it changes no numerical or scientific gate. The full
three-by-4000 campaign remains configured for manual CI and was not dispatched.

| Fine stage | Execution | Completed iterations | Converged | Numerical | Audit | Measurement screen | Wall s |
|---|---|---|---|---|---|---|---|
| 1 | completed | 400 | fail | fail | pass | not assessed | 237.142964 |
| 2 | completed | 400 | fail | fail | pass | not assessed | 285.98553 |

Completed fine work is **800 iterations**,
separate from **18412 coarse iterations**. Preparation
took 36.6527153 seconds; total new campaign wall
time including verification and collection was 717.397537
seconds. The source's historical wall time is provenance, not new CPU time.
There was no new cold level-2 control and there is no new speedup claim.

## Reproduce the amended local proof

Use the patched repository, pinned runtime, explicitly fetched data and the
complete `evidence/refinement-backstep/source` archive from the bundle:

```sh
python validation/refinement_campaign.py --source SOURCE --foam-root ROOT --data DATA --iterations 400 --max-stages 2 --timeout-s 450 --preparation-s 180 --output-mib 1024 --memory-mib 4096 --output NEW_CAMPAIGN
```

## Actual final fields and gates

| Field | Final initial residual | Gate |
|---|---|---|
| Ux | 7.56855284e-07 | <= 1e-7 |
| Uy | 1.04252155e-05 | <= 1e-7 |
| p | 2.58771131e-06 | <= 1e-7 |
| k | 2.07397116e-06 | <= 1e-7 |
| omega | 5.91755728e-09 | <= 1e-7 |

Reported final local continuity: 6.01088324e-12
(target <=1e-6). Stored boundary-flux imbalance:
1.47058637e-13 (target <=1e-6).
Independent max abs(div(phi))*H/U:
2.40333222e-07
(target <=1e-4). The archive verifier also checks finite/sign-valid returned
U/p/k/omega/nut fields.

| Wall | Maximum y+ | Gate |
|---|---|---|
| lowerWall | 0.252708115 | <= 1 |
| upstreamWall | 0.472776443 | <= 1 |
| upperWall | 0.343150518 | <= 1 |
| stepWall | 0.515304066 | <= 1 |

The final independent-audit verdict is `True`. An audit
of conservation and wall sampling does not establish nonlinear convergence.

| Final-iterate observable | Value | Original screen target |
|---|---|---|
| U profile x/H=1 | 0.0450744424 | RMSE <= 0.10 |
| U profile x/H=4 | 0.0644289412 | RMSE <= 0.10 |
| U profile x/H=6 | 0.0928660368 | RMSE <= 0.10 |
| U profile x/H=10 | 0.0912487631 | RMSE <= 0.10 |
| Signed Cf | 0.000389754549 | RMSE <= 0.001 |
| Reattachment x/H | 6.65862688 | error <= 0.75 H from 6.26 H |

These are metrics of the **actual final iterate**. The measurement-screen
verdict is `not assessed` and its status is
`not_assessed: the numerical gate failed; the metrics describe the final iterate only`. Individual metrics near their targets
cannot override an unaccepted numerical or independent gate.

## Conditional two-grid comparison

No inter-grid differences are promoted as accepted mesh sensitivity.

When assessed, velocity sample identities match station, sample ID and physical
y/H exactly; Cf is compared at common positive experimental x/H positions
without extrapolation. `mesh_sensitivity.passed` means both grids pass the
original gates, not that the difference between them is below an invented
threshold. The native canyon's separate 5% target is not used here.

## Retained accepted cavity proof

The retained real Foundation-13 cavity campaign passes. Its cold source took
696 iterations; the fine chain took
1356 iterations in stages 400, 400, 400 and 156.
Both grids pass their original numerical, independent and Ghia-reference gates.
Maximum centreline change is 0.00753181251
lid-speed units. The coarse and fine Ghia maximum errors are
0.00896632356 and
0.0070799887, against 0.06 each.
This is a numerical-reference exercise, not physical validation. Its complete
source/stage fields are retained separately as `evidence/refinement-cavity`;
its work is not added to the backstep ledger.

## Integrity, development finding and tests

The report retains 4 successful archive
checkpoints, including final collection. Every retained stage is bound to its
actual parent, runtime, mesh, fields, final time and work. The complete source
and stages remain available in the patch bundle; summary-only records are not
used as restart sources.

The late-file regression deliberately adds `case/123/U` after a real cavity
archive is sealed. The campaign rejects it with CFD-X015 and the underlying
CFD-X006, keeps the file and stops without a second stage or a new seal.
A separate working-directory cavity source reproduced the strict progress
failure: an empty `case/500/uniform` directory reappeared while every file still
matched the original manifest. That source was quarantined, including its empty
directory shape. The final retained positive cavity proof was regenerated under
a fresh private path. A new real-runtime regression and retained probe recreate
the empty-directory failure. The original mechanism remains unproven; no
progress rule was relaxed. See the
[investigation](../docs/iterations/06-archive-investigation.md).

A pre-release review reproduced an acceptance/cancellation race in the new
campaign layer. Cancellation now overrides acceptance even after a solver has
returned; its regression passes normally and under `python -O`. An early fine
trial was interrupted to deploy this fix (last observed started pseudo-time
238, host session exit 130). It had no sealed final archive, was not
used as a source and is not counted as completed work in the final trial.
Its producer, partial report, log and interruption receipt are retained as
development evidence in the bundle. Two subsequent host sessions disappeared at started iterations 1457 and
1193 without solver returns or seals (exit statuses unknown), including the
heartbeat repetition. Their records are retained; no partial snapshot was
continued. The fresh amended short proof restarted from the same verified cold
source. The larger convergence objective remains a CI experiment.

All 30 campaign tests pass in normal and optimized Python, including five real
Foundation-13 tests in each mode. All existing backend (38), resolution (41),
restart (54), mapping (58) and CLI (35) tests also pass in both modes. That is
256 tests per interpreter mode, with the runtime tests enabled. Core Rust
format/clippy/release tests pass (32 tests), as do Ruff, native analytic/empty-ABL,
flow-order, cavity and SciPy-reference verification. No native equation or
experimental protocol changed.

## Interpretation and remaining work

The local implementation/returned-field proof is complete; the original long
fine-grid convergence experiment is not. Run the configured larger manual-CI
trial on a sustained runner to pursue accepted fine fields. Owner hardware is
not required for that experiment.

- Retain the exact fine-field outcome and residual trends when deciding another
  budget or a separate solver-method experiment. A larger budget is not evidence
  that convergence is guaranteed.
- A successful numerical pair still needs another accepted refinement and a
  defensible convergence regime before a GCI. Mapping an already mapped source
  to another mesh requires separately tested chained provenance; it is not
  enabled by this campaign.
- Inlet/near-wall reconstruction uncertainty, model-form sensitivity and velocity
  measurement uncertainty remain open. The benchmark has no passive-gas data.
- Native canyon throughput, building-wall treatment and measured canyon/gas
  qualification remain separate gates. Owner-machine, MPI and GPU work stays
  deferred while the owner is travelling with a phone.

The [guide](../integrations/REFINEMENT_CAMPAIGN.md),
[plan](../docs/iterations/06-refinement-campaign-plan.md) and
[tutorial prompt](../tutorials/refinement-campaign-prompt.md) describe the
implemented workflow and the meaning of its verdicts.
