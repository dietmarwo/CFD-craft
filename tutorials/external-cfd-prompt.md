# Compare CFD predictions with independent evidence

Use CFD-craft's external backend and `docs/model-cards/openfoam-backend.md`.

1. Check out a named revision and build the native CLI with --locked. Stage the
   pinned Foundation-13 package with the provided installer on Ubuntu 24.04.
2. Run `external_cfd.py --preset cavity` first. Check each solver against Ghia
   and against the other solver, including the different vertical coordinates.
3. Run the smoke backstep experiment with the frozen protocol and raw-data
   hashes. Use a fresh output directory and a declared per-case wall budget.
4. Inspect every execution and numerical status before discussing measurement
   errors. Preserve failed rows. Do not increase tolerances to obtain a pass.
5. Use the study preset for mesh sensitivity only when the smoke calculation
   and resources justify it. Incomplete meshes cannot support grid convergence.
6. Report what is measured, which data define the inlet, which data are held
   out, the turbulence assumptions, and what remains unqualified. A velocity
   comparison does not validate concentrations or the native canyon solver.

Deliver the report, paired samples, runtime/input identities and figures.
Do not contact data owners, publish results or use Dietmar's home machines.
