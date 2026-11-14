# Implicit steady pseudo-time (stages P4 and P5a): results

Date: 1 November 2026. Plan and predeclared gates:
[accuracy and steady-solver plan](../history/accuracy-steady-plan.md), stages P4
and P5a. Method: [flow model card](../model-cards/flow.md), "Steady
pseudo-time algorithms". Campaign script: `validation/steady_algorithms.py`
(its cavity default is `implicit_viscous`; P5a uses `--algorithm implicit_projection`).

All measurements: steady Re=100 lid-driven cavity, opt-in multigrid pressure,
one solver thread, a 2-vCPU Intel Xeon VM that also ran other work, so timings
are approximate. Hosted reproduction is stage M.

## Summary

| Stage | Gate | Result |
|---|---|---|
| P4 `implicit_viscous` | same fixed point (mode difference shrinks ≥ 5× per 10× tightening) | **failed** (see below); the round-off pair agrees to 1e-12 |
| P4 | unchanged acceptance | pass |
| P4 | restart identity | pass |
| P4 | cost | 1.5–2.2× faster than explicit |
| P5a `implicit_projection` | same fixed point | pass: 7.8–13.5× per decade |
| P5a | unchanged acceptance | pass |
| P5a | restart identity | pass |
| P5a | cost: ≥ 2× below the better of explicit and P4 at 24² and 48² | pass: 13× and 18× below P4 |

P5a passed its cost gate, so the conditional stage P5b (local pseudo-time
steps with a face-weighted projection) is not built.

## Fixed point

Predeclared test: the 24² cavity in the explicit mode and the candidate mode at
the case tolerances (steady residual 1e-5, monitor 1e-3) and with both tightened
10× and 100×; the maximum face-velocity difference between the modes must
shrink at least 5× per decade. One pair is converged near round-off (residual
1e-11, monitor 1e-9). "To reference" is each mode's distance to the round-off
explicit solution, reported, not gated.

### P4 `implicit_viscous`

| Scheme | Tightening | Steps explicit / P4 | Mode difference | To reference: explicit / P4 |
|---|---|---|---:|---|
| donor_cell | 1× | 2010 / 1170 | 1.29e-6 | 1.34e-5 / 1.21e-5 |
| donor_cell | 10× | 2490 / 1440 | 2.98e-8 | 1.33e-6 / 1.30e-6 |
| donor_cell | 100× | 2970 / 1710 | 7.48e-9 | 1.31e-7 / 1.39e-7 |
| van_leer | 1× | 2460 / 1440 | 3.38e-7 | 1.83e-5 / 1.80e-5 |
| van_leer | 10× | 3060 / 1800 | 1.02e-7 | 1.81e-6 / 1.71e-6 |
| van_leer | 100× | 3660 / 2160 | 1.67e-8 | 1.79e-7 / 1.62e-7 |

Shrink per decade: donor-cell 43.2× and **4.0×**, van Leer **3.3×** and 6.1×.
The gate fails for both schemes, and the failure is kept. The round-off pairs
differ by 3.6e-13 (donor) and 1.0e-12 (van Leer). Each mode's own distance to
the round-off solution falls exactly 10× per decade, so both converge to the
same fixed point; the two modes follow nearly the same path, and their small
mutual difference depends on where in a 30-step monitor window each one stops.
The gate measures that difference, so it fluctuates. It is not changed after
the fact. P4 stays an opt-in option with this recorded failure; P5a, which
passes the same gate, is the recommended implicit mode.

### P5a `implicit_projection`

| Scheme | Tightening | Steps explicit / P5a | Mode difference | To reference: explicit / P5a |
|---|---|---|---:|---|
| donor_cell | 1× | 2010 / 180 | 1.06e-5 | 1.34e-5 / 2.79e-6 |
| donor_cell | 10× | 2490 / 210 | 9.13e-7 | 1.33e-6 / 4.13e-7 |
| donor_cell | 100× | 2970 / 240 | 7.02e-8 | 1.31e-7 / 6.09e-8 |
| van_leer | 1× | 2460 / 210 | 1.17e-5 | 1.83e-5 / 6.62e-6 |
| van_leer | 10× | 3060 / 270 | 1.50e-6 | 1.81e-6 / 3.15e-7 |
| van_leer | 100× | 3660 / 300 | 1.10e-7 | 1.79e-7 / 6.86e-8 |

Shrink per decade: donor-cell 11.6× and 13.0×, van Leer 7.8× and 13.5×: pass.
The round-off pairs differ by 1.0e-11 (donor, 4860 explicit steps against 390
outer iterations) and 9.8e-12 (van Leer, 6060 against 480). At each tolerance
P5a is closer to the converged solution than the explicit mode.

## Acceptance and restart

Every run of both campaigns reached the unchanged steady gates: the fixed-point
runs above, plus Poiseuille, Couette and the 24² cavity with donor-cell, van
Leer and the unlimited scheme. Rust tests (`tests/implicit.rs`) check restart
bit identity after 3 of 6 outer iterations for both algorithms and two schemes,
the CFL ramp, and that explicit runs do no and report no inner work.

## Operators

`tests/implicit.rs` also checks:

- the P4 stencil is the linear part of the production viscous right-hand side,
  to 1e-12, on a cavity, a masked cavity, an open channel, a slip lid, Couette
  and Poiseuille, and is symmetric and negative definite;
- the P5a matrix equals an independent plain-array assembly of
  I/Δτ + frozen-flux first-order upwind − ν·L on a periodic grid, to 1e-10;
- constants are in its advective and viscous kernel for a divergence-free field,
  it has nonpositive couplings and dominance by 1/Δτ, also with walls;
- the inner solve reaches its relative tolerance.

## Inner-solver pilot (P5a)

Declared before running: van Leer, 24² and 48², two runs each; candidates
symmetric Gauss–Seidel with 2 or 4 sweeps, and Jacobi-preconditioned BiCGStab
to a relative residual of 0.1 (cap 50); select the lowest sum of mean solver
times among candidates accepted on both grids.

| Candidate | 24² iterations | 24² s | 48² iterations | 48² s | Sum s |
|---|---:|---:|---:|---:|---:|
| SGS, 2 sweeps | 240 | 0.573 | 390 | 3.95 | 4.52 |
| SGS, 4 sweeps | 210 | 0.483 | 300 | 3.08 | 3.57 |
| BiCGStab | 210 | 0.506 | 270 | 2.81 | **3.32** |

All runs were accepted with Ghia errors 0.00543 (24²) and 0.00501–0.00502
(48²). BiCGStab was selected; the margin over four SGS sweeps (7%) is within
this host's timing noise.

## Cost

Van Leer, solver seconds to the unchanged gates:

| Grid | Explicit | P4 | P5a | P5a speed-up over explicit | Ghia error |
|---|---:|---:|---:|---:|---:|
| 24² | 9.43 (2460 steps) | 6.13 (1440) | 0.51 (210) | 18× | 0.00543 |
| 48² | 123.4 (7230) | 55.5 (3120) | 3.06 (270) | 40× | 0.00500–0.00502 |

Donor-cell with P5a: 0.26 s at 24² (180 iterations) and 1.75 s at 48² (270),
Ghia errors unchanged at 0.0276 and 0.0169. The cost at the 0.01 target is now
about 0.5 s for native at 24² on this host, where OpenFOAM's hosted solver time
at 24² is 0.63 s; the hosted stage M measurement compares both on one runner.

The flux form makes an outer iteration about 1.7× as costly as with donor-cell
(11 against 6.5 ms at 48²); the advective kernel is the next performance target.
