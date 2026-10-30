# Backstep: audit the calculation before comparing with measurements

Start from the [external backend guide](../integrations/OPENFOAM.md), the
[model card](../docs/model-cards/openfoam-backend.md) and the
[wall-resolution plan](../docs/iterations/03-wall-resolution-plan.md).

## Question and scope

Can a backstep calculation pass the existing numerical gate, an independent
local face-flux check and a consistent near-wall-resolution check? A plausible
velocity plot or a small global mass imbalance alone does not answer this.
The [recorded results](../validation/RESOLUTION_RESULTS.md) say which recipe
has reached which gate.

Use the pinned Foundation-13 runtime, a fresh output directory and the verified
Driver--Seegmiller measurements. No GPU or MPI is required. Do not change the
experimental protocol or fit downstream measurements.

## Run and inspect

```sh
python tutorials/backstep_resolution.py --preset smoke --foam-root ROOT \
  --data VERIFIED_DATA --iterations 20000 --timeout-s 3500 --output runs/resolution-smoke
```

`ROOT` is the OpenFOAM root (for example `runs/openfoam13/runtime/opt/openfoam13`
after the installer) and `VERIFIED_DATA` a directory of measurements fetched by
`validation/backstep_data.py` or a previous study. Omit `--data` to fetch the
frozen measurement files. Exit 0 means every requested case was accepted and
passed its screen. Exit 2 means the study retained unaccepted evidence; inspect
`report.json` and every row's execution, error, progress and limits. Exit 1
means a workflow, input or runtime error, including a failure to prepare a case.
A NaN/Inf solver log or a diverging continuity error stops a solve early with
CFD-X010. A timeout/failure has no accepted final field, so its measurement
comparison is not assessed.

The presets are:

| Preset | Cases | Purpose |
|---|---|---|
| smoke | wall-resolved/simplec level 1 | The wall-resolved reference recipe on its coarse mesh |
| controls | legacy and wall-resolved meshes, each with the legacy and simplec profiles; all level 1 | A 2x2 design: each pair changes only the mesh or only the pressure-coupling profile |
| study | wall-resolved/simplec levels 1, 2, 3 | Same-recipe sensitivity; finer levels are skipped after a coarser level is not accepted |

Each attempted case has its own wall-time budget, covering mesh generation,
solve and postprocessing. Defaults are 900 seconds and 6000 iterations; the
CLI limits are 3600 seconds and 20000 iterations per case. Numerical acceptance
of the reference recipe needs more than 6000 iterations, so pass the limits
shown above. The output budget is 512 MiB and the child address-space limit
2048 MiB. The controls preset can spend four case budgets, the study three.

For a completed archive, independently inspect the actual mesh and stored phi:

```sh
python validation/audit_openfoam_mesh.py --run RUN --output NEW_AUDIT.json
```

It exits 0 when its checks pass, 2 when they fail or the archive has no final
field to audit, and 1 for an invalid archive or output path. Its own `passed`
is separate from `numerical_passed`. It recomputes Cartesian volumes and cell
divergence from owner/neighbour face fluxes. An internal flux error can cancel
globally while violating local continuity. The frozen local audit target is
max(abs(div(phi)))*H/U <=1e-4. This complements the existing reported local
continuity and boundary-flux gates; it does not replace or relax them.

For the wall-resolved package the audit reads first-cell distances on all four
solid walls, checks them against the generated geometric-series heights and
computes y+ from the tangential stored wall traction. It requires max(y+) <=1
on every patch and reports where the maximum lies. It uses the actual Cartesian
mesh, not just a nominal cell count, and supports only the bounded conforming,
axis-aligned hexahedral cases.

## Interpret the report

Keep execution, numerical acceptance, independent continuity/wall resolution,
measurement screening and physical qualification separate. The wall-resolved
package can reach a measurement screen only after both numerical and
independent gates pass. Compare mesh pairs only when both levels are accepted
under the same wall and solver package. Do not infer GCI from two grids or an
incomplete series. Physical qualification is always left open by this workflow.

The legacy mesh remains the default. The wall-resolved mesh refines the lower,
upper, upstream and step walls without cell-size jumps between its blocks; SST
uses k=0, omegaWallFunction and zero wall eddy viscosity through
nutLowReWallFunction. The reference `simplec` profile uses SIMPLEC with
pressure relaxation 1 and transport relaxation 0.7. The first-order `simple`
profile (classic SIMPLE, relaxation 0.1, PCG pressure, zero initial interior
velocity) remains available through `openfoam_backend.py prepare` as a
stability reference; it is not an accuracy reference.

The benchmark has no scalar measurements and cannot validate gas dispersion,
the native k-epsilon model or a street canyon.
