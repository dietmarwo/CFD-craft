# Working on CFD-craft

Read README.md, docs/ai-context.md and the model card for the component being changed.

Run relevant tests with --locked. Required core checks are cargo fmt, clippy -D warnings, and cargo test --release --workspace --locked. Python evidence checks use explicit exceptions and must retain their behavior under python -O.

Keep native termination, numerical assessment and experimental validation separate. Do not weaken tolerances after seeing a failure. Preserve failed runs in reports. Claims must refer to the actual returned fields, consumed case, initial state and implementation.

Changes to pressure operators require topology/nullspace, projection and independent reference tests. Changes to transport require mass, positivity, unit normalization and refinement checks. Changes to RANS require the empty-ABL check and a published model-card change. A faster iteration with weaker accuracy is not a performance improvement.

Keep this release uniform-grid, passive-gas, CPU scope. Add a new physics model only with a concrete verification/validation fixture. Do not copy separately licensed CFD implementations into the MIT core. Keep generated large fields, private data and host paths outside canonical repository documentation.
