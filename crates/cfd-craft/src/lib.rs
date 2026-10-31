#![forbid(unsafe_code)]
//! A bounded, inspectable CPU research solver. See the model cards for scope.
pub mod case;
pub mod flow;
pub mod grid;
pub mod output;
pub mod pressure;
pub mod profiling;
pub mod solver;
pub mod transport;
pub mod verification;

pub type Result<T> = std::result::Result<T, String>;
