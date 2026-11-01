# Implicit steady iteration with RANS and constituents (stages P5c and P5d): results

Date: 1 November 2026. Plan and predeclared gates:
[accuracy and steady-solver plan](../docs/ACCURACY_STEADY_PLAN.md), stages P5c
and P5d. Method: [flow model card](../docs/model-cards/flow.md) ("Steady
pseudo-time algorithms" and "Neutral turbulence package") and
[transport model card](../docs/model-cards/transport.md). Campaign script:
`validation/steady_algorithms.py --case canyon`.

All measurements: one solver thread on a 2-vCPU Intel Xeon VM (2.1 GHz) that
also ran other work, so timings are approximate. The P5c/P5d code is commit
`2ffedec`; the recipe rows at the end use the performance iterations
(`validation/PERFORMANCE_ITERATIONS_RESULTS.md`).

## Summary

| Stage | Gate | Result |
|---|---|---|
| P5c | same fixed point as the explicit mode on the development canyon, with the tightening test (mode differences of U, k and ε shrink ≥ 5× per decade) | **failed for U on the second decade** (2.9×); k and ε pass; the round-off pair agrees to 1.5e-10 |
| P5c | empty-ABL check with unchanged gates (2% U, 5% k and ε in H..5H) | pass, in steady mode: drifts 0.26% / 0.81% / 3.44%, equal to the explicit steady run's |
| P5c | zero floor events | pass in every run |
| P5c | canyon 27k and 93k accepted | pass |
| P5c | model card updated | done |
| P5d | mass budget, negative mass, positivity | pass: relative budget defects ≤ 3.1e-13, no negative mass |
| P5d | unit normalization and superposition | pass: doubling the emission doubles every concentration to 1e-12 (Rust test, both implicit algorithms) |
| P5d | steady mass balance, receptors | pass: receptors equal the explicit mode's to 2.2e-7 (development canyon) and 5e-7 (27k) |
| P5d | refinement | the discrete steady state is the explicit mode's at every grid; the canyon itself is not grid-converged (below) |

## Fixed point (P5c)

The development canyon (`cases/canyon/wh1-wind270.json`, 18×16×12, open sides,
`ground_open_top`) without its tracer, explicit and `implicit_projection`, at
the case tolerances (steady residual 1e-5, monitor 1e-3) and with both
tightened 10× and 100×. Differences are maxima over the field, relative to the
explicit field's maximum. "To reference" is each run's distance to the
round-off explicit solution (reported, not gated).

| Tightening | Steps explicit / implicit | Solver s | U difference | k difference | ε difference | To reference, U: explicit / implicit |
|---|---|---|---:|---:|---:|---|
| 1 | 1000 / 500 | 11.8 / 4.0 | 1.69e-5 | 3.40e-5 | 3.47e-5 | 1.7e-5 / 1.4e-6 |
| 10 | 1200 / 500 | 14.1 / 4.0 | 2.10e-6 | 4.74e-6 | 3.24e-6 | 3.4e-6 / 1.4e-6 |
| 100 | 1400 / 700 | 15.2 / 5.2 | 7.28e-7 | 7.17e-7 | 5.22e-7 | 9.0e-7 / 1.7e-7 |

Shrink per decade: U 8.1 and **2.9**, k 7.2 and 6.6, ε 10.7 and 6.2. The U gate
fails on the second decade and is recorded as failed. The last column shows
why: at 100× the mode difference is the explicit run's own distance to the
converged solution (9.0e-7), while the implicit run is five times closer.

Round-off pair: the turbulence-residual probe of `assess` has a floor near
1.8e-10 on this case in both modes (it differences k over one 1e-6-scaled
explicit step), so the cavity's 1e-11 tolerance is unreachable; the campaign
uses 1e-9 for the residual and the monitor. Explicit 2,600 steps (31.1 s),
implicit 1,000 (7.5 s); differences U 1.5e-10, k 1.0e-10, ε 6.1e-11. A separate
pair run to the iteration limit (residual tolerance 1e-11, 140,642 explicit and
200,000 implicit steps, momentum residuals 3.2e-15 and 8.6e-16, both stopped by
the same 1.805e-10 turbulence floor) differs by 1.2e-14 (U), 7.3e-15 (k) and
9.8e-15 (ε): the two modes have the same fixed point.

## Empty ABL (P5c)

The empty-ABL check is transient in `run_suite.py`; the implicit algorithms run
in steady mode only, so the check ran in steady mode for both (new option
`run_suite.py --abl-steady`, gates unchanged):

| Mode | Steps | Solver s | Drift U / k / ε (H..5H) | Floors |
|---|---:|---:|---|---:|
| explicit | 2700 | 27.2 | 0.262% / 0.810% / 3.427% | 0 |
| `implicit_projection` | 400 | 5.0 | 0.263% / 0.806% / 3.437% | 0 |

## Tracer and grids (P5c, P5d)

Development canyon with its line-source tracer, case settings:

| Mode | Steps | Solver s | Relative budget defect | Max receptor difference |
|---|---:|---:|---:|---:|
| explicit | 3800 | 42.0 | 7.5e-16 | — |
| `implicit_projection` | 1300 | 10.9 | 6.1e-14 | 2.2e-7 |

Performance canyons (`cases/performance/canyon-27k.json`, 36×32×24, and
`canyon-93k.json`, 54×48×36), with the tracer:

| Grid | Mode, numerics | Steps | Solver s | Accepted | Floors | Budget defect |
|---|---|---:|---:|---|---:|---:|
| 27k | explicit, case settings | 14,400 | 2974 | yes (needs more than the case's 7,000 steps) | 0 | 2.3e-15 |
| 27k | implicit, case settings | 1,400 | 180* | yes | 0 | 1.9e-13 |
| 27k | implicit recipe | 1,000 | 70.7 | yes | 0 | 1.1e-13 |
| 93k | implicit, case settings | 2,500 | 1772* | yes | 0 | 9.0e-14 |
| 93k | implicit recipe | 2,500 | 684 | yes | 0 | 3.1e-13 |

\* two runs shared the two cores. Implicit recipe: `implicit_projection`,
`pressure_relative_tolerance` 0.1 and `max_time_step_s` 100, with the CFL cap
of performance iteration 7 (commit `5d08fc5`). At 27k the implicit receptors
equal the explicit ones to 5e-7 (case settings) and 1.2e-6 (recipe), within
the steady tolerances. Within the case's own budgets (7,000 steps, 240 s) the
explicit mode does not finish the 27k canyon; the implicit mode does.

Refinement: the sensor1 receptor is 2.31e-7 kg/m³ on the development grid,
5.29e-7 at 27k and 6.75e-7 at 93k in both modes. The sub-stepping changes the
path, not the discrete steady state, so the refinement behavior is the
explicit mode's; the canyon is not grid-converged on these grids, which
remains the open fine-grid gate of the model card.

## Choices made on the development cases

- Scalar sub-step cap 16 (`solver::SCALAR_SUBSTEPS_MAX`): with the final
  recipe, caps 4, 8, 16 and 32 reach the development canyon's gates in 1000,
  600, 400 and 400 outer iterations (4.5, 2.8, 2.4 and 3.6 s).
- The turbulence inner solves use the momentum correction's predeclared
  BiCGStab tolerance and cap (0.1, 50); one iteration per solve sufficed in
  most outer iterations.
