# CFD-craft: native accuracy and steady-solver plan (P3–P5)

Date: 1 November 2026. Base: `main` at `f358be6` (merged PR #14, anisotropic
pressure multigrid).

## Implementation status

Stage V is implemented. Read the [frozen verification protocol](20-momentum-verification-plan.md) and [measured baseline](../evidence/momentum-verification.md) for its actual evidence, retained failures and hosted-reproduction status.

Status on 1 November 2026, after PR #16: stages P3a, P3b, P4, P5a, P5c, P5d and
M are implemented and recorded ([second-order momentum](../evidence/second-order-momentum.md),
[implicit steady](../evidence/implicit-steady.md),
[RANS and constituents](../evidence/implicit-rans.md),
[matched accuracy](../evidence/matched-accuracy.md)); ten performance
iterations followed ([results](../evidence/performance-iterations.md)).
P5b was not built, because P5a passed its cost gate. The P4 and P5c fixed-point
shrink statistics each failed on one decade; both failures are recorded. All
new numerics are opt-in; the defaults remain donor-cell advection, the explicit
steady algorithm and IC(0). Open: masked multigrid (P2b), setup cost (P2c) and
a decision on defaults. The rest of this document is the plan as written.

## Goal

Close the native/OpenFOAM gap where it actually lies: accuracy per cell and the
number of iterations to a steady state. Pressure is no longer the main cost.

The plan does this by implementing published finite-volume methods in Rust from
the literature: second-order momentum advection, implicit treatment in
pseudo-time and an implicit steady iteration. It does **not** port or translate
OpenFOAM code (see [Ground rules](#ground-rules)). OpenFOAM stays what it is
today: an external reference run through the adapter.

## Where the gap is now

Hosted accuracy sweep on the solver code merged as `f358be6` (run
41267955525; GitHub runner, AMD EPYC 9V74, 4 CPUs, one solver thread), steady
Re=100 lid-driven cavity, native with opt-in multigrid:

| Grid | Native Ghia error | Native steps | Native solver s | OpenFOAM Ghia error | OpenFOAM iterations | OpenFOAM solver s |
|---|---:|---:|---:|---:|---:|---:|
| 12² | 0.0597 | 630 | 0.31 | — | — | — |
| 24² | 0.0276 | 2,010 | 4.42 | 0.0090 | 696 | 0.64 |
| 48² | 0.0170 | 6,390 | 59.6 | 0.0071 | 2,132 | 5.42 |

- **Accuracy per cell.**
  - Native momentum advection is first-order donor-cell in advective form
    (`flow.rs`, `momentum_rhs`). Its numerical viscosity, about U·h/2, is
    twice the physical viscosity at 24².
  - Native does not reach the 0.01 target through 48², so equal-accuracy cost
    is undefined today.
- **What the OpenFOAM reference actually runs** (`integrations/openfoam_cases.py`):
  - **Advection:** `bounded Gauss linearUpwind grad(U)` with an unlimited
    `Gauss linear` gradient. That is unlimited second-order upwind. "Bounded"
    there is OpenFOAM's correction for steady-state continuity errors, not a
    limiter.
  - **Coupling:** SIMPLE with `consistent yes`, which is SIMPLEC.
    Under-relaxation is 0.5 for U and 0.2 for p; GAMG pressure solves use
    `relTol` 0.01.
  - **Stopping rule:** `residualControl` 1e-7, which differs from native
    acceptance through `assess`. Iteration counts are therefore not directly
    comparable; cost at equal accuracy is.
  - **Ghia metric:** OpenFOAM improves only from 0.0090 to 0.0071 between 24²
    and 48², an observed order of about 0.3. The metric is near a floor, so
    the Ghia error alone cannot measure a scheme's order.
- **Steps to a steady state.** Steady mode marches SSPRK2 pseudo-time with a
  projection per stage. The step is limited by advection and diffusion together
  (`solver.rs`, `timestep`). Diffusion is about 40% of the limit at 24² and 57%
  at 48², and steps grow about 3.2× per refinement.
- **Span cells.** Native computes two span cells for a 2D case, OpenFOAM one.
  That doubles native cavity work but does not matter for the 3D canyon.

## Stages

| Stage | Change | Default output changes? | Exit gate (summary) | Expected effect (estimate, not measured) |
|---|---|---|---|---|
| V | Verification fixtures and baseline; same grid list for both backends | No | Fixtures in CI; donor-cell baseline recorded; fixtures distinguish first from second order | None by itself |
| P3a | Second-order momentum advection, laminar, walls and periodic boundaries, opt-in | No | Order, conservation, stability, insulation tests; accepted cavity sweep | Ghia error near OpenFOAM's at equal grid; a first finite equal-accuracy ratio |
| P4 | Implicit viscous term in steady pseudo-time, delta form, opt-in | No | Same fixed point as explicit steady mode; unchanged gates | 1.7× (24²) to 2.3× (48²) fewer steps, minus solve cost |
| P5a | Implicit steady iteration with a uniform pseudo-time step and projection, delta form, opt-in | No | Same fixed point; unchanged gates; restart identity; cost gate | A large reduction in iterations (amount unknown) |
| P5b | Local pseudo-time steps with a consistent face-weighted projection; **only if** P5a fails its cost gate | No | Pressure-operator rules in AGENTS.md; same fixed point | Faster convergence in slow-flow regions |
| P3b, P5c | Open boundaries and RANS for P3a and P5a | No | Outlet closure tests, empty-ABL check, canyon, model card | Same levers on the canyon |
| P5d | Scalar transport with the implicit flow algorithms | No | AGENTS.md transport checks | Needed for the dust study |
| M | Matched-accuracy measurement against OpenFOAM, hosted reproduction | No | Predeclared protocol; failures kept | The first honest cost-at-accuracy ratio |

Recommended order: V → P3a → P4 → P5a → (decision) P5b → P3b, P5c, P5d, with M
after each stage. P2b (masked multigrid) can run in parallel. Nothing here
depends on it, because the implicit stages work with IC(0) on masked grids.

## Ground rules

### Clean-room implementation

- AGENTS.md already says: "Do not copy separately licensed CFD implementations
  into the MIT core." OpenFOAM is GPL v3; CFD-craft is MIT. A translation of
  OpenFOAM code would generally be a derivative work.
- Implement from the papers and textbooks listed under [Sources](#sources).
  Implementers do not consult OpenFOAM source code, its listings on
  cpp.openfoam.org, its code listings in books, or other GPL CFD code while
  working on these stages.
- The flow model card currently links an OpenFOAM source listing
  (`atmBoundaryLayer_8H_source.html`) as a method reference. Replace that link
  with a non-source reference before P3b and P5c, which touch that area (see
  [Decisions](#decisions-needed)).
- Each PR lists the sources it implements, in its plan and in the model card.
- OpenFOAM is used only as a black-box reference through the adapter: run it,
  compare its fields and costs. Reading our own OpenFOAM case files (the
  recipe) is fine.
- Names are generic (`second_order_upwind`, `limited_upwind`,
  `implicit_projection`), not OpenFOAM dictionary keywords.

### Opt-in, with unchanged defaults

- Every new behavior sits behind a new `numerics` field whose default
  reproduces the current behavior. Defaults are not serialized
  (`skip_serializing_if`, as for `pressure_preconditioner`), so existing case
  and checkpoint hashes are unchanged.
- Default runs stay **byte-identical** to `main` in `fields.json`,
  `checkpoint.json`, `probes.csv`, `geometry.json` and `case.json`, with
  identical steps and work. Each stage adds this control for the steady cavity,
  a transient case and a masked canyon.
- Changing a default is a separate later decision (see
  [Decisions](#decisions-needed)).

### Acceptance never moves

- `assess` stays the single acceptance path. It recomputes the steady momentum
  residual from `momentum_rhs` and the pressure gradient, plus continuity, the
  volume balance and the monitor stability check. Their thresholds
  (`steady_residual_tolerance`, `steady_monitor_tolerance`, 1e-4 local
  continuity, 1e-5 volume balance) are unchanged.
- `momentum_rhs` dispatches on the selected advection scheme, so the steady
  residual is always the residual of the equations actually solved.
- Implicit stages are written in **delta form**: they solve for a correction
  driven by the full steady residual. Inexact inner solves, approximate
  Jacobians, under-relaxation and pseudo-time steps then change only the path.
  - At a fixed point, δ = 0, so the residual R = 0.
  - The pressure update α_p·φ is constant at a fixed point, so Gφ = 0.
  - Together these are exactly what `assess` checks.

  Inner solves start from a zero initial guess for δ, which keeps them
  deterministic.
- No limiter freezing, residual smoothing of the acceptance check, or other
  device that changes the discrete equations at the end of a run.
- `max_time_step_s` keeps its meaning, an upper bound on the (pseudo-)time
  step, in every mode. The measurement protocol predeclares its value for each
  configuration.

### Evidence and repository rules

- Predeclare each measurement protocol in the stage plan before measuring.
  Keep failed and slower rows in the reports.
- A fix comes with a test that fails without it. Each new diagnostic gets a
  code in `docs/diagnostics.md` with the offending field path.
- Each numerical change updates `docs/model-cards/flow.md`. RANS changes add
  the empty-ABL check and a published model-card change. Transport changes
  need the mass, positivity, unit-normalization and refinement checks.
- **Required checks for every PR:**
  - Rust: `cargo fmt`, clippy with `-D warnings` on all targets,
    `cargo test --release --workspace --locked`;
  - Python: `ruff format --check .` and `ruff check .`, with the Python suites
    passing in normal and `python -O` mode;
  - evidence code: explicit exceptions, and `zip(..., strict=True)` for records
    that must correspond.
- Each stage gets an opt-in CI selector or input that reproduces its campaign
  on a GitHub runner, and a results document with a hosted-reproduction
  section.

## Stage V: verification fixtures and baseline

The existing periodic-shear fixture (`validation/flow_accuracy.py`) has zero
advection (u depends on z only), so it cannot see the momentum scheme's order.
Add fixtures that can, and record donor-cell results first.

1. **Operator truncation test (Rust, new `tests/momentum.rs`).**
   - Evaluate the advective part of `momentum_rhs` on an analytic,
     divergence-free, periodic field (a 2D Taylor–Green velocity in x–z) at 8
     predeclared random phase offsets, on grids N = 32, 64, 128, 256. Compare
     with the analytic ∂(u_d u_a)/∂x_d at the face centers.
   - The phase offsets prevent a false pass: with an unshifted field and N
     divisible by 4, the extrema sit exactly on nodes or zero-flux faces.
   - Report L1, L2 and max-norm errors. The gate statistic is the
     least-squares slope of log L1 against log h over the four grids, per
     phase.
   - For donor-cell, assert a mean slope below 1.2. This proves the test can
     tell first from second order; a NumPy model of the operator gives 0.97.
   - Add a test-only entry point for the advective part. The donor-cell
     production path keeps its floating-point operation order; today advection
     and viscosity accumulate per direction in one loop. The byte-identity
     controls check that.
2. **Translating Taylor–Green vortex (Python, `validation/momentum_accuracy.py`).**
   - Periodic x and z, two periodic span cells, plus a uniform offset velocity
     U₀. Without the offset, a second-order scheme's advective error is mostly
     a pressure gradient that the projection removes, so the fixture would test
     mainly the viscous terms. With U₀, it tests advection.
   - Choose the viscosity so that cell Peclet numbers span about 1–10 over the
     grids.
   - Supply the initial field through a generated, checksummed checkpoint, as
     `flow_accuracy.py` does. The exact solution decays as exp(−2νk²t) while
     translating with U₀.
   - Run grids 16, 32, 64 with a fixed small time step, and a separate
     time-step refinement showing that the time error is negligible. Record the
     observed L1, L2 and max-norm orders.
3. **Momentum conservation.** In the fully periodic box with the offset U₀,
   track the total momentum of each component. Normalize its change by
   Σ|u_a|·V. Donor-cell in advective form is the recorded baseline.
4. **Boundedness and stability.** A transverse velocity step v(x) carried by a
   uniform periodic flow U in x is divergence-free and advected passively.
   Record new extrema and any growth after 1,000 steps at the case's
   `advective_cfl_max`.
5. **Insulation across solids.** Perturb face velocities on the far side of a
   blocked face. The momentum right-hand side on the near side must stay
   bit-identical. This guards the wider stencils of P3a.
6. **Same grid list for both backends.**
   - The OpenFOAM recipe currently accepts only n = 24·{1, 2, 3}
     (`integrations/openfoam_cases.py`, `validation/accuracy_sweep.py`).
     Extend the recipe, the sweep and `compare_backends.py` to a predeclared
     list, for example 16, 24, 32, 48, run for **both** backends. Comparing
     native at 16 or 32 with OpenFOAM at 24 only would bias "coarsest grid
     reaching 0.01" toward native.
   - Keep "no extrapolated crossing".
7. **Native self-convergence.** Add a native reference run at 96² (or finer if
   the budget allows) with the same scheme. Report the observed order of the
   centerline velocity against it, because the Ghia metric is near its floor
   and cannot show scheme order by itself.

**Exit:** all fixtures in CI. The donor-cell baseline (operator slopes,
Taylor–Green orders, conservation, extrema, the two-backend sweep on the new
grid list, self-convergence) is recorded in a results document. No numerical
change.

## Stage P3a: second-order momentum advection (laminar)

### Method

- **New field:** `numerics.momentum_advection`, with values:
  - `"donor_cell"`: default, unchanged;
  - `"second_order_upwind"`: unlimited (s = a below; ψ(r) = r in Sweby's
    notation). This is the scheme class the OpenFOAM recipe uses;
  - `"limited_upwind"`: requires `numerics.momentum_limiter`, one of
    `"van_albada"`, `"van_leer"` or `"monotonized_central"`.

  The limiter field is rejected otherwise, with coded diagnostics.
- **Flux form on the staggered grid** (Harlow and Welch; Ferziger, Perić and
  Street, ch. 7):
  - for the velocity component on an a-face, the momentum control volume is
    centered on that face;
  - the advecting volume fluxes through its faces are second-order
    interpolations of the face velocities (the classic MAC averages);
  - the transported component is reconstructed on each momentum-cell face.

  Each momentum-cell face carries one single-valued flux shared by its two
  momentum cells. The fluxes telescope, so the scheme conserves momentum in a
  periodic box. The interpolated fluxes of a momentum cell also sum to the mean
  of the discrete divergences of its two pressure cells. That sum is zero after
  projection, which makes the flux form consistent with the advective form.
- **Reconstruction:** an upwind-biased MUSCL-type face value (van Leer), written
  with Sweby's limiter function. With U, UU and D the upwind, far-upwind and
  downwind samples, a = φ_U − φ_UU and b = φ_D − φ_U, the face value is
  φ_f = φ_U + ½·s(a, b). Use division-free forms, because b = 0 occurs in
  uniform regions, in Poiseuille and Couette flow, and at a start from rest:
  - unlimited second-order upwind: s = a;
  - van Albada: s = ab(a + b)/(a² + b²) if ab > 0, else 0;
  - van Leer: s = 2ab/(a + b) if ab > 0, else 0;
  - monotonized central: s = sign(b)·min(2|a|, |a + b|/2, 2|b|) if ab > 0,
    else 0, as in `transport.rs`;
  - test-only control s = 0, which is flux-form first-order upwind. It is
    **not** the production donor-cell scheme (advective form, advecting
    velocity averaged from cell centers); the two differ at O(h). It is checked
    against an independent NumPy flux-form reference instead.
- **Boundary closure in this stage:**
  - **Supported:** walls, moving walls, blocked faces and periodic axes. The U
    and D samples use the existing `sample` and `wall_ghost` logic.
  - **No reach through solids:** where UU is not a real interior face (a ghost,
    a blocked face or a domain edge), use s = 0 on that momentum face, which is
    a local first-order closure.
  - **Open boundaries:** the momentum cell of an outlet face lies half outside
    the domain, so its outer flux is undefined. Reject open boundaries with a
    coded diagnostic until P3b defines and tests an outlet and inflow closure.
- **Time integration** is unchanged: SSPRK2 with a projection per stage.
  - **Bounded schemes:** in the semi-discrete form above, the forward-Euler TVD
    bound is CFL ≤ 0.5, and SSPRK2 keeps it (Gottlieb and Shu). The existing
    `advective_cfl_max` cap of 0.45 lies inside the bound.
  - **Unlimited scheme:** second-order upwind is unstable with forward Euler
    at any CFL. With two-stage RK2 it is stable up to CFL 0.5 in 1D. The
    stability fixture checks the multidimensional case at the cap.
- **RANS:** the new schemes with `flow.kind = neutral_rans` are rejected with a
  coded diagnostic until P3b.
- **Cost:** the wider stencil roughly doubles the advective part of the
  momentum right-hand side. Measure it and record it in the profile.

### Gates (predeclared)

1. **Operator order** (8 phases, N = 32–256, least-squares L1 slope):
   - each limited scheme: mean slope ≥ 1.8 and every phase ≥ 1.6. A NumPy
     model of the operator gives minimum 1.87 and mean 1.93 for van Albada,
     1.78 and 1.96 for van Leer, 1.77 and 2.13 for MC. TVD limiters fall back
     to first order in strips around smooth extrema, so L2 and max-norm slopes
     are reported, not gated;
   - `second_order_upwind`: every phase ≥ 1.9 in L1, L2 and max norm (model:
     2.05).
2. **Translating Taylor–Green:** L1 velocity order ≥ 1.7 for every scheme;
   L2 and max-norm orders reported.
3. **Conservation:** total momentum change, normalized by Σ|u_a|·V, at most
   1e-13 per 100 steps.
4. **Boundedness and stability:**
   - limited schemes: no new extrema beyond 1e-12 of the initial range after
     1,000 steps at `advective_cfl_max`;
   - `second_order_upwind`: overshoot reported, and no growth of the maximum
     over the run (stability).

   A scheme that needs a smaller `advective_cfl_max` is rejected; the cap is
   not raised.
5. **Insulation:** bit-identical near-side right-hand side.
6. **Controls:**
   - default byte-identity (see Ground rules);
   - Poiseuille and Couette: the advective contribution is zero to round-off,
     and the fields match donor-cell's to round-off;
   - the s = 0 control matches the NumPy flux-form reference;
   - restart bit-identity for a cavity with each new scheme (resume after 3
     steps, compare with the uninterrupted run).
7. **Cavity sweep** on the shared grid list plus the native self-convergence
   reference:
   - every run reaches the unchanged steady gates within 20,000 steps and
     600 s;
   - report the Ghia error, the self-convergence order, steps and solver time.
   - A scheme that stalls above the steady residual tolerance fails, and its
     rows are kept. The stall described by Venkatakrishnan is a known risk for
     limiters. Do not rescue it by freezing the limiter or changing the
     tolerance.

### Selection rule (predeclared)

- Among the schemes that pass all gates, recommend the one with the lowest
  native solver time on the coarsest grid that reaches Ghia error ≤ 0.01. If
  none reaches it, recommend the one with the lowest error at 48², and report
  that the target was missed.
- If an unlimited and a limited scheme tie within timing noise, prefer the
  limited one, because the canyon needs boundedness.
- Keep only passing schemes selectable. Donor-cell stays the default.

## Stage P3b: open boundaries and RANS for second-order advection

- **Outlet and inflow closures:**
  - outlet: the outer momentum-cell flux uses the outlet face velocity as the
    advecting flux and a zero-gradient upwind value with s = 0;
  - inflow: the prescribed inflow value.

  Test with an open-channel case (Poiseuille with an outlet) and with the
  insulation and conservation fixtures adapted to open boundaries.
- **RANS:** allow the new schemes with `neutral_rans` only after:
  - the empty-ABL check passes with unchanged gates (2% U, 5% k and ε in
    H..5H);
  - the development canyon case (W/H = 1, 270°, 18×16×12) reaches the steady
    gates with zero floor events;
  - the flow model card is updated, with the OpenFOAM source-listing link
    replaced.
- **Unchanged:** the k and ε equations keep their current advection,
  `Advection::LinearUpwind` in `transport.rs`, which is first-order upwind
  despite its name. Changing that is a separate transport change with its own
  AGENTS.md checks.
- **If the empty-ABL check fails,** keep the rejection diagnostic and record
  the failure.

## Stage P4: implicit viscous term in steady pseudo-time

### Method

- **New field:** `numerics.steady_algorithm`, with `"explicit"` (default:
  today's SSPRK2 pseudo-time) and `"implicit_viscous"`. Rejected in transient
  mode, with constituents (until P5d) and with RANS (until P5c), each with a
  coded diagnostic.
- **Delta form inside the SSPRK2 stage structure.** Forward Euler is unstable
  for unlimited second-order upwind, so keep both stages. In each stage:
  1. R(u, p) = `momentum_rhs`(u) − G p, the same residual that `assess`
     checks.
  2. Solve (I − Δτ·L_ν) δ = Δτ·R, where L_ν is the existing viscous stencil.
     The wall ghosts are affine (2·target − value), so δ satisfies the
     homogeneous ghost condition.
  3. Add δ, enforce boundary velocities, project with the existing operator and
     preconditioner, and update the pressure incrementally.

  The step average is unchanged. At a fixed point both stages give δ = 0.
- **Time step:** Δτ follows the advective limit only,
  `advective_cfl_max / Σ_a (max|u_a|/h_a)`, capped by `max_time_step_s`.
- **Linear solver:** each face-component system is symmetric positive
  definite. Use matrix-free PCG with a Jacobi or symmetric Gauss–Seidel
  preconditioner, separate from the pressure operator (so the pressure-operator
  rules do not apply).
  - Inner relative tolerance and iteration cap are predeclared algorithm
    parameters, for example 1e-3 and 50, not changed after seeing results.
  - The inner loops check cancellation and the wall-time limit.
- **Profiling and results:**
  - new phase `MomentumSolve`, counters for inner iterations and solves, and
    `check_profile.py` rules for them (for example inner iterations ≤ cap ×
    solves);
  - the summary gains an optional `momentum_solver_iterations`, omitted when
    zero so existing results are unchanged; update the result contract.

### Gates (predeclared)

1. **Same fixed point.** Cavity 24² with donor-cell and with the P3a scheme.
   - Run the explicit and implicit modes at the case tolerance and at
     tolerances tightened 10× and 100×. These are stricter test settings, not
     looser gates.
   - The maximum field difference between the modes must shrink by at least
     5× for each 10× tightening.
   - Also compare one pair converged as far as round-off allows.
2. **Unchanged acceptance:** all steady cavity, Poiseuille and Couette cases
   accepted with unchanged gates.
3. **Restart identity:** checkpoint after 3 steps, resume, and compare
   bit-for-bit. Δτ depends only on the state, so no new checkpoint fields are
   needed.
4. **Cost:** steps and solver time on the cavity sweep. A slower result is
   recorded and closes the stage as "not useful".

## Stage P5a: implicit steady iteration with a uniform pseudo-time step

### Method

- **New value:** `numerics.steady_algorithm = "implicit_projection"`, with the
  same rejections as P4.
- **Outer iteration n:**
  1. Compute R(uⁿ, pⁿ).
  2. Assemble A ≈ I/Δτ − ∂R/∂u from two parts:
     - the advective part is the first-order upwind operator with advecting
       fluxes frozen at uⁿ (Picard linearization);
     - the viscous part is −L_ν, as in P4.

     A is a diagonally dominant M-matrix, and I/Δτ > 0 keeps it nonsingular,
     including on fully periodic grids.
  3. Solve A δ = R approximately, starting from zero.
  4. Set u* = uⁿ + δ and enforce boundary velocities.
  5. Project with the existing operator at scale Δτ; set pⁿ⁺¹ = pⁿ + α_p·φ.
- **Relation to SIMPLEC.** With a uniform Δτ and divergence-free fluxes, the
  momentum-matrix coefficient a_P − Σ a_nb equals 1/Δτ away from walls. That
  is the consistent SIMPLEC coefficient. So projecting at scale Δτ is a
  SIMPLEC-type correction except next to walls, where the viscous ghost terms
  add to it. The OpenFOAM recipe uses SIMPLEC as well. A uniform Δτ is
  therefore the consistent starting point; local steps come only in P5b.
- **Deferred correction:** the second-order part of the advective term enters
  only through R, explicitly (Khosla and Rubin; Hayase, Humphrey and Greif). In
  delta form the converged solution is the solution of the full P3a equations.
- **Pseudo-time schedule:** a deterministic CFL ramp from the outer-iteration
  count, CFL_n = min(CFL_max, CFL_0·gⁿ). Δτ = CFL_n / Σ_a (max|u_a|/h_a), capped
  by `max_time_step_s`, so a fluid at rest gets a finite step.
  - For reference, the cavity file's `max_time_step_s` of 0.1 caps the CFL at
    about 3.5 at 24² and 7 at 48². The protocol predeclares the cap per
    configuration and runs a larger value as a separate predeclared variant.
  - Because Δτ depends only on `steps` and the state, restarts need no new
    state. Residual-based switched evolution relaxation (Mulder and van Leer)
    is a later option; it would need a checkpoint field with a migration test.
- **Linear solver for A** (nonsymmetric). Two candidates, chosen by a
  predeclared pilot on cavity 24 and 48 by solver time to acceptance:
  - k symmetric Gauss–Seidel sweeps (k ∈ {2, 4});
  - BiCGStab (van der Vorst) with a Jacobi preconditioner, to a relative
    tolerance of 0.1.
- **Masks:** blocked faces are fixed at zero and excluded from A. The pressure
  projection uses IC(0) on masked grids, so P5a does not wait for P2b.
- **Accounting:**
  - `steps` counts outer iterations;
  - `physical_time_s` reports accumulated pseudo-time, as the explicit steady
    mode does;
  - the monitor window, `max_steps` and all acceptance checks are unchanged in
    meaning.

### Gates (predeclared)

1. **Fixed point, acceptance, restart:** same fixed point (with the P4
   tightening test), unchanged acceptance and restart identity, as in P4.
2. **Cost gate:** solver time to acceptance on cavity 24² and 48² at least 2×
   below the better of explicit mode and P4, with the selected P3a scheme.
   - OpenFOAM's iteration counts are reported for context only, because its
     stopping rule differs.
   - If P5a fails the gate, or converges only with a CFL cap that leaves slow
     regions (the cavity core, canyon recirculation) lagging, P5b starts.
3. **Diagnostics recorded:** outer iterations, inner work, pressure work and
   the CFL schedule actually used, so that failure modes can be distinguished.

## Stage P5b (conditional): local pseudo-time steps with a consistent projection

- **Only if** P5a fails its cost gate.
- **Method** (Patankar; Van Doormaal and Raithby):
  - local Δτ_f per face, from the local advective rate and capped;
  - the projection uses the matching face coefficients, the SIMPLEC
    coefficients of A including the wall terms. The pressure operator becomes
    face-weighted, −div(d_f G).

  A local Δτ with a global projection scale is inconsistent, and that is where
  over-correction comes from; this stage removes it. The staggered grid needs no
  Rhie–Chow interpolation.
- **Pressure-operator rules apply** (AGENTS.md): topology and nullspace tests,
  projection tests, and an independently assembled reference.
- **Preconditioner:** for the weighted operator, use the cached plain-Laplacian
  hierarchy (multigrid or IC(0)). It is still symmetric positive definite and
  needs no rebuild per outer iteration. Measure whether rebuilding pays off.
- **Gates:** as P5a, plus the pressure-operator tests.

## Stage P5c: implicit steady iteration with RANS

- **Method:**
  - segregated implicit k and ε steps after each momentum–pressure update, in
    delta form;
  - keep the current positive implicit destruction terms;
  - lag the wall functions (explicit, from uⁿ), because they are nonlinear.
- **Gates:**
  - same fixed point as the explicit steady mode on the development canyon,
    with the tightening test;
  - empty-ABL check with unchanged gates;
  - zero floor events;
  - canyon 27k and 93k accepted;
  - model card updated.
- This is the stage that matters for the dust study, and where the steady
  canyon cost can be compared with OpenFOAM's (P6 in the gap status).

## Stage P5d: scalar transport with the implicit flow algorithms

- `step` advances constituents explicitly with the flow step. With P4 or P5,
  that step exceeds the scalar diffusion and advection limits, and positivity
  would fail (CFD-E053). P4 and P5 therefore reject constituents until this
  stage.
- **Options**, decided in this stage's plan:
  1. Sub-step the existing explicit transport within each outer iteration, at
     its own stable step.
  2. Implicit steady transport in delta form on the converged flow.
  3. A frozen-flow transport run that restarts from a converged flow
     checkpoint. This needs a restart-contract change, because prescribed flow
     is uniform-only today.
- **Gates:** the AGENTS.md transport checks (mass, positivity, unit
  normalization, refinement), the steady mass balance and the existing
  receptor and superposition tests.

## Stage M: matched-accuracy measurement

- **Protocol (predeclared):**
  - same host, one solver thread, Rust stable and locked dependencies;
  - one warmup plus three alternating timed native/OpenFOAM pairs;
  - steady cavity on the shared grid list, native budgets 600 s and 20,000
    steps, the OpenFOAM recipe unchanged apart from the grid list;
  - the existing archive and field audits and the 0.06 Ghia screen.
- **Report:**
  - solver and workflow time;
  - Ghia error, the native self-convergence order;
  - steps or outer iterations, PCG and inner-solver work;
  - both backends' cost on the coarsest grid that reaches 0.01;
  - `native_over_openfoam_at_target` once native reaches the target;
  - the two stopping rules side by side;
  - no extrapolated crossing.
- **Configurations:**
  - donor-cell explicit (baseline);
  - the passing P3a schemes, explicit;
  - the selected P3a scheme with P4;
  - the selected P3a scheme with P5a, and with P5b if built.
- **Hosted reproduction:** extend `external=accuracy` with inputs
  `native_momentum` and `native_steady` next to `native_pressure`.
- **Afterwards:** update `validation/PERFORMANCE_GAP_STATUS.md` and the
  roadmap.

## Schema, diagnostics and code summary

| Item | Values | Default | Rejections (coded diagnostics) |
|---|---|---|---|
| `numerics.momentum_advection` | `donor_cell`, `second_order_upwind`, `limited_upwind` (only passing schemes stay) | `donor_cell`, not serialized | new schemes with open boundaries until P3b; with RANS until P3b |
| `numerics.momentum_limiter` | `van_albada`, `van_leer`, `monotonized_central` (only passing ones stay) | none | required with `limited_upwind`; rejected otherwise |
| `numerics.steady_algorithm` | `explicit`, `implicit_viscous`, `implicit_projection` (`implicit_local` if P5b is built) | `explicit`, not serialized | non-explicit in transient mode; with constituents until P5d; with RANS until P5c |
| Implicit parameters (CFL ramp, inner tolerance and cap, α_p) | predeclared constants in the first version | — | values outside the declared ranges, if exposed later |

Code areas:

- **`flow.rs`:** a test entry point for the advective part; the flux-form
  second-order advection; the upwind Jacobian assembly for P5a.
- **New `momentum_solve.rs`:** face-component matrix-free operators; PCG for
  P4; symmetric Gauss–Seidel and BiCGStab for P5a.
- **`solver.rs`:** dispatch on `steady_algorithm`; delta-form stages and outer
  iterations; Δτ policy.
- **`case.rs`:** fields, defaults, validation, memory preflight for the
  inner-solver storage.
- **`profiling.rs`, `validation/check_profile.py`:** new phases and counters.
- **`integrations/openfoam_cases.py`, `validation/`:** the shared grid list;
  `momentum_accuracy.py`; `accuracy_sweep` and `compare_backends` options; CI
  inputs.
- **Docs:**
  - `docs/model-cards/flow.md`, `docs/decisions/numerics.md`,
    `docs/diagnostics.md`, `docs/result-contract.md` (optional summary field),
    `docs/ai-context.md`;
  - the user manual's numerics section;
  - one plan and one results document per stage.

## Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Limiter chatter stalls steady convergence above the residual tolerance | Steady runs never accept | Several limiters plus the unlimited scheme in the sweep; failures kept; no limiter freezing |
| TVD limiters drop to first order at smooth extrema, and the Ghia metric samples extrema | Limited schemes less accurate than the unlimited one | Unlimited second-order upwind is a candidate; selection by cost at target |
| Unlimited scheme oscillates at high cell Peclet numbers | Overshoot; unsuitable for RANS or transport-coupled cases | Overshoot reported; limited schemes kept for the canyon |
| First-order closure at walls and solids | Global order below 2 | Measured by self-convergence; a second-order one-sided closure only with its own test |
| Inconsistent projection scale (local steps) | Oscillating outer iterations | Uniform Δτ in P5a; consistent face weights in P5b |
| Inner solves dominate cost | No net gain | Predeclared pilot; stop at "not useful" and record it |
| Nonlinear wall functions in implicit RANS | Slow or unstable convergence | Lagged wall terms; RANS only after the laminar stages |
| Scalar transport with large pseudo-time steps | Positivity failure | Rejected until P5d |
| Default drift | Existing results change | Byte-identity controls at every stage |

## Decisions needed

1. **Clean-room rule.** Confirm that implementers work only from the cited
   literature and do not consult OpenFOAM source code. This plan assumes yes.
   Related: replace the model card's link to the OpenFOAM
   `atmBoundaryLayer_8H_source.html` listing with a non-source reference. The
   card already states that no OpenFOAM code is included, but the link points
   implementers at source code.
2. **Inner tolerances.** P4 and P5 need loose inner tolerances and caps as
   algorithm parameters. Final acceptance is unchanged, and the delta form
   keeps the fixed point exact. The project rules treat tolerance policy as an
   owner decision, so this needs approval in principle; the values are
   predeclared in each stage plan.
3. **Unbounded scheme.** The OpenFOAM cavity reference uses unlimited
   second-order upwind. Allowing `second_order_upwind` as a selectable,
   unbounded option (with overshoot reported) makes the comparison fair and is
   probably the most accurate choice on the cavity. Limited schemes remain for
   the canyon.
4. **Defaults.** Keep donor-cell and the explicit steady mode as defaults until
   stage M shows the new options are better at equal accuracy. Changing a
   default changes the results and hashes of existing cases, so it should be a
   separate, announced change.
5. **Order.** Accuracy first (P3a), then steps (P4, P5a), is recommended:
   accuracy is the larger lever, and P5a's deferred correction is built around
   the final scheme. The alternative, P4 first, is easier to verify because it
   does not change the discrete equations, but it improves cost at a grid where
   native still misses the target.

## Expected outcome

All figures in this section are estimates, not measurements.

- **After P3a:** Ghia error close to OpenFOAM's at the same grid. Native would
  probably reach 0.01 at 24–32², giving the first finite equal-accuracy ratio.
  With today's native cost at 24² (4.4 s against OpenFOAM's 0.64 s, hosted),
  that ratio would be roughly 5–20×.
- **After P4:** 1.7–2.3× fewer pseudo-time steps on the cavity, minus the cost
  of the viscous solves.
- **After P5a or P5b:** outer iterations of the same order as OpenFOAM's
  SIMPLEC. The goal is native within about 2× of OpenFOAM's solver time at
  equal accuracy on the cavity. The real test is the RANS canyon after P5c
  and P5d.
- **Optional later:**
  - a native 2D mode with one span cell, which halves cavity cost and makes the
    comparison like-for-like;
  - P2c hierarchy setup cost;
  - kernel fusion and SIMD;
  - parallel momentum and smoother kernels.

## Sources

Implement from these. None of them is OpenFOAM source code.

- **Textbooks:**
  - S. V. Patankar, *Numerical Heat Transfer and Fluid Flow*, Hemisphere, 1980.
    SIMPLE, under-relaxation, staggered grids.
  - J. H. Ferziger, M. Perić and R. L. Street, *Computational Methods for Fluid
    Dynamics*, 4th ed., Springer, 2020. Finite volumes, deferred correction,
    SIMPLE/SIMPLEC, steady solvers.
  - H. K. Versteeg and W. Malalasekera, *An Introduction to Computational Fluid
    Dynamics: The Finite Volume Method*, 2nd ed., Pearson, 2007. TVD schemes,
    SIMPLEC.
  - H. Jasak, *Error Analysis and Estimation for the Finite Volume Method with
    Applications to Fluid Flows*, PhD thesis, Imperial College London, 1996.
    Background on second-order finite-volume schemes. Use the text, not code.
- **Staggered grid and flux form:**
  - F. H. Harlow and J. E. Welch, Phys. Fluids 8 (1965) 2182–2189.
  - Y. Morinishi, T. S. Lund, O. V. Vasilyev and P. Moin, J. Comput. Phys. 143
    (1998) 90–124.
- **Reconstruction, limiters and TVD time integration:**
  - B. van Leer, J. Comput. Phys. 14 (1974) 361–370.
  - B. van Leer, J. Comput. Phys. 23 (1977) 276–299 (monotonized central).
  - P. K. Sweby, SIAM J. Numer. Anal. 21 (1984) 995–1011.
  - G. D. van Albada, B. van Leer and W. W. Roberts, Astron. Astrophys. 108
    (1982) 76–84.
  - S. Gottlieb and C.-W. Shu, Math. Comp. 67 (1998) 73–85.
- **Steady convergence with limiters:** V. Venkatakrishnan, J. Comput. Phys.
  118 (1995) 120–130.
- **Deferred correction:**
  - P. K. Khosla and S. G. Rubin, Comput. Fluids 2 (1974) 207–209.
  - T. Hayase, J. A. C. Humphrey and R. Greif, J. Comput. Phys. 98 (1992)
    108–118.
- **Delta form and pseudo-time continuation:**
  - R. M. Beam and R. F. Warming, AIAA J. 16 (1978) 393–402.
  - W. A. Mulder and B. van Leer, J. Comput. Phys. 59 (1985) 232–246.
  - C. T. Kelley and D. E. Keyes, SIAM J. Numer. Anal. 35 (1998) 508–523.
- **Pressure–velocity coupling:** J. P. Van Doormaal and G. D. Raithby, Numer.
  Heat Transfer 7 (1984) 147–163 (SIMPLEC).
- **Linear solvers:** H. A. van der Vorst, SIAM J. Sci. Stat. Comput. 13 (1992)
  631–644 (BiCGStab).
- **Verification:**
  - G. I. Taylor and A. E. Green, Proc. R. Soc. A 158 (1937) 499–521.
  - P. J. Roache, J. Fluids Eng. 124 (2002) 4–10.
  - U. Ghia, K. N. Ghia and C. T. Shin, J. Comput. Phys. 48 (1982) 387–411.
