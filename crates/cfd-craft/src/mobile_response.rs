//! R3: one accepted flow preparation per wind, then cold scalar-only solves.
//!
//! The original scalar SSPRK2 step, stability cap and full returned-field gates
//! are shared with the coupled solver. No pressure, momentum or turbulence
//! update is performed by a response solve. This is an explicit initialization
//! path, not a cross-case restart or a new physical model.
use crate::{
    Result,
    case::*,
    flow,
    grid::Grid,
    solver::{self, Control, RunResult, State},
    transport,
};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// Provenance for scalar responses on one accepted, immutable flow state.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct FrozenFlowEvidence {
    /// Physics hash of the source flow-only case.
    pub flow_physics_sha256: String,
    /// SHA-256 of length-prefixed little-endian f64 velocity,p,k,epsilon arrays.
    pub flow_state_sha256: String,
    /// Source implementation of the accepted flow preparation.
    pub source_sha256: String,
    /// Source flow assessment; only steady_discrete_solution is accepted.
    pub assessment: String,
    /// Coupled flow steps used in the preparation, counted separately.
    pub preparation_steps: usize,
    /// Number of nonprescribed native flow solves: 0 for analytic prescribed flow,1 otherwise.
    pub native_flow_solves: usize,
    /// Flow updates during this scalar response; always zero.
    pub response_flow_updates: usize,
    /// The transport starts from the declared (required zero) concentration field.
    pub initialization: String,
}
/// Hash only the immutable flow arrays, with lengths to distinguish layouts.
pub fn flow_state_hash(state: &State) -> String {
    let mut bytes = Vec::new();
    for v in [&state.velocity, &state.pressure, &state.k, &state.epsilon] {
        bytes.extend_from_slice(&(v.len() as u64).to_le_bytes());
        for x in v {
            bytes.extend_from_slice(&x.to_le_bytes());
        }
    }
    hash_bytes(&bytes)
}
fn flow_case(c: &Case) -> Case {
    let mut f = c.clone();
    f.constituents.clear();
    f.sources.clear();
    f.initial_conditions.clear();
    f.receptors.clear();
    f
}
/// Immutable, bounded accepted flow and its represented topology.
/// Source and receptor choices may change between responses; the flow case may not.
pub struct PreparedFlow {
    case: Case,
    grid: Grid,
    /// Actual accepted native flow result, suitable for a separate sealed archive.
    pub result: RunResult,
    identity: FrozenFlowEvidence,
}
impl PreparedFlow {
    /// Prepare one cold accepted flow. A source-response study requires steady,
    /// linear-upwind transport and zero initial concentration (CFD-E089).
    pub fn prepare(case: &Case, control: &Control) -> Result<Self> {
        let c = Self::preparation_case(case)?;
        let result = solver::run(&c, control, None)?;
        Self::from_accepted(case, result)
    }
    /// Validate all original source/receptor supports before preparing a flow.
    pub fn preparation_case(case: &Case) -> Result<Case> {
        let (check, _) = crate::input::full_check(case);
        if !check.valid {
            return Err(serde_json::to_string(&check).unwrap());
        }
        if case.run.mode != Mode::Steady
            || case.numerics.transport != Advection::LinearUpwind
            || !case.initial_conditions.is_empty()
        {
            return Err("CFD-E089: mobile_response.case: require steady linear_upwind and zero initial concentrations".into());
        }
        Ok(flow_case(case))
    }
    /// Adopt a separately archived flow preparation, preserving failed-flow
    /// archives at the caller. Identity and all field gates are checked again.
    pub fn from_accepted(case: &Case, result: RunResult) -> Result<Self> {
        let c = Self::preparation_case(case)?;
        if result.summary.termination != "completed"
            || result.summary.assessment != "steady_discrete_solution"
            || !result.summary.checks.iter().all(|x| x.passed)
            || result.summary.source_sha256 != crate::SOURCE_SHA256
            || result.summary.case_sha256 != hash_bytes(&serde_json::to_vec(&c).unwrap())
            || result.summary.physics_sha256 != c.physics_hash()
        {
            return Err(format!(
                "CFD-E089: mobile_response.flow: preparation {} / {} or identity mismatch; no response columns produced",
                result.summary.termination, result.summary.assessment
            ));
        }
        let grid = Grid::build(&c)?;
        solver::validate_state(&c, &grid, &result.state)?;
        let (checks, _, _, _) = solver::assess(&c, &grid, &result.state, &[], &[]);
        if !checks.iter().all(|check| check.passed) {
            return Err(
                "CFD-E089: mobile_response.flow: recomputed preparation gates failed".into(),
            );
        }
        let identity = FrozenFlowEvidence {
            flow_physics_sha256: c.physics_hash(),
            flow_state_sha256: flow_state_hash(&result.state),
            source_sha256: result.summary.source_sha256.clone(),
            assessment: result.summary.assessment.clone(),
            preparation_steps: result.state.steps,
            native_flow_solves: usize::from(!c.flow.prescribed()),
            response_flow_updates: 0,
            initialization: "cold_scalar_on_verified_frozen_flow".into(),
        };
        Ok(Self {
            case: c,
            grid,
            result,
            identity,
        })
    }
    /// The consumed source flow-only case, for archived preparation evidence.
    pub fn case(&self) -> &Case {
        &self.case
    }
    /// Cold scalar transport on the frozen flow. All native mass, positivity,
    /// steady-equation, continuity and monitor gates remain required.
    pub fn run(&self, case: &Case, control: &Control) -> Result<RunResult> {
        case.validate()?;
        if flow_case(case).physics_hash() != self.case.physics_hash()
            || case.run.mode != Mode::Steady
            || !case.initial_conditions.is_empty()
            || case.numerics.transport != Advection::LinearUpwind
        {
            return Err("CFD-E089: mobile_response.case: flow controls differ, transport is nonlinear, or initial scalar field is nonzero".into());
        }
        let retained = (self.result.state.velocity.len()
            + 3 * self.grid.count()
            + case.constituents.len().saturating_mul(self.grid.count()))
            * 8;
        if case.check().estimated_peak_mib + retained as f64 / 1048576.
            > case.run.memory_limit_mib as f64
        {
            return Err("CFD-E089: run.memory_limit_mib: frozen-flow retained arrays exceed response budget".into());
        }
        control.check()?;
        let g = &self.grid;
        let sources = transport::source_fields(case, g)?;
        let weights = case
            .receptors
            .iter()
            .map(|r| transport::receptor_weights(g, r))
            .collect::<Result<Vec<_>>>()?;
        let mut state = solver::initial_state(case, g);
        state.velocity.clone_from(&self.result.state.velocity);
        state.pressure.clone_from(&self.result.state.pressure);
        state.k.clone_from(&self.result.state.k);
        state.epsilon.clone_from(&self.result.state.epsilon);
        state.floor_events = self.result.state.floor_events;
        let initial = hash_bytes(&serde_json::to_vec(&state).map_err(|e| e.to_string())?);
        solver::validate_state(case, g, &state)?;
        let nut = flow::eddy_viscosity(g, &state.k, &state.epsilon);
        let d: Vec<_> = (0..case.constituents.len())
            .map(|j| solver::diffusivity(case, &nut, j))
            .collect();
        let operator = (d.len() == 1).then(|| transport::FixedRhs::new(g, &state.velocity, &d[0]));
        let mut buffers: Vec<_> = (0..case.constituents.len())
            .map(|_| solver::ScalarBuffers::default())
            .collect();
        let mut termination = "iteration_limit".to_string();
        let mut error = None;
        while state.steps < case.run.max_steps {
            if let Err(e) = control.check() {
                termination = e;
                break;
            }
            let dt = solver::timestep_for(SteadyAlgorithm::Explicit, case, g, &state, &nut);
            if !dt.is_finite() || dt <= 0. {
                termination = "diverged".into();
                error = Some(
                    "CFD-E055: numerics.max_time_step_s: invalid frozen transport step".into(),
                );
                break;
            }
            let mut next = state.clone();
            for j in 0..case.constituents.len() {
                let temporary;
                let op = if let Some(op) = &operator {
                    op
                } else {
                    temporary = transport::FixedRhs::new(g, &state.velocity, &d[j]);
                    &temporary
                };
                solver::advance_scalar(
                    case,
                    g,
                    j,
                    &mut next.concentrations[j],
                    &state.velocity,
                    &d[j],
                    &sources[j],
                    dt,
                    &mut next.budgets[j],
                    &mut buffers[j],
                    Some(op),
                );
            }
            next.steps += 1;
            next.time_s += dt;
            next.scalar_time_s = Some(next.time_s);
            if let Err(e) = solver::validate_state(case, g, &next) {
                termination = "diverged".into();
                error = Some(e);
                break;
            }
            if next.concentrations.iter().flatten().any(|x| *x < 0.) {
                termination = "diverged".into();
                error = Some("CFD-E053: concentrations: negative fixed-flow scalar field".into());
                break;
            }
            state = next;
            state
                .monitor_history
                .push(solver::monitor(case, g, &state, &weights));
            if state.monitor_history.len() > 3 * case.numerics.monitor_window {
                state.monitor_history.remove(0);
            }
            if state.steps.is_multiple_of(case.numerics.monitor_window) {
                let (checks, _, _, _) = solver::assess(case, g, &state, &sources, &weights);
                if checks.iter().all(|x| x.passed) {
                    termination = "completed".into();
                    break;
                }
            }
        }
        let mut result = solver::finish_run(
            case,
            g,
            state,
            &sources,
            &weights,
            termination,
            error,
            initial,
            control,
        );
        if flow_state_hash(&result.state) != self.identity.flow_state_sha256 {
            return Err("CFD-E089: mobile_response.flow: immutable flow changed".into());
        }
        result.summary.frozen_flow = Some(self.identity.clone());
        Ok(result)
    }
}
