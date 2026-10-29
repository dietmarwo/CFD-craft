# Numerical decisions for 0.1

1. Use face-flux projection on a uniform masked grid. Build and test one operator definition before adding geometry formats or refinement blocks.
2. Use matrix-free PCG with cached IC(0). This improves the small reference cases but does not solve the fine-grid throughput problem. Multigrid remains a justified next investigation, rather than an untested capability claim.
3. Use explicit diffusion and bounded timestep selection. This is simple to verify and increasingly expensive on fine RANS grids. Semi-implicit viscous/turbulence transport is the other primary performance investigation.
4. Retain linear transport alongside MUSCL. It provides exact response matrices, reference comparisons and a simpler failure diagnosis.
5. Keep one neutral inlet/wall/turbulence combination. Its coefficient and upper-boundary choices are recorded; a change needs the empty-ABL test.
6. Keep execution artifacts separate from optimization claims. A completed command is not an inferred optimization optimum or a validated CFD result.
7. Keep generated performance failures. A change in hardware or work budget needs a new run identity and evidence.
