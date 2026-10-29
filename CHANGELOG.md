# Changelog

## [Unreleased]

First version, 0.1.0, a research prototype. Experimental canyon validation and a successful fine-grid resolution study remain open gates.

### Added

- Rust flow and passive-transport library and the `cfd-craft` CLI (describe, check, preview, run, report, verify) with strict case and result schemas.
- `check` diagnostics with codes and field paths, including COST 732 domain and blockage warnings for RANS cases; a catalog in docs/diagnostics.md.
- Masked-grid pressure projection with one gauge per closed fluid component and IC(0)-preconditioned CG.
- Laminar flow with moving walls, and a neutral k–epsilon package with Richards–Hoxey inflow and rough-wall functions.
- Conservative passive transport (linear upwind or MUSCL/MC with SSPRK2), point, line and volume sources, point and volume receptors, and checked restart.
- Run archives with a manifest, a completion marker and `report` verification; an independent archived-field checker in Python.
- Analytic and reference verification (periodic shear, Gaussian transport, Poiseuille, Couette, lid cavity, a SciPy sparse reference, an empty-ABL consistency check), source inversion and finite-canyon tutorials.
- A command launcher for optimization-jobs and an optional native fcmaes simulation worker.
