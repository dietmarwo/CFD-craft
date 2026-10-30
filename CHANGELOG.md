# Changelog

## [Unreleased]

First version, 0.1.0, a research prototype. Experimental canyon validation and a successful fine-grid resolution study remain open gates.

### Added

- Iteration 02: bounded OpenFOAM Foundation-13 execution with hashed inputs, runtime/library identity, process-group cancellation, hard address-space and per-file limits, and independent stored boundary-flux checks.
- A cavity comparison between the native and external solvers, a frozen Driver--Seegmiller experimental screening protocol, exact raw-data identities, paired downstream profiles and signed skin-friction/reattachment metrics. These do not qualify the native canyon solver.
- A reproducible non-root installer for the tested OpenFOAM package, external execution boundary tests and an optional real-backend CI job.

- Rust flow and passive-transport library and the `cfd-craft` CLI (describe, check, preview, run, report, verify) with strict case and result schemas.
- `check` diagnostics with codes and field paths, including COST 732 domain and blockage warnings for RANS cases; a catalog in docs/diagnostics.md. Run, restart, output and `report` errors carry codes as well.
- Memory and output estimates that bound the measured peak and the written artifacts, including the monitor history and the per-receptor text; a host-memory refusal that comes before any grid allocation.
- `preview`, which checks the coarsened case and compares its solid volume and fluid topology with the original's cell mask without building the original grid.
- Masked-grid pressure projection with one gauge per closed fluid component and IC(0)-preconditioned CG, checked against an independently assembled reference on a masked grid with an outlet, a sealed pocket and a periodic axis.
- Laminar flow with moving walls, and a neutral k–epsilon package with Richards–Hoxey inflow and rough-wall functions.
- Conservative passive transport (linear upwind or MUSCL/MC with SSPRK2), point, line and volume sources, point and volume receptors, and checked restart.
- Steady acceptance over three successive 100-step monitor windows, with recomputed equation residuals and balances.
- Run archives with a manifest, a completion marker and `report` verification; an independent archived-field checker in Python.
- Analytic and reference verification (periodic shear, Gaussian transport, Poiseuille, Couette, lid cavity, a SciPy sparse reference, an empty-ABL consistency check), source inversion and finite-canyon tutorials.
- A command launcher for optimization-jobs and an optional native fcmaes simulation worker.
