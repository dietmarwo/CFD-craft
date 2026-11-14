//! Opt-in wall-time accounting at solver phase boundaries.
//!
//! Inclusive phases nest; only exclusive times can be added. One collector can
//! be shared by callers on different threads, with a separate stack per thread.
//! No lock or clock read is required inside a numerical cell/PCG iteration.
//!
//! Enable it with [`Control::with_profiling`](crate::solver::Control::with_profiling)
//! and read the [`Profile`] with
//! [`Control::profile`](crate::solver::Control::profile) after the solve.
//! The CLI's `profile` command writes the same record into its
//! `cfd-craft.native-profile/0.1` envelope; its JSON schema is the
//! `phase_profile_schema` of `cfd-craft describe`. See the
//! [profiling guide](https://github.com/dietmarwo/CFD-craft/blob/main/docs/developer/profiling.md).
//!
//! ```
//! # let json = r#"{"schema_version": "cfd-craft.case/0.1", "name": "tiny",
//! #   "domain": {"size_m": [4.0, 1.0, 1.0]}, "grid": {"cells": [8, 2, 2]},
//! #   "boundaries": {"x": "open", "y": "periodic", "z": "periodic"},
//! #   "flow": {"kind": "laminar", "initial_velocity_m_s": [1.0, 0.0, 0.0],
//! #            "viscosity_m2_s": 0.1},
//! #   "numerics": {"transport": "linear_upwind", "max_time_step_s": 1.0,
//! #     "advective_cfl_max": 0.4, "pressure_relative_tolerance": 1e-10,
//! #     "pressure_max_iterations": 100, "steady_residual_tolerance": 1e-5,
//! #     "steady_monitor_tolerance": 1e-3, "monitor_window": 10},
//! #   "run": {"mode": "steady", "end_time_s": 1.0, "max_steps": 3,
//! #     "wall_time_limit_s": 30.0, "threads": 1, "memory_limit_mib": 64},
//! #   "output": {"fields": false, "checkpoint": false, "max_total_mib": 4}}"#;
//! use cfd_craft::{case::Case, solver::{self, Control}};
//!
//! let case: Case = serde_json::from_str(json).unwrap();
//! let control = Control::new(30.0).with_profiling();
//! let result = solver::run(&case, &control, None)?;
//! let profile = control.profile()?.expect("profiling enabled");
//! assert_eq!(profile.phases["step"].calls, 3);
//! // Exclusive times add up; inclusive times nest and must not be summed.
//! let total: f64 = profile.phases.values().map(|p| p.exclusive_s).sum();
//! assert!((total - profile.accounted_exclusive_s).abs() < 1e-12);
//! // Attempted pressure work covers at least the retained iterations.
//! assert!(profile.phases["pressure_solve"].work_units >= result.summary.pressure_iterations as u64);
//! # Ok::<(), String>(())
//! ```
use crate::Result;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, HashMap},
    marker::PhantomData,
    rc::Rc,
    sync::{Arc, Mutex},
    thread::{self, ThreadId},
    time::{Duration, Instant},
};

/// A measured solver phase. Its snake_case name (for example
/// `pressure_solve`) is the key in [`Profile::phases`]. Phases nest: an
/// enclosing phase's inclusive time contains its subphases.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    /// One whole [`solver::run`](crate::solver::run) call.
    SolverRun,
    /// Semantic case checks at the start of a run.
    CaseValidation,
    /// Building the grid.
    GridSetup,
    /// Source densities and receptor weights.
    InputSetup,
    /// Initial or restart state, its validation and hash.
    StateSetup,
    /// Choosing the next time step, including the eddy-viscosity check.
    Timestep,
    /// One transactional step with its momentum, pressure, turbulence and
    /// scalar subphases.
    Step,
    /// Evaluating the momentum right-hand side.
    MomentumRhs,
    /// Inexact implicit momentum-correction solves; work units are inner iterations.
    MomentumSolve,
    /// Forming the momentum update (and assembling implicit matrices) before
    /// the projection.
    VelocityUpdate,
    /// A pressure projection, including its solve.
    PressureProjection,
    /// A pressure PCG solve; work units are attempted iterations.
    PressureSolve,
    /// Building the cached IC(0) factor; occurs only when it is built.
    PressureFactorSetup,
    /// Building the multigrid hierarchy; occurs only when it is (re)built.
    PressureMultigridSetup,
    /// Gathering the compact operator of one pressure solve.
    PressureOperatorSetup,
    /// A k-epsilon update: in each `neutral_rans` step, and once after the
    /// initial projection.
    Turbulence,
    /// Inexact implicit k and ε correction solves; work units are inner iterations.
    TurbulenceSolve,
    /// Transport of one constituent within a step.
    ScalarTransport,
    /// Checking the candidate state before it is committed.
    StateValidation,
    /// Appending a monitor row.
    Monitor,
    /// Recomputing the numerical checks.
    Assessment,
    /// Writing the run archive (CLI).
    ArchiveWrite,
}

/// Accumulated time and work of one phase over all its calls.
#[derive(Clone, Debug, Default, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct PhaseTiming {
    /// Number of finished spans of this phase.
    pub calls: u64,
    /// Wall seconds including nested phases. Do not add these up.
    pub inclusive_s: f64,
    /// Wall seconds excluding nested phases; these add up to
    /// `accounted_exclusive_s`.
    pub exclusive_s: f64,
    /// Attempted inner iterations: PCG for pressure_solve, the implicit
    /// correction solves for momentum_solve and turbulence_solve; zero for other phases.
    pub work_units: u64,
    /// Operator products: the compact pressure products plus the independent
    /// true-residual products of pressure_solve, and one (CG) or two
    /// (BiCGStab) per inner iteration of the implicit solves.
    pub operator_applications: u64,
    /// Applications of the selected preconditioner.
    pub preconditioner_applications: u64,
    /// Independent face-by-face residual recomputations of pressure_solve.
    pub true_residual_checks: u64,
    /// Multilevel work of pressure_solve with the multigrid preconditioner;
    /// omitted otherwise.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub multigrid: Option<crate::multigrid::MultigridWork>,
}

/// A phase profile (schema `cfd-craft.phase-profile/0.1`): wall time and
/// work per solver phase. Only exclusive times may be added. Work includes
/// failed attempts, so it can exceed the counters of the retained state.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    /// Always `cfd-craft.phase-profile/0.1`.
    pub schema_version: String,
    /// Wall seconds since the control was created, at the snapshot.
    pub elapsed_s: f64,
    /// Sum of the exclusive seconds of all phases.
    pub accounted_exclusive_s: f64,
    /// Elapsed minus exclusive phases for a single serial invocation. Parallel
    /// callers may have aggregate phase time exceeding elapsed wall time.
    pub unattributed_s: f64,
    /// Timing of each phase that ran, keyed by its snake_case phase name.
    pub phases: BTreeMap<String, PhaseTiming>,
}

#[derive(Default)]
struct Frame {
    id: u64,
    children: Duration,
}
#[derive(Default)]
struct Data {
    phases: BTreeMap<String, PhaseTiming>,
    stacks: HashMap<ThreadId, Vec<Frame>>,
    next_id: u64,
    invalid_nesting: bool,
}
#[derive(Clone, Default)]
pub(crate) struct Collector(Arc<Mutex<Data>>);

impl Collector {
    pub(crate) fn span(&self, phase: Phase) -> Span {
        let thread = thread::current().id();
        let mut data = self.0.lock().unwrap_or_else(|e| e.into_inner());
        let id = data.next_id;
        data.next_id += 1;
        data.stacks.entry(thread).or_default().push(Frame {
            id,
            ..Frame::default()
        });
        Span {
            active: Some((self.clone(), phase, thread, id, Instant::now())),
            work_units: 0,
            operator_applications: 0,
            preconditioner_applications: 0,
            true_residual_checks: 0,
            multigrid: None,
            // A span must finish on the thread whose phase stack it entered.
            _same_thread: PhantomData,
        }
    }
    pub(crate) fn snapshot(&self, elapsed_s: f64) -> Result<Profile> {
        let data = self.0.lock().unwrap_or_else(|e| e.into_inner());
        if data.invalid_nesting {
            return Err("CFD-B003 profile.nesting: spans must finish in nested order".into());
        }
        if data.stacks.values().any(|s| !s.is_empty()) {
            return Err("CFD-B003 profile.active: finish all phase spans before snapshot".into());
        }
        let phases = data.phases.clone();
        let accounted_exclusive_s = phases.values().map(|p| p.exclusive_s).sum::<f64>();
        Ok(Profile {
            schema_version: "cfd-craft.phase-profile/0.1".into(),
            elapsed_s,
            accounted_exclusive_s,
            unattributed_s: elapsed_s - accounted_exclusive_s,
            phases,
        })
    }
}

/// A scoped timer; disabled spans do not read a clock or acquire a lock.
/// Dropping on an error path retains the attempted phase and its work.
///
/// Created by [`Control::span`](crate::solver::Control::span). A span is not
/// `Send`: it must finish on the thread that started it.
pub struct Span {
    active: Option<(Collector, Phase, ThreadId, u64, Instant)>,
    pub(crate) work_units: u64,
    pub(crate) operator_applications: u64,
    pub(crate) preconditioner_applications: u64,
    pub(crate) true_residual_checks: u64,
    pub(crate) multigrid: Option<crate::multigrid::MultigridWork>,
    _same_thread: PhantomData<Rc<()>>,
}
impl Span {
    pub(crate) fn disabled() -> Self {
        Self {
            active: None,
            work_units: 0,
            operator_applications: 0,
            preconditioner_applications: 0,
            true_residual_checks: 0,
            multigrid: None,
            _same_thread: PhantomData,
        }
    }
}
impl Drop for Span {
    fn drop(&mut self) {
        let Some((collector, phase, thread, id, began)) = &self.active else {
            return;
        };
        let elapsed = began.elapsed();
        let mut data = collector.0.lock().unwrap_or_else(|e| e.into_inner());
        if data.stacks.get(thread).and_then(|s| s.last()).map(|f| f.id) != Some(*id) {
            data.invalid_nesting = true;
            if let Some(stack) = data.stacks.get_mut(thread) {
                stack.retain(|f| f.id != *id);
            }
            return;
        }
        let stack = data.stacks.get_mut(thread).expect("phase thread stack");
        let frame = stack.pop().expect("phase span stack");
        if let Some(parent) = stack.last_mut() {
            parent.children += elapsed;
        }
        if stack.is_empty() {
            data.stacks.remove(thread);
        }
        let key = serde_json::to_value(phase)
            .expect("phase name")
            .as_str()
            .expect("phase string")
            .to_string();
        let timing = data.phases.entry(key).or_default();
        timing.calls += 1;
        timing.inclusive_s += elapsed.as_secs_f64();
        timing.exclusive_s += elapsed.saturating_sub(frame.children).as_secs_f64();
        timing.work_units += self.work_units;
        timing.operator_applications += self.operator_applications;
        timing.preconditioner_applications += self.preconditioner_applications;
        timing.true_residual_checks += self.true_residual_checks;
        if let Some(work) = &self.multigrid {
            timing
                .multigrid
                .get_or_insert_with(Default::default)
                .merge(work);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn out_of_order_spans_are_rejected_instead_of_publishing_bad_accounting() {
        let c = Collector::default();
        let outer = c.span(Phase::SolverRun);
        let inner = c.span(Phase::Step);
        drop(outer);
        drop(inner);
        assert!(c.snapshot(1.0).unwrap_err().contains("profile.nesting"));
    }
    #[test]
    fn nested_time_is_counted_once_and_active_snapshots_are_rejected() {
        let collector = Collector::default();
        let start = Instant::now();
        {
            let _outer = collector.span(Phase::SolverRun);
            let mut inner = collector.span(Phase::PressureSolve);
            inner.work_units = 7;
            assert!(
                collector
                    .snapshot(0.0)
                    .unwrap_err()
                    .contains("profile.active")
            );
        }
        let p = collector.snapshot(start.elapsed().as_secs_f64()).unwrap();
        let outer = &p.phases["solver_run"];
        let inner = &p.phases["pressure_solve"];
        assert_eq!(inner.calls, 1);
        assert_eq!(inner.work_units, 7);
        assert!((outer.exclusive_s + inner.inclusive_s - outer.inclusive_s).abs() < 1e-12);
        assert!(p.unattributed_s >= 0.0);
    }
    #[test]
    fn thread_stacks_do_not_mix() {
        let collector = Collector::default();
        std::thread::scope(|s| {
            for _ in 0..2 {
                let c = collector.clone();
                s.spawn(move || {
                    let _outer = c.span(Phase::SolverRun);
                    let _inner = c.span(Phase::Step);
                });
            }
        });
        let p = collector.snapshot(0.0).unwrap();
        assert_eq!(p.phases["solver_run"].calls, 2);
        assert_eq!(p.phases["step"].calls, 2);
        assert!((p.accounted_exclusive_s - p.phases["solver_run"].inclusive_s).abs() < 1e-12);
    }
}
