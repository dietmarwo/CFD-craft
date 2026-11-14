#![forbid(unsafe_code)]
#![warn(missing_docs)]
//! The core library of [CFD-craft](https://github.com/dietmarwo/CFD-craft): a
//! bounded, inspectable CPU research solver for incompressible flow on
//! uniform Cartesian grids and conservative passive-gas dispersion, built to
//! be driven and checked by programs and agents.
//!
//! A case is data: one strict JSON document ([`case::Case`]) declares the
//! domain, grid, boundaries, flow model, solid boxes, constituents, sources,
//! receptors, numerics and every budget. A run reports why it stopped, what
//! its recomputed numerical checks support, the model scope, and the identity
//! of its input, initial state and build.
//!
//! # Status
//!
//! Version 0.1.1 is a **research prototype**. The coarse finite-canyon
//! examples converge under independent continuity and mass checks.
//! Experimental canyon validation (blocked by access to raw benchmark data)
//! and a successful fine-grid resolution study remain open; the first
//! finer-grid study exceeded its compute budgets. These are
//! physical-qualification gates: a numerically accepted run is not
//! experimentally validated urban CFD, and every result says so in
//! [`Summary::experimental_validation`](solver::Summary::experimental_validation).
//!
//! The release scope is uniform grids, box geometry, passive gas and CPU
//! execution. Particles, vegetation, LES, chemistry, annual statistics,
//! stretched grids, masked multigrid and GPU execution are not implemented.
//! See the [roadmap](https://github.com/dietmarwo/CFD-craft/blob/main/docs/developer/roadmap.md),
//! the [recorded results](https://github.com/dietmarwo/CFD-craft/blob/main/docs/evidence/native-verification.md)
//! and the [model cards](https://github.com/dietmarwo/CFD-craft/blob/main/docs/model-cards/README.md).
//!
//! # What is implemented
//!
//! - Staggered finite volumes with face velocities, box masks and
//!   fluid-component discovery ([`grid`]).
//! - Matrix-free pressure projection with one gauge per closed fluid
//!   component, IC(0)-preconditioned PCG by default and opt-in symmetric
//!   multigrid on unmasked grids ([`pressure`], [`multigrid`]).
//! - Laminar flow, moving walls and one neutral k-epsilon package with
//!   rough-wall functions ([`flow`]); donor-cell or opt-in conservative
//!   second-order momentum advection; SSPRK2 pseudo-time or opt-in implicit
//!   steady algorithms ([`momentum_solve`], [`turbulence_solve`]).
//! - Passive gas with point, line and volume sources and point or
//!   volume-average receptors, by first-order upwind or bounded MUSCL
//!   transport ([`transport`]).
//! - Explicit step, time, memory and output budgets, cooperative
//!   cancellation, transactional steps, checksummed restarts and run archives
//!   ([`solver`], [`output`]), and opt-in phase profiling ([`profiling`]).
//!
//! # Entry points
//!
//! | Task | API |
//! |---|---|
//! | Parse a case strictly, with JSON paths in errors | [`input::parse_case`] |
//! | Check a case (coded diagnostics, estimates) | [`Case::check`](case::Case::check), [`Case::validate`](case::Case::validate), [`input::full_check`] |
//! | Run a case within limits | [`solver::run`] with a [`Control`](solver::Control) |
//! | Read the outcome | [`RunResult`](solver::RunResult): [`Summary`](solver::Summary), [`State`](solver::State) |
//! | Save and resume | [`output::checkpoint_bytes`], [`output::read_checkpoint`] |
//! | Publish or verify a run archive | [`output::create_run_dir`], [`output::write_run`], [`output::read_verified`] |
//! | Measure solver phases | [`Control::with_profiling`](solver::Control::with_profiling), [`profiling::Profile`] |
//!
//! For ordinary applications prefer these to the low-level modules. Grid,
//! face and state vectors can be used directly, but they carry invariants
//! (layout, gauges, fixed boundary faces) that the module docs state.
//!
//! # Quickstart
//!
//! A point source in a uniform 1 m/s flow, solved to a steady state on a
//! 32-cell grid:
//!
//! ```
//! use cfd_craft::{input, solver::{self, Control}};
//!
//! let json = r#"{
//!   "schema_version": "cfd-craft.case/0.1", "name": "quickstart",
//!   "domain": {"size_m": [4.0, 1.0, 1.0]}, "grid": {"cells": [8, 2, 2]},
//!   "boundaries": {"x": "open", "y": "periodic", "z": "periodic"},
//!   "flow": {"kind": "prescribed_uniform", "velocity_m_s": [1.0, 0.0, 0.0]},
//!   "constituents": [{"id": "tracer", "diffusivity_m2_s": 0.01}],
//!   "sources": [{"kind": "point", "id": "S0", "constituent": "tracer",
//!                "point_m": [0.5, 0.5, 0.5], "rate_kg_s": 1e-6}],
//!   "receptors": [{"kind": "point", "id": "R1", "point_m": [3.0, 0.5, 0.5]}],
//!   "numerics": {"transport": "linear_upwind", "max_time_step_s": 1.0,
//!     "advective_cfl_max": 0.4, "pressure_relative_tolerance": 1e-10,
//!     "pressure_max_iterations": 100, "steady_residual_tolerance": 1e-5,
//!     "steady_monitor_tolerance": 1e-3, "monitor_window": 10},
//!   "run": {"mode": "steady", "end_time_s": 1.0, "max_steps": 2000,
//!     "wall_time_limit_s": 30.0, "threads": 1, "memory_limit_mib": 64},
//!   "output": {"fields": false, "checkpoint": false, "max_total_mib": 4}
//! }"#;
//!
//! // Strict parsing: an unknown field fails as CFD-E000 with its JSON path.
//! let case = input::parse_case(json.as_bytes())
//!     .map_err(|report| serde_json::to_string(&report).unwrap())?;
//! // Semantic checks: ranges, units, budgets and geometry.
//! case.validate()?;
//!
//! let control = Control::new(case.run.wall_time_limit_s);
//! let result = solver::run(&case, &control, None)?;
//! let summary = &result.summary;
//! // Ok(..) can still be cancelled or incomplete: read both verdicts.
//! assert_eq!(summary.termination, "completed");
//! assert_eq!(summary.assessment, "steady_discrete_solution");
//! assert!(summary.checks.iter().all(|check| check.passed));
//!
//! // Look receptors up by ID. Downstream, the plume has mixed over the
//! // 1 m2 cross-section, so the concentration approaches rate / (U A).
//! let tracer = summary.constituents.iter().find(|c| c.id == "tracer").unwrap();
//! let r1 = tracer.receptors_kg_m3["R1"];
//! assert!((r1 - 1e-6).abs() < 1e-8);
//! println!("R1 = {:.3} micrograms/m3 after {} steps", r1 * 1e9, summary.steps);
//! # Ok::<(), String>(())
//! ```
//!
//! The library does not create a Rayon thread pool from `run.threads`; run
//! [`solver::run`] inside `pool.install` when thread accounting matters. The
//! CLI and the Python binding do this, and also own signal handling, host
//! memory preflight and archive provenance.
//!
//! # Conventions
//!
//! - SI units, named in the field suffixes (`_m`, `_m_s`, `_kg_s`, `_kg_m3`).
//!   Concentrations are kg/m3; multiply by 1e9 for micrograms/m3. Pressure is
//!   kinematic, m2/s2.
//! - Coordinates are local east (x), north (y) and up (z). Wind directions
//!   are meteorological: where the wind blows from, clockwise from north.
//! - Cells are ordered x fastest, index `(k * ny + j) * nx + i`; face arrays
//!   are concatenated by axis (see [`grid::Grid`]).
//! - Errors are [`Result`] with a `String` message that starts with a stable
//!   code such as `CFD-E033`, listed in the
//!   [diagnostics catalog](https://github.com/dietmarwo/CFD-craft/blob/main/docs/diagnostics.md).
//!   Match the code, not the English text.
//!
//! # Related crates and documents
//!
//! - [`cfd-craft-cli`](https://crates.io/crates/cfd-craft-cli): the
//!   `cfd-craft` command (`describe`, `check`, `run`, `profile`, `preview`,
//!   `report`, `verify`) with checksummed archives, restarts and signals.
//! - [`cfd-craft` on PyPI](https://pypi.org/project/cfd-craft/): the Python
//!   binding (`check`, `simulate`, `describe`), see the
//!   [Python chapter](https://dietmarwo.github.io/CFD-craft/guide/11-python.html).
//! - The [guide](https://dietmarwo.github.io/CFD-craft/guide/) explains the
//!   numerical and evidence concepts in worked chapters, ordered by
//!   difficulty; its [Rust library chapter](https://dietmarwo.github.io/CFD-craft/guide/20-rust-library.html)
//!   covers this crate.
//! - The [result contract](https://github.com/dietmarwo/CFD-craft/blob/main/docs/result-contract.md)
//!   defines termination, assessment, archives and identities; the
//!   [flow](https://github.com/dietmarwo/CFD-craft/blob/main/docs/model-cards/flow.md)
//!   and [transport](https://github.com/dietmarwo/CFD-craft/blob/main/docs/model-cards/transport.md)
//!   model cards state the numerical methods and their limits.
//! - [Runnable library examples](https://github.com/dietmarwo/CFD-craft/tree/main/crates/cfd-craft/examples)
//!   and the [repository](https://github.com/dietmarwo/CFD-craft) with its
//!   verification cases, independent checkers and recorded evidence.
pub mod case;
pub mod flow;
pub mod grid;
pub mod momentum_solve;
pub mod multigrid;
pub mod output;
pub mod pressure;
pub mod profiling;
pub mod solver;
pub mod transport;
pub mod turbulence_solve;
pub mod verification;

/// Result of the fallible library functions. The error is a message that
/// normally starts with a stable code (`CFD-E…: …`). For an invalid case,
/// [`case::Case::validate`] and the functions that call it, such as
/// [`grid::Grid::build`] and [`solver::run`], return the serialized
/// [`case::CheckReport`] instead.
pub type Result<T> = std::result::Result<T, String>;

pub mod input;
/// Fingerprint of the core package sources and its build lockfile.
///
/// Lowercase hex SHA-256 over this crate's `src` Rust files, build script
/// and manifest, plus the root workspace manifest and lockfile in a checkout,
/// or the packaged lockfile in a crates.io build, so the two differ. A bare
/// library run reports it as `source_sha256`; the CLI and the Python binding
/// combine it with their own fingerprints.
pub const SOURCE_SHA256: &str = env!("CFD_SOURCE_SHA");
/// Compiler used to build the core: the `rustc --version` line, part of the
/// summary's `build_version`.
pub const RUSTC_VERSION: &str = env!("CFD_RUSTC");
