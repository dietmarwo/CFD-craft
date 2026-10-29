# Case, result and provenance

The public schemas are generated from the actual types by cfd-craft describe. Case version is cfd-craft.case/0.1. Result version is cfd-craft.result/0.1. Unknown fields, unsupported variants and duplicate object fields are rejected by the typed parser; semantic checks enforce physical values, geometry and budgets.

The illustrative JSON in the earlier planning document was a draft. Use the canonical files in cases/ and the current describe output. This release fixes uniform grids and passive mass in its type definitions instead of accepting unused kind tags.

## Status

Termination describes why execution stopped. Assessment describes what its numerical checks support. Experimental validation is a separate label/report.

| Situation | Termination | Assessment |
|---|---|---|
| Steady criteria all met | completed | steady_discrete_solution |
| Requested physical interval completed, checks met | completed | transient_interval_completed |
| Budget or cancellation before completion | iteration_limit / wall_time_limit / cancelled | incomplete |
| Complete execution with failed checks | completed | failed_checks |
| Failed numerical step | diverged | incomplete |

A failed step is not committed. The saved state is the last accepted state and the error records the attempted-step failure. Passing checks on that earlier state does not promote an incomplete run.

## Files

- case.json: normalized consumed case.
- summary.json: actual stopping reason, checks, physical scales, work and receptor values.
- geometry.json: cell counts, connected components and mask hash.
- probes.csv: final receptor values in kg/m3.
- fields.json: optional state archive including native face velocities.
- checkpoint.json: optional restart wrapper with payload checksum and physics identity.
- manifest.json: file hashes, source/executable/build identity, initial-state hash and platform/thread scope.
- complete.json: manifest checksum, written last.

The manifest identifies the actual initial state as well as the case. Two restarts of the same case from different accepted states therefore remain distinguishable. Keep parent checkpoints when their initial states must be reproduced.

Checkpoint compatibility excludes the name, output policy and run budgets from the physics hash. Changing the requested endpoint can change the last clipped timestep; exact step-for-step restart comparisons interrupt a run by its work budget while preserving the same physical endpoint. Reject checkpoints beyond the new requested horizon.

Files use atomic temporary-write/rename publication and refuse occupied run directories. Complete files can describe a numerically incomplete run. Removing a completion marker or altering a hashed artifact makes report reject the archive.

## Numerical check scope

Current steady targets are normalized local continuity 1e-4, net boundary balance 1e-5, physical equation residual from the case, and three stable monitor windows. Scalar cumulative relative budget defect is bounded by 1e-9, with tighter results observed on analytic fixtures. Floor events are forbidden for accepted turbulence runs.

Steady scalar acceptance additionally requires instantaneous source plus inflow to balance outflow within 1e-6 of a declared flux scale. Initial mass supplies a fixed absolute scale for source-free decay. A growing concentration cannot pass merely by making its relative equation residual small. Steady source support in an unanchored fluid component is rejected before time stepping.

The turbulence-floor counter refers to state updates. The separate wall algebraic epsilon minimum is part of the documented prototype wall model; it is not an additional independent acceptance certificate.

The Rust application recomputes checks from the fields. The Python checker separately reconstructs current continuity, mass, source-rate/time accounting and the recorded cumulative-budget equation. Full time-history flux reconstruction and independent turbulent-equation evaluation are not claimed.

Missing/unavailable numeric values are JSON null with an explicit context. Compare them as unavailable values, not zero. Numerical repeatability is scoped to a tested executable/platform/work budget. Wall-time-limited iteration counts are not reproducibility targets.
