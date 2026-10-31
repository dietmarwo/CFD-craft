# Native/OpenFOAM gap-closing baseline

Measured 31 October 2026 on the code of `6759996` plus the profiling and sweep tools. The native numerics measured are IC(0)-PCG pressure, donor-cell momentum and SSPRK2 steps; profiling leaves their results unchanged.

## Protocol

One hosted Linux machine, AMD EPYC 9V74 80-Core Processor (full hardware/cgroup record retained), rustc 1.99.1, Python 3.12.14, Foundation-13 package 20260407. Each solve uses one thread. The container exposes 9 logical CPUs with an 8-CPU quota and 8 GiB memory limit. Runs are serial; affinity and CPU frequency are not pinned. Compilation/installation are excluded.

The accuracy sweep uses one unscored warmup and three timed repetitions per configuration, alternating backend order within each shared-grid block. Native 12² is a diagnostic block. Native has two periodic span cells; OpenFOAM has one empty span cell. The same Ghia stations and existing 0.06 screen are retained. The 0.01 development target is additional. Every row, including a separate deliberately incomplete campaign, is retained.

## Same-host accuracy and cost

| Method | Flow-plane grid | Solver median, s | Workflow median, s | Steps / outer iterations | Ghia error | All timed rows accepted |
|---|---:|---:|---:|---:|---:|---|
| native-steady | 12² | 0.3164 | 0.3825 | 630 | 0.05968212 | True |
| native-steady | 24² | 7.2419 | 7.3165 | 2010 | 0.02756134 | True |
| openfoam-steady | 24² | 0.7780 | 1.4891 | 696 | 0.00896632 | True |
| native-steady | 48² | 172.7545 | 172.8390 | 6390 | 0.01695144 | True |
| openfoam-steady | 48² | 5.8880 | 6.7908 | 2132 | 0.00707998 | True |

OpenFOAM reaches error ≤0.01 at 24². Native does not reach it on the tested 12²/24²/48² grids. Its cost at the target and the cross-backend equal-accuracy ratio are therefore unavailable. No target crossing is extrapolated. The cavity is a numerical reference, not an experimental validation of urban dispersion.

Workflow time includes preparation, a bounded child process, archive checks and centerline sampling. Native solver time is its `elapsed_s`; OpenFOAM solver time encloses `foamRun` startup, case I/O and solve. GNU-time RSS means maximum individual process RSS including waited descendants, not simultaneous aggregate memory. Complete timers, ranges, RSS, order, inputs and producer hashes accompany the report.

The original three-method comparator was also rerun:

| Method | Workflow median, s | Solver median, s | Work |
|---|---:|---:|---:|
| openfoam-steady | 1.2911 | 0.7289 | 696 |
| native-steady | 7.3597 | 7.3164 | 2010 |
| native-transient | 14.7326 | 14.6880 | 4093 |

That experiment has one warmup per method and all six method orders once. Its workflow timer has a different scope from the new sweep, so use each named experiment within its own protocol.

## Actual phase attribution

The following are medians of per-run wall-time fractions over the profiled timed controls. Pressure projection includes its linear solve/setup subphases; it is not added to those subphases again.

| Case | Pressure projection share | Momentum RHS share | Scalar transport share |
|---|---:|---:|---:|
| cavity24 | 77.92% | 19.75% | 0.00% |
| scalar27k | 0.00% | 0.00% | 62.19% |
| canyon27k | 84.34% | 10.91% | 0.70% |

One separately profiled 48² run retained 6390 steps and 1262035 pressure iterations, with assessment `steady_discrete_solution`. Its pressure-projection share was 88.34%; attempted PCG work was 1262035, and the profiler recorded 1274815 fine-operator applications, including 12780 independent true-residual checks. This one phase observation is not a repeated timing estimate.

## Instrumentation cost and exact-state checks

The merged baseline, candidate plain command and candidate profile command were run in recorded orders: one warmup per mode, five timed rounds for the cavity and two timed rounds for each fixed-work control. Every returned state was byte-identical across all three builds/modes within each case; independent field audits passed. There is no performance threshold or solver-speedup claim.

| Case | Profile/plain solver ratio, paired median | Candidate plain/baseline solver ratio, paired median | Profile/plain process ratio, paired median |
|---|---:|---:|---:|
| cavity24 | 0.9777 | 1.0313 | 0.9808 |
| scalar27k | 0.9372 | 1.1129 | 0.9995 |
| canyon27k | 1.0002 | 1.0208 | 1.0049 |

The scalar and canyon controls use fixed work and can end at their iteration limits; their independent audit is distinct from steady convergence. GNU time was unavailable on this host, so RSS is retained as null rather than estimated from other runs. Ratios above 1 mean the numerator cost more. They include timing noise and order/host effects; inspect the retained ranges. Short prescribed-flow controls are particularly sensitive to fixed process overhead. Profiling near a deadline can change the final retained step.

## Incomplete and rejected observations

A deliberate one-step native / 50-iteration OpenFOAM sweep completed with unaccepted rows and exit 2. Its numerical, independent-check and reference statuses remain separate, and no configuration is promoted into cost-at-target results. A failed-pressure test records attempted work even though no step commits.

The final sweep freezes and checks its input/producer identities before and after each row. A development campaign with a changed producer was rejected; its report is retained separately and supplies no timing claim here.

## Archives with an empty recorded time directory

In three of the four 48² OpenFOAM runs (the timed rounds, not the warmup), the summary written at sealing lists an old time directory, `250` or `500`, that holds no files; the final fields are at iteration 2132 in every run. This is the anomaly described in the [archive investigation](../docs/iterations/06-archive-investigation.md). The sweep verified each archive on the measuring host, where the directory existed. The evidence copy kept files only, so these three archives fail `openfoam_backend.py report` after restoration and verify again once the empty directories are recreated. All 72 native archives, the other 15 OpenFOAM archives and the 13 profile envelopes in the evidence verify as copied. The timing and Ghia-error results of the three runs come from their final fields and are unaffected. Use `validation/archive_evidence.py` to transfer such evidence with its directory entries.

## Next numerical iteration

Proceed to P1: a fixed linear symmetric multigrid preconditioner for the unchanged pressure equation, initially on supported unmasked grids. Retain IC(0), fine-operator/true-residual checks and independent topology/projection references. Measure setup, repeated solves, memory and accepted-workflow cost. Momentum accuracy remains a separate high-priority stage because pressure throughput alone cannot establish the missing 0.01 accuracy target.

See the [profiling guide](../docs/PROFILING.md), [iteration plan](../docs/iterations/17-gap-measurement-plan.md) and [earlier backend comparison](BACKEND_COMPARISON.md).
