# Roadmap

This page maps the iterations of the initial project plan to what 0.1.0 contains, and lists the next steps. The plan's illustrative case file was a draft; the schemas from `cfd-craft describe` are authoritative.

## Status by iteration

| Iteration | Plan | State in 0.1.0 |
|---|---|---|
| 0. Skeleton and contracts | Workspace, CI, schemas, coded diagnostics, describe/check/run | Done. Diagnostics carry codes and field paths ([catalog](diagnostics.md)) |
| 1. Verified flow core | Staggered grid with vertical stretching, projection with multigrid, Poiseuille, cavity, manufactured solutions | Partly. Uniform grids only; PCG with IC(0) instead of multigrid ([decisions](decisions/numerics.md)). Verified with periodic shear (spatial and temporal order), Poiseuille, Couette and the Re=100 cavity. VTK through `validation/export_vtk.py` |
| 2. Passive dispersion and the first agent loop | Bounded transport, sources, receptors, mass budget, a job prototype | Done, including a SciPy sparse reference and the optimization-jobs command launcher |
| 3. Boundary layer and street canyon | k-epsilon, rough walls, Richards–Hoxey inflow, GeoJSON footprints, grid series, CODASC | Partly. The k-epsilon package passes the empty-ABL check in H..5H. Canyon cases are boxes on coarse grids. The resolution series did not finish within its budgets, so there is no GCI. CODASC data were not obtained. No GeoJSON input yet |
| 4. Particles and vegetation | PM bins, deposition, porous vegetation | Not started |
| 5. Agent integration | Job worker, fcmaes models, experiment-craft | Partly, ahead of order: an fcmaes application worker with evaluate, BiteOpt retry and GP surrogate profiles |
| 6. Neighborhoods and annual statistics | CityGML/CityJSON, Michelstadt, wind-rose ensembles | Not started |
| 7. Measurements and inversion | Footprints, inversion, measurement operator | Partly, ahead of order: a synthetic source-inference tutorial with held-out receptors and model mismatch |
| 8. LES and acceleration | LES, GPU, LBM comparison | Not started |

## The gate that decides what comes next

Throughput is the limit. The steady canyon cost grows roughly with the sixth power of the refinement ratio: explicit diffusion and advection bound the pseudo-time step, and every step solves the pressure equation twice with about 50 CG iterations each. The 36x32x24 and 54x48x36 canyon grids did not converge within 300 seconds, so the resolution study, and with it any physical canyon claim, waits on a faster solver.

## Next steps, in order

1. **Throughput:** a multigrid preconditioner or solver for the pressure equation, semi-implicit diffusion for momentum, k-epsilon and scalars, and solving the passive scalar after the flow has converged. Each step is accepted only if the verification suite and the empty-ABL check still pass with unchanged tolerances.
2. **Near-wall consistency:** a log-consistent velocity gradient in wall-adjacent cells, so that the empty ABL also stays homogeneous below H, and a physical building-wall roughness that does not depend on the cell width.
3. **Resolution study:** the canyon at 10 or more cells per building height, a domain that meets the COST 732 clearances, and a GCI.
4. **Measured data:** CODASC or another canyon dataset with its license and metadata, a protocol frozen before evaluation, and an OpenFOAM comparison of the same case.
5. **Particles and vegetation (Iteration 4),** once a resolved canyon passes its gate.

Open questions about the target city, the instruments and the particle sizes of interest remain as in the initial plan.
