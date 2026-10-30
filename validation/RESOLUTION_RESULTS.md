# Recorded wall-resolved backstep results

These results cover the wall-resolved Driver--Seegmiller backstep recipes and
the independent Cartesian audit. The [external results](EXTERNAL_RESULTS.md)
record the legacy recipe; the [plan](../docs/iterations/03-wall-resolution-plan.md)
states the targets and the [model card](../docs/model-cards/openfoam-backend.md)
the recipes. Rerun the commands and read the reports rather than treating these
values as targets: wall times and the iterations reached within a budget depend
on the machine.

## Result

The `wall-resolved`/`simplec` recipe at level 1 (48896 cells) is the first
backstep calculation here to pass the nonlinear gate: it converged after 18412
iterations, with every final initial residual <=1e-7 and the solver's own
convergence report. It passes the independent audit, so its measurement screen
is assessed, and the screen passes. This is one mesh: there is no mesh pair, no
GCI and no physical qualification, and the screening targets are broad (a
predictor that ignores the step scores 0.067 at x/H=1, inside the 0.10 target).
An earlier wall-resolved spacing, with a cell-width jump at the step plane,
diverged in every run; the legacy wall-function recipe still stalls.

## Recorded run

~~~sh
python tutorials/backstep_resolution.py --preset smoke --iterations 20000 \
  --timeout-s 3500 --data runs/external-study/measurements \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --output runs/resolution-study
~~~

The study exited 0: one requested case, accepted and passed. Execution
completed in 3037.4 s of the 3500 s budget, including mesh generation and
postprocessing. The final initial residual of p is 1.19776e-8; its median over
the last tenth of the iterations is 1.449e-8, against 2.527e-8 over the tenth
before. The development run of the same dictionaries (below) stopped at the
same iteration with the same p residual; its final Ux, Uy, k and omega residuals
are 1.00e-7, 6.0e-8, 3.6e-8 and 4.5e-11.

**Independent audit.** Maximum local divergence 6.38e-11 H/U against 1e-4
(maximum relative cell imbalance 2.4e-7). Largest first-cell y+ per wall, from
the tangential stored traction, against the limit of 1:

| Wall | Maximum y+ | Where (x/H, y/H) | Median y+ |
|---|---:|---|---:|
| step | 0.963 | 0, 0.9995: just below the lip | 0.123 |
| upstream floor | 0.877 | -0.001, 1: just before the lip | 0.799 |
| upper | 0.658 | 49.84, 9: outlet | 0.559 |
| lower | 0.484 | 49.84, 0: outlet | 0.431 |

The comparison's own estimate of the lower-wall first-cell y+ over the scored
region 1 < x/H < 12 has median 0.34 (range 0.02--0.41).

**Measurement screen** (frozen protocol; targets in the last column):

| x/H | RMSE U/Uref | Below y/H=2 | Maximum error | No-step predictor RMSE | Target |
|---|---:|---:|---:|---:|---:|
| 1 | 0.0449 | 0.0551 | 0.152 | 0.0675 | 0.10 |
| 4 | 0.0646 | 0.0793 | 0.148 | 0.179 | 0.10 |
| 6 | 0.0931 | 0.115 | 0.172 | 0.237 | 0.10 |
| 10 | 0.0912 | 0.112 | 0.178 | 0.322 | 0.10 |

Lower-wall Cf RMSE is 0.000417 against 0.001 (Cf=0 everywhere scores 0.00145).
Predicted reattachment is 6.7064 H against a measured 6.26 +/-0.10 H: the 0.45 H
error is inside the 0.75 H screening target but outside the reported
experimental uncertainty. As in the legacy record, the errors below y/H=2 at
x/H=6 and 10 exceed 0.10; the outer flow lowers the full-profile RMSE. The
stalled legacy iterate reattaches at 6.45 H; its metrics carry no weight.

## Development runs on the same dictionaries

Before the recorded run, the three solver profiles ran on the wall-resolved
level-1 mesh with the same backend (`openfoam_backend.py` as below) and
byte-identical generated dictionaries, each on a GitHub-hosted ubuntu-24.04
runner with four cores (CPU model in the table). Their audits used an earlier
revision of the auditor with the same continuity and y+ computations. They are
development evidence, not the record.

| Profile | Iterations | Wall time | Runner CPU | Final initial residuals p / Ux / k | Audit: max div(phi)*H/U; max y+ lower / upstream / upper / step | Reattachment | Cf RMSE | Profile RMSE at x/H=1 / 4 / 6 / 10 |
|---|---:|---:|---|---|---|---:|---:|---|
| legacy | 6000 | 509 s | AMD EPYC 9V45 | 2.07e-4 / 2.34e-5 / 2.90e-5 | 3.4e-7; 0.48 / 0.88 / 0.64 / 0.96 | 6.775 H | 4.17e-4 | 0.045 / 0.064 / 0.095 / 0.086 |
| legacy | 20000 | 1742 s | AMD EPYC 9V45 | 6.95e-7 / 1.31e-6 / 2.44e-6 | 1.7e-9; 0.48 / 0.88 / 0.66 / 0.96 | 6.706 H | 4.18e-4 | 0.045 / 0.065 / 0.093 / 0.091 |
| simplec | 6000 | 981 s | Intel Xeon 8370C | 7.76e-7 / 5.33e-6 / 1.53e-5 | 2.7e-9; 0.48 / 0.88 / 0.66 / 0.96 | 6.706 H | 4.22e-4 | 0.045 / 0.065 / 0.093 / 0.091 |
| simplec | 18412, converged | 2979 s | AMD EPYC 7763 | 1.20e-8 / 1.00e-7 / 3.56e-8 | 6.4e-11; 0.48 / 0.88 / 0.66 / 0.96 | 6.706 H | 4.17e-4 | 0.045 / 0.065 / 0.093 / 0.091 |
| simple | 6000 | 1953 s | Intel Xeon 6973P-C | 2.12e-3 / 2.53e-5 / 4.79e-5 | 2.8e-12; 0.60 / 0.90 / 0.77 / 0.99 | 5.179 H | 9.74e-4 | 0.049 / 0.056 / 0.085 / 0.152 |

The long SIMPLEC run is the only one that reached the nonlinear gate: every
final initial residual <=1e-7, with the solver's own convergence report, at
iteration 18412. Its independent audit and measurement screen passed. The other
runs stopped at their iteration limit; their screens are not assessed and their
metrics describe final iterates only. No run diverged. The residual medians over
the last tenth of the iterations are below those of the tenth before for every
field, by 17--51% for the GAMG profiles; the `simple` profile's k residual fell
only 2.5%. The mean continuity error stayed below 1e-4 (legacy, simplec) and
1e-11 (simple). Between 6000 and 20000 iterations the legacy profile's
reattachment moved from 6.775 to 6.706 H, the value of the converged SIMPLEC
solution; its other metrics agree with it to one unit in the last digit shown. The
first-order `simple` profile converged slowest and its final iterate differs
most from the measurements.

The largest y+ is on the step wall, 0.96--0.99 at level 1, followed by the
upstream wall near the step lip, 0.88--0.90. Both are close to the y+ <=1 gate;
their first cells halve at level 2.

## Earlier streamwise spacing

The earlier wall-resolved spacing kept the legacy upstream grading (32 cells per
level, last width 0.064 H) next to a 4.6e-4 H first downstream cell: a 140:1
width jump along the whole step plane, plus 2.4:1 jumps at x/H=1 and 12.
Foundation-13 checkMesh does not test width ratios and reported no error. All
nine level-1 runs on that spacing, eight development variants (the `simplec`
and `simple` profiles, GAMG and PCG pressure, tighter linear solves, first-order
momentum, a cold start, gradient limiting and a steeper wall grading) and a
recorded `simple` run, diverged. Their mean continuity error grew roughly
exponentially and passed 1 (in units of U_ref/H) at iterations 7 to 154, before
their last started iteration (39 to 700). Eight then logged NaN/Inf residuals;
the first, run before the NaN guard existed, timed out after 900 s. The
recorded `simple` run logged NaN/Inf at started iteration 700, after 322.10 s of
a 420 s budget; in its last saved field (iteration 500) the velocity exceeded
1e15 everywhere and the k and omega maxima lay in the last cell before the
step plane. These runs used an unspecified Ubuntu 24.04 x86_64 cloud machine.

The two spacings generate identical dictionaries apart from `blockMeshDict`.
With that single difference, the `simple` profile diverged on the earlier
spacing and stayed stable for 6000 iterations on the current one: the
streamwise spacing, whose largest defect was the step-plane jump, caused the
divergence, not the solver profile. The current guard stops such a run when its
continuity error passes 1 (CFD-X010).

## Legacy mesh, SIMPLEC control

On the legacy wall-function mesh (22656 cells), the `simplec` profile ran 6000
iterations in 277.45 s on the same unspecified cloud machine without numerical
acceptance. Its final pressure initial residual is 0.00168726, and the medians
over the last two tenths of its iterations are about 0.001758 for p, 0.000195
for k and 0.000237 for omega in both windows: the same stall as the legacy
profile ([external results](EXTERNAL_RESULTS.md)), although the pressure
relaxation changed from 0.2 to 1 and the transport relaxation from 0.5 to 0.7.
Its relative boundary-flux imbalance is 4.9021e-10 and its independent local
divergence 3.54708e-5, below 1e-4: small mass errors do not establish
momentum/turbulence convergence. Between its saved iterations 4250 and 6000 the
largest velocity change (3.2e-3 U_ref) lies in the first cells above the
upstream floor near the inlet, a row whose k-based y+ spans 6 to 14, and 34
first cells under the upper wall cross the wall functions' switch point (about
11.5) between the two snapshots.

## Independent audit checks

Starting from an actual returned cavity archive (576 cells, converged at
iteration 696, local divergence 4.05294e-9), add 0.01 m3/s to its first internal
face flux and recompute the archive's checksums and completion marker. The
global boundary budget is unchanged and the archive verifier still passes. The
independent auditor rejects the altered field: its maximum local normalized
divergence is 57.6, against 1e-4. This deliberate synthetic corruption shows
what the local check adds; it is not a physical-validation result. The real
runtime tests repeat it on GitHub.

On the actual Foundation-13 `blockMesh` output of the wall-resolved level-1
recipe, the real runtime tests check the first-cell distance on all four walls,
the represented volume of 48.2 m3, and that every cell width equals the tested
grading model, with neighbouring widths within a factor 1.2 in x and 1.35 in y.

## Implementation and machine

The recorded run used OpenFOAM Foundation 13 package `20260407` (build
`13-441953dfbb42`, serial, f64, 32-bit labels) with Python 3.12 on a
GitHub-hosted ubuntu-24.04 runner with four cores of an AMD EPYC 7763. The
implementation files had these SHA-256 identities; the development runs used the
same `openfoam_backend.py` and generated the same dictionaries.

| File | SHA-256 |
|---|---|
| tutorials/backstep_resolution.py | `dbe4a43014df73ebb02558c232bd3c6c370dfc68a0371e6ad86211eb79e80f15` |
| integrations/openfoam_backend.py | `801f7e2a444b6212f92638b8ca1cbe0e7269485a239bf03ba948f2d15aca8d38` |
| integrations/openfoam_cases.py | `07c4b8a92f4c943f9a58846e44a506b1280bc3b921dcd667db6bab3788f4fbed` |
| validation/audit_openfoam_mesh.py | `a0b1695599bfff99f35417d9b9351e48704b6237dddb0d2e518b4d7ace12c7b7` |
| validation/compare_backstep.py | `5141c2e7e9b22850e6a7143dab21dcb28002c527740257c1097c569e0d9a4a3e` |
| validation/backstep_data.py | `736281b80881ffb8c3773fb54b0288245d6a92352bcd42ecd1eac376754d964d` |

## Software verification

At the recorded implementation, in CI with the pinned runtime and locally
without it:

- Rust formatting, Clippy with warnings denied and the 32 release tests pass.
- Ruff formatting and lint checks pass.
- The 35 native CLI tests, the 38 external-backend tests and the 41 resolution
  tests pass in normal and optimized Python. The resolution tests fail when any
  one of 30 deliberate reversions of their checks is applied (the mesh spacing,
  the log scan, the auditor's gates and readers, the tutorial's acceptance and
  error handling, the comparison's audit gate). Synthetic fixtures remain
  labeled as such; the real-runtime tests check the actual `blockMesh` output
  and a corrupted returned flux.

## Reproduce

~~~sh
python integrations/install_openfoam13.py --output runs/openfoam13
python tutorials/external_cfd.py --preset study --timeout-s 300 \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --output runs/external-study
python tutorials/backstep_resolution.py --preset smoke --iterations 20000 \
  --timeout-s 3500 --data runs/external-study/measurements \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --output runs/resolution-study
~~~

The `external-backend` job of the CI workflow runs these commands on manual
dispatch and publishes the numbers as notices. For one profile on its own:

~~~sh
python integrations/openfoam_backend.py prepare --case backstep --level 1 \
  --iterations 20000 --mesh-family wall-resolved --solver-profile legacy \
  --data runs/external-study/measurements --output runs/wall-legacy-input
python integrations/openfoam_backend.py run --case runs/wall-legacy-input \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --timeout-s 3500 \
  --memory-mib 2048 --output-mib 512 --output runs/wall-legacy
python validation/audit_openfoam_mesh.py --run runs/wall-legacy --output runs/wall-legacy-audit.json
python validation/compare_backstep.py --run runs/wall-legacy \
  --data runs/external-study/measurements --output runs/wall-legacy-comparison
~~~

The controls preset (`--preset controls`) runs the 2x2 mesh/profile design at
level 1; the cavity corruption check is
`test_returned_internal_flux_corruption_is_detected` in
`validation/test_resolution.py`, which runs when `CFD_OPENFOAM_ROOT` is set.

## Open questions

- **Mesh sensitivity.** A level-2 case has four times the cells of the
  level-1 solve, which took about 50 minutes, and more iterations would be
  expected; it is not expected to finish within the 3600 s per-case limit. A
  converged pair needs a larger budget or a start from the interpolated coarse
  solution. No GCI or mesh-independent claim is made.
- **Near-wall resolution margin.** The step wall's largest y+ (0.96) and the
  upstream wall's near the lip (0.88) are close to the y+ <=1 gate at level 1.
- **Inlet.** The inlet velocity falls linearly from the first measured point to
  zero at each wall, about 140 wall units on the lower wall, and the inlet omega
  near the walls is far below its viscous value. A composite inner-layer profile
  matched to the measured outer profile, or a developing inflow, is the next
  sensitivity to examine; the over-predicted reattachment (0.45 H, outside the
  0.10 H experimental uncertainty) may depend on it.
- **Legacy stall.** A continuous wall-function package on the legacy mesh
  (blended omegaWallFunction with nutUSpaldingWallFunction) is a one-change
  test of the buffer-layer explanation.
- **Outlet.** U, k and omega use zeroGradient at the outlet; inletOutlet would
  prevent backflow during a cold start.
- **Flux gate.** The gated measure tightens as cells shrink; the relative cell
  imbalance is reported beside it for comparison across levels.

Physical qualification stays open: inlet uncertainty, mesh sensitivity and
model-form sensitivity are separate gates, and there are no scalar
measurements. Nothing here qualifies the native canyon model.
