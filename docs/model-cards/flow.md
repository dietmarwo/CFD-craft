# Flow model 0.1

## Scope

Constant-density incompressible flow, flat ground, uniform Cartesian cells, box and optional polygon-prism masks, CPU f64. Face velocities and cell pressure share the same divergence/gradient definition. Local coordinates are east/north/up. Pressure is kinematic pressure in m2/s2; the isotropic 2k/3 contribution is absorbed in RANS pressure.

Within one face evaluation, the advective samples and the viscous coefficients
use the same staggered neighbor faces: wall ghosts at wall and blocked faces,
periodic wrapping and outlet sampling.

By default the momentum predictor uses first-order donor-cell advection of each staggered velocity component and an explicit variable-viscosity stencil. The extra variable-viscosity symmetric-stress contribution is reconstructed from cell gradients under the incompressibility assumption. It is not a claim of globally second-order momentum accuracy.

`numerics.momentum_advection` selects, opt-in, a conservative flux form of the
advective term instead (Harlow and Welch, 1965; Morinishi, Lund, Vasilyev and
Moin, 1998; Ferziger, Perić and Street, ch. 7):

- each momentum control volume is centered on its face; the advecting velocity
  on a control-volume face is the MAC average of the two face velocities that
  meet there;
- the transported component is reconstructed upwind, φ_f = φ_U + ½·s(a, b)
  with a = φ_U − φ_UU and b = φ_D − φ_U (van Leer, 1974, in Sweby's 1984
  notation), division-free;
- `second_order_upwind` uses s = a (unlimited, not bounded). `limited_upwind`
  with `numerics.momentum_limiter` uses van Albada (van Albada, van Leer and
  Roberts, 1982), van Leer, or monotonized central (van Leer, 1977);
- every control-volume face carries one flux shared by its two momentum cells,
  so momentum is conserved to round-off in a periodic box;
- the near samples at walls and solids use the same ghost values as the viscous
  term. Where the far-upwind sample is not an interior face, that face falls
  back to s = 0 (first order), so no stencil reaches through a solid.

At an open boundary (stage P3b) the outer half of an outlet's momentum cell
advects with the outlet face velocity and a zero-gradient value (s = 0); its
tangential faces extrapolate the inside cell's advecting velocity. Inflow faces
are prescribed. With `neutral_rans` the near-wall samples use the wall-function
ghosts as before, and the k and ε equations keep their first-order upwind
transport. These closures passed the empty-ABL check with unchanged gates and
the development canyon with zero floor events for all four schemes before
`neutral_rans` was allowed. Donor-cell remains the default, and default runs
are byte-identical to the earlier release. Time integration
(SSPRK2 with a projection per stage) and the CFL cap are unchanged. The
[second-order momentum results](../evidence/second-order-momentum.md)
record operator orders of 2.06 (unlimited) and 1.92–1.95 mean L1 (limited),
translating-vortex orders of 2.0–2.3, momentum conservation to 1e-16, bounded
limited schemes, and a steady Re=100 cavity Ghia error of 0.005–0.006 at 24²,
against 0.028 for donor-cell.

An incremental projection is applied to each SSPRK2 velocity stage. Tests recover second-order decay for periodic viscous shear. General unsteady open-boundary pressure order is not established by that fixture. The intended urban use is a checked steady solution.

### Steady pseudo-time algorithms

In steady mode, `numerics.steady_algorithm` selects how pseudo-time advances.
All options are written in delta form: they solve for a correction δ driven by
the full steady residual R(u, p) = `momentum_rhs`(u) − G p, which is exactly
what `assess` recomputes. Inexact inner solves, approximate Jacobians and the
pseudo-time step change only the path; at a fixed point δ = 0 and the pressure
correction is zero (Beam and Warming, 1978; Ferziger, Perić and Street, ch. 8).

- `explicit` (default): SSPRK2 with a projection per stage, Δτ limited by
  advection and diffusion together. Unchanged from the earlier release.
- `implicit_viscous` (stage P4): the same SSPRK2 stages, each solving
  (I − Δτ·ν·L) δ = Δτ·R with the existing viscous stencil (wall ghosts are
  affine, so δ obeys the homogeneous ghost relation). Δτ follows the advective
  limit only. Jacobi-preconditioned CG from δ = 0, relative tolerance 1e-3,
  at most 50 iterations per solve.
- `implicit_projection` (stage P5a): one outer iteration solves
  A δ = R with A = I/Δτ + first-order upwind advection with advecting velocities
  frozen at uⁿ (Picard) − ν·L. The second-order part of the advection enters
  only through R (deferred correction: Khosla and Rubin, 1974; Hayase, Humphrey
  and Greif, 1992). Then u* = uⁿ + δ is projected at scale Δτ and the pressure
  correction is added in full. With a uniform Δτ, a_P − Σ a_nb = 1/Δτ away from
  walls, the consistent SIMPLEC coefficient (Van Doormaal and Raithby, 1984), so
  this is a SIMPLEC-type coupling. A is diagonally dominant with nonpositive
  couplings. The inner solve is Jacobi-preconditioned BiCGStab (van der Vorst,
  1992) from δ = 0 to a relative residual of 0.1, at most 50 iterations,
  selected by a predeclared pilot against symmetric Gauss–Seidel. Pseudo-time
  follows a deterministic CFL ramp CFL_n = min(5, 1.0·1.2ⁿ), Δτ = CFL_n / Σ_a
  max|u_a|/h_a, capped by `max_time_step_s`; restarts need no extra state. The
  cap of 5 was chosen on the development cases (24² and 48² cavities,
  development canyon); before it the ramp grew to 1e6 and only
  `max_time_step_s` bounded it. Each projection is a correction: at a fixed
  point it requires div u = 0 whatever its inner tolerance, so a relTol-style
  `pressure_relative_tolerance` of 0.1 changes the path, not the steady state.
  The recommended implicit recipe is that tolerance with a non-binding
  `max_time_step_s` (100) so the ramp sets the step
  ([performance results](../evidence/performance-iterations.md)).

- `implicit_projection` with `neutral_rans` (stage P5c): A uses the face
  viscosities of the momentum right-hand side (ν + ν_t, averaged with an
  interior neighbor), and wall-function ghosts are linearized with ν_t and the
  cell velocities lagged at uⁿ, because the wall functions are nonlinear. The
  variable-viscosity cross term stays explicit. After the momentum–pressure
  update, segregated implicit k and ε steps in delta form follow (see the
  [turbulence package](#neutral-turbulence-package)).
- Constituents (stage P5d) advance in explicit SSPRK2 sub-steps within each
  outer iteration of either implicit algorithm: the fewest equal sub-steps of
  at most the explicit stable step (the explicit algorithm's step formula at the
  new velocity), capped at 16 steps of that size. The transport scheme, budgets,
  positivity and receptors are those of the explicit step; only the pseudo-time
  the constituents cover per outer iteration changes, and with it the path, not
  the steady state.

The implicit options run in steady mode only (CFD-E045). Prescribed flow, and
`implicit_viscous` with RANS, are rejected (CFD-E047). A singular or nonfinite
correction system stops the run with CFD-E056 (momentum) or CFD-E057 (k, ε).
`steps` counts outer iterations, `physical_time_s` accumulates
pseudo-time, and `momentum_solver_iterations` the inner iterations. Acceptance,
the monitor window and all thresholds are unchanged. See the
[implicit steady results](../evidence/implicit-steady.md): on the
Re=100 cavity, `implicit_projection` reaches the unchanged gates in 180–300
outer iterations, 18–40× faster than the explicit mode at the same accuracy.
With RANS and a tracer ([P5c/P5d results](../evidence/implicit-rans.md))
it keeps the explicit fixed point (round-off pair to 1.5e-10), the empty-ABL
check and zero floor events, and accepts the 27k and 93k canyons; the
predeclared tightening statistic fails for U on one decade, where the
difference is the explicit run's own convergence error.

Stage V adds [momentum verification](../evidence/momentum-verification.md)
without changing these equations. Eight shifted periodic Taylor–Green operator
tests and a translating-vortex refinement measure donor-cell's first-order
advection, with separate time refinement. The periodic vortex also records
mean-momentum drift: the default donor-cell advective form is not a
conservative shared momentum-flux scheme (the opt-in flux form above is). The 1000-step transverse-step fixture measures extrema at
the existing CFL cap; its intentional work limit is not numerical acceptance.
These are analytic verification fixtures, not experimental validation.

## Pressure

The matrix-free operator is minus divergence times gradient. Internal faces have one shared flux. On a periodic axis with one cell (a two-dimensional run) a face joins a cell to itself; it carries no pressure difference, and the IC(0) factor skips it. Pressure-outlet correction is zero; fixed normal-velocity faces use a homogeneous correction derivative. A closed fluid component has a mean-zero gauge and a compatibility check.

By default PCG uses a cached incomplete Cholesky factor with zero fill. A tiny shift regularizes only the preconditioner, not the solved operator. Recomputed residuals use the compatible mean-zero right-hand side in closed components. The nominal recurrent tolerance is checked against an independently formed operator residual, allowing a documented round-off margin of ten times the target plus 1e-12.

The IC(0) factor is stored as contiguous row offsets, column indices and values.
Construction sums duplicate periodic edges in face order, sorts each row and
intersects sorted rows without per-row allocations. Each solve builds a compact
list of interior and outlet face weights in face order for its PCG products; the
list is local to the solve, so changed grid coefficients take effect at the next
solve, and the final residual check uses the face-by-face operator instead. PCG
keeps the preconditioned residual in one buffer, so nothing is allocated per
iteration. The memory estimate includes 112 bytes per cell for factor
construction and the face list, before its 25% margin.

Projection forms its right-hand side and the per-cell round-off scale in one
cell pass, in the axis order of the divergence, and applies the correction
gradient directly to the faces. [Performance results](../evidence/native-cpu-performance.md)
give paired timings of these kernels at fixed work.

Projection residuals, actual face-flux continuity and boundary balance are separate checks. An opt-in [symmetric multigrid preconditioner](../developer/pressure-multigrid.md) supports
unmasked grids with Galerkin coarse operators and a direct coarse solve. The
fine equation, projection and residual gates are unchanged; masks still use
IC(0). Strong unequal spacings select symmetric principal line/small-plane
blocks and semicoarsening, with a setup/memory warning; see the
[measured anisotropy coverage](../evidence/anisotropic-pressure.md).
Component-preserving masked multigrid, general sparse direct factorization and
MPI remain open. Experimental model qualification is unchanged.

## Neutral turbulence package

The closure is nu_t = C_mu k² / epsilon. Constants are:

| Constant | Value |
|---|---:|
| C_mu | 0.09 |
| C_epsilon1 | 1.44 |
| C_epsilon2 | 1.92 |
| sigma_k | 1 |
| kappa | 0.4 |
| sigma_epsilon | kappa² / ((C_epsilon2-C_epsilon1) sqrt(C_mu)) = 1.111111... |

This coefficient choice supports the high-Re neutral log-layer equilibrium, rather than mixing an inlet profile with unrelated standard coefficients.

The inlet profiles are U = u_star/kappa log((z+z0)/z0), k = u_star²/sqrt(C_mu), and epsilon = u_star³/(kappa(z+z0)). Wind direction is meteorological direction from, so horizontal components are [-U sin(theta), -U cos(theta)].

Ground momentum uses a log-law stress based on adjacent tangential velocity. Wall dissipation follows C_mu^(3/4) k^(3/2)/(kappa distance), which remains meaningful at stagnation cells. Wall production uses the stress and k-derived friction scale. A cell with several wall faces, such as a canyon floor cell between two buildings, uses the mean of the wall production and of the wall dissipation over those faces, with equal weights. Omitting `building_roughness_m` preserves the legacy small effective non-ground wall roughness min(inlet z0, 0.001 cell width). Supplying it uses that positive physical z0 for non-ground wall stress, production and dissipation, independent of cell width. Ground z0 is unchanged. Neither wall option has independent urban-wall validation yet.

That building-wall adaptation depends on cell width. A future qualification study must replace it with an explicit physical wall parameterization before treating refinement as a pure discretization study. The current canyon grid experiments combine numerical and wall-model sensitivity.

The upper boundary has zero normal velocity, the equilibrium tangential stress and reference k/epsilon diffusion treatment. That stress closure is what makes `ground_open_top` an open top, so laminar cases may not use it (CFD-E023): without the closure the top would act as a no-slip lid. This is a particular neutral-domain closure, not a reproduction of an arbitrary tunnel ceiling. Side faces are classified from the prescribed wind as inlet, pressure outlet or impermeable slip.

Production and the variable-viscosity cross terms look up the six cell
neighbors once per cell and use them for every tensor component; a missing
neighbor at a blocked or boundary face falls back to the cell itself. A
regression test pins the bit patterns of the momentum, production and
turbulence-step results on an open and a periodic canyon grid.

Turbulence destruction terms use positive implicit denominators. Wall epsilon is an explicit algebraic constraint; tiny k/epsilon floors are counted. Any floor event prevents numerical acceptance. Excessive eddy viscosity causes a reported divergence instead of silent clipping.

With `steady_algorithm = implicit_projection` (stage P5c), each outer
iteration solves, after the momentum–pressure update,
(I/Δτ − T_k + ε/k) δk = T_k(k) + P − ε and
(I/Δτ − T_ε + C_ε2 ε/k) δε = T_ε(ε) + C_ε1 P ε/k − C_ε2 ε²/k.
T is the first-order upwind transport of the explicit step (its linear part,
including the upper-boundary diffusion term); P, the diffusivities, ε/k and the
wall functions are lagged at the start of the iteration, and the implicit
destruction terms are the explicit step's. Wall-function cells keep the
algebraic ε, as identity rows δε = ε_wall − ε. Each solve is Jacobi-preconditioned
BiCGStab from δ = 0 to a relative residual of 0.1, at most 50 iterations,
profiled as `turbulence_solve`. Floors are counted as in the explicit step. At a
fixed point δ = 0, so the explicit step's residuals are zero there too; the
steady residual is measured with the explicit step size for every algorithm.

The counter covers state-update floors. The wall algebraic relation itself has a minimum epsilon of 1e-14 and is not separately counted by that field; its activity must be treated as an additional regime check before physical qualification.

## Evidence and limitations

Verification covers Poisson/projection identities, gauges, analytic channels, Couette flow, periodic viscous shear and the Re=100 lid cavity. The empty-ABL test compares near-outlet U/k/epsilon to the inlet at heights H..5H under frozen tolerances. It is a consistency check for this setup. The suite also reports, without a gate, the drift below H. There the cell-centered velocity gradient of the second cell overestimates the logarithmic gradient, so production and epsilon run high: on the canonical empty-ABL grid epsilon is up to 16 % above the inlet profile below H (U 4 %, k 4 %), and more on coarser vertical grids. A log-consistent near-wall gradient is an open improvement.

The illustrative canyon examples are not exact CODASC geometry/inflow reproductions. Their coarse-grid numerical convergence does not validate urban dispersion. Fine-grid pressure/explicit-time throughput is an open performance gate. No buoyancy, stratification, traffic turbulence, chemistry or unsteady turbulent statistics are represented. Opt-in vegetation (below) and opt-in particles (transport model card) have their own numerical verification and no experimental validation.

Method references: Richards and Hoxey (1993), Richards and Norris (2011), and Hargreaves and Wright, "On the use of the k–ε model in commercial CFD software to model the neutral atmospheric boundary layer", J. Wind Eng. Ind. Aerodyn. 95 (2007) 355–369. No OpenFOAM source code is included or was consulted for these methods.

## Porous vegetation

`vegetation` contains axis-aligned volumes with `id`, `min_m`, `max_m`,
`leaf_area_density_m2_m3` (LAD, inverse meters), `drag_coefficient` (Cd),
optional `leaf_deposition_velocity_m_s`, and `turbulence_closure`.
Membership uses fluid-cell centers; overlapping boxes add their coefficients.
Buildings keep their existing impermeable mask. Vegetation changes momentum,
turbulence and particle transport; it does not change the pressure equation.

The momentum acceleration is \(-C_d\,\mathrm{LAD}|U|U_i\).
At staggered faces, the nonnegative cell coefficient
\(C_d\,\mathrm{LAD}|U|\) is averaged from adjacent fluid cells and multiplies
the native face component. It enters both the full nonlinear residual and a
frozen implicit diagonal. The explicit-pseudo-time path uses a positive
semi-implicit drag correction; implicit-viscous and implicit-projection paths
include it in their correction matrices. All have the same steady fixed point.
The transient canopy drag fixture verifies first-order time convergence for
this semi-implicit treatment. The gas SSPRK2 second-order claim does not apply
to canopy momentum. General unsteady urban canopy accuracy remains unvalidated.

The canopy contributions are

\[
S_k=C_d\,\mathrm{LAD}(\beta_p |U|^3-\beta_d |U|k),\qquad
S_\epsilon=C_d\,\mathrm{LAD}(C_{\epsilon4}\beta_p|U|^3\epsilon/k
-C_{\epsilon5}\beta_d|U|\epsilon).
\]

| Source coefficient set | beta_p | beta_d | C_e4 | C_e5 |
|---|---:|---:|---:|---:|
| `green1992` (default) | 1 | 4 | 1.5 | 1.5 |
| `sanz2003` | 1 | 5.1 | 0.9 | 0.9 |

The equations and coefficient convention are documented by
[Viana Parente Lopes, Palma and Silva Lopes (2021), equations 1.1–1.3 and table 1](https://doi.org/10.1017/jfm.2020.927).
`green1992` is the set of Green (1992) in that table. `sanz2003` is the set of
Sanz (2003) as tabulated there, where it is listed under
[Katul et al. (2004)](https://doi.org/10.1023/B:BOUN.0000037333.48760.e5).
Only canopy source coefficients switch; the existing ambient k-epsilon
constants, wall functions and upper-boundary treatment remain fixed. This is
a model-range comparison within the existing closure, not a reproduction of
all settings used by those publications. Both explicit and implicit turbulence
updates retain canopy destruction implicitly and evaluate the same residual.
Algebraic epsilon wall cells keep the established wall condition.

Particle leaf removal is \(\mathrm{LAD}\,v_{leaf}\,c\), integrated in the
same SSPRK2 budget as settling; the CFL allowance includes this loss rate.
Removed mass is `deposited_kg.vegetation`, with its current rate reported per
bin. Gases have no leaf sink. A prescribed-flow study must set
Cd=0; positive canopy drag is rejected rather than silently ignored.

With zero LAD, all additional operators return before changing arithmetic;
whole returned state bytes, including k/epsilon and counters, match a case
without vegetation. The empty-ABL zero-LAD fixture checks this explicitly.
Nonzero-LAD fixtures verify uniform force/drag equilibrium,
pressure-drop/integrated-drag balance, prescribed-flow exponential leaf decay,
leaf-block spatial attenuation/refinement and both published source formulas.
`summary.vegetation` stores current drag power per unit density (m5/s3), volume
integrated drag acceleration (m4/s2), represented cells and an explicit
`verified_numerics_unvalidated_physics` label. It is an instantaneous work rate,
not a reconstructed history of cumulative mechanical work. The independent
checker recomputes these from the archived face velocities and canopy boxes.
Drag power uses the actual staggered momentum sink, summed over active face
dual volumes (face area times pressure-gradient distance), including half
volumes at outlets. `drag_quadrature` identifies this convention; the power is
the exact discrete sink work in that face inner product, rather than a separate
cell-centered estimate.

No heat, cooling, radiation, seasonal leaf dynamics, leaf-size dependence,
wake-resolved flow or experimental urban-canopy qualification is claimed.
