# Iteration 02: established-solver execution and experimental evidence

Date: 29 October 2026. Baseline: `0bcbc8c9bae55923513c953aac7c8b7183e31605`
(merged first-release and plan-v2-alignment PRs).

## Decision

Develop CFD-craft as an optimization and validation workbench with a native
research solver and an established external backend. Experimental credibility
is specific to a configuration and observable. Code agreement, numerical
convergence and agreement with measurements remain separate assessments.

The merged code already strengthens memory/output preflight, structured
diagnostics, returned-field audits, source identity, pressure references and
three 100-step steady monitor windows. Preserve those changes.

## Work and acceptance gates

1. Add a bounded, shell-free adapter for **OpenFOAM Foundation 13**, tested with
   package `20260407`. Generate original input dictionaries for two canonical
   cases; do not copy solver implementations or silently accept another fork.
   Preserve fresh-directory behavior, input and runtime hashes, logs, actual
   iterations, timeouts and failures. A zero process exit alone is insufficient.
2. Run a laminar Re=100 cavity in both backends. Compare corresponding
   centerline velocities and the existing Ghia numerical reference. Use the
   existing maximum-error target of 0.06 lid-speed units for each solver. This
   is numerical cross-checking, not experimental validation.
3. Fetch the Driver–Seegmiller backward-facing-step raw measurements from TMR
   with frozen SHA-256 identities and explicit provenance. Do not make CI
   depend on restricted data or bundle another project's licensed code.
   Use the upstream x/H=-4 mean-velocity profile as an inlet condition;
   downstream x/H=1,4,6,10 profiles remain evaluation data.
4. Freeze a development comparison protocol **before running the case**:
   downstream mean-U profile RMSE <=0.10 Uref at each station, lower-wall Cf
   RMSE <=0.001, and reattachment error <=0.75 H against 6.26 H. These are
   project screening targets, not published certification criteria. Retain
   failed metrics. Experimental uncertainty of reattachment is +/-0.10 H;
   profile uncertainty and unmeasured inlet turbulence components must remain
   explicit. A single coarse comparison cannot qualify the native canyon model.
5. Execute a small mesh series where cloud budgets permit. Report convergence,
   input assumptions and mesh sensitivity separately from measurement error.
   Do not tune constants or relax thresholds after observing predictions.
6. Add negative tests for corrupted input/data/sample identity, malformed or
   nonfinite results, incomplete execution, timeout, version mismatch and
   optimized-Python behavior. Run repository-required Rust and Python checks.
7. Provide an agent prompt, reproduction guide, results and an implementation
   log. Package a patch against the exact merged base and check application on
   a pristine checkout. Keep generated large fields outside the source tree.

## Deliberate limits

No new native physics or claimed Rust speed advantage. The native wall
roughness and pressure throughput still need their own numerical iteration.
The external backstep uses its own documented RANS/inlet package; it does not
inherit the native canyon's assumptions. No scalar-dispersion validation is
implied by a velocity-only experiment. No home hardware, purchases, owner
contact, publication or deployment is needed.

## Primary references

- [TMR experiment description and raw files](https://tmbwg.github.io/turbmodels/backstep_val.html).
- Driver and Seegmiller (1985), DOI: [10.2514/3.8890](https://doi.org/10.2514/3.8890).
- [Foundation 13 incompressibleFluid module](https://cpp.openfoam.org/v13/classFoam_1_1solvers_1_1incompressibleFluid.html).
- [NASA validation assessment](https://www.grc.nasa.gov/www/wind/valid/tutorial/valassess.html).
