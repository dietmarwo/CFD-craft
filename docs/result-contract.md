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

Source identity is package-safe: each crate fingerprints its Rust sources,
manifest, build script and source lockfile; the CLI combines its fingerprint
with the core's. A direct library call identifies the core, while the Python
binding also identifies its native wrapper. Cargo normalizes packaged manifests
and lockfiles, so registry and checkout builds can have different fingerprints.
These are distribution identities, not a guarantee that a downstream consumer
resolved exactly that lockfile. Applications embedding the library should also
record their own resolved Cargo.lock and application build identity.

- case.json: normalized consumed case.
- summary.json: actual stopping reason, checks, physical scales, work and receptor values.
- geometry.json: cell counts, connected components, mask hash and the cells of each box.
- probes.csv: final receptor values in kg/m3.
- fields.json: optional state archive including native face velocities.
- checkpoint.json: optional restart wrapper with payload checksum and physics identity.
- manifest.json: file hashes, artifacts omitted for the output budget, the input case file hash, source/executable/build identity, initial-state hash and platform/thread scope.
- complete.json: manifest checksum, written last.

The manifest identifies the actual initial state as well as the case. Two restarts of the same case from different accepted states therefore remain distinguishable. Keep parent checkpoints when their initial states must be reproduced.

Checkpoint compatibility excludes `name`, `output` and the whole `run` section (mode, horizon, budgets, threads) from the physics hash. Changing the requested endpoint can change the last clipped timestep; exact step-for-step restart comparisons interrupt a run by its work budget while preserving the same physical endpoint. Reject checkpoints beyond the new requested horizon.

The run directory is created before the solve: a missing parent (CFD-E063) or an existing destination (CFD-E062) fails at once. The output estimate in the check report bounds what a run writes: the fields and checkpoint, the monitor history they carry, and the case, summary and probe text, which grow with the receptors, boxes and sources. A run that passed the check therefore does not normally omit anything. Files use atomic temporary-write/rename publication. If fields or the checkpoint would exceed the output budget, they are omitted and listed in the manifest under `omitted`; the small artifacts are still written and the run exits 2. Complete files can describe a numerically incomplete run.

`report` rejects an archive with CFD-E064 when the completion marker or manifest is missing or altered, a listed artifact changed, an entry is not listed, a file is not a regular file, an artifact the case requested is missing without being listed as omitted, summary.json does not describe case.json, the manifest and summary disagree on the source or initial state, or the manifest has an unsupported schema, lacks a required small artifact or lists an unknown artifact name. For an archive whose manifest lists omitted artifacts it prints the summary, repeats CFD-E061 with the omitted names on stderr, and exits 0. Unkeyed hashes do not stop someone from rewriting and rehashing an archive on purpose; validation/check_fields.py recomputes the physics checks for that reason.

With an implicit `numerics.steady_algorithm`, `summary.json` also reports
`momentum_solver_iterations`, the cumulative inner iterations of the implicit
momentum-correction solves; `steps` then counts outer iterations. The field is
omitted for the explicit default, as is the matching checkpoint field, so
existing results and checkpoints are unchanged. With constituents, the
archived state (fields and checkpoint) also carries `scalar_time_s`, the
pseudo-time the constituents covered: an implicit algorithm advances them in at
most 16 explicit stable sub-steps per outer iteration, so it can be less than
`time_s`, and emitted mass equals the source rate times it. Explicit runs omit
it (it equals `time_s` there).

## Numerical check scope

Current steady targets are normalized local continuity 1e-4, net boundary balance 1e-5, physical equation residual from the case, and three stable monitor windows. Scalar cumulative relative budget defect is bounded by 1e-9, with tighter results observed on analytic fixtures. Floor events are forbidden for accepted turbulence runs.

Steady scalar acceptance additionally requires instantaneous source plus inflow to balance outflow within 1e-6 of a declared flux scale. Initial mass supplies a fixed absolute scale for source-free decay. A growing concentration cannot pass merely by making its relative equation residual small. Steady source support in an unanchored fluid component is rejected before time stepping.

The turbulence-floor counter refers to state updates. The separate wall algebraic epsilon minimum is part of the documented prototype wall model; it is not an additional independent acceptance certificate.

The Rust application recomputes checks from the fields. The Python checker separately reconstructs current continuity, mass, source-rate/time accounting and the recorded cumulative-budget equation. Full time-history flux reconstruction and independent turbulent-equation evaluation are not claimed.

Missing/unavailable numeric values are JSON null with an explicit context. Compare them as unavailable values, not zero. Numerical repeatability is scoped to a tested executable/platform/work budget. Wall-time-limited iteration counts are not reproducibility targets.
