# Passive transport 0.1

Solve a cell-integrated advection–diffusion balance using the projected face fluxes. One internal face contributes equal and opposite flux to its adjacent fluid cells. Molecular diffusivity is nonnegative; RANS adds nu_t/Sc_t. The canyon cases use a molecular value for a trace gas (1.5e-5 m2/s), so the turbulent Schmidt number controls the mixing; a large constant would dominate nu_t/Sc_t in the canyon and mask it.

The linear reference uses donor-cell upwind and the higher-order option monotonized-central MUSCL reconstruction; both advance with SSPRK2. Timestep restrictions account for advective and diffusive rates, and cap the combined allowance at 0.45. Observed convergence is measured; limiter behavior can reduce order for other fields.

With an implicit steady flow algorithm (`numerics.steady_algorithm`, stage
P5d), the same SSPRK2 step runs in sub-steps within each outer iteration: the
fewest equal sub-steps of at most the explicit stable step, capped at 16 such
steps (`solver::SCALAR_SUBSTEPS_MAX`). Every sub-step keeps the explicit step's
stability limits, budgets and positivity, so the steady state, its mass balance
and the receptors do not depend on the pseudo-time step; only the number of
outer iterations to reach them does. When the cap binds the constituents cover
less pseudo-time than the flow; the state records theirs as `scalar_time_s`,
and the emitted mass is the source rate times it.

Domain walls/slip faces and masked solids have no scalar flux. Inlets use zero local-increment concentration, including scalar backflow values. Pressure outlets have zero diffusive gradient. Background concentration is a separately interpreted physical contribution.

Point sources use the containing cell. Lines are split at exact grid crossings and normalized by physical length. Volumes use Cartesian overlap and the declared volumetric rate. Source support intersecting a solid is rejected; there is no silent redistribution or clipping.

Point receptors use multilinear cell-center interpolation, clamped to the nearest center at the outer boundary. Any positive-weight solid cell invalidates the stencil. Volume receptors use exact overlap weights and reject solid intersections.

Stored evidence separates initial, emitted, boundary-in, boundary-out and remaining mass. The final difference is audited without treating numerical correction as a physical sink. Negative concentrations beyond round-off stop the run; concentrations are never clipped to conceal failure.

The archived-field checker recomputes every receptor value from the stored concentration field with these weights. Transport never changes a solid cell, so its concentration stays exactly zero; the checker requires that, and a restart checkpoint with mass in a solid cell is rejected (CFD-E051).

For exact response matrices, use fixed flow/diffusivity and linear_upwind. A nonlinear limiter invalidates exact superposition. The source-inference tutorial verifies combined versus separate sources, holds out receptors, includes an unidentifiable matrix and repeats observations with changed inflow/grid.

The independent SciPy reference assembles the steady uniform-flow matrix and compares the full concentration field with a direct sparse solve. This is numerical verification, not measured atmospheric validation.

A step builds its candidate state separately, from only the fields it changes,
and replaces the state only after the state, velocity and positivity checks
pass; the monitor history is checked in place and moved over last. A pressure
failure, a cancellation or a late check failure leaves the whole state
unchanged, and constituents without a supplied source array keep their values.

## Opt-in spherical aerosol bins (urban U5)

A constituent may declare `particle` with `diameter_m`, `density_kg_m3`, an
optional `settling_velocity_m_s`, and optional
`ground_deposition_velocity_m_s` and `roof_deposition_velocity_m_s` (both
zero by default). Absence of `particle` preserves the gas equation and its
serialized case/state bytes. No feedback on air, chemistry, agglomeration,
resuspension or non-spherical shape correction is represented.

Computed settling uses the Stokes–Cunningham spherical terminal speed

\[
w_s = \frac{(\rho_p-\rho_a) g d^2 C_c}{18\mu},\quad
C_c=1+\mathrm{Kn}(1.257+0.4e^{-1.1/\mathrm{Kn}}),\quad
\mathrm{Kn}=2\lambda/d.
\]

The reference atmosphere is fixed and explicit: 293.15 K, 101325 Pa,
\(\rho_a=1.204\,\mathrm{kg/m^3}\),
\(\mu=1.81\times10^{-5}\,\mathrm{Pa\,s}\),
\(\lambda=66\,\mathrm{nm}\), and
\(g=9.80665\,\mathrm{m/s^2}\). Formula evaluation requires particle Reynolds
number at most 0.1. Higher-Re particles need a user-supplied terminal speed;
that choice and the fixed atmosphere are assumptions, especially at altitude.
The formula and its limits follow the primary model description in
[AerSett v1.0, Mailler et al. (2023)](https://gmd.copernicus.org/articles/16/1119/2023/).

Settling adds a conservative first-order vertical donor flux to the existing
advection–diffusion operator. It is first order even when gas advection uses
MUSCL. Its outgoing rate enters the same positivity CFL limit as advection,
diffusion and surface removal. Settling leaves through an open lower boundary;
the incoming increment at an open top is zero. Impermeable upward-facing ground
and roofs absorb at \((w_s+v_d)c\); the separately specified \(v_d\) excludes
settling. Vertical walls have no particle deposition in this release.

The SSPRK2-integrated cumulative budget is initial + emitted + boundary-in =
airborne + boundary-out + deposited. Ground and roof deposits are separate
surface classes in the checkpoint and summary. The independent archived-field
checker recomputes current surface fluxes, settling, aerodynamic classification,
airborne mass, cumulative accounting and receptor sums. Cumulative deposited
mass is the time-integrated ledger; a final airborne field alone cannot
reconstruct its time history.

`particulate_matter.PM2.5` and `.PM10` sum only spherical bins whose representative
unit-density aerodynamic diameter passes the cutoff, with slip correction in
the diameter conversion. A bin crossing a cutoff is not fractionally split.
These are local-source concentration increments, with no regional background,
not regulatory sample predictions. Numerical fixtures cover a descending layer,
absorbing ground, roof flux, periodic settling refinement and superposition,
Stokes units and validity, and the exponential interior settling–diffusion
operator balance. The exponential fixture tests the interior operator; it does
not claim that an absorbing column with no supply has a nonzero steady state.
Experimental aerosol/urban-deposition validation remains open.

### Complete steady settling–diffusion column

The source-free interior exponential check is complemented by
`cases/verification/particle-steady-column.json`: a closed-air column of height
L=1 m, with a uniform volumetric source q=4e-6 kg/(m3 s) above z_s=0.75 m,
settling w=0.2 m/s, diffusivity D=0.1 m2/s, additional bottom deposition
v_d=0.1 m/s and zero total flux at the top. The bottom is absorbing with
J(0)=(w+v_d) C(0), where downward total flux J=wC+D C'.

Below the source, Q=q(L-z_s), C_0=Q/(w+v_d) and

\[
C(z)=Q/w+(C_0-Q/w)\exp(-wz/D).
\]

Within the source layer,
\(C_p(z)=q(L-z)/w+qD/w^2\) and
\(C(z)=C_p(z)+[C(z_s)-C_p(z_s)]\exp[-w(z-z_s)/D]\).
This solution satisfies J(L)=0 and continuity of concentration and flux at
z_s. The finite-volume deposition law samples the adjacent cell center rather
than an extrapolated surface value, so first-order boundary convergence is
expected. Cold-start 16/32/64-cell runs compare the complete returned steady
profile with this analytic solution, and verify source/deposition equality,
mass conservation and positivity under frozen error/refinement gates.

Steady particles may use a deposition/leaf sink in place of an air outlet.
The case-level screen requires a relevant declared sink candidate; source
preflight then requires a represented positive sink in every source-bearing
fluid component. Connectivity is necessary, not a proof of reachability or
convergence, and the numerical steady-equation and mass gates still apply.
A passive gas retains the original outlet requirements (CFD-E020/CFD-E043).
