# Second-order momentum advection (stage P3a): results

<!-- check: none: record of past runs -->

Date: 1 November 2026. Plan and predeclared gates:
[accuracy and steady-solver plan](../history/accuracy-steady-plan.md), stage P3a.
Base: `main` at `6d33850` (merged PR #15).

## What changed

`numerics.momentum_advection` selects, opt-in, a conservative flux form of the
momentum advection on the staggered grid with an upwind-biased reconstruction
(`second_order_upwind`, or `limited_upwind` with `numerics.momentum_limiter` =
`van_albada`, `van_leer` or `monotonized_central`). Donor-cell stays the default.
The method and its sources are in the [flow model card](../model-cards/flow.md).
Stage P3b, at the end of this document, adds the open-boundary closure and
allows `neutral_rans`.

## Gates

All gates were declared in the plan before the scheme existed. All schemes pass
all gates.

### 1. Operator order

`tests/momentum.rs`, `second_order_schemes_meet_the_predeclared_operator_orders`:
the production `momentum_rhs` with viscosity and forcing zeroed, on the shifted
periodic Taylor–Green field at the 8 predeclared phases, N = 32, 64, 128, 256.
Least-squares slopes of the error norms:

| Scheme | L1 mean | L1 min | L2 mean | L2 min | Max mean | Max min | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| second_order_upwind | 2.057 | 2.049 | 2.088 | 2.085 | 2.207 | 2.204 | every phase ≥ 1.9 in all norms: pass |
| van_albada | 1.916 | 1.887 | 1.500 | 1.413 | 0.997 | 0.783 | L1 mean ≥ 1.8, every phase ≥ 1.6: pass |
| van_leer | 1.921 | 1.835 | 1.494 | 1.319 | 0.999 | 0.702 | pass |
| monotonized_central | 1.948 | 1.746 | 1.491 | 1.045 | 1.014 | 0.430 | pass |

The plan's NumPy model of the operator predicted 2.05 for the unlimited scheme
and L1 minima/means of 1.87/1.93 (van Albada), 1.78/1.96 (van Leer) and
1.77/2.13 (monotonized central). As expected, the limiters fall back to first
order in strips around smooth extrema, so their L2 and max-norm slopes are
lower; those norms are reported, not gated. Donor-cell's mean L1 slope is 0.997.

### 2. Translating Taylor–Green

`validation/momentum_accuracy.py --scheme NAME`: periodic x and z, offset
velocity (0.7, 0.2, 0.3), grids 16, 32, 64 at a fixed step of 0.0005 s, with a
separate time refinement.

| Scheme | L1 order | L2 order | Max order | Time / spatial error at 64² | Gate (L1 ≥ 1.7) |
|---|---:|---:|---:|---:|---|
| donor_cell (Stage V baseline) | 0.974 | 0.975 | 0.959 | 5.0e-6 | — |
| second_order_upwind | 1.999 | 2.008 | 2.027 | 9.4e-5 | pass |
| van_albada | 2.044 | 1.901 | 1.585 | 1.6e-4 | pass |
| van_leer | 2.159 | 2.062 | 1.760 | 2.0e-4 | pass |
| monotonized_central | 2.320 | 2.321 | 2.139 | 2.7e-4 | pass |

The 64² L1 velocity errors are 6.6e-5, 4.1e-5, 3.1e-5 and 2.3e-5 for the four
schemes. Time errors stay below 0.03 % of the spatial errors.

### 3. Conservation

Total momentum change of each component, normalized by Σ|u_a|·V, per 100 steps,
largest over all vortex runs: 4.2e-17 (unlimited), 2.5e-17, 5.7e-17 and 5.8e-17
(limited), against the 1e-13 gate. Donor-cell drifts by 1.8e-3 per 100 steps at
16². The Rust test `flux_form_advection_conserves_periodic_momentum` checks the
operator alone on a field that is not divergence-free.

### 4. Boundedness and stability

The transverse step v(x) carried by a uniform flow, 1,000 steps at
`advective_cfl_max` 0.45:

| Scheme | Final range (initial 0–1) | New extrema | Gate |
|---|---|---:|---|
| donor_cell | 0.42–0.58 (smeared) | 0 | — |
| second_order_upwind | −0.226–1.226 | 0.226 (reported) | no growth from step 500 (0.2277) to 1000 (0.2257): pass |
| van_albada | 0.0076–0.9924 | 0 | ≤ 1e-12: pass |
| van_leer | 0.0009–0.9991 | 0 | pass |
| monotonized_central | 0.0000–1.0000 | 0 | pass |

The cap of 0.45 was not lowered for any scheme.

### 5. Insulation

`second_order_schemes_keep_a_solid_barrier_insulating`: perturbing the far side
of a two-cell barrier leaves the near-side right-hand side bit-identical for
every scheme, and a near-side perturbation does change it.

### 6. Controls

- **Default byte identity:** the steady cavity, a transient Poiseuille run and
  a masked canyon (3 steps), built from this branch and from `main` (`6d33850`),
  have byte-identical `fields.json`, `checkpoint.json`, `probes.csv`,
  `geometry.json` and `case.json`, with identical work: 2010 steps and 204,850
  pressure iterations, 2/0 and 3/365.
- **Shear flows:** on Poiseuille and Couette fields u(z), the advective
  contribution of every scheme is exactly zero, and the right-hand side equals
  donor-cell's to 1e-14.
- **Independent reference:** `flux_form_matches_an_independent_periodic_reference`
  compares all five reconstructions, including the s = 0 control, with a separate
  plain-array implementation on a 6×5×7 periodic grid with three spacings, to
  1e-12.
- **Restart:** a 12² steady cavity run for 6 steps equals 3 steps plus a
  resumed 3, bit for bit, for every scheme.
- **Diagnostics:** CFD-E037 (limiter rules) carries the field path; default
  numerics are not serialized. P3a also rejected open boundaries and RANS
  (CFD-E038, CFD-E039); stage P3b retired both codes after its gates passed.

### 7. Cavity sweep

Steady Re=100 lid-driven cavity, native only, opt-in multigrid pressure, one
thread, this host (2-vCPU Intel Xeon VM), budgets 20,000 steps and 600 s. Every
row reached the unchanged steady gates. Donor-cell's hosted errors on the same
grids are 0.0380, 0.0276, 0.0235 and 0.0170
([Stage V](momentum-verification.md)).

| Grid | Scheme | Steps | Solver s | Ghia error |
|---|---|---:|---:|---:|
| 16² | second_order_upwind | 1,320 | 2.24 | 0.0230 |
| 16² | van_albada | 1,320 | 2.08 | 0.0257 |
| 16² | van_leer | 1,320 | 2.27 | 0.0243 |
| 16² | monotonized_central | 1,320 | 1.93 | 0.0225 |
| 24² | donor_cell | 2,010 | 4.98 | 0.0276 |
| 24² | second_order_upwind | 2,490 | 10.14 | 0.00578 |
| 24² | van_albada | 2,460 | 9.95 | 0.00589 |
| 24² | van_leer | 2,460 | 9.43 | 0.00544 |
| 24² | monotonized_central | 2,490 | 9.74 | 0.00494 |
| 32² | second_order_upwind | 3,870 | 28.5 | 0.00733 |
| 32² | van_albada | 3,840 | 28.6 | 0.00332 |
| 32² | van_leer | 3,840 | 29.1 | 0.00365 |
| 32² | monotonized_central | 3,840 | 28.9 | 0.00400 |
| 48² | second_order_upwind | 7,230 | 123.9 | 0.00660 |
| 48² | van_albada | 7,230 | 125.5 | 0.00487 |
| 48² | van_leer | 7,230 | 123.4 | 0.00500 |
| 48² | monotonized_central | 7,230 | 124.2 | 0.00515 |

The 24² times are medians of three rounds (donor 4.59–5.07 s; unlimited
9.58–10.35; van Albada 9.94–10.49; van Leer 9.28–9.81; monotonized central
9.51–9.83). The other rows are single runs, measured while the host also built
code, so they are approximate.

**Every second-order scheme reaches the 0.01 target at 24², the same grid as
OpenFOAM** (whose hosted error there is 0.0090). Donor-cell reaches it only at
96². The Ghia error is near its floor: it does not fall monotonically with the
grid, which is why the plan adds a self-convergence measurement.

### Self-convergence (selected scheme)

Van Leer at 96² as a same-scheme reference (22,830 steps, 1,742 s, accepted,
Ghia error 0.00504), and the mean absolute centerline difference at 257
stations for the shared grids:

| Grid | L1 difference to 96² |
|---|---:|
| 16² | 0.00920 |
| 24² | 0.00406 |
| 32² | 0.00198 |
| 48² | 0.00062 |

Least-squares order 2.45, against 1.28 for donor-cell with the same method in
Stage V. A finite reference inflates the order as the grids approach it, so this
is a descriptive difference, not an exact error or a grid-convergence index.

## Selection

Predeclared rule: among passing schemes, the lowest native solver time on the
coarsest grid that reaches 0.01; prefer a limited scheme over the unlimited one
within timing noise. The coarsest grid is 24² for all four. **`limited_upwind`
with `van_leer`** has the lowest median there (9.43 s); monotonized central
(9.74 s) overlaps it within noise. All four schemes stay selectable.

## Cost

The flux form costs about 3.8 ms per step at 24² against 2.5 ms for donor-cell,
and needs 22% more steps (2,460 against 2,010) because the steady monitors
settle later. Cost at the target on this host is therefore 9.4 s for native
against 0.63 s for OpenFOAM on the hosted runner: roughly 15×, where before
P3a native needed 96² and about 826 s (roughly 1,300×). The hosts differ, so
the hosted stage M measurement gives the actual ratio. Steps to a steady state
(P4, P5a) and the cost per step are the remaining levers.

## Stage P3b: open boundaries and RANS

### Outlet closure

The outer half of an outlet's momentum cell advects with the outlet face
velocity and a zero-gradient value (s = 0), and its tangential faces
extrapolate the inside cell's advecting velocity; inflow faces are prescribed.
Tests (`tests/momentum.rs`):

- uniform flow through an open channel has an advective contribution of at most
  1e-14 on every face, including the outlets, for all four schemes;
- the open channel (10×2×6, inflow 0.4 m/s) reaches the unchanged steady gates
  with every scheme, in the explicit mode and with `implicit_projection`.

While adding this, a defect in the P5a matrix showed up: at an outlet, the
indices of its advecting velocities fell back to cell 0 and to the outlet's own
face for a missing cell, so the Jacobian rows of outlet faces depended on
unrelated velocities. The delta form kept the fixed point, but the path was
wrong. `implicit_matrix_rows_at_an_outlet_use_only_adjacent_velocities` fails
without the fix; the rows now use the same zero-gradient closure.

### RANS

Predeclared conditions for allowing the schemes with `neutral_rans`: the
empty-ABL check with unchanged gates (2% U, 5% k and ε in H..5H), and the
development canyon (W/H = 1, 270°, 18×16×12) reaching the steady gates with zero
floor events. Both were run with a build that only lifted the rejection:

| Scheme | ABL drift U / k / ε | ABL floors | Canyon steps | Canyon solver s | Canyon floors | Canyon gates |
|---|---|---:|---:|---:|---:|---|
| donor_cell (control) | 0.23% / 0.94% / 2.68% | 0 | 3,800 | 42.1 | 0 | pass |
| second_order_upwind | 0.22% / 0.92% / 2.70% | 0 | 5,100 | 70.6 | 0 | pass |
| van_albada | 0.23% / 0.88% / 2.72% | 0 | 3,100 | 45.4 | 0 | pass |
| van_leer | 0.23% / 0.88% / 2.69% | 0 | 3,100 | 46.8 | 0 | pass |
| monotonized_central | 0.22% / 0.89% / 2.66% | 0 | 3,000 | 43.5 | 0 | pass |

All conditions hold, so `neutral_rans` is allowed with every scheme.
`run_suite.py --abl-numerics '{"momentum_advection": ...}'` reproduces the ABL
check; with van Leer the whole verification suite passes (drifts 0.22%, 0.88%,
2.69%). The k and ε equations keep their first-order upwind transport.

The canyon's receptor concentrations depend on the momentum scheme: sensor0 is
9.6e-8 kg/m³ with donor-cell, 7.4e-8 with van Leer and 1.4e-7 with the unlimited
scheme. That is numerical sensitivity on a coarse development grid, not a
validation statement; the canyon validation gate is unchanged.
