# Bounded mapped refinement: results

The declared level-2 backstep campaign of the
[plan](../docs/iterations/06-refinement-campaign-plan.md), run on a
GitHub-hosted runner on 31 October 2026 from commit
`e7b095277ac1346806984ae4070bc18ac1e9aefe`. The campaign code of that commit is
the current code; later commits change tests, notices and documentation only.

## Outcome

The campaign **did not produce an accepted fine grid**. All three declared
stages of 4000 iterations completed, and the stop reason is `stage_limit`. Every
stage passed the independent audit (local flux and wall y+), but none passed the
numerical gate: after 12000 fine iterations the final initial residuals of Uy
(1.81e-7) and k (1.05e-7) are still above 1e-7, and the solver did not report
convergence. The two-grid comparison was therefore not assessed. Physical
qualification remains false.

The residuals fell steadily through all three stages. The Uy residual, which had
seemed to level off near 1e-5 in shorter runs, fell by a factor of about 7 per
stage. Whether one more stage would pass the gate is an extrapolation; this
campaign does not show it.

| Item | Value |
|---|---|
| Workflow run | [41151497327](https://github.com/dietmarwo/CFD-craft/actions/runs/41151497327), dispatch input `external=refinement` |
| Runner | GitHub-hosted ubuntu-24.04, AMD EPYC 9V45, 4 CPUs (serial solve) |
| Evidence | artifact `resolution-evidence` (13026704954, 139081798 bytes, `sha256:c05c07f37b68e395801a43a3fa8fd708170dd476bf8825a4a81c9ef70c440f72`), containing `runs/refinement-campaign/report.json` and `runs/refinement-campaign-evidence.zip` |
| Workflow completed / passed | `True` / `False` |
| Stop reason | `stage_limit` |
| Completed / started fine iterations | 12000 / 12000 |
| Source iterations (separate) | 18412 |
| Archive checkpoints | 5 (source snapshot, three returned stages, final collection) |
| Campaign wall time | 5507.2 s, of which preparation 23.5 s |
| `refinement_campaign.py` | `6173411c59ed07a83c4d5f42836dbedb117507eb3bd07733f11825d2ce707b02` |

## Source and declared work

The same job first ran the wall-resolved SIMPLEC level-1 backstep cold, in one
run with a 20000-iteration budget (`backstep_resolution.py --preset smoke`).
It converged at 18412 iterations in 1988.2 s, with a final pressure residual of
1.20e-8. It passed the independent audit (max abs(div(phi))·H/U 6.4e-11, highest
wall y+ 0.963 on the step wall) and the measurement screen:

| Source observable | Value | Screen target |
|---|---|---|
| U profile RMSE x/H = 1, 4, 6, 10 | 0.0449, 0.0646, 0.0931, 0.0912 | ≤ 0.10 each |
| Signed Cf RMSE (17 points) | 4.17e-4 | ≤ 1e-3 |
| Reattachment | 6.706 H | within 0.75 H of 6.26 H |

The campaign took this archive (48896 cells) as its source and mapped it once to
level 2 (195584 cells). The declared limits, frozen before mapping, were three
stages of at most 4000 iterations, 3500 s per solve, 900 s for preparation,
1024 MiB output and 4096 MiB child address space per stage. The mapping replay
matched the earlier runs exactly: 185984 cells took their nearest source cell
and 9600 another of the 27 nearest (largest rank 4, largest distance ratio
1.1601).

## Stages

| Stage | Iterations | Wall s | Converged | Numerical | Audit | Measurement screen |
|---|---:|---:|---|---|---|---|
| 1 | 4000 | 1800.4 | no | fail | pass | not assessed |
| 2 | 4000 | 1778.8 | no | fail | pass | not assessed |
| 3 | 4000 | 1737.7 | no | fail | pass | not assessed |

Final initial residual of each stage; the gate is ≤ 1e-7 for every field:

| Field | Stage 1 | Stage 2 | Stage 3 | Reduction per stage |
|---|---:|---:|---:|---|
| Ux | 2.92e-7 | 1.22e-7 | **7.72e-8** | 2.4, 1.6 |
| Uy | 9.06e-6 | 1.19e-6 | 1.81e-7 | 7.6, 6.6 |
| p | 8.06e-7 | 1.03e-7 | **1.56e-8** | 7.8, 6.6 |
| k | 6.93e-7 | 2.55e-7 | 1.05e-7 | 2.7, 2.4 |
| omega | 1.60e-9 | 5.73e-10 | **2.46e-10** | 2.8, 2.3 |

Bold values meet the gate. The pressure residual's median over the last tenth
of each stage, against the tenth before, was 8.5e-7 / 9.7e-7, 1.13e-7 / 1.42e-7
and 1.72e-8 / 2.11e-8.

Each stage ran at about 0.44 s per iteration. The level-1 source ran at about
0.11 s per iteration with a quarter of the cells.

## Independent audit of the fine stages

| Stage | max abs(div(phi))·H/U | Max relative cell imbalance |
|---|---:|---:|
| 1 | 1.29e-8 | 3.5e-6 |
| 2 | 8.8e-10 | 3.5e-8 |
| 3 | 2.4e-10 | 1.1e-7 |

The local-flux target is ≤ 1e-4. Maximum y+ at stage 3: lower wall 0.253,
upstream wall 0.473, upper wall 0.343, step wall 0.515 (target ≤ 1; the same to
three digits in every stage). A passing audit of conservation and wall sampling
does not establish nonlinear convergence.

## Final-iterate observables

These are metrics of fields that are **not numerically accepted**. The
measurement screen was not assessed, and the differences from the source are not
a mesh sensitivity.

| Observable | Source (level 1, accepted) | Stage 1 | Stage 2 | Stage 3 |
|---|---:|---:|---:|---:|
| U profile RMSE x/H = 1 | 0.04493 | 0.04507 | 0.04508 | 0.04508 |
| U profile RMSE x/H = 4 | 0.06459 | 0.06499 | 0.06501 | 0.06502 |
| U profile RMSE x/H = 6 | 0.09314 | 0.09360 | 0.09379 | 0.09380 |
| U profile RMSE x/H = 10 | 0.09119 | 0.09185 | 0.09191 | 0.09188 |
| Signed Cf RMSE | 4.172e-4 | 3.918e-4 | 3.927e-4 | 3.929e-4 |
| Reattachment x/H | 6.7064 | 6.6788 | 6.6811 | 6.6805 |

Between stages 2 and 3 the reattachment length moved by 0.0006 H and the profile
errors by at most 3e-5.

## Two-grid comparison

Not assessed: it requires both final numerical assessments and independent
audits to pass. When assessed, velocity samples are paired by station, sample ID
and physical y/H, and Cf is compared at common positive measured x/H positions
without extrapolation. `mesh_sensitivity.passed` means both grids pass the
original gates, not that their difference is below a threshold. Two grids do not
give a GCI.

## Integrity

Every checkpoint passed: the copied source had the manifest the plan froze;
each stage's receipt bound its parent's manifest, final time, fields, mesh,
runtime and cumulative fine work; every archive kept the manifest of its first
checkpoint; each sealed summary stated what its run returned; and the producing
files kept the hashes the plan froze. The CI step zipped the complete campaign
directory, including empty directories, and rejected symlinks.

## Reproduce

On a runner with the pinned Foundation-13 runtime, dispatch the CI workflow with
`external=refinement`, or run:

```sh
python validation/backstep_data.py --output runs/measurements
python tutorials/backstep_resolution.py --preset smoke --iterations 20000 \
  --timeout-s 3500 --data runs/measurements --foam-root ROOT \
  --output runs/resolution-study
python validation/refinement_campaign.py \
  --source runs/resolution-study/wall-resolved-simplec-level1 \
  --iterations 4000 --max-stages 3 --timeout-s 3500 --preparation-s 900 \
  --data runs/measurements --foam-root ROOT --output runs/refinement-campaign
```

Exit code 2 means a completed campaign with unaccepted evidence, as here.

## Earlier executions

These preceded the declared campaign. None supplied a source for it.

- **Reduced run (workflow check).** Two stages of 400 iterations, 450 s per
  solve and 180 s preparation, on a cloud machine. It reused the accepted
  level-1 archive of workflow run
  [41106074755](https://github.com/dietmarwo/CFD-craft/actions/runs/41106074755)
  (artifact 13008679534, SHA-256
  `34ff3df6f86741413aed94a4ffd5c34498de1bba8ce47f2191553d8445931322`, source
  manifest `d90c70c78997c3de30b658cea631fd873fcbad5f2f02ea8793def42750c5284a`).
  It stopped at `stage_limit` after 800 fine iterations, with Uy at 1.04e-5
  and p at 2.6e-6; all audits passed. Its limits were frozen in its report
  before it started, but the plan was changed to declare it only afterwards.
- **Runs that ended early.** A prototype was cancelled at started iteration 238
  to correct the cancellation rule. Two runs of the declared campaign on the
  same cloud machine ended at started iterations 1457 and 1193 without a
  returned solver record or seal, for unknown reasons. Their records were kept;
  nothing from them was continued.
- **Cavity proof.** A real Foundation-13 cavity campaign passes: the cold
  level-1 source converged in 696 iterations; the mapped level-2 chain took
  1356 iterations in stages of 400, 400, 400 and 156. Both grids pass their
  numerical, independent and Ghia-reference checks (maximum Ghia errors 0.00897
  and 0.00708 against 0.06), and the largest centerline change between the grids
  is 0.0075 lid-speed units. This is numerical verification, not physical
  validation.
- **Reappearing directory.** On the same cloud machine, a sealed cavity source
  later showed an empty old time directory while every file still matched its
  manifest. The archive checks rejected it; the cause is unproven. See the
  [investigation](../docs/iterations/06-archive-investigation.md). It has not
  occurred on GitHub.

## Tests

The campaign tests run in normal and optimized Python. Without the runtime they
cover limits, the source snapshot, observations, the two-grid comparison,
lineage, checkpoints, stopping, cancellation, the command line and the CI
notices. With `CFD_OPENFOAM_ROOT` set, five more tests run real cavity
campaigns, including an archive changed after sealing and a reappearing empty
directory; they passed on GitHub in run
[41151500191](https://github.com/dietmarwo/CFD-craft/actions/runs/41151500191).

## Open questions

- **Another declared trial.** The stage-3 fields are retained and pass the audit.
  An accepted level-2 backstep needs a new declared campaign with more fine work,
  for example four or five stages of 4000 iterations, within the 360-minute job.
  The number must be declared before it runs; this result does not justify a
  smaller gate.
- **Mesh sensitivity.** An accepted level-2 grid gives a two-grid comparison, not
  a GCI. A third level requires chained mapping provenance, which the campaign
  does not support.
- **Other uncertainty.** Inlet and near-wall reconstruction, turbulence-model
  form and measurement uncertainty remain open. The benchmark has no passive-gas
  data.
- **Native gates.** Native canyon throughput, building-wall treatment and
  measured canyon and gas qualification are separate and unchanged.

The [guide](../integrations/REFINEMENT_CAMPAIGN.md) and the
[tutorial prompt](../tutorials/refinement-campaign-prompt.md) describe the
workflow and the meaning of its verdicts.
