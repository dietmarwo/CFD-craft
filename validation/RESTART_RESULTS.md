# Recorded steady-continuation results

These results cover same-mesh steady field continuation of the OpenFOAM
backend ([guide](../integrations/STEADY_RESTART.md),
[plan](../docs/iterations/04-steady-continuation-plan.md)). The
[resolution results](RESOLUTION_RESULTS.md) record the wall-resolved reference
recipe solved in one run. Rerun the commands and read the reports rather than
treating these values as targets; wall times depend on the machine.

## Result

Continued in stages, the wall-resolved/`simplec` level-1 backstep reaches the
same converged solution as one uninterrupted run. Four stages (6000, 6000, 6000
and 412 iterations) converge after 18412 cumulative iterations, the iteration at
which the single run converges. Both pass the nonlinear gate, the independent
audit and the measurement screen, and the final fields differ by about 2e-12 in
U, far inside every preregistered bound. Short fixed-work comparisons of the
cavity and of the backstep's `simple` profile meet their equivalence bounds.
The source flux gate stops early `simplec` sources; whether that gate suits
continuation is an open decision (below). This is one coarse mesh: nothing here
is a mesh pair, a GCI or physical qualification.

## Staged solve of the wall-resolved reference

The `external-resolution` CI job ran the single control and then the staged
chain on the same runner, and compared them with `compare_restart.py --mode
converged`. The bounds were declared before either result was read.

| Quantity | Staged chain | Single run | Bound | Check |
|---|---:|---:|---|---|
| Completed iterations | 18412 (4 stages) | 18412 | within 5% | pass |
| Numerical gate, audit, screen | passed | passed | both pass | pass |
| Reattachment | 6.7063877 H | 6.7063877 H | 0.01 H | pass |
| Lower-wall Cf RMSE | 4.171678e-4 | 4.171678e-4 | 1e-5 | pass |
| Profile RMSE at x/H=1 / 4 / 6 / 10 | 0.044934662 / 0.064592104 / 0.093141628 / 0.091193745 | same | 1e-4 each | pass |
| Max y+ lower / upstream / upper / step | 0.484081 / 0.877159 / 0.658362 / 0.962831 | same | 0.01 each | pass |
| Max abs U difference | 1.94e-12 m/s | | 1e-3 | pass |
| Max abs p difference | 2.73e-13 m2/s2 | | 1e-3 | pass |
| k / omega / nut: max difference over control max | 1.9e-12 / 5.7e-15 / 1.3e-10 | | 1e-3 | pass |

The stages took 599.9, 638.8, 648.2 and 46.0 s (1933 s in total) and the single
run 1984.6 s, each against a 3500 s budget. Stages 1 to 3 ended at their
iteration limit without numerical acceptance; each then seeded the next stage,
so each passed the source flux gate. Stage 4 stopped at numerical acceptance
(`numerically_accepted`). The final p initial residual is 1.19776e-8 on both
paths. The audits give max abs(div(phi))*H/U 6.39e-11 for the chain and
6.38e-11 for the single run.

The single run reproduces the [recorded resolution
result](RESOLUTION_RESULTS.md) to all digits shown there, apart from the wall
time. A development run of the same comparison, on a runner with an AMD EPYC
7763 and an earlier source check that is not adopted (see below), gave the same
differences to all digits shown; its stages took 940.7, 969.0, 1002.5 and 70.7 s
and its single run 2982 s.

The receipt resets the local pseudo-time and the solver history, so a converged
chain is not expected to be bitwise identical to the single run; here the
largest relative difference in any cell is 3.0e-7 in p.

## Fixed-work comparisons

A fixed-work comparison continues FIRST iterations for SECOND and compares the
final fields with an uninterrupted FIRST + SECOND run of the same recipe. Its
bounds were declared before the comparisons: 1e-6 in U and p for the cavity,
1e-5 for the backstep, and 1e-5 for k/omega/nut relative to the control's
largest magnitude. Neither path needs to converge, and no measurement screen
follows from a pass.

| Case | Split | Max abs U difference | Max abs p difference | Turbulence: max difference over control max | Result |
|---|---|---:|---:|---:|---|
| cavity, real-runtime test | 400 + 200 against 600 | <1e-6 | <1e-6 | — | pass |
| backstep wall-resolved `simple`, level 1 | 250 + 250 against 500 | 1.54519e-6 m/s | 2.88676e-7 m2/s2 | 1.82e-6 (nut; k 1.10e-6, omega 1.46e-8) | pass |

The cavity test asserts the bounds and does not print the differences; the cloud
run below measured them at round-off. The backstep comparison ran twice, on
runners with four cores of an AMD EPYC 7763 and of an AMD EPYC 9V74, with the
same differences to all digits shown. The second run, with the final version of
`compare_restart.py`, also gated both final face fluxes: max abs(div(phi))*H/U
is 1.28e-11 for the continued run and 1.24e-11 for the control, against 1e-4.
The p difference is gated without removing a constant offset. The largest cell-
relative differences, reported but not gated, are 0.0136 in U and 0.0074 in p;
they lie in cells where the control's value is below 4e-4 of its largest
magnitude. Each path did 500 iterations, and neither reached the nonlinear gate.
The source, the continued stage and the control took 112.6, 114.1 and 219.7 s on
the EPYC 7763 and 100.1, 100.7 and 196.0 s on the EPYC 9V74, against 600 s
limits. These early fields are equivalence fixtures: on the cloud machine their
wall-resolution audit failed (step-wall first-cell y+ 1.41 at the end, 3.25 in
the source).

## Earlier evidence

The comparisons below ran on a cloud machine (Ubuntu 24.04.3, AMD EPYC 9V74,
eight-core quota, Python 3.12.14) with the same runtime and an earlier revision
of the receipt, the stage loop and the cadence rule, which generates the same
dictionaries for these recipes. The archives are not part of the repository.

| Comparison | Result |
|---|---|
| Cavity 400 + 200 against 600 | max U difference 1.03e-15 m/s, p 6.6e-16 m2/s2 after removing a constant offset (bounds 1e-6) |
| Cavity: restart from iteration 400 until convergence | converged after 296 more iterations, 696 in total, passing the nonlinear gate and the audit; its fields equal those of a cold run converged at 696 to 1.0e-15 in U and 2.0e-15 in p |
| Backstep `simple`, 250 + 250 against 500 | the U, k, omega and nut differences of the CI comparison above, to the digits shown; p 2.63e-7 after removing a 2.55e-8 offset; 111.8, 114.0 and 219.5 s |
| Backstep `simplec`, source at 500 iterations | rejected by the source flux gate: max abs(div(phi))*H/U 0.00483124 against 1e-4, although mean continuity is 3.56e-8 and the boundary imbalance 8.6e-9; no stage input created |
| Staged study, two 500-iteration `simplec` stages | one completed, unaccepted stage, stop at the source gate, levels 2 and 3 not started, exit 2 |

One earlier run of that staged study was found, after the workflow had sealed
its first stage, to contain an additional `case/250` time directory; its
comparison was rejected (CFD-X006 `archive.progress`). The cause is unknown.
The verifier caught it, and the archive was not resealed to accept it.

## Source eligibility: an open decision

A completed stage seeds the next only if its stored face flux passes the
auditor's local gate, max abs(div(phi))*H/U <=1e-4, as preregistered. The
evidence collected here bears on whether that gate suits its role; it has not
been changed:

- The measure follows the last pressure solve's relative tolerance. The `simple`
  profile (PCG, relative tolerance 0) scores 1.5e-11 at iteration 250; the
  reference `simplec` profile (GAMG, relative tolerance 1e-3) scores 0.0048 at
  iteration 500, 2.7e-9 at 6000 and 6.6e-10 at 10000. The cold start every run
  begins from scores 5.6.
- It tightens like H/dx with refinement, which is where continuation is needed.
- An uninterrupted run continues from exactly the state the gate rejects.
- A development run on GitHub, with a scale-free source check (net cell flux
  over U_ref*dz*sqrt(dx*dy) <=1e-2) in place of the gate, continued the
  rejected 500-iteration `simplec` source for 500 iterations. Against the
  uninterrupted 1000 iterations the fields differ by 7.25e-5 in U, 3.36e-5 in p
  and up to 4.2e-4 of the largest nut, beyond the 1e-5 equivalence bounds.
  Early `simplec` restarts therefore perturb the trajectory more than `simple`
  ones, although converged staged solves agree with the single run.
- That scale-free check is a plausibility check, not an integrity check: an
  all-zero or uniformly scaled phi passes, and so do about a quarter of
  single-face sign flips on low-flux faces of the 500-iteration source.

## Implementation and machine

The CI runs used OpenFOAM Foundation 13 package `20260407` (build
`13-441953dfbb42`, serial, f64, 32-bit labels) with Python 3.12 on GitHub-hosted
ubuntu-24.04 runners with four cores: an AMD EPYC 9V45 for the staged chain
and its single-run control, which ran one after the other in the same job, and
an AMD EPYC 7763 and an AMD EPYC 9V74 for the two fixed-work runs. The
implementation files had these SHA-256 identities:

| File | SHA-256 |
|---|---|
| integrations/openfoam_restart.py | `97d4ef6bfbf1a19b674c5b7ff04fce1e27daafb16e0006aa36904d001b4febb6` |
| integrations/openfoam_backend.py | `5c75ea48aae2fd8ffb7339182c918c10ea0c8da4f310a666b8fdef3c03e1ec98` |
| integrations/openfoam_cases.py | `f0e79c2e8054884c56e38e740b8dcc5708134fb44fbbe379ca6ed22ec6a38860` |
| tutorials/backstep_resolution.py | `97fd503e8f54102cf2936a8cefdd673e90f6e26fd93eb966061537c5a1d93fe5` |
| validation/compare_restart.py | `a183c4876c24ee11017cb9e1ed2b9903ab79af5b3d57a2d00e69857fa1cd295b`; the converged comparison and the first fixed-work run used `7e7eb7beff9dec4d007481a7da27f19e75ab78b405d2cb2ea599036a1eceb744`, which differs only by that gate and its docstring |
| validation/restart_equivalence.py | `77a282e03a11919fcaa159c00c60df791a2afaeac0e8659b79a6424ac2c7ecec` |
| validation/audit_openfoam_mesh.py | `9274c2151328ea0fbde8b083eb184b4d2b36767f4d5d514907735678b0d77cd1` |
| validation/compare_backstep.py | `5141c2e7e9b22850e6a7143dab21dcb28002c527740257c1097c569e0d9a4a3e` |
| validation/backstep_data.py | `736281b80881ffb8c3773fb54b0288245d6a92352bcd42ecd1eac376754d964d` |

## Software verification

At the recorded implementation, in CI with the pinned runtime and locally
without it:

- Rust formatting, Clippy with warnings denied and the 32 release tests pass on
  stable Rust and on 1.88.0.
- Ruff formatting and lint checks pass.
- The 35 native CLI tests, the 38 external-backend tests, the 41 resolution
  tests and the 54 continuation tests pass in normal and optimized Python. Seven
  continuation tests need the runtime and run in the `external-backend` job:
  cavity fixed-work and converged-chain comparisons, a restart to the unchanged
  numerical gate, runtime and mesh mismatches that stop before `foamRun` and
  leave a verifiable failure, and a corrupted or resealed bad-flux source that
  is rejected before any input is created.
- Each of 51 deliberate reversions of the receipt checks, the stage loop, the
  cadence rule and the comparison tools, and of two more of the fixed-work flux
  gate, makes at least one continuation test fail.

## Reproduce

~~~sh
python integrations/install_openfoam13.py --output runs/openfoam13
python validation/backstep_data.py --output runs/measurements
python tutorials/backstep_resolution.py --preset smoke --iterations 20000 \
  --timeout-s 3500 --data runs/measurements \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --output runs/resolution-study
python tutorials/backstep_resolution.py --preset smoke --iterations 6000 \
  --max-stages 4 --timeout-s 3500 --data runs/measurements \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --output runs/resolution-staged
python validation/compare_restart.py --mode converged --data runs/measurements \
  --run runs/resolution-staged/wall-resolved-simplec-level1-stage4 \
  --control runs/resolution-study/wall-resolved-simplec-level1 \
  --output runs/staged-comparison.json
python validation/restart_equivalence.py --case backstep --solver-profile simple \
  --first 250 --second 250 --timeout-s 600 --data runs/measurements \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --output runs/equivalence-simple
python validation/restart_equivalence.py --case cavity --first 400 --second 200 \
  --timeout-s 60 --foam-root runs/openfoam13/runtime/opt/openfoam13 \
  --output runs/equivalence-cavity
~~~

The `external-backend` and `external-resolution` jobs of the CI workflow run
these comparisons on manual dispatch (the cavity ones as real-runtime tests in
`validation/test_restart.py`) and publish their numbers as notices. The stage
directory in the comparison command is the chain's last stage, which the study
report names.

## Open questions

- The source eligibility decision above, and stage lengths for level 2, where
  the gate is about twice as strict and a 3500 s stage holds roughly 4500
  iterations.
- Which turbulence-model state a restart does not carry in the SST backstep
  (the restarted iteration's residuals differ by about 1e-4 relative); one
  hypothesis is that nut is recomputed from k and omega at start-up.
- The cause of the extra time directory in the earlier staged study; the
  [mapping results](MAPPING_RESULTS.md) record a second occurrence.
- A fine-mesh campaign from a coarse-to-fine start (see the
  [mapping results](MAPPING_RESULTS.md)); then mesh, inlet and model
  sensitivity. Nothing here qualifies the native canyon model or passive-gas
  transport.
