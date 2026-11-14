# Audit a wall-resolved backstep

<!-- check: openfoam -->
<!-- check: long -->
<!-- check: timeout=4000 -->

This chapter decides whether a backward-facing-step calculation may be compared with measurements at all: it runs the wall-resolved reference recipe, audits its mesh, face fluxes and near-wall resolution independently, and reads the report level by level. You need the runtime of [chapter 15](15-openfoam-first-run.md), a checkout with the validation requirements and about an hour of one CPU core.

No GPU and no MPI are needed. The experimental protocol stays frozen, and no parameter is fitted to the downstream measurements.

## Setup

Run all commands from the root of a checkout, with the runtime at `runs/openfoam13/runtime/opt/openfoam13`. Fetch the hash-checked measurements, then run the reference recipe once; the later sections read this run:

```bash
mkdir -p runs
python validation/backstep_data.py --output runs/measurements
python tutorials/backstep_resolution.py --preset smoke \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --data runs/measurements \
  --iterations 20000 --timeout-s 3500 --output runs/resolution-smoke
```

## The question

Can a backstep calculation pass three checks: the existing numerical gate (every final initial residual at most 1e-7 and the solver's own convergence report), an independent local face-flux check, and a consistent near-wall resolution check? A plausible velocity plot or a small global mass imbalance does not answer this. The legacy recipe of [chapter 16](16-compare-solvers.md) fails the first check. Only a calculation that passes all three reaches the measurement screen.

## Run the reference recipe

The setup ran the smoke preset: the `wall-resolved` mesh with the `simplec` profile at level 1, in one stage of at most 20,000 iterations and 3,500 s. Its run archive is `runs/resolution-smoke/wall-resolved-simplec-level1` and its report `runs/resolution-smoke/report.json`:

```python
import json

r = json.load(open("runs/resolution-smoke/report.json"))
print("workflow completed:", r["workflow_completed"], "passed:", r["passed"])
for row in r["rows"]:
    print(
        row["name"],
        "accepted:",
        row["accepted"],
        "passed:",
        row["passed"],
        "stop:",
        row.get("continuation_stop_reason"),
    )
print("physical qualification:", r["physical_qualification"])
```

The tutorial exits 0 when every requested case was accepted and passed its screen, and 2 when it kept unaccepted evidence; then read every row's execution, error, progress and limits in `report.json`. Exit 1 means a workflow, input or runtime error, including a failure to prepare a case. A NaN or infinite value in the solver log, or a diverging continuity error, stops a solve early with `CFD-X010`. A timeout or failure has no accepted final field, so its measurement comparison is not assessed. Without `--data` the tutorial fetches the frozen measurement files itself.

In the [resolution record](../evidence/backstep-resolution.md) (the record gives no date) this run converged after 18,412 iterations, executed in 3,037.4 s of its 3,500 s budget, passed the independent audit and the measurement screen, and exited 0. Three reruns on other runners converged at the same iteration. It is one mesh: no mesh pair, no GCI, no physical qualification, and the screen's targets are broad (a predictor that ignores the step scores 0.067 at x/H = 1, inside the 0.10 target).

## Presets and budgets

| Preset | Cases | Purpose |
|---|---|---|
| `smoke` | wall-resolved / `simplec`, level 1 | The reference recipe on its coarse mesh |
| `controls` | legacy and wall-resolved meshes, each with the legacy and `simplec` profiles, level 1 | A 2 x 2 design: each pair changes only the mesh or only the pressure coupling |
| `study` | wall-resolved / `simplec`, levels 1, 2, 3 | Same-recipe sensitivity; finer levels are skipped after a coarser one is not accepted |

Each stage has its own wall-time budget covering mesh generation, solve and post-processing: `--timeout-s` (default 900 s, at most 3,600 s) and `--iterations` (default 6,000, at most 20,000). The reference recipe needs more than 6,000 iterations to be accepted, so pass the limits of the setup. The output budget is 512 MiB and the child address-space limit 2,048 MiB per stage. The `controls` preset can spend up to four times `--max-stages` stage budgets, the `study` preset three times.

## Continue in bounded stages

With `--max-stages N` (1 to 8, default 1) a completed but unaccepted stage seeds the next stage on the same mesh with its verified fields and face flux ([chapter 17](17-continuation-and-mapping.md)). The recorded staged run of the reference recipe is (`ROOT` and `VERIFIED_DATA` stand for the runtime root and a measurement directory):

```sh
python tutorials/backstep_resolution.py --preset smoke --iterations 6000 \
  --max-stages 4 --timeout-s 3500 --foam-root ROOT --data VERIFIED_DATA \
  --output runs/resolution-staged
```

Every stage is kept, as `wall-resolved-simplec-level1`, then `wall-resolved-simplec-level1-stage2` and so on. In a row, `execution` and the comparison describe the last stage, `completed_solver_iterations` and `started_iterations` count work across stages, and `continuation_stop_reason` says why the chain ended:

| Reason | Meaning |
|---|---|
| `numerically_accepted` | The stage passed the nonlinear gate; the audit and the screen still decide acceptance |
| `converged_without_numerical_acceptance` | The solver reported convergence but the gate failed; another stage would report convergence again at its first iteration |
| `stage_limit` | The last permitted stage completed without convergence |
| `execution_failed`, `execution_timeout`, `execution_cancelled`, `no_final_field` | The stage stopped without an eligible final field |
| `cancelled` | The study was canceled between stages |
| `source_ineligible: …` | The completed stage fails the source flux gate and cannot seed the next (exit 2; finer meshes are skipped) |

Other preparation, archive or I/O errors stop the workflow with exit 1. Disk use and time grow with the number of stages; there is no automatic resume across separate CI jobs. Iteration limits need a divisor between 50 and 250 for the write cadence (any multiple of 50 works), so that a stopped stage still writes a final field. In the [continuation record](../evidence/steady-continuation.md) (the record gives no date) four stages of 6,000, 6,000, 6,000 and 412 iterations reached the same converged solution as the single run, at the same cumulative iteration, with final fields about 2e-12 apart in U.

## Audit mesh, flux and y+

```bash
python validation/audit_openfoam_mesh.py \
  --run runs/resolution-smoke/wall-resolved-simplec-level1 --output runs/audit.json
```

The audit reads the archive's actual mesh, not a nominal cell count. It recomputes Cartesian cell volumes and each cell's divergence from the owner and neighbor face fluxes, because an internal flux error can cancel globally while violating local continuity. The frozen target is max abs(div(phi)) * H / U <= 1e-4. This complements the reported local continuity and boundary-flux gates; it does not replace or relax them.

For the wall-resolved mesh it also reads the first-cell distances on all four solid walls, checks them against the generated geometric-series heights, and computes y+ from the tangential stored wall traction. It requires max(y+) <= 1 on every wall and reports where the maximum lies. It supports only the bounded, conforming, axis-aligned hexahedral cases of the backend.

It exits 0 when its checks pass, 2 when they fail or the archive has no final field, and 1 for an invalid archive or output path. Its own `passed` is separate from `numerical_passed`. In the [resolution record](../evidence/backstep-resolution.md) the reference run's largest local divergence was 6.38e-11 H/U, and the largest first-cell y+ was 0.963 (on the step wall, just below the lip), both within their limits.

## Read the report

Keep five levels apart: execution, numerical acceptance, the independent continuity and wall-resolution audit, the measurement screen, and physical qualification. A wall-resolved calculation reaches the measurement screen only after both the numerical gate and the audit pass. Compare two mesh levels only when both are accepted under the same wall treatment and solver profile. Do not infer a GCI from two grids or from an incomplete series. This workflow always leaves physical qualification open (`physical_qualification.passed` is false).

## Recipes

The legacy mesh with wall functions stays the default of `openfoam_backend.py prepare`. The `wall-resolved` mesh (`--mesh-family wall-resolved`) refines the lower, upper, upstream and step walls without cell-size jumps between its blocks; SST uses k = 0, `omegaWallFunction` and zero wall eddy viscosity through `nutLowReWallFunction`. The reference `simplec` profile (`--solver-profile simplec`) uses SIMPLEC with pressure relaxation 1 and transport relaxation 0.7. The first-order `simple` profile (classic SIMPLE, relaxation 0.1, PCG pressure, zero initial interior velocity) is a stability reference, not an accuracy reference. For example:

```sh
python integrations/openfoam_backend.py prepare --case backstep --level 1 \
  --mesh-family wall-resolved --solver-profile simplec --iterations 20000 \
  --data VERIFIED_DATA --output NEW_INPUT
```

The benchmark has no scalar measurements and cannot validate gas dispersion, the native k-epsilon model or a street canyon.

## A task for an agent

> Using the pinned Foundation 13 runtime, a fresh output directory and the verified Driver and Seegmiller measurements, determine whether the wall-resolved `simplec` backstep at level 1 passes the numerical gate, the independent local face-flux audit and the all-wall y+ check. Run `tutorials/backstep_resolution.py --preset smoke` with the limits of this chapter, then `validation/audit_openfoam_mesh.py` on the returned archive.
>
> Report execution, numerical acceptance, the audit, the measurement screen and physical qualification separately, with the actual returned fields. Keep every failed or stopped stage. Do not change the protocol, fit downstream measurements, loosen a gate or promote a saved snapshot to a final result. If you continue in stages, explain the `continuation_stop_reason`. Compare mesh levels only when both are accepted, and state that two grids give no GCI.

## Next

- [Chapter 19](19-refinement-campaign.md): map the accepted level-1 result to level 2 and continue it in a bounded campaign.
- [Chapter 17](17-continuation-and-mapping.md): how continuation and mapping work.
