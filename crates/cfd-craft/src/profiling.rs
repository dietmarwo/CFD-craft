//! Opt-in wall-time accounting at solver phase boundaries.
//!
//! Inclusive phases nest; only exclusive times can be added. One collector can
//! be shared by callers on different threads, with a separate stack per thread.
//! No lock or clock read is required inside a numerical cell/PCG iteration.
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

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    SolverRun,
    CaseValidation,
    GridSetup,
    InputSetup,
    StateSetup,
    Timestep,
    Step,
    MomentumRhs,
    VelocityUpdate,
    PressureProjection,
    PressureSolve,
    PressureFactorSetup,
    PressureOperatorSetup,
    Turbulence,
    ScalarTransport,
    StateValidation,
    Monitor,
    Assessment,
    ArchiveWrite,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct PhaseTiming {
    pub calls: u64,
    pub inclusive_s: f64,
    pub exclusive_s: f64,
    /// Attempted PCG iterations for pressure_solve; zero for other phases.
    pub work_units: u64,
    pub operator_applications: u64,
    pub preconditioner_applications: u64,
    pub true_residual_checks: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    pub schema_version: String,
    pub elapsed_s: f64,
    pub accounted_exclusive_s: f64,
    /// Elapsed minus exclusive phases for a single serial invocation. Parallel
    /// callers may have aggregate phase time exceeding elapsed wall time.
    pub unattributed_s: f64,
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
pub struct Span {
    active: Option<(Collector, Phase, ThreadId, u64, Instant)>,
    pub(crate) work_units: u64,
    pub(crate) operator_applications: u64,
    pub(crate) preconditioner_applications: u64,
    pub(crate) true_residual_checks: u64,
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
