# Recorded verification results

These numbers were produced by the commands given with each table, from the source fingerprint `f2286e5db2c3b5ca627409b85fca94d42e17f4469372abecf08b3794e9606644` (`cfd-craft describe`), built with rustc 1.97.0 on the machine described under Measured resources, Python 3.13, NumPy 2.5.3 and SciPy 1.18.1. Rerun the commands and read the reports rather than treating these values as targets; wall times depend on the machine.

This is a tested research prototype. Experimental urban validation is blocked by data access, and the canyon resolution study does not finish within its budgets (see the last section).

## Checks and numerical verification

| Check | Result | Command |
|---|---|---|
| Rust regressions | 32 passed (rustc 1.97 here; CI runs 1.88.0 and stable) | `cargo test --release --workspace --locked` |
| CLI, launcher and independent-checker boundaries | 35 passed, also under `python -O` | `python validation/test_cli.py` |
| Periodic shear spatial / temporal order | 1.9972 / 2.0102 | `python validation/flow_accuracy.py` |
| 3D Gaussian transport, relative L2 errors at 24, 36, 48 cells | 0.0595233, 0.0265493, 0.0136076; order 2.32 for the finest pair (gate: at least 1.8) | `python validation/run_suite.py` |
| The same at 48, 72, 96 cells | 0.0136076, 0.0054900, 0.0030418; order 2.05 | `python validation/run_suite.py --preset study` |
| Poiseuille maximum speed error, 16 wall-normal cells | 0.00488 m/s | `python validation/run_suite.py` |
| Empty ABL drift of U / k / epsilon at heights H..5H (gated) | 0.23 % / 0.94 % / 2.68 % (gates 2 % / 5 % / 5 %) | `python validation/run_suite.py` |
| Empty ABL drift below H (reported, not gated) | 4.0 % / 3.6 % / 16.2 % over 8 cells | `python validation/run_suite.py` |
| Re=100 lid cavity, maximum centerline difference from Ghia et al. | 0.0275 lid-speed units (gate 0.06) | `python validation/cavity.py` |
| Steady transport against an independent SciPy sparse solve | 6.08e-13 relative L2 | `python validation/scipy_reference.py` |
| Exact-source superposition defect | 3.9e-16 | `python tutorials/source_inference.py` |
| Bounded 2 % observation-noise rate error | 2.01 % | `python tutorials/source_inference.py` |
| Changed-inflow inverse rate error | 5.90 % | `python tutorials/source_inference.py` |
| Changed-inflow and changed-grid inverse rate error | 5.16 % | `python tutorials/source_inference.py --preset study` |

## Coarse finite-canyon cases

`python tutorials/canyon_study.py --preset sensitivity` runs the three canonical cases in cases/canyon and three variants of the W/H = 1 case. `--preset smoke` runs only the first three; their rows are identical.

All six reached a steady discrete solution, passed the independent archived-field checks and had no turbulence-floor events. The grid has 18x16x12 cells of 1 m x 1 m x 0.5 m: each building is one cell wide and two cells high, and the W/H = 1 street is one column of cells. These cases exercise the coupled flow and gas workflow; they cannot resolve a canyon vortex and support no physical claim.

| Case | Steps | Pseudo-time (s) | Momentum residual | Sensors 0-3 (µg/m³) |
|---|---:|---:|---:|---|
| canyon-wh1-wind270 | 3800 | 122.01 | 8.1e-11 | 96.5, 230.7, 97.1, 141.0 |
| canyon-wh2-wind270 | 3800 | 121.89 | 1.6e-08 | 48.0, 124.7, 47.7, 77.1 |
| canyon-wh1-wind225 | 1800 | 58.53 | 4.5e-07 | 28.5, 60.1, 93.7, 19.4 |
| schmidt-0.5 | 4200 | 110.57 | 2.5e-10 | 86.1, 189.0, 86.5, 112.0 |
| schmidt-0.9 | 3500 | 128.00 | 4.5e-11 | 103.3, 261.2, 104.0, 163.7 |
| extended-outlet | 3900 | 125.22 | 5.9e-11 | 96.5, 230.8, 97.1, 141.1 |

Steady acceptance compares three successive 100-step monitor windows, so the step counts are multiples of 100. The tracer has a molecular diffusivity of 1.5e-5 m²/s, so the turbulent Schmidt number controls the mixing: from Sc_t = 0.5 to 0.9 the sensor-1 concentration rises from 189 to 261 µg/m³.

## Measured resources

Measured on a cloud virtual machine with two cores of an Intel Xeon processor (no further model information exposed), 8 GB of memory, Linux x86_64. Peak memory is the maximum resident set size of a 30-step run (`ru_maxrss`); the estimate is `estimated_peak_mib` from `check`.

| Case | Cells | Peak memory (MiB) | Estimate (MiB) |
|---|---:|---:|---:|
| periodic tracer 24x12x12 | 3,456 | 22.5 | 29.6 |
| lid cavity 24x2x24 | 1,152 | 20.6 | 27.1 |
| empty ABL 16x4x48, four threads | 3,072 | 22.9 | 30.8 |
| canyon 18x16x12 | 3,456 | 23.5 | 29.6 |
| canyon 36x32x24 | 27,648 | 52.4 | 54.7 |
| canyon 54x48x36 | 93,312 | 87.3 | 122.8 |
| canyon 100x100x100, three steps | 1,000,000 | 851.7 | 1063.6 |

At one million cells the measured inventory is 0.89 kB (893 bytes) per cell. The three steps took 121 s of wall time, mostly on one core, including grid construction and the first pressure factorization.

The steady canyon cases on 18x16x12 take 17–63 s of wall time each when the sensitivity preset runs two two-thread solves at a time (`wall_s` in the report). Each run directory, with fields and checkpoint, holds about 1.1 MiB; the extended-outlet case holds 1.4 MiB.

## Optimizer integration

`python integrations/run_jobs.py --runner optimization-run` with optimization-run built from optimization-jobs cc6b03d. Evaluate, BiteOpt retry and the experimental GP surrogate completed through the application worker. Retry and GP each used 24 new CFD evaluations and one recheck, with no failed or cancelled evaluations.

The baseline objective was 1.8682465; the selected BiteOpt and GP values were 1.8657713 and 1.6799143. Values are the maximum receptor concentration divided by 1e-8 kg/m³. One small deterministic experiment does not rank optimizers.

## Open gates

`python tutorials/canyon_study.py --preset study` adds the W/H = 1 case on finer grids. Neither finished within its 300-second budget, so there is no grid-convergence result or GCI. The script runs two two-thread solves at a time, so on this two-core machine the two grids shared the cores; the steps reached depend on the machine:

| Grid | Cells | Steps reached | Pseudo-time reached (s) | Momentum residual |
|---|---:|---:|---:|---:|
| 36x32x24 | 27,328 fluid | 1571 | 15.20 | 4.4e-03 |
| 54x48x36 | 92,232 fluid | 304 | 1.42 | 0.14 |

The coarse grid needed about 120 s of pseudo-time to reach a steady state. The [roadmap](../docs/roadmap.md) lists the throughput work this requires.

The building-wall roughness adaptation depends on the cell width, so a refinement series also changes the wall model; an explicit physical wall parameterization is needed before refinement can isolate discretization error.

Raw CODASC files and the required metadata and terms were not obtained; validation/data-inventory.json records what was tried. The experimental evaluator refuses an unfrozen protocol. A matched OpenFOAM run and an external domain review remain future evidence.
