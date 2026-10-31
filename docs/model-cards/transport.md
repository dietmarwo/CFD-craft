# Passive transport 0.1

Solve a cell-integrated advection–diffusion balance using the projected face fluxes. One internal face contributes equal and opposite flux to its adjacent fluid cells. Molecular diffusivity is nonnegative; RANS adds nu_t/Sc_t. The canyon cases use a molecular value for a trace gas (1.5e-5 m2/s), so the turbulent Schmidt number controls the mixing; a large constant would dominate nu_t/Sc_t in the canyon and mask it.

The linear reference uses donor-cell upwind. The higher-order option uses monotonized-central MUSCL reconstruction with SSPRK2. Timestep restrictions account for advective and diffusive rates, and cap the combined allowance at 0.45. Observed convergence is measured; limiter behavior can reduce order for other fields.

Domain walls/slip faces and masked solids have no scalar flux. Inlets use zero local-increment concentration, including scalar backflow values. Pressure outlets have zero diffusive gradient. Background concentration is a separately interpreted physical contribution.

Point sources use the containing cell. Lines are split at exact grid crossings and normalized by physical length. Volumes use Cartesian overlap and the declared volumetric rate. Source support intersecting a solid is rejected; there is no silent redistribution or clipping.

Point receptors use multilinear cell-center interpolation, clamped to the nearest center at the outer boundary. Any positive-weight solid cell invalidates the stencil. Volume receptors use exact overlap weights and reject solid intersections.

Stored evidence separates initial, emitted, boundary-in, boundary-out and remaining mass. The final difference is audited without treating numerical correction as a physical sink. Negative concentrations beyond round-off stop the run; concentrations are never clipped to conceal failure.

The archived-field checker recomputes every receptor value from the stored concentration field with these weights. Transport never changes a solid cell, so its concentration stays exactly zero; the checker requires that, and a restart checkpoint with mass in a solid cell is rejected (CFD-E051).

For exact response matrices, use fixed flow/diffusivity and linear_upwind. A nonlinear limiter invalidates exact superposition. The source-inference tutorial verifies combined versus separate sources, holds out receptors, includes an unidentifiable matrix and repeats observations with changed inflow/grid.

The independent SciPy reference assembles the steady uniform-flow matrix and compares the full concentration field with a direct sparse solve. This is numerical verification, not measured atmospheric validation.

Stepping builds an unpublished candidate with only the state fields it needs.
Projected velocities/pressures and updated scalar arrays are constructed by
their stages instead of cloned and discarded. Existing monitor history is
validated by reference and transferred only after every state, velocity and
positivity gate succeeds. Pressure failure, cancellation or a late validation
failure leaves all original State fields intact. Transport arithmetic and
accounting are unchanged.
