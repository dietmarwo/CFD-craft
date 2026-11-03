#![forbid(unsafe_code)]
//! A bounded, inspectable CPU research solver. See the model cards for scope.
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

pub type Result<T> = std::result::Result<T, String>;

pub mod input;
/// Fingerprint of the core package sources and its build lockfile.
pub const SOURCE_SHA256: &str = env!("CFD_SOURCE_SHA");
/// Compiler used to build the core.
pub const RUSTC_VERSION: &str = env!("CFD_RUSTC");
