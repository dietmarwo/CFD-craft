# Release qualification

Version 0.1.0 is a source research prototype, with an explicitly open experimental canyon-validation gate.

Before a new source release:

1. Use a clean checkout and committed lockfiles. Run fmt, clippy, Rust tests and Python CLI tests in normal and optimized mode.
2. Reproduce analytic flow/transport, cavity, independent sparse reference and empty-ABL results.
3. Reproduce canonical canyon smoke/sensitivity cases. Keep every failed refinement case.
4. Record the actual executable/source hashes, compiler, initial-state identity and dependency versions.
5. Check input/output schemas and all documented examples.
6. Build/test the optional worker independently and check actual runner result states.

Before a physically validated canyon release, additionally acquire authorized measured data, reconstruct the exact setup, freeze the sample/threshold protocol before held-out evaluation, and obtain successful grid/domain studies with uncertainty appropriate to the claimed effect.

Tagging, publishing packages and commissioning machines are separate user actions. The current package does not imply any of them occurred.
