# Recorded external-backend results

These numbers were produced by the commands below. The implementation files had the SHA-256 identities listed at the end. The run used OpenFOAM Foundation 13 package `20260407` (build `13-441953dfbb42`, serial, f64, 32-bit labels) on a GitHub-hosted ubuntu-24.04 runner with four cores of an AMD EPYC 7763, using Python 3.12. The `external-backend` job of the CI workflow runs exactly these commands on manual dispatch. Rerun them and read the reports rather than treating these values as targets; wall times and the iterations reached within a time budget depend on the machine.

The cavity comparison passes. The backstep does **not** pass its numerical gate: the coarse solve stalls, and the finer meshes time out. Its measurement screen is therefore not assessed. Nothing here qualifies the native canyon model or passive-gas transport.

~~~sh
python integrations/install_openfoam13.py --output runs/openfoam13
python tutorials/external_cfd.py --preset study --timeout-s 300 \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 \
  --output runs/external-study
~~~

## Cavity: native and OpenFOAM against Ghia

Re=100. The native case advances to 30 s; OpenFOAM solves the steady equations and converged in 696 iterations. Ghia et al. is a numerical reference, not an experiment. OpenFOAM's vertical axis is y, the native one z.

| Comparison | Maximum error / lid speed | Target |
|---|---:|---:|
| Native versus Ghia | 0.0275488 | 0.06 |
| OpenFOAM versus Ghia | 0.00896632 | 0.06 |
| Native versus OpenFOAM at the Ghia stations | 0.0311705 | 0.06 |

## Backstep: OpenFOAM against Driver–Seegmiller measurements

The raw [TMR measurements](https://tmbwg.github.io/turbmodels/backstep_val.html) are fetched with frozen SHA-256 identities. The x/H=-4 profile defines the inlet; the 112 downstream velocity samples and 17 lower-wall Cf values are evaluation data. No case parameter is fitted to them.

**Numerical status, level 1 (22,656 cells):** all 6000 iterations ran in 260 s, with no convergence report. The final pressure initial residual is 1.19e-3, against the gate of 1e-7. Over the last 600 iterations its median is 1.492e-3, against 1.488e-3 over the 600 before: the solve is stalled, not slowly converging. Local continuity and the stored boundary-flux imbalance are small, but every pressure solve makes them small, so they do not show a steady solution.

The first lower-wall cell centre lies at y+ 13 (median; range 2.4–16.7) in the scored region 1 < x/H < 12. That is the buffer layer, where the k-based wall function switches.

**Metrics at the final iterate.** These describe one iterate of a stalled solve, not a solution. They carry no evidential weight, and the measurement screen is not assessed.

| x/H | Samples | RMSE U/Uref | Below y/H=2 | Maximum error | No-step predictor RMSE | Target |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 28 | 0.0467 | 0.0571 | 0.139 | 0.0675 | 0.10 |
| 4 | 28 | 0.0654 | 0.0804 | 0.143 | 0.179 | 0.10 |
| 6 | 28 | 0.0927 | 0.115 | 0.171 | 0.237 | 0.10 |
| 10 | 28 | 0.0922 | 0.113 | 0.180 | 0.322 | 0.10 |

The no-step predictor is the inlet profile above y/H=1 and zero below. At x/H=1 it scores 0.0675, inside the 0.10 target, so that target does not discriminate there. Below y/H=2, the shear layer and recovery region, the errors at x/H=6 and 10 exceed the target; the outer flow, which is easy to match, lowers the full-profile RMSE.

Lower-wall Cf RMSE is 0.000491 against a target of 0.001; Cf=0 everywhere would score 0.00145. Predicted reattachment is 6.4505 H against a measured 6.26 ± 0.10 H. The 0.19 H error is inside the 0.75 H screening target but outside the reported experimental uncertainty. The profile file supplies no mean-U uncertainty.

## Mesh levels

| Level | Cells | Execution | Iterations started in 300 s | Numerically accepted |
|---|---:|---|---:|---|
| 1 | 22,656 | completed | 6000 | no (stalled) |
| 2 | 90,624 | timeout | 1458 | no |
| 3 | 203,904 | timeout | 570 | no |

Levels 2 and 3 reached about 24 % and 10 % of their 6000 iterations; finishing them needs roughly 20 and 50 minutes of serial time. Their final iteration was not written, so they are marked not evaluable rather than given a score. With no two accepted levels there is no mesh sensitivity and no GCI.

Since refinement moves the first cell toward y+ 1–10, a converged series would also cross wall-treatment regimes. A wall-resolved or wall-function-consistent mesh is needed before the series can be interpreted.

## Earlier configurations, all failed

Before the recorded configuration, the level-1 backstep was run with four recipes. All ended without numerical acceptance:

| Recipe | Iterations | Final p residual | Outcome |
|---|---:|---:|---|
| 1 | 3000 | 6.0e-3 | gate not reached (CFD-X007) |
| 2 | 6000 | 1.25e-3 | gate not reached (CFD-X007) |
| 3, first-order momentum advection | — | — | timeout at 600 s (CFD-X004) |
| 4, the recorded configuration | 6000 | 1.19e-3 | gate not reached (CFD-X007) |

An independent earlier run of the recorded configuration on an eight-core cloud machine gave the same level-1 metrics and cavity errors to the digits shown here; levels 2 and 3 reached 1406 and 522 iterations there.

## What is needed next

The next steps are:
- a backstep configuration that converges (the stall persists across recipes; SIMPLEC with pressure relaxation 0.2 and the wall-function buffer layer are candidates to examine);
- a mesh whose near-wall treatment is consistent across levels;
- an accepted mesh series;
- inlet-turbulence and model sensitivity;
- justified screening targets.

The native wall roughness and throughput tasks, measured canyon concentrations and an external passive-scalar comparison are separate work. No general urban-model validation or Rust performance advantage is claimed.

Reproduction: [OPENFOAM.md](../integrations/OPENFOAM.md). Assumptions: [external model card](../docs/model-cards/openfoam-backend.md).

## Implementation identities (SHA-256)

| File | SHA-256 |
|---|---|
| integrations/openfoam_backend.py | `1eb6773f07e1ec8ec525eed2a1edffaeeedac4464fd82c1885c70ce68b5dec48` |
| integrations/openfoam_cases.py | `65b2758c4cec66387ae9daa832dad9aa4b893b782407fdb264441efb5c3e09c7` |
| validation/backstep_data.py | `736281b80881ffb8c3773fb54b0288245d6a92352bcd42ecd1eac376754d964d` |
| validation/compare_backstep.py | `da322ea468ed7af5c6e1b62aa44520994537c7d23f1e755f2213710f44a6b577` |
| tutorials/external_cfd.py | `63512ea458ba17d09791e80886a25f52bd54749236d4cccb0914c08a38b63a6e` |
