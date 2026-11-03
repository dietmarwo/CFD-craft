# CFD-craft 0.1.0 — experimental release

The native solver is a research prototype. Experimental canyon validation,
measured-data access and successful finer-grid/domain evidence remain open.
An experimental package release does not claim physical qualification.

Prepared distributions:
- PyPI `cfd-craft==0.1.0` (ABI3, Python >=3.10).
- Rust crates: `cfd-craft`, `cfd-craft-cli` at 0.1.0.

The new Python API runs the Rust solver in-process, releases the GIL, shares
strict CLI preflight and returns native summaries. It supports cooperative
cancellation and Python interrupts. The native CLI remains the archive, field,
restart and profile interface. Package-safe source fingerprints cover the core
and the active wrapper. No numerical default or acceptance threshold changed.

Release automation verifies crate archives, rebuilt sdists and installed wheels.
Platform matrix results must pass before publication; locally tested Linux
artifacts alone do not establish Windows/macOS acceptance. See RELEASING.md for
the exact publishing and post-publication checks.
