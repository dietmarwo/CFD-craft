# External-backend results: iteration 02

Date: 29 October 2026. Repository base: `0bcbc8c9bae55923513c953aac7c8b7183e31605`.

The backend, raw-data ingestion and comparison workflow are implemented.
The cavity numerical comparison passes. The backstep **does not pass its
numerical gate**, and the finer meshes time out. This is preliminary experimental
comparison evidence; it does not qualify the native canyon or scalar transport.

## Verification and numerical comparison

- Native Rust baseline: 32 numerical/integrity regressions passed.
- Existing CLI: 35 tests passed normally and under `python -O`.
- External boundaries: 26 tests, including actual Foundation-13 cavity runs,
  version guards, cancellation, limits and returned-field corruption.
- Native analytic/empty-ABL suite: passed. The existing below-H ABL caveat remains.
- Ruff formatting/lint, Rust formatting and clippy: passed locally.

| Cavity comparison | Maximum error / lid speed | Gate |
|---|---:|---:|
| Native versus Ghia | 0.02754881 | 0.06 |
| OpenFOAM versus Ghia | 0.00896632 | 0.06 |
| Native versus OpenFOAM at Ghia stations | 0.03117048 | 0.06 |

The native cavity is advanced to 30 s; OpenFOAM solves the steady problem.
Ghia is a numerical reference, not an experiment. OpenFOAM uses vertical y;
the native case uses vertical z.

## Actual experimental comparison

The raw [Driver--Seegmiller/TMR measurements](https://tmbwg.github.io/turbmodels/backstep_val.html)
were downloaded and their three frozen hashes verified. Upstream x/H=-4 data
define the inlet; the 112 downstream velocity samples are evaluation data.

| x/H | Samples | RMSE U/Uref | Maximum absolute error U/Uref |
|---|---:|---:|---:|
| 1 | 28 | 0.046651 | 0.138803 |
| 4 | 28 | 0.065449 | 0.143084 |
| 6 | 28 | 0.092739 | 0.171011 |
| 10 | 28 | 0.092163 | 0.179677 |

Lower-wall Cf RMSE: **0.00049054**, at 17 measured positions, under the
project screening target of 0.001. Predicted reattachment: **6.450500 H**,
versus measured 6.26 +/-0.10 H. Its 0.190500 H error meets the
looser 0.75 H project screen but **exceeds the reported experimental uncertainty**.
Mean-U uncertainty is not supplied by the profile file. These are screening
targets, not a published certification standard.

The coarse case ends at 6000 iterations without reported nonlinear convergence.
Its final pressure initial residual is 0.00118683,
above the frozen 1e-7 gate. Stored boundary-flux imbalance is only
1.70881e-09; a good global mass budget alone cannot
make this an accepted solve. Final fields are finite and positive where required;
no turbulence-bounding message is recorded.

## Bounded mesh attempts

| Level | Cells | Execution | Last started iteration | Wall seconds | Numerically accepted |
|---|---:|---|---:|---:|---|
| 1 | 22656 | completed | 6000 | 263.10 | no |
| 2 | 90624 | timeout | 1406 | 300.07 | no |
| 3 | 203904 | timeout | 522 | 300.06 | no |

The two timeouts retain their logs and saved snapshots. A started final iteration
is not necessarily completed. Their comparisons are not evaluable at the final
iteration because that field was not written; no missing prediction is replaced
by a favorable value. There are no two accepted meshes, so mesh sensitivity and
GCI are not established. The same 300-second per-case wall budget was used.

## Reproducibility and remaining work

Foundation 13 package `20260407` (`13-441953dfbb42`), Linux x86_64, serial f64,
32-bit labels. The host allocation was eight CPU cores/eight GiB; each external
child used a 2048 MiB address-space cap. The package checksum, consumed inputs,
actual runtime libraries and execution harness identities are recorded.

After this campaign, process-group teardown and archive-version validation were
hardened. The exact campaign source snapshot is retained; generated physics
inputs and OpenFOAM runtime are unchanged. The final verifier rechecks all four
external archives and reproduces the measurement metrics. A fresh cavity run and
the final boundary tests use the hardened implementation.

Required next work is a numerically converged backstep configuration and an
accepted mesh series, followed by inlet-turbulence/model sensitivity and a
quantified uncertainty assessment. The native wall/throughput problems, measured
canyon concentrations and external passive-scalar comparison remain separate.
No general urban-model validation or Rust performance advantage is claimed.

Reproduction: [OPENFOAM.md](../integrations/OPENFOAM.md). Scientific assumptions:
[external model card](../docs/model-cards/openfoam-backend.md). The ZIP evidence
preserves complete small/cavity and coarse-backstep archives; large timeout
fields are summarized, with their original manifests retained.
