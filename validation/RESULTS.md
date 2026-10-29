# Development verification: 29 October 2026

Source fingerprint: dbd8957a1061f8a0f260ad306df36dc2b182697eb9ec64714ac558af139e658b.

This source release is a tested research prototype. Experimental urban validation remains blocked, and successful fine-grid canyon qualification remains open.

## Measured checks

| Check | Result |
|---|---|
| Rust numerical/integrity regressions | 18 passed, on Rust 1.99.1 and 1.88.0 |
| CLI/independent-checker boundaries | 16 passed in normal mode; 16 under Python -O |
| Clippy / formatting | Checked locally; workflow included for CI |
| Periodic shear spatial order | 1.9972 |
| Periodic shear temporal order | 2.0102 |
| 3D Gaussian transport relative L2 errors | 0.0136076, 0.00548996, 0.00304178 |
| Gaussian finest-pair observed order | 2.0525 |
| Poiseuille maximum speed error, 16 wall-normal cells | 0.00488276 m/s |
| Re=100 cavity centerline maximum difference | 0.0275488 lid-speed units |
| Independent SciPy steady transport difference | 7.29621e-08 relative L2 |
| Empty ABL maximum drift U / k / epsilon | 0.234% / 0.941% / 2.675% |
| Exact-source superposition defect | 2.16166e-16 |
| Changed-grid/inflow inverse rate error | 5.157% |
| Bounded 2% observation-noise rate error | 2.011% |
| One-million-cell allocation/one prescribed step | 483.9 MiB peak RSS; 0.717 s |

The memory probe has no pressure solve or scalar field. It is not a million-cell RANS throughput benchmark. CPU allocation was eight cores, with an 8 GiB cgroup limit on Linux x86_64.

## Final coarse canyon cases

All six passed their numerical and independent archived-field checks. Each has zero turbulence-floor events and a separately checked instantaneous scalar source/removal balance.

| Case | Accepted steps | Physical pseudo-time (s) | Momentum residual | Turbulence residual |
|---|---:|---:|---:|---:|
| canyon-wh1-wind270 | 2840 | 87.057 | 1.24e-08 | 2.55e-10 |
| canyon-wh2-wind270 | 2920 | 89.422 | 2.62e-07 | 3.17e-09 |
| canyon-wh1-wind225 | 1840 | 57.032 | 1.37e-06 | 4.55e-08 |
| schmidt-0.5 | 3160 | 80.072 | 2.42e-08 | 5.48e-10 |
| schmidt-0.9 | 2640 | 91.599 | 8e-09 | 2e-10 |
| extended-outlet | 2960 | 90.735 | 8.65e-09 | 2.26e-10 |

These intentionally coarse boxes are illustrative full-scale cases, not the exact CODASC wind tunnel. No experimental validation label is earned.

## Optimizer integration

Evaluate, BiteOpt retry and the experimental GP surrogate completed through the real application worker. Retry and GP each used 24 new CFD evaluations and one counted recheck, with zero failed evaluations.

The baseline objective was 1.86824651; selected BiteOpt and GP values were 1.8657713 and 1.67991428. Values are maximum receptor concentration divided by 1e-8 kg/m3. One small deterministic experiment does not rank optimizers.

## Open gates

The development resolution study reached 300-second budgets on grids 36x32x24 and 54x48x36 before convergence. Its failed reports are retained in the delivery evidence; no GCI or grid-independent physical result is claimed. Final coarse suites were rerun after the subsequent closed-component/provenance/steady-balance fixes.

The prototype building-wall roughness adaptation depends on cell width; an explicit physical wall parameterization is needed before refinement can isolate discretization error.

Raw CODASC files and required metadata/terms were not obtained. The experimental evaluator explicitly refuses the unfrozen protocol. A matched OpenFOAM urban run and external domain review remain future evidence.

Reproduce using the commands in README.md, then inspect actual reports rather than treating these development numbers as universal performance targets.
