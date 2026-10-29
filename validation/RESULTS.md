# Recorded verification results

These numbers were produced by the commands given with each table, from the source fingerprint `cf389faa8b2127e2e1716df0b9fc718b5f46df6e398f5500c9b942397774dc5e` (`cfd-craft describe`), built with rustc 1.97.0 on Linux x86_64 with two cores, Python 3.12, NumPy 2.5.4 and SciPy 1.18.1. Rerun the commands and read the reports rather than treating these values as targets; wall times depend on the machine.

This is a tested research prototype. Experimental urban validation is blocked by data access, and the canyon resolution study does not finish within its budgets (see the last section).

## Checks and numerical verification

| Check | Result | Command |
|---|---|---|
| Rust regressions | 30 passed (rustc 1.97 here; CI runs 1.88.0 and stable) | `cargo test --release --workspace --locked` |
| CLI, launcher and independent-checker boundaries | 34 passed, also under `python -O` | `python validation/test_cli.py` |
| Periodic shear spatial / temporal order | 1.9972 / 2.0102 | `python validation/flow_accuracy.py` |
| 3D Gaussian transport, relative L2 errors at 24, 36, 48 cells | 0.0595233, 0.0265493, 0.0136076; order 2.32 for the finest pair (gate: at least 1.8) | `python validation/run_suite.py` |
| The same at 48, 72, 96 cells | 0.0136076, 0.0054900, 0.0030418; order 2.05 | `python validation/run_suite.py --preset study` |
| Poiseuille maximum speed error, 16 wall-normal cells | 0.00488 m/s | `python validation/run_suite.py` |
| Empty ABL drift of U / k / epsilon at heights H..5H (gated) | 0.23 % / 0.94 % / 2.68 % (gates 2 % / 5 % / 5 %) | `python validation/run_suite.py` |
| Empty ABL drift below H (reported, not gated) | 4.0 % / 3.6 % / 16.2 % over 8 cells | `python validation/run_suite.py` |
| Re=100 lid cavity, maximum centerline difference from Ghia et al. | 0.0275 lid-speed units (gate 0.06) | `python validation/cavity.py` |
| Steady transport against an independent SciPy sparse solve | 7.30e-08 relative L2 | `python validation/scipy_reference.py` |
| Exact-source superposition defect | 2.2e-16 | `python tutorials/source_inference.py` |
| Bounded 2 % observation-noise rate error | 2.01 % | `python tutorials/source_inference.py` |
| Changed-inflow inverse rate error | 5.90 % | `python tutorials/source_inference.py` |
| Changed-inflow and changed-grid inverse rate error | 5.16 % | `python tutorials/source_inference.py --preset study` |

## Coarse finite-canyon cases

`python tutorials/canyon_study.py --preset sensitivity` runs the three canonical cases in cases/canyon and three variants of the W/H = 1 case. `--preset smoke` runs only the first three; their rows are identical.

All six reached a steady discrete solution, passed the independent archived-field checks and had no turbulence-floor events. The grid has 18x16x12 cells of 1 m x 1 m x 0.5 m: each building is one cell wide and two cells high, and the W/H = 1 street is one column of cells. These cases exercise the coupled flow and gas workflow; they cannot resolve a canyon vortex and support no physical claim.

| Case | Steps | Pseudo-time (s) | Momentum residual | Sensors 0-3 (µg/m³) |
|---|---:|---:|---:|---|
| canyon-wh1-wind270 | 3760 | 120.73 | 9.2e-11 | 96.5, 230.7, 97.1, 141.0 |
| canyon-wh2-wind270 | 3760 | 120.61 | 1.8e-08 | 48.0, 124.7, 47.7, 77.1 |
| canyon-wh1-wind225 | 1760 | 57.23 | 5.6e-07 | 28.5, 60.1, 93.7, 19.4 |
| schmidt-0.5 | 4120 | 108.46 | 3.1e-10 | 86.1, 189.0, 86.5, 112.0 |
| schmidt-0.9 | 3520 | 128.74 | 4.2e-11 | 103.3, 261.2, 104.0, 163.7 |
| extended-outlet | 3880 | 124.58 | 6.3e-11 | 96.5, 230.8, 97.1, 141.1 |

The tracer has a molecular diffusivity of 1.5e-5 m²/s, so the turbulent Schmidt number controls the mixing: from Sc_t = 0.5 to 0.9 the sensor-1 concentration rises from 189 to 261 µg/m³.

## Optimizer integration

`python integrations/run_jobs.py --runner optimization-run` with optimization-run built from optimization-jobs cc6b03d. Evaluate, BiteOpt retry and the experimental GP surrogate completed through the application worker. Retry and GP each used 24 new CFD evaluations and one recheck, with no failed or cancelled evaluations.

The baseline objective was 1.8682465; the selected BiteOpt and GP values were 1.8657713 and 1.6799143. Values are the maximum receptor concentration divided by 1e-8 kg/m³. One small deterministic experiment does not rank optimizers.

## Open gates

`python tutorials/canyon_study.py --preset study` adds the W/H = 1 case on finer grids. Neither finished within its 300-second budget, so there is no grid-convergence result or GCI. The script runs two two-thread solves at a time, so on this two-core machine the two grids shared the cores; the steps reached depend on the machine:

| Grid | Cells | Steps reached | Pseudo-time reached (s) | Momentum residual |
|---|---:|---:|---:|---:|
| 36x32x24 | 27,328 fluid | 1559 | 15.08 | 4.4e-03 |
| 54x48x36 | 92,232 fluid | 306 | 1.43 | 0.13 |

The coarse grid needed about 120 s of pseudo-time to reach a steady state. The [roadmap](../docs/roadmap.md) lists the throughput work this requires.

The building-wall roughness adaptation depends on the cell width, so a refinement series also changes the wall model; an explicit physical wall parameterization is needed before refinement can isolate discretization error.

Raw CODASC files and the required metadata and terms were not obtained; validation/data-inventory.json records what was tried. The experimental evaluator refuses an unfrozen protocol. A matched OpenFOAM run and an external domain review remain future evidence.
