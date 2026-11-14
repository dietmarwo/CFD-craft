# Recorded coarse-to-fine initialization results

These results cover one-level mesh initialization of the OpenFOAM backend
([guide](../integrations/MESH_INITIALIZATION.md),
[plan](../docs/iterations/05-mesh-initialization-plan.md)). The
[continuation results](RESTART_RESULTS.md) and the
[resolution results](RESOLUTION_RESULTS.md) record the accepted level-1
backstep that the backstep starts below use as their source. Rerun the commands
and read the reports rather than treating these values as targets; wall times
depend on the machine.

## Result

A coarse result initializes the next finer level as intended, and the receipt
binds the consumed fields to it. A mapped and a cold level-2 cavity converge to
the same fields (5.1e-9 in U) and pass every declared check. On the
wall-resolved backstep the path works from the accepted level-1 solution: after
3000 level-2 iterations the mapped start's pressure residual is 1.1e-6, against
6.4e-5 for a cold start with the same limits. Neither start reached the
nonlinear gate, so there is no accepted level-2 backstep, no mesh pair, no GCI
and no physical qualification.

## Cavity: mapped against cold

`validation/mapping_equivalence.py` solves the 24x24 Re=100 cavity (level 1),
maps it to a new 48x48 case (level 2) and solves that, and solves a cold 48x48
case with the same settings. The bounds were declared before the runs.

| Check | Mapped / cold level 2 | Declared bound |
|---|---|---|
| Final numerical gate | passed / passed | both pass |
| Iterations to convergence | 1356 / 2132 | reported only |
| Maximum U difference | 5.11115e-9 m/s | <=1e-4 |
| Maximum p difference, no offset removed | 2.4529e-9 m2/s2 | <=1e-4 |
| Maximum local div(phi)*H/U, independent audit | 1.67052e-9 / 1.67193e-9 | <=1e-4 each |
| Ghia centerline error | 0.00707999 / 0.00707998 | <=0.06 each |

The source converged after 696 iterations. The run wall times, including mesh
generation, checks and postprocessing, were 0.89 s for the source, 0.65 s for
the preparation, 2.94 s for the mapped run and 4.24 s for the cold run. One run
supports no speed claim, and the source and preparation work come on top of the
mapped run's. The Ghia profile is a numerical reference: the report sets
`physical_qualification` to false.

The replay found the nearest source cell for every one of the 2304 cells, and
the actual-runtime tests check every mapped value against the coarse cell that
contains the fine cell's centre, the target boundary dictionaries against the
generated ones, and a same-mesh continuation of the mapped result.

## mapNearest on the backstep meshes

An actual-runtime test generates the wall-resolved level-1 (48896 cells) and
level-2 (195584 cells) backstep meshes with `blockMesh`, writes distinct smooth
synthetic values of U, p, k, omega and nut on level 1 and maps them with
`mapFields -consistent -mapMethod mapNearest`. Every level-2 cell takes all
five values from one level-1 cell. For 185984 cells that is the cell with the
nearest centre; for the other 9600 it is another nearby cell, at most the
fourth nearest and at most 1.16 times as far as the nearest centre. The replay
accepts any of the 27 nearest cells, in every field at once, and records these
counts; 27 was set before these statistics were known. The fields are
synthetic: this is a check of the utility and of the replay, not a turbulent
solve.

## Backstep level 2: mapped and cold starts

`validation/mapped_start.py` started level 2 (195584 cells) of the
wall-resolved `simplec` recipe twice, with the same iteration limit (3000),
budget (3500 s, 1024 MiB output) and runner: once mapped from the accepted
single level-1 run (18412 iterations), once cold. It is a report: no gate was
declared, and neither run is numerically accepted, so the measurement screen is
not assessed. The metrics describe each final iterate only.

| Quantity after 3000 iterations | Mapped start | Cold start |
|---|---:|---:|
| Execution | completed, not converged | completed, not converged |
| Final initial residual p / Ux / Uy | 1.06e-6 / 3.6e-7 / 1.1e-5 | 6.4e-5 / 5.4e-5 / 6.8e-4 |
| Final initial residual k / omega | 1.0e-6 / 2.2e-9 | 1.7e-4 / 5.9e-8 |
| p residual median, last / previous tenth | 1.10e-6 / 1.14e-6 | 6.8e-5 / 8.9e-5 |
| Independent audit | passed | passed |
| Max abs(div(phi))*H/U | 1.3e-8 | 5.4e-6 |
| Max y+ lower / upstream / upper / step | 0.25 / 0.47 / 0.34 / 0.52 | 0.29 / 0.49 / 0.33 / 0.53 |
| Reattachment, final iterate | 6.686 H | 5.579 H |
| Cf RMSE, final iterate | 3.9e-4 | 4.9e-4 |
| Profile RMSE at x/H=1 / 4 / 6 / 10, final iterate | 0.045 / 0.065 / 0.094 / 0.091 | 0.038 / 0.038 / 0.034 / 0.049 |
| Run wall time | 2201.7 s | 2111.2 s |

Preparation took 38.5 s and the source run 3161.4 s; those are additional to the
mapped start. The replay statistics of the real fields equal those of the
synthetic fields above (185984 nearest, 9600 other nearby cells, rank at most
4), as expected, since the addressing depends on the meshes only. All maximum y+
values are about half the level-1 values, as the wall spacing halves.

The mapped iterate is still close to the level-1 solution (reattachment 6.686 H
against 6.706 H) and its pressure residual falls slowly, by 4% over the last
tenth of the run, so these numbers do not predict the converged level-2 answer
or when it is reached. The cold iterate is far from converged; its closer
profile errors carry no weight.

## Earlier evidence

The cavity comparison also ran on a cloud machine (AMD EPYC, eight-core quota,
Python 3.12.14) with the same runtime and an earlier revision of the mapping
code without the replay. It gave the same iterations, differences, local
continuity and Ghia errors to all digits shown above. One earlier run of the
same experiment there was rejected when its archives were verified (CFD-X006
`archive.progress`): a time directory that the solver had removed was present
again after the archive was sealed, although the manifests list only the
initial and final times. No archive was resealed to accept it; the
[continuation results](RESTART_RESULTS.md) record a similar occurrence on that
machine. It has not occurred in any GitHub run. The archives are not part of
the repository.

## Implementation and machine

The GitHub runs used OpenFOAM Foundation 13 package `20260407` (build
`13-441953dfbb42`, serial, f64, 32-bit labels) with Python 3.12 on GitHub-hosted
ubuntu-24.04 runners with four cores: an AMD EPYC 9V45 for the tests and the
cavity experiment, and an Intel Xeon Platinum 8370C for the level-1 solve and
the level-2 starts. The implementation files had these SHA-256 identities:

| File | SHA-256 |
|---|---|
| integrations/openfoam_mapping.py | `b2360565ff3fbbecfb01490763d8e888e704410bf4d48c7e1f708b2ddc78fadb` |
| integrations/openfoam_backend.py | `1f733f86f08acfe5d87b514678c67ec718ce7b72cb3019779ded7405a7c91969` |
| integrations/openfoam_restart.py | `202d4605ca82f4625b5bd24b49af046de64ff534c0d7597f566862d9abe31a35` |
| integrations/openfoam_cases.py | `f0e79c2e8054884c56e38e740b8dcc5708134fb44fbbe379ca6ed22ec6a38860` |
| validation/mapping_equivalence.py | `f017ef254219d9ba497b0a41c9a9ba53d22c23ea1c909e8df10aa24c6eeabd76` |
| validation/mapped_start.py | `689cc37f98227be8fad1a0a9f6cfb4a961fdec652c9f0a8a750e08839baea1d3` |
| validation/audit_openfoam_mesh.py | `9274c2151328ea0fbde8b083eb184b4d2b36767f4d5d514907735678b0d77cd1` |
| validation/compare_restart.py | `a183c4876c24ee11017cb9e1ed2b9903ab79af5b3d57a2d00e69857fa1cd295b` |
| validation/compare_backstep.py | `5141c2e7e9b22850e6a7143dab21dcb28002c527740257c1097c569e0d9a4a3e` |
| tutorials/backstep_resolution.py | `97fd503e8f54102cf2936a8cefdd673e90f6e26fd93eb966061537c5a1d93fe5` |

## Software verification

At the recorded implementation, in CI with the pinned runtime and locally
without it:

- Rust formatting, Clippy with warnings denied and the 32 release tests pass on
  stable Rust and on 1.88.0.
- Ruff formatting and lint checks pass.
- The 35 native CLI, 38 external-backend, 41 resolution, 54 continuation and 58
  mapping tests pass in normal and optimized Python. Eight mapping tests need
  the runtime: the cavity's nearest cells and boundaries, a mapped run that
  converges and is continued on its mesh, occupied outputs and unaccepted
  sources, a source-copy race, deadline and cancellation, runtime and rebuilt
  mesh mismatches that stop before the solve, and the backstep mapping check
  above. The others use real-format square meshes with distinct values,
  stand-ins for the utilities and mocked runs; they change each receipt,
  evidence and preparation check in turn, resealed consistently.
- Each of 72 disabled `require` checks of `openfoam_mapping.py`, one at a time,
  and each of 24 further deliberate reversions (the replay, the receipt values,
  the field reader, the failure record, the drivers) makes at least one test
  fail.

## Reproduce

~~~sh
python integrations/install_openfoam13.py --output runs/openfoam13
CFD_OPENFOAM_ROOT="$PWD/runs/openfoam13/runtime/opt/openfoam13" \
  python validation/test_mapping.py -v
python validation/mapping_equivalence.py \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --timeout-s 180 \
  --output runs/mapping-cavity
python validation/backstep_data.py --output runs/measurements
python tutorials/backstep_resolution.py --preset smoke --iterations 20000 \
  --timeout-s 3500 --data runs/measurements \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --output runs/resolution-study
python validation/mapped_start.py \
  --source runs/resolution-study/wall-resolved-simplec-level1 --iterations 3000 \
  --timeout-s 3500 --data runs/measurements \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --output runs/mapped-start
~~~

The `external-backend` job of the CI workflow runs the tests and the cavity
experiment; the `external-resolution` job, dispatched with `mapping` or `all`,
runs the single level-1 solve and the level-2 starts. Both publish their
numbers as notices.

## Open questions

- A level-2 campaign: stage lengths, and whether the source flux gate suits
  continuation, an open decision in the
  [continuation results](RESTART_RESULTS.md).
- Sources from a continued or mapped chain, conservative interpolation, and a
  check of the stored templates against the generator at verification (it
  needs the measurement files for the backstep).
- Restart comparisons (`compare_restart.py`) count only fine-grid work and do
  not report a mapped initialization.
- The cause of the reappearing time directory on the cloud machine.
