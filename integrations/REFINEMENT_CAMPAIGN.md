# A bounded mapped refinement campaign

`validation/refinement_campaign.py` connects the existing one-level mapper to
verified same-mesh continuation and final acceptance. It retains the complete
coarse source and every returned fine stage. Read the
[plan](../docs/iterations/06-refinement-campaign-plan.md) and the
[results](../validation/REFINEMENT_RESULTS.md) before budgeting a larger run.

This is a serial CPU workflow using the separately installed, pinned Foundation
13 runtime; GPUs and MPI are not needed. The native solver, SST recipe,
restart/mapping schemas and measurement protocol are unchanged. A completed
campaign can produce scientifically unaccepted evidence.

## Run

Install the dependencies and runtime as in [OPENFOAM.md](OPENFOAM.md), explicitly
fetch the hash-checked measurements, and obtain a complete accepted cold coarse
archive. The resolution tutorial can produce that source:

```sh
mkdir -p runs
python validation/backstep_data.py --output runs/measurements
python tutorials/backstep_resolution.py --preset smoke --iterations 20000 \
  --timeout-s 3500 --data runs/measurements --foam-root ROOT \
  --output runs/coarse-reference
```

Continue only after that report passes. Before it creates its output, the
campaign verifies the source and requires its numerical acceptance, the full
independent audit and its measurement screen (for the cavity, the Ghia
reference check); it rejects unsupported inputs and an output inside the source.
The defaults are the declared campaign of three 4000-iteration stages:

```sh
python validation/refinement_campaign.py \
  --source runs/coarse-reference/wall-resolved-simplec-level1 \
  --foam-root ROOT --data runs/measurements \
  --iterations 4000 --max-stages 3 --timeout-s 3500 --preparation-s 900 \
  --output-mib 1024 --memory-mib 4096 --output runs/refinement-campaign
python validation/external_notices.py runs/refinement-campaign/report.json \
  "refinement campaign"
```

`ROOT` is the installed `runtime/opt/openfoam13` directory. A fresh output path
and an existing parent are required. Re-running never overwrites or resumes an
old campaign. Use a new path for another declared trial. For quick real-solver
verification, an accepted cold cavity archive also works, without `--data`.

Supported sources are generated cold level 1 or 2 cavity archives, and cold
`wall-resolved`/`simplec` backstep archives. The target is exactly the next level.
A mapped or continued archive cannot be used for another cross-mesh mapping.
The campaign does use its own mapped stage as the first parent of ordinary
same-mesh continuation, subject to the existing local-flux eligibility gate.

## Limits and stop reasons

`--iterations` is a per-stage maximum, 50..20000, with the existing divisor-based
write cadence. `--max-stages` is 1..8. Runtime/preparation limits must be finite
and in (0,3600] seconds; output is 1..2048 MiB per stage and child address space
256..8192 MiB. The preparation has one shared deadline for its utilities; each
execution has its own shared deadline for its child commands. Hashing, copying,
auditing and report collection add host overhead. The finite stage count also
bounds cumulative requested work and retained stage output; it is not an
aggregate CPU or filesystem quota. The retained source must fit the declared
copy budget, equal to one stage's output allowance.

The plan, source identities, limits and producer hashes are written before
mapping. Once prepared, mapping is performed only once. A stage that completes
without convergence may be continued when `prepare-restart` accepts its final
fields and phi. A completed but ineligible stage ends the trial with
`source_ineligible`; its rejection diagnostic and archive remain evidence.

The `stop_reason` is one of:

- `accepted`: the stage converged and passed the numerical, audit and
  measurement (cavity: Ghia reference) checks;
- `converged_without_numerical_acceptance`,
  `converged_without_independent_acceptance`, `measurement_screen_failed`
  (for the cavity, the Ghia reference check): converged, but a check failed;
- `execution_timeout`, `execution_failed`, `execution_cancelled`: the stage
  stopped; `no_final_field`: it completed without a final field;
- `source_ineligible`: the next stage's source failed the flux gate;
- `stage_limit`: every declared stage completed without convergence;
- `cancelled` and `workflow_error`.

Timeouts and cancelled or failed executions are never continued and an older
saved snapshot is never promoted. A cancellation overrides acceptance if it
arrives after a solver has returned, but an integrity or workflow error stays an
error after a cancellation. If the audit or the measurement comparison of a
returned stage cannot be read (for example when sampling hit the deadline),
that stage records the failure as its observation and the campaign carries on
with the stop reason of its execution. Exit 0 means the declared scientific
gates passed, 2 means retained unaccepted or cancelled evidence, and 1 means
invalid input or a campaign workflow error. `workflow_completed` describes
collection of a valid bounded trial, not its scientific acceptance.
`completed_fine_iterations` counts the iterations of stages with a final field;
`started_fine_iterations` also counts those of stopped stages.

## Evidence and integrity

The fresh directory contains:

| Path | Meaning |
|---|---|
| `report.json` | Frozen plan and hash; phase, stop reason, per-stage assessments, work and archive checkpoints |
| `source/` | Complete checked copy of the original accepted coarse archive, including its seals |
| `mapped-input/` | Generated fine boundaries and controls, mapped volume fields and independently replayed mapping evidence |
| `stage-01/`, `stage-02/`, ... | Complete returned archives, including actual consumed inputs, mesh, fields, logs, summary, manifest and completion marker |
| `stage-02-input/`, ... | Verified same-mesh initialization receipts and copied inputs |

Source bytes are checked during copying, both source and copy inventories are
checked afterwards, and the copy must have the manifest the plan froze. Every
complete parent and stage is reverified after a stage returns and at final
collection. At each of these checkpoints:

- continuation receipts must bind the retained parent's manifest, case, final
  time, fields, mesh, runtime, acceptance and cumulative fine work, and the
  first mapping must bind the retained coarse parent;
- every archive must keep the manifest it had at its first checkpoint, so the
  last stage, which no child receipt binds, cannot be resealed unnoticed;
- each stage's sealed summary must state the execution status, verdict, error
  and numerical assessment its run returned;
- the stage records and the producing files must have the implementation
  identities the plan froze.

Coarse iterations and historical coarse wall time remain separate from newly
performed fine work and campaign wall time.

An extra file or changed archive stops collection with `CFD-X015
refinement.archives.*` and the underlying diagnostic. The campaign does not
delete an extra time directory, reseal an archive or accept an earlier field to
make the result pass. The deliberate late-file test demonstrates detection and
containment. It does not establish the root cause of the anomaly seen on a
cloud machine, where a source's file hashes were unchanged but an empty old time
directory reappeared; see the
[investigation record](../docs/iterations/06-archive-investigation.md). Keep
empty directory entries when transferring or zipping a failed archive; a
file-only copy loses that evidence.

For an individual stage, use `openfoam_backend.py report STAGE` and
`audit_openfoam_mesh.py --run STAGE --output NEW_AUDIT.json`. Report-only
summaries cannot replace the retained fields. Unkeyed hashes detect
inconsistency; they do not authenticate an untrusted producer.

## Scientific meaning

Each stage retains separate execution, numerical, independent-audit and
measurement/reference verdicts. Final nonlinear residuals, explicit convergence,
reported continuity, stored boundary flux, finite/sign-valid fields, local
divergence and all-wall y+ use the existing gates. Backstep measurement screening
remains unassessed unless its numerical and independent gates pass.

Only two numerically accepted, independently audited grids enter the
`mesh_sensitivity` comparison. Velocity samples use exactly matching station,
sample-ID and physical-height identities. Backstep Cf is interpolated at the
same positive experimental x/H positions without extrapolation. Reattachment,
velocity and Cf changes are descriptive; no new inter-grid tolerance is
invented. `mesh_sensitivity.passed` means both grids pass their original
numerical, audit and measurement/reference checks. It does not mean their
differences are small or that mesh independence was established. The native
canyon's separate 5% target is not transferred to this external experiment.

Two grids do not provide a GCI. `physical_qualification` remains false even if
the original screens pass: inlet uncertainty, another refinement, model-form
sensitivity and measurement uncertainty still require work. The backstep has
no passive-gas concentration data and does not qualify the native canyon.

## Tests and manual CI

```sh
CFD_OPENFOAM_ROOT=ROOT python validation/test_refinement.py -v
CFD_OPENFOAM_ROOT=ROOT python -O validation/test_refinement.py -v
```

Without that environment variable the contract tests run and the five actual
Foundation-13 tests are skipped. Actual tests cover a converged mapped and
continued cavity, a bounded unconverged cavity, occupied output and post-seal
file and empty-time-directory corruption. Synthetic records and mocked runs
exercise every receipt, checkpoint, stop and verdict rule; they are not flow
evidence.

The manual workflow's `external=refinement` selector runs the level-1 reference
solve and then the declared campaign of three 4000-iteration stages, and
uploads `runs/refinement-campaign-evidence.zip` with the fine fields and
explicit directory entries; symlinks are rejected before serialization, and a
test runs this exact workflow step. The selector is not part of `all`.
