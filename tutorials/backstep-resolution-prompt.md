# Backstep: audit the calculation before comparing with measurements

Start from the [external backend guide](../integrations/OPENFOAM.md), the
[model card](../docs/model-cards/openfoam-backend.md) and the
[iteration 03 plan](../docs/iterations/03-wall-resolution-plan.md).

## Question and scope

Can a backstep calculation pass the existing numerical gate, an independent
local face-flux check and a consistent near-wall-resolution check? A plausible
velocity plot or a small global mass imbalance alone does not answer this.
The new recipe is experimental and has not passed numerical acceptance.

Use the pinned Foundation-13 runtime, a fresh output directory and the verified
Driver--Seegmiller measurements. No local workstation, GPU or MPI is required.
Do not change the experimental protocol or fit downstream measurements.

## Run and inspect

```sh
python tutorials/backstep_resolution.py --preset smoke --foam-root ROOT \
  --data VERIFIED_DATA --timeout-s 300 --iterations 6000 --output runs/resolution-smoke
```

Omit `--data` to fetch the frozen measurement files. Exit 2 means the study
retained unaccepted evidence; inspect `report.json` and every row's execution,
error, progress and limits. Exit 1 means a top-level workflow/input error.
A nonfinite solver log stops early with CFD-X010. A timeout/failure has no
accepted final field, so its measurement comparison is not assessed.

The presets are:

| Preset | Cases | Purpose |
|---|---|---|
| smoke | wall-resolved/simple level 1 | Bounded experimental reference, not an expected passing solve |
| controls | legacy/legacy, legacy/simplec, wall-resolved/legacy, wall-resolved/simple; all level 1 | First pair changes only the pressure/transport relaxation profile; the other cases explore different packages |
| study | wall-resolved/simple levels 1, 2, 3 | Same-recipe sensitivity; skip finer levels after a nonaccepted coarser level |

Each attempted case has its own wall-time budget, including mesh generation,
solve and postprocessing. Defaults are 900 seconds and 6000 iterations; the
public CLI limits are 3600 seconds and 20000 iterations per case. The output
budget is 512 MiB and the child address-space limit is 2048 MiB. The controls
preset can spend four case budgets. Start with smoke.

For a completed archive, independently inspect the actual mesh and stored phi:

```sh
python validation/audit_openfoam_mesh.py --run RUN --output NEW_AUDIT.json
```

This audit requires a completed final iteration field, even if that iterate
failed the numerical convergence gate. Its own `passed` is separate from
`numerical_passed`. It recomputes Cartesian volumes and cell divergence from
owner/neighbour face fluxes. An internal flux error can cancel globally while
violating local continuity. The frozen local audit target is
max(abs(div(phi)))*H/U <=1e-4. This complements the existing reported local
continuity and boundary-flux gates; it does not replace or relax them.

For the wall-resolved package the audit reads first-cell distances on all four
solid walls, checks them against the generated geometric-series heights and
computes y+ from the tangential stored wall traction. Require max(y+) <=1 on
every patch. It uses the actual Cartesian mesh, not just a nominal cell count.
It supports only the bounded conforming, axis-aligned hexahedral cases.

## Interpret the report

Keep execution, numerical acceptance, independent continuity/wall resolution,
measurement screening and physical qualification separate. The new package
can reach a measurement screen only after both numerical and independent
gates pass. Compare mesh pairs only when both levels are accepted under the
same wall and solver package. Do not infer GCI from two grids or an incomplete
series. Physical qualification is always left open by this workflow.

The legacy mesh remains the default. The experimental mesh refines the lower,
upper, upstream and step walls; SST uses k=0, omegaWallFunction and zero wall
eddy viscosity through nutLowReWallFunction. Its `simple` profile uses a zero
interior-velocity start, bounded upwind momentum, limited U/k/omega gradients,
PCG/DIC pressure, absolute pressure tolerance 1e-12, zero relative pressure
tolerance and 0.1 relaxation. This first-order, heavily damped reference has
still developed nonfinite residuals. Its implementation is not a convergence
or accuracy claim. See [iteration 03 results](../validation/RESOLUTION_RESULTS.md).

The benchmark has no scalar measurements and cannot validate gas dispersion,
the native k-epsilon model or a street canyon.
