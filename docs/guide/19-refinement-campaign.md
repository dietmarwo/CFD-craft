# A bounded refinement campaign

<!-- check: openfoam -->
<!-- check: long -->

This chapter maps an accepted coarse backstep once to the next finer mesh, continues the fine solve in bounded stages, and reports honestly when the fine grid does not earn acceptance. You need the runtime of [chapter 15](15-openfoam-first-run.md), a checkout with the validation requirements, and several hours of one CPU core for the declared campaign; a quick cavity variant is at the end.

`validation/refinement_campaign.py` composes the one-level mapping and the same-mesh continuation of [chapter 17](17-continuation-and-mapping.md) with the unchanged final gates. It is a serial CPU workflow; GPUs and MPI are not needed. The SST recipe, the restart and mapping schemas and the measurement protocol are unchanged by it.

## Setup

Run all commands from the root of a checkout, with the runtime at `runs/openfoam13/runtime/opt/openfoam13`. Fetch the measurements and produce the coarse source with the reference recipe of [chapter 18](18-backstep-resolution.md) (about an hour):

```bash
mkdir -p runs
python validation/backstep_data.py --output runs/measurements
python tutorials/backstep_resolution.py --preset smoke --iterations 20000 \
  --timeout-s 3500 --data runs/measurements \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 \
  --output runs/coarse-reference
```

## The goal and its limits

A fine-grid result must earn acceptance: the same numerical, audit and measurement gates as the coarse one, with no gate loosened, no output resealed and no pre-failure snapshot promoted. A completed campaign can therefore produce scientifically unaccepted evidence, and that is a valid outcome.

The [refinement record](../evidence/refinement-campaign.md) of 31 October 2026 is such an outcome. All three declared stages of 4,000 iterations completed and every stage passed the independent audit (local flux and wall y+), but none passed the numerical gate: after 12,000 fine iterations the final initial residuals of Uy (1.81e-7) and k (1.05e-7) were still above 1e-7. The stop reason was `stage_limit`, the workflow completed, `passed` was false, the two-grid comparison was not assessed, and physical qualification stayed false. The residuals were still falling; whether one more stage would pass is an extrapolation the campaign does not show. More stages are not an accuracy argument.

## Produce the accepted coarse source

The setup ran the coarse reference. Continue only when its report passes:

```python
import json
r = json.load(open("runs/coarse-reference/report.json"))
if not r["passed"]:
    raise SystemExit("the coarse reference is not accepted; do not start a campaign")
print("source:", "runs/coarse-reference/" + r["rows"][0]["name"])
```

Before it creates its output, the campaign verifies the source itself and requires its numerical acceptance, the full independent audit and its measurement screen (for the cavity, the Ghia reference check). Supported sources are cold-generated level 1 or 2 cavity archives and cold `wall-resolved` / `simplec` backstep archives; the target is exactly the next level. A mapped or continued archive cannot be mapped again.

## Run the campaign

```bash
python validation/refinement_campaign.py \
  --source runs/coarse-reference/wall-resolved-simplec-level1 \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --data runs/measurements \
  --iterations 4000 --max-stages 3 --timeout-s 3500 --preparation-s 900 \
  --output-mib 1024 --memory-mib 4096 --output runs/refinement-campaign || echo "exit $?"
python validation/external_notices.py runs/refinement-campaign/report.json \
  "refinement campaign"
```

These are the declared campaign of three 4,000-iteration stages, also the script's defaults. The output path must be new, its parent must exist, and it may not lie inside the source; a rerun never overwrites or resumes an old campaign, so use a new path for another declared trial. The notices summarize the report: one for the campaign, one per stage and one for the implementation identities. GitHub keeps 4,096 characters of an annotation, so a longer notice is split at line ends into numbered parts.

```python
import json
r = json.load(open("runs/refinement-campaign/report.json"))
print("workflow completed:", r["workflow_completed"], "passed:", r["passed"])
print("stop reason:", r["stop_reason"])
print("fine iterations completed / started:",
      r["completed_fine_iterations"], r["started_fine_iterations"])
print("coarse source iterations (separate):", r["source_iterations"])
print("physical qualification:", r["physical_qualification"])
```

## Limits and stop reasons

`--iterations` is a per-stage maximum from 50 to 20,000, with the divisor-based write cadence of chapter 17. `--max-stages` is 1 to 8. The time limits `--timeout-s` and `--preparation-s` must lie in (0, 3600] seconds; output is 1 to 2,048 MiB per stage and the child address space 256 to 8,192 MiB. The preparation has one shared deadline for its utilities; each execution has its own deadline for its child commands. Hashing, copying, auditing and collection add host overhead. The stage count bounds cumulative requested work and retained output; it is not a CPU or file-system quota. The copied source must fit one stage's output allowance.

The plan, source identities, limits and producer hashes are written before mapping, and mapping is performed once. A stage that completes without convergence is continued only when `prepare-restart` accepts its final fields and face flux. `stop_reason` is one of:

| Value | Meaning |
|---|---|
| `accepted` | The stage converged and passed the numerical, audit and measurement (cavity: Ghia reference) checks |
| `converged_without_numerical_acceptance`, `converged_without_independent_acceptance`, `measurement_screen_failed` | Converged, but a check failed |
| `execution_timeout`, `execution_failed`, `execution_cancelled` | The stage stopped |
| `no_final_field` | It completed without a final field |
| `source_ineligible` | The next stage's source failed the flux gate; its diagnostic and archive remain evidence |
| `stage_limit` | Every declared stage completed without convergence |
| `cancelled`, `workflow_error` | The campaign was cancelled, or hit a workflow error |

Timeouts and cancelled or failed executions are never continued. A cancellation overrides acceptance if it arrives after a solver returned, but an integrity or workflow error stays an error after a cancellation. If the audit or the measurement comparison of a returned stage cannot be read (for example when sampling hit the deadline), the stage records that failure and the campaign continues with the stop reason of its execution.

The script exits 0 when the declared scientific gates passed, 2 for retained unaccepted or cancelled evidence, and 1 for invalid input or a workflow error. `workflow_completed` describes the collection of a valid bounded trial, not its acceptance. `completed_fine_iterations` counts stages with a final field; `started_fine_iterations` also counts stopped ones.

## The evidence directory

| Path | Content |
|---|---|
| `report.json` | The frozen plan and its hash; phase, stop reason, per-stage assessments, work and archive checkpoints |
| `source/` | A complete checked copy of the accepted coarse archive, with its seals |
| `mapped-input/` | Generated fine boundaries and controls, mapped volume fields and the replayed mapping evidence |
| `stage-01/`, `stage-02/`, … | Complete returned archives: consumed inputs, mesh, fields, logs, summary, manifest, completion marker |
| `stage-02-input/`, … | Verified same-mesh initialization receipts and copied inputs |

For one stage use `python integrations/openfoam_backend.py report STAGE` and `python validation/audit_openfoam_mesh.py --run STAGE --output NEW_AUDIT.json`. A summary alone cannot replace the retained fields. Coarse iterations and historical coarse wall time stay separate from the new fine work and the campaign wall time.

## Integrity checkpoints

Source bytes are checked during copying, both inventories afterwards, and the copy must have the manifest the plan froze. Every complete parent and stage is verified again after each stage returns and at final collection. At each of these checkpoints:

- continuation receipts must bind the retained parent's manifest, case, final time, fields, mesh, runtime, acceptance and cumulative fine work, and the first mapping must bind the retained coarse parent;
- every archive must keep the manifest it had at its first checkpoint, so the last stage, which no child receipt binds, cannot be resealed unnoticed;
- each stage's sealed summary must state the execution status, verdict, error and numerical assessment its run returned;
- the stage records and producing files must have the implementation identities the plan froze.

An extra file or a changed archive stops collection with `CFD-X015` at `refinement.archives.*` and the underlying diagnostic. The campaign does not delete an extra time directory, reseal an archive or accept an earlier field to make the result pass. Unkeyed hashes detect inconsistency; they do not authenticate an untrusted producer.

An OpenFOAM time directory can be empty and still be part of the evidence (see the [archive investigation](../history/06-archive-investigation.md), which did not establish the root cause of such a directory reappearing on a cloud machine). Keep empty directory entries when you copy or zip a campaign; a file-only copy loses them, and the copy then fails verification.

## What the verdicts mean

Each stage keeps separate execution, numerical, independent-audit and measurement verdicts. Backstep measurement screening stays unassessed unless the numerical and independent gates pass.

Only two numerically accepted, independently audited grids enter `mesh_sensitivity`. Velocity samples are paired by exactly matching station, sample ID and physical height; skin friction is interpolated at the same experimental x/H positions without extrapolation. Changes of reattachment length, velocity and skin friction are descriptive; no new inter-grid tolerance is invented. `mesh_sensitivity.passed` means both grids pass their original checks. It does not mean their differences are small or that mesh independence was shown.

Two grids do not give a GCI. `physical_qualification` stays false even when every screen passes: inlet uncertainty, another refinement, model-form sensitivity and measurement uncertainty still need work. The backstep has no passive-gas data and does not qualify the native canyon.

## A quick exercise with the cavity

An accepted cold cavity works as a source without `--data`, and stages of 400 iterations (up to four) are enough for a quick real-solver check. Its Ghia reference is numerical, not experimental:

```sh
python integrations/openfoam_backend.py prepare --case cavity --level 1 \
  --iterations 3000 --output runs/foam-cavity-input
python integrations/openfoam_backend.py run --case runs/foam-cavity-input \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 \
  --timeout-s 180 --output runs/foam-cavity
python validation/refinement_campaign.py --source runs/foam-cavity \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 \
  --iterations 400 --max-stages 4 \
  --output runs/cavity-campaign
```

## Tests and the hosted run

```sh
CFD_OPENFOAM_ROOT=ROOT python validation/test_refinement.py -v
CFD_OPENFOAM_ROOT=ROOT python -O validation/test_refinement.py -v
```

Without `CFD_OPENFOAM_ROOT` the contract tests run and the five real-solver tests are skipped. The real tests cover a converged mapped and continued cavity, a bounded unconverged cavity, an occupied output, and post-seal file and empty-time-directory corruption. Synthetic records and mocked runs exercise every receipt, checkpoint, stop and verdict rule; they are not flow evidence.

The manual CI selection `external=refinement` (not part of `all`) runs the level-1 reference solve and then the declared campaign, and uploads `runs/refinement-campaign-evidence.zip` with the fine fields and explicit directory entries; symbolic links are rejected before the zip is written.

## A task for an agent

> Inspect a complete accepted cold level-1 wall-resolved SIMPLEC backstep archive. Verify its seals, actual returned fields, independent local-flux and all-wall y+ audit, measurement screen and exact runtime. Freeze a new trial before execution: target level 2, at most three stages of 4000 iterations, 3500 seconds per execution, preparation deadline 900 seconds, 1024 MiB output per stage and 4096 MiB child address space. Use the campaign driver in a fresh directory. Map once and continue only eligible completed fine stages.
>
> Keep every returned stage and the complete source. Report the final stage's iterations, cumulative completed fine iterations and the coarse source's historical work separately. Preserve numerical failures, stopped executions, source rejection and archive mismatches. Never loosen a gate, reseal changed output or use a pre-failure snapshot. Explain the actual stopping reason.
>
> If both grids pass the numerical and independent gates, compare their observables at the same physical sample identities. State their original measurement verdicts and the size of the grid changes. If either grid is not accepted, state that mesh sensitivity was not assessed. Two grids provide neither a GCI nor physical qualification. Describe the remaining inlet, refinement and model-form work. GPU and MPI work is out of scope.

The finished report must answer:

1. Which source bytes, producer code and runtime were actually consumed?
2. Which stage first met each gate, and what work was performed on each mesh?
3. Did the final source, parent and archive checks still pass at collection?
4. Which comparisons are assessed, and what does each `passed` field mean?
5. Which remaining scientific question can the next bounded trial resolve?

## Next

- [Chapter 20](20-rust-library.md): call the native solver in process from Rust.
- The [refinement record](../evidence/refinement-campaign.md): the declared backstep campaign, stage by stage.
