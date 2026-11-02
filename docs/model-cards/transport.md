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
