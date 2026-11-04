//! The native solve: bounded execution of a [`Case`], its state, and the
//! result contract `cfd-craft.result/0.1`.
//!
//! [`run`] is the entry point. It validates the case, builds the grid and the
//! source and receptor weights, starts from the initial state or a restart
//! [`State`], and advances transactional steps until the steady checks pass,
//! the transient interval is complete, or a budget, cancellation or failed
//! step stops it. A [`Control`] supplies the wall-time allowance,
//! cancellation, an optional external poll and optional profiling. The
//! returned [`RunResult`] holds the [`Summary`] (the JSON result), the final
//! state and the geometry evidence.
//!
//! Keep the questions of the result separate:
//!
//! - [`Summary::termination`] says why execution stopped: `completed`,
//!   `iteration_limit`, `wall_time_limit`, `cancelled` or `diverged`.
//! - [`Summary::assessment`] says what the recomputed [`Check`]s support:
//!   `steady_discrete_solution`, `transient_interval_completed`,
//!   `failed_checks` or `incomplete`.
//! - [`Summary::experimental_validation`] is always `not_validated`: a
//!   numerically accepted run is not a validated urban flow.
//!
//! A failed step never commits its candidate: the returned state is the last
//! accepted one, and [`Summary::error`] records the failure. The result types
//! derive `JsonSchema`; their doc comments are the `description` entries of
//! the `result_schema` that `cfd-craft describe` prints. See the
//! [result contract](https://github.com/dietmarwo/CFD-craft/blob/main/docs/result-contract.md).
//!
//! The lower-level functions ([`step`], [`assess`], [`timestep`],
//! [`monitor`]) are research interfaces; they expect a grid built from the
//! same case and state vectors of its dimensions.
use crate::{
    Result,
    case::*,
    flow,
    grid::{GeometryEvidence, Grid},
    pressure,
    profiling::{Collector, Phase, Profile, Span},
    transport,
};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};

/// Cooperative execution control of one solve: a wall-time allowance, a
/// cancellation flag, an optional external poll and optional phase
/// profiling.
///
/// The solver calls [`check`](Self::check) before every step and every eight
/// iterations of the pressure and implicit inner solves, so cancellation is
/// prompt but not instantaneous. The clock starts when the control is
/// created. A stop between steps ends the run as `cancelled` or
/// `wall_time_limit` with the last accepted state.
///
/// ```
/// use cfd_craft::solver::Control;
/// use std::sync::atomic::Ordering;
///
/// let control = Control::new(60.0);
/// assert!(control.check().is_ok());
/// control.cancelled.store(true, Ordering::Relaxed);
/// assert_eq!(control.check().unwrap_err(), "cancelled");
///
/// // An external poll: any error stops the run as `cancelled`.
/// let polled = Control::with_poll(60.0, || Err("job deadline".to_string()));
/// assert_eq!(polled.check().unwrap_err(), "cancelled");
/// ```
pub struct Control {
    /// Set to `true`, from any thread, to request cancellation. Clone the
    /// `Arc` before starting the solve; the CLI sets it from its SIGINT and
    /// SIGTERM handlers.
    pub cancelled: Arc<AtomicBool>,
    start: Instant,
    limit: Duration,
    external: Option<Box<dyn Fn() -> Result<()> + Send + Sync>>,
    profiling: Option<Collector>,
}
impl Control {
    /// A control with a wall-time allowance of `seconds`, counted from now,
    /// and no poll or profiling. Pass the case's `run.wall_time_limit_s` to
    /// reproduce the CLI's limit.
    ///
    /// # Panics
    ///
    /// If `seconds` is negative, not finite or too large for a
    /// [`Duration`]; validate user input first ([`Case::check`] requires a
    /// finite positive `run.wall_time_limit_s` of at most seven days).
    pub fn new(seconds: f64) -> Self {
        Self {
            cancelled: Arc::new(AtomicBool::new(false)),
            start: Instant::now(),
            limit: Duration::from_secs_f64(seconds),
            external: None,
            profiling: None,
        }
    }
    /// A wall-time allowance plus an external cancellation or deadline poll.
    ///
    /// A poll error stops the run as `cancelled`, or as `wall_time_limit` when the
    /// poll returns exactly that text. Its own message is not kept, so a run is
    /// never reported as diverged because an external caller stopped it.
    ///
    /// # Panics
    ///
    /// As [`new`](Self::new), for an invalid `seconds`.
    pub fn with_poll(seconds: f64, poll: impl Fn() -> Result<()> + Send + Sync + 'static) -> Self {
        let mut c = Self::new(seconds);
        c.external = Some(Box::new(poll));
        c
    }
    /// `Ok` while the solve may continue. Otherwise the error is exactly
    /// `"cancelled"` (a poll error other than `"wall_time_limit"`, or the
    /// [`cancelled`](Self::cancelled) flag) or `"wall_time_limit"` (the poll
    /// returned that text, or the allowance is used up). The poll runs first.
    pub fn check(&self) -> Result<()> {
        if let Some(poll) = &self.external {
            poll().map_err(|e| {
                if e == "wall_time_limit" {
                    e
                } else {
                    "cancelled".to_string()
                }
            })?;
        }
        if self.cancelled.load(Ordering::Relaxed) {
            Err("cancelled".into())
        } else if self.start.elapsed() >= self.limit {
            Err("wall_time_limit".into())
        } else {
            Ok(())
        }
    }
    /// Wall seconds since the control was created; reported as the summary's
    /// `elapsed_s`.
    pub fn elapsed(&self) -> f64 {
        self.start.elapsed().as_secs_f64()
    }
    /// Enable phase measurements without changing case or result schemas.
    /// Read them with [`profile`](Self::profile) after the solve; see the
    /// [`profiling`](crate::profiling) module.
    pub fn with_profiling(mut self) -> Self {
        self.profiling = Some(Collector::default());
        self
    }
    /// Start timing `phase` until the returned [`Span`] is dropped. Spans
    /// must finish in nested order on the thread that started them. Without
    /// [`with_profiling`](Self::with_profiling) the span is disabled and
    /// costs neither a clock read nor a lock.
    pub fn span(&self, phase: Phase) -> Span {
        self.profiling
            .as_ref()
            .map_or_else(Span::disabled, |p| p.span(phase))
    }
    /// Snapshot after every span has finished; work includes failed attempts.
    ///
    /// `Ok(None)` without [`with_profiling`](Self::with_profiling). An
    /// active or out-of-order span is an error, `CFD-B003 profile.active` or
    /// `CFD-B003 profile.nesting`.
    ///
    /// ```
    /// use cfd_craft::{profiling::Phase, solver::Control};
    ///
    /// assert!(Control::new(10.0).profile().unwrap().is_none());
    /// let control = Control::new(10.0).with_profiling();
    /// drop(control.span(Phase::Monitor));
    /// let profile = control.profile().unwrap().expect("profiling enabled");
    /// assert_eq!(profile.schema_version, "cfd-craft.phase-profile/0.1");
    /// assert_eq!(profile.phases["monitor"].calls, 1);
    /// ```
    pub fn profile(&self) -> Result<Option<Profile>> {
        self.profiling
            .as_ref()
            .map(|p| p.snapshot(self.elapsed()))
            .transpose()
    }
}
/// Cumulative mass budget of one constituent, in kg. At any accepted state
/// the mass in the domain should equal `initial_kg + emitted_kg + inflow_kg -
/// outflow_kg`; the `mass_budget` check bounds the relative defect. Every
/// entry is finite and nonnegative.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Budget {
    /// Mass at the cold start of the calculation; restarts keep it.
    pub initial_kg: f64,
    /// Mass emitted by the sources so far.
    pub emitted_kg: f64,
    /// Mass that entered through boundary faces so far.
    pub inflow_kg: f64,
    /// Mass that left through boundary faces so far.
    pub outflow_kg: f64,
}
/// The complete solver state: what fields.json archives and a checkpoint
/// restores. Vectors follow the grid layout of [`Grid`]: one value per face
/// (in `Grid::faces` order) or per cell (x fastest), with solid cells
/// included. Counters are cumulative from the cold start, across restarts.
///
/// [`validate_state`] checks a state against a case before it is used.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct State {
    /// Accepted steps, or outer iterations with an implicit steady algorithm.
    pub steps: usize,
    /// Time covered in seconds: physical time in transient mode, pseudo-time
    /// in steady mode.
    pub time_s: f64,
    /// Face-normal velocity of every face in m/s, the native staggered field.
    pub velocity: Vec<f64>,
    /// Kinematic pressure of every cell in m2/s2, with a mean-zero gauge in
    /// each fluid component without an outlet.
    pub pressure: Vec<f64>,
    /// Turbulent kinetic energy of every cell in m2/s2; zero without
    /// `neutral_rans` and in solid cells.
    pub k: Vec<f64>,
    /// Dissipation rate of every cell in m2/s3; zero without `neutral_rans`
    /// and in solid cells.
    pub epsilon: Vec<f64>,
    /// Concentration fields in kg/m3, one per constituent in case order, one
    /// value per cell (always zero in solid cells).
    pub concentrations: Vec<Vec<f64>>,
    /// Mass budget of each constituent, in case order.
    pub budgets: Vec<Budget>,
    /// Turbulence updates that hit the 1e-14 floor of k or epsilon; any
    /// event fails the `turbulence_floor_events` check.
    pub floor_events: usize,
    /// Pressure PCG iterations of the retained steps, including the initial
    /// projection.
    pub pressure_iterations: usize,
    /// Inner iterations of implicit momentum-correction solves; omitted when
    /// zero, so explicit checkpoints keep their bytes.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub momentum_solver_iterations: usize,
    /// Pseudo-time the constituents have covered, when it differs from
    /// `time_s`: an implicit steady algorithm advances them in at most
    /// `SCALAR_SUBSTEPS_MAX` explicit stable sub-steps per outer iteration.
    /// Emitted mass is the source rate times this time. Omitted (and equal to
    /// `time_s`) for explicit runs, so their checkpoints keep their bytes.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub scalar_time_s: Option<f64>,
    /// The last monitor rows, at most three monitor windows, one per step:
    /// see [`monitor`] for the columns. They feed the `monitor_stability`
    /// check of steady runs.
    pub monitor_history: Vec<Vec<f64>>,
}
fn is_zero(v: &usize) -> bool {
    *v == 0
}
/// One numerical check, recomputed by the solver from the current fields. A
/// check passes when its value is finite and at most its threshold.
/// Continuity and residual values are normalized with the case's velocity and
/// length scales (`neutral_rans`: `speed_m_s` and `reference_height_m`;
/// otherwise the reference speed, at least 1 m/s, and the shortest domain
/// side).
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Check {
    /// What is checked: `local_continuity`, `boundary_volume_balance`,
    /// `steady_momentum_equations`, `steady_turbulence_equations`,
    /// `turbulence_floor_events`, `monitor_stability`, or per constituent
    /// `<id>.mass_budget`, `<id>.negative_mass`, `<id>.steady_equation` and
    /// `<id>.steady_mass_balance`. The steady checks appear in steady mode
    /// only, the turbulence checks with `neutral_rans` only.
    pub name: String,
    /// The measured value, or null when it is not finite or not available,
    /// such as `monitor_stability` before three full monitor windows. A null
    /// value fails.
    pub value: Option<f64>,
    /// Largest accepted value, a fixed gate or the tolerance from the case.
    pub threshold: f64,
    /// Whether the value is finite and at most the threshold.
    pub passed: bool,
    /// How the value was obtained, for example `application recomputation
    /// from current fields`.
    pub method: String,
}
/// Evidence for one constituent at the returned state: mass budget,
/// extrema, the steady residual, instantaneous rates and receptor values.
/// Cumulative quantities are in kg, rates in kg/s, concentrations in kg/m3.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct ScalarEvidence {
    /// The constituent ID.
    pub id: String,
    /// Mass in the domain, the sum of concentration times cell volume.
    pub mass_kg: f64,
    /// Cumulative mass emitted by the sources.
    pub emitted_kg: f64,
    /// Cumulative mass that entered through boundary faces.
    pub inflow_kg: f64,
    /// Cumulative mass that left through boundary faces.
    pub outflow_kg: f64,
    /// `mass_kg` minus initial, emitted and inflow mass plus outflow mass.
    pub budget_defect_kg: f64,
    /// Absolute budget defect over the sum of initial, emitted, inflow and
    /// outflow mass; the `mass_budget` check requires at most 1e-9.
    pub relative_budget_defect: f64,
    /// Smallest concentration over the fluid cells.
    pub minimum_kg_m3: f64,
    /// Largest concentration over all cells, at least 0.
    pub maximum_kg_m3: f64,
    /// Mass of the negative concentrations, as a positive number; never
    /// clipped.
    pub negative_mass_kg: f64,
    /// Largest steady-equation residual |dc/dt| over the cells, normalized by
    /// the velocity scale, the length scale and `maximum_kg_m3`.
    pub steady_residual: f64,
    /// Emission rate of the represented sources.
    pub source_rate_kg_s: f64,
    /// Current rate of mass entering through boundary faces.
    pub boundary_inflow_rate_kg_s: f64,
    /// Current rate of mass leaving through boundary faces.
    pub boundary_outflow_rate_kg_s: f64,
    /// Concentration at each receptor, keyed by receptor ID. JSON maps are
    /// sorted lexically (`R10` before `R2`), so look values up by ID.
    pub receptors_kg_m3: BTreeMap<String, f64>,
}
/// The result of one native run (schema `cfd-craft.result/0.1`), written as
/// summary.json: identities, the stopping reason and numerical verdict, work
/// counters, geometry, the recomputed checks and per-constituent evidence.
/// `termination` says why execution stopped; `assessment` says what the
/// checks support; experimental validation is a separate question. Null
/// means unavailable in the stated context, not zero.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Summary {
    /// Always `cfd-craft.result/0.1`.
    pub schema_version: String,
    /// The case name.
    pub name: String,
    /// SHA-256 of the consumed, normalized case as compact JSON.
    pub case_sha256: String,
    /// Physics hash of the case: the case without `name`, `run` and
    /// `output`. Checkpoints are compatible across cases with the same value.
    pub physics_sha256: String,
    /// SHA-256 of the starting state (cold or restored), so restarts from
    /// different states stay distinguishable.
    pub initial_state_sha256: String,
    /// Why execution stopped: `completed`, `iteration_limit` (step budget),
    /// `wall_time_limit`, `cancelled` or `diverged` (a failed step, recorded
    /// in `error`).
    pub termination: String,
    /// Numerical verdict: `steady_discrete_solution` or
    /// `transient_interval_completed` (completed with every check passed),
    /// `failed_checks` (completed, some check failed) or `incomplete` (any
    /// other termination). Never upgraded because the last state looks
    /// reasonable.
    pub assessment: String,
    /// The failure that stopped the run, usually with its code (for example
    /// `CFD-E033: pressure iteration limit 100`), or `cancelled` /
    /// `wall_time_limit` when the stop came inside a step; null otherwise.
    pub error: Option<String>,
    /// Model label: `incompressible_laminar`,
    /// `prescribed_flow_passive_transport` or `neutral_k_epsilon_rough_wall`;
    /// the CLI prefixes `preview: ` for a coarsened preview.
    pub model_scope: String,
    /// Always `not_validated; see validation/data-inventory.json`: numerical
    /// acceptance is not experimental validation.
    pub experimental_validation: String,
    /// Retained steps (outer iterations with an implicit steady algorithm),
    /// cumulative across restarts.
    pub steps: usize,
    /// Time covered in seconds; pseudo-time in steady mode.
    pub physical_time_s: f64,
    /// Wall seconds of this invocation, from the creation of its control.
    pub elapsed_s: f64,
    /// Cumulative pressure PCG iterations of the retained steps.
    pub pressure_iterations: usize,
    /// Inner iterations of implicit momentum-correction solves, when selected.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub momentum_solver_iterations: Option<usize>,
    /// Turbulence updates that hit the k or epsilon floor; any event fails
    /// the turbulence checks.
    pub turbulent_floor_events: usize,
    /// Number of fluid cells.
    pub fluid_cells: usize,
    /// Number of solid cells.
    pub solid_cells: usize,
    /// Number of face-connected fluid regions, each with its own pressure
    /// gauge unless it touches an outlet.
    pub fluid_components: usize,
    /// SHA-256 of the cell mask, one byte per cell (1 fluid, 0 solid) in
    /// cell order; also in geometry.json.
    pub mask_sha256: String,
    /// The preflight memory estimate of the case check, in MiB.
    pub estimated_peak_mib: f64,
    /// Every recomputed check of the returned state.
    pub checks: Vec<Check>,
    /// Evidence for each constituent, in case order.
    pub constituents: Vec<ScalarEvidence>,
    /// Largest absolute face velocity in m/s.
    pub velocity_max_m_s: f64,
    /// Largest normalized momentum residual, null for prescribed flow.
    pub momentum_residual: Option<f64>,
    /// Largest normalized k or epsilon residual, `neutral_rans` only.
    pub turbulence_residual: Option<f64>,
    /// Largest relative change between the means of three successive monitor
    /// windows over all monitor columns (flow norm, constituent masses,
    /// receptor values and, with `neutral_rans`, mean k and epsilon); null
    /// before three full windows. The `monitor_stability` value of steady
    /// runs.
    pub receptor_relative_change: Option<f64>,
    /// Source fingerprint of the producing build. A library run reports the
    /// core crate's; the CLI and the Python binding combine it with their own.
    pub source_sha256: String,
    /// Package version and compiler of the producing build, as
    /// `<version>; <rustc version>`.
    pub build_version: String,
    /// The case's declared `run.threads`, not a measurement of the pool.
    pub threads: usize,
}
/// The cold-start state of a case: face velocities from
/// [`Flow::vector`], zero pressure, the `neutral_rans` equilibrium k and
/// epsilon in fluid cells, the initial concentrations and their initial
/// masses, and zero counters.
pub fn initial_state(c: &Case, g: &Grid) -> State {
    let concentrations = transport::initial_fields(c, g);
    let budgets = concentrations
        .iter()
        .map(|v| Budget {
            initial_kg: v.iter().sum::<f64>() * g.volume,
            emitted_kg: 0.0,
            inflow_kg: 0.0,
            outflow_kg: 0.0,
        })
        .collect();
    let k = (0..g.count())
        .map(|i| {
            if g.fluid[i] {
                c.flow.turbulence(g.center(i)[2]).0
            } else {
                0.0
            }
        })
        .collect();
    let epsilon = (0..g.count())
        .map(|i| {
            if g.fluid[i] {
                c.flow.turbulence(g.center(i)[2]).1
            } else {
                0.0
            }
        })
        .collect();
    State {
        steps: 0,
        time_s: 0.0,
        velocity: g.initial_velocity(c),
        pressure: vec![0.0; g.count()],
        k,
        epsilon,
        concentrations,
        budgets,
        floor_events: 0,
        pressure_iterations: 0,
        momentum_solver_iterations: 0,
        scalar_time_s: None,
        monitor_history: vec![],
    }
}
/// Checks that a state fits the case and grid before it is used, for example
/// a restart: vector dimensions (`CFD-E050`), finite values, nonnegative k,
/// epsilon and budgets, a `scalar_time_s` within `time_s`, a finite monitor
/// history, and zero concentration in solid cells (all `CFD-E051`). It does
/// not check the physics identity; [`output::read_checkpoint`](crate::output::read_checkpoint)
/// does that.
pub fn validate_state(c: &Case, g: &Grid, s: &State) -> Result<()> {
    validate_with_history(c, g, s, &s.monitor_history)
}
fn validate_with_history(c: &Case, g: &Grid, s: &State, history: &[Vec<f64>]) -> Result<()> {
    if s.velocity.len() != g.faces.len()
        || s.pressure.len() != g.count()
        || s.k.len() != g.count()
        || s.epsilon.len() != g.count()
        || s.concentrations.len() != c.constituents.len()
        || s.budgets.len() != c.constituents.len()
        || s.concentrations.iter().any(|v| v.len() != g.count())
    {
        return Err("CFD-E050: checkpoint dimensions do not match case".into());
    }
    if !s.time_s.is_finite()
        || s.time_s < 0.0
        || s.scalar_time_s
            .is_some_and(|t| !t.is_finite() || t < 0.0 || t > s.time_s * (1.0 + 1e-12) + 1e-300)
        || s.velocity
            .iter()
            .chain(&s.pressure)
            .chain(&s.k)
            .chain(&s.epsilon)
            .chain(s.concentrations.iter().flatten())
            .any(|v| !v.is_finite())
        || s.k.iter().chain(&s.epsilon).any(|v| *v < 0.0)
        || s.budgets.iter().any(|b| {
            [b.initial_kg, b.emitted_kg, b.inflow_kg, b.outflow_kg]
                .iter()
                .any(|v| !v.is_finite() || *v < 0.0)
        })
        || history.iter().flatten().any(|v| !v.is_finite())
    {
        return Err("CFD-E051: nonfinite or invalid state".into());
    }
    // Transport never changes a solid cell, so a state with mass there is not one it produced.
    if s.concentrations
        .iter()
        .any(|v| v.iter().zip(&g.fluid).any(|(x, fluid)| !fluid && *x != 0.0))
    {
        return Err("CFD-E051: nonzero concentration in a solid cell".into());
    }
    Ok(())
}
fn diffusivity(c: &Case, nut: &[f64], s: usize) -> Vec<f64> {
    let sc = if let Flow::NeutralRans {
        turbulent_schmidt, ..
    } = &c.flow
    {
        *turbulent_schmidt
    } else {
        1.0
    };
    nut.iter()
        .map(|n| c.constituents[s].diffusivity_m2_s + n / sc)
        .collect()
}
/// The next stable time step in seconds for the case's steady algorithm,
/// capped by `numerics.max_time_step_s`. `explicit` limits advection and
/// diffusion together with `numerics.advective_cfl_max` (at most 0.45),
/// `implicit_viscous` limits advection only, and `implicit_projection`
/// follows the CFL ramp of
/// [`momentum_solve::ramp_cfl`](crate::momentum_solve::ramp_cfl). `nut` is
/// the eddy viscosity per cell ([`flow::eddy_viscosity`]). [`run`] clips the
/// step to the end time of a transient run.
pub fn timestep(c: &Case, g: &Grid, s: &State, nut: &[f64]) -> f64 {
    timestep_for(c.numerics.steady_algorithm, c, g, s, nut)
}
fn timestep_for(algorithm: SteadyAlgorithm, c: &Case, g: &Grid, s: &State, nut: &[f64]) -> f64 {
    let mut umax = [0.0f64; 3];
    for (f, u) in g.faces.iter().zip(&s.velocity) {
        umax[f.axis] = umax[f.axis].max(u.abs());
    }
    let adv = (0..3).map(|a| umax[a] / g.dx[a]).sum::<f64>();
    let maxnut = nut.iter().copied().fold(0.0, f64::max);
    let sc = if let Flow::NeutralRans {
        turbulent_schmidt, ..
    } = &c.flow
    {
        *turbulent_schmidt
    } else {
        1.0
    };
    let dmax = c
        .constituents
        .iter()
        .map(|x| x.diffusivity_m2_s + maxnut / sc)
        .fold(c.flow.viscosity() + maxnut, f64::max);
    let diffusion = 2.0 * dmax * g.dx.iter().map(|h| 1.0 / (h * h)).sum::<f64>();
    match algorithm {
        SteadyAlgorithm::Explicit => c
            .numerics
            .max_time_step_s
            .min(c.numerics.advective_cfl_max.min(0.45) / (adv + diffusion).max(1e-30)),
        // Implicit viscosity removes the diffusive limit; advection stays explicit.
        SteadyAlgorithm::ImplicitViscous => c
            .numerics
            .max_time_step_s
            .min(c.numerics.advective_cfl_max.min(0.45) / adv.max(1e-30)),
        // A deterministic CFL ramp from the outer-iteration count; restarts need no state.
        SteadyAlgorithm::ImplicitProjection => c
            .numerics
            .max_time_step_s
            .min(crate::momentum_solve::ramp_cfl(s.steps) / adv.max(1e-30)),
    }
}
fn flow_euler(
    c: &Case,
    g: &Grid,
    u: &[f64],
    p: &[f64],
    nut: &[f64],
    dt: f64,
    control: &Control,
) -> Result<(Vec<f64>, Vec<f64>, usize, usize)> {
    let rhs = {
        let _phase = control.span(Phase::MomentumRhs);
        flow::momentum_rhs(c, g, u, nut)
    };
    let velocity_update = control.span(Phase::VelocityUpdate);
    let grad = g.gradient(p);
    let mut inner = 0;
    let mut v: Vec<_> = if c.numerics.steady_algorithm == SteadyAlgorithm::ImplicitViscous {
        // Delta form: (I - dt L_nu) delta = dt R with the full steady residual R.
        let b: Vec<_> = rhs.iter().zip(&grad).map(|(r, p)| dt * (r - p)).collect();
        let stencil = g
            .momentum_stencil
            .get_or_init(|| crate::momentum_solve::Stencil::build(c, g));
        let (delta, info) =
            crate::momentum_solve::solve_viscous(stencil, c.flow.viscosity(), dt, &b, control)?;
        inner = info.iterations;
        u.iter().zip(delta).map(|(u, d)| u + d).collect()
    } else {
        u.iter()
            .zip(rhs)
            .zip(grad)
            .map(|((u, r), p)| u + dt * (r - p))
            .collect()
    };
    g.enforce_velocity(c, &mut v);
    let mut pp = p.to_vec();
    drop(velocity_update);
    let info = pressure::project(
        g,
        &mut v,
        &mut pp,
        dt,
        c.numerics.pressure_relative_tolerance,
        c.numerics.pressure_max_iterations,
        control,
    )?;
    g.enforce_velocity(c, &mut v);
    Ok((v, pp, info.iterations, inner))
}
/// One outer iteration of the implicit steady algorithm (P5a), in delta form:
/// A δ = R(u, p), u* = u + δ, then a projection at the pseudo-time step. At a
/// fixed point δ = 0 and the projection's correction is zero, so R = 0 and the
/// velocity is solenoidal, which is what `assess` checks.
fn implicit_iteration(
    c: &Case,
    g: &Grid,
    u: &[f64],
    p: &[f64],
    nut: &[f64],
    dt: f64,
    control: &Control,
) -> Result<(Vec<f64>, Vec<f64>, usize, usize)> {
    let rhs = {
        let _phase = control.span(Phase::MomentumRhs);
        flow::momentum_rhs(c, g, u, nut)
    };
    let velocity_update = control.span(Phase::VelocityUpdate);
    let residual: Vec<_> = rhs.iter().zip(g.gradient(p)).map(|(r, p)| r - p).collect();
    let stencil = g
        .momentum_stencil
        .get_or_init(|| crate::momentum_solve::Stencil::build(c, g));
    let matrix = if c.flow.rans() {
        stencil.implicit_matrix_rans(c, g, u, nut, dt)
    } else {
        stencil.implicit_matrix(u, c.flow.viscosity(), dt)
    };
    drop(velocity_update);
    let (delta, info) =
        crate::momentum_solve::solve_implicit(stencil, &matrix, &residual, control)?;
    let mut v: Vec<_> = u.iter().zip(delta).map(|(u, d)| u + d).collect();
    g.enforce_velocity(c, &mut v);
    let mut pp = p.to_vec();
    let projection = pressure::project(
        g,
        &mut v,
        &mut pp,
        dt,
        c.numerics.pressure_relative_tolerance,
        c.numerics.pressure_max_iterations,
        control,
    )?;
    g.enforce_velocity(c, &mut v);
    Ok((v, pp, projection.iterations, info.iterations))
}
/// Cap on explicit scalar sub-steps per implicit outer iteration (P5d). The
/// constituents then advance by at most this many explicit stable steps per
/// outer iteration; their steady state does not depend on the step sizes.
pub const SCALAR_SUBSTEPS_MAX: usize = 16;

/// Sub-step count and size for a pseudo-time step `dt` with explicit stable
/// step `stable`: the fewest equal sub-steps of at most `stable`, capped at
/// `SCALAR_SUBSTEPS_MAX` steps of size `stable`.
pub fn scalar_substeps(dt: f64, stable: f64) -> (usize, f64) {
    let needed = (dt / stable).ceil();
    if needed <= SCALAR_SUBSTEPS_MAX as f64 {
        let n = (needed as usize).max(1);
        (n, dt / n as f64)
    } else {
        (SCALAR_SUBSTEPS_MAX, stable)
    }
}

/// Reused buffers of the SSPRK2 scalar step.
#[derive(Default)]
struct ScalarBuffers {
    r1: Vec<f64>,
    stage: Vec<f64>,
    r2: Vec<f64>,
}

/// One SSPRK2 step of scalar transport, with its budget increments, written
/// into `concentration` in place.
#[allow(clippy::too_many_arguments)]
fn advance_scalar(
    c: &Case,
    g: &Grid,
    concentration: &mut [f64],
    velocity: &[f64],
    d: &[f64],
    source: &[f64],
    dt: f64,
    budget: &mut Budget,
    buffers: &mut ScalarBuffers,
    fixed: Option<&transport::FixedRhs>,
) {
    let ScalarBuffers { r1, stage, r2 } = buffers;
    // Linear upwind with a fixed flow: evaluate from the gathered faces.
    let fixed = fixed.filter(|_| c.numerics.transport == crate::case::Advection::LinearUpwind);
    let rhs = |x: &[f64], out: &mut Vec<f64>| match fixed {
        Some(op) => op.eval(x, source, out),
        None => transport::rhs_into(
            g,
            x,
            velocity,
            d,
            source,
            c.numerics.transport,
            |_| 0.0,
            out,
        ),
    };
    let (source1, inflow1, outflow1) = rhs(concentration, r1);
    stage.clear();
    stage.extend(concentration.iter().zip(r1.iter()).map(|(a, b)| a + dt * b));
    let (source2, inflow2, outflow2) = rhs(stage, r2);
    for ((a, b), r) in concentration.iter_mut().zip(stage.iter()).zip(r2.iter()) {
        *a = 0.5 * (*a + b + dt * r);
    }
    budget.emitted_kg += 0.5 * dt * (source1 + source2);
    budget.inflow_kg += 0.5 * dt * (inflow1 + inflow2);
    budget.outflow_kg += 0.5 * dt * (outflow1 + outflow2);
}

/// Advances `s` by one step (one outer iteration with an implicit steady
/// algorithm) of size `dt`, transactionally.
///
/// The candidate state is built beside `s`: flow (SSPRK2 with a projection
/// per stage, or one implicit correction and projection), turbulence and the
/// constituents with their budgets. It replaces `s` only when every gate
/// passes, so on `Err` the state is unchanged. `sources` are the source
/// densities of [`transport::source_fields`], one per constituent; a shorter
/// slice leaves the remaining constituents unchanged. Errors are the
/// control's `"cancelled"` / `"wall_time_limit"`, or a coded failure such as
/// `CFD-E033` (pressure limit), `CFD-E051` (nonfinite state), `CFD-E052`
/// (velocity divergence) or `CFD-E053` (negative concentration).
///
/// The monitor history is not updated; [`run`] appends [`monitor`] rows.
pub fn step(
    c: &Case,
    g: &Grid,
    s: &mut State,
    sources: &[Vec<f64>],
    dt: f64,
    control: &Control,
) -> Result<()> {
    let _step = control.span(Phase::Step);
    control.check()?;
    let nut = flow::eddy_viscosity(g, &s.k, &s.epsilon);
    // Build the next state off to the side: pressure/cancellation failure cannot publish half a step.
    let mut next = State {
        steps: s.steps,
        time_s: s.time_s,
        velocity: if c.flow.prescribed() {
            s.velocity.clone()
        } else {
            Vec::new()
        },
        pressure: if c.flow.prescribed() {
            s.pressure.clone()
        } else {
            Vec::new()
        },
        k: s.k.clone(),
        epsilon: s.epsilon.clone(),
        concentrations: Vec::with_capacity(s.concentrations.len()),
        budgets: s.budgets.clone(),
        floor_events: s.floor_events,
        pressure_iterations: s.pressure_iterations,
        momentum_solver_iterations: s.momentum_solver_iterations,
        scalar_time_s: s.scalar_time_s,
        monitor_history: Vec::new(),
    };
    if c.numerics.steady_algorithm == SteadyAlgorithm::ImplicitProjection {
        let (v, p, n, m) = implicit_iteration(c, g, &s.velocity, &s.pressure, &nut, dt, control)?;
        next.velocity = v;
        next.pressure = p;
        next.pressure_iterations += n;
        next.momentum_solver_iterations += m;
        if c.flow.rans() {
            let _phase = control.span(Phase::Turbulence);
            let info = crate::turbulence_solve::implicit_step(
                c,
                g,
                &next.velocity,
                &mut next.k,
                &mut next.epsilon,
                dt,
                control,
            )?;
            next.floor_events += info.floor_events;
        }
    } else if !c.flow.prescribed() {
        let (v, p, n1, m1) = flow_euler(c, g, &s.velocity, &s.pressure, &nut, dt, control)?;
        let (v2, p2, n2, m2) = flow_euler(c, g, &v, &p, &nut, dt, control)?;
        next.momentum_solver_iterations += m1 + m2;
        next.velocity = s
            .velocity
            .iter()
            .zip(v2)
            .map(|(a, b)| 0.5 * (a + b))
            .collect();
        next.pressure = p2;
        g.enforce_velocity(c, &mut next.velocity);
        next.pressure_iterations += n1 + n2;
        if c.flow.rans() {
            let _phase = control.span(Phase::Turbulence);
            next.floor_events +=
                flow::turbulence_step(c, g, &next.velocity, &mut next.k, &mut next.epsilon, dt);
        }
    }
    if !sources.is_empty() {
        // The implicit steady algorithm's pseudo-time step exceeds the explicit
        // transport limits, so constituents advance in explicit sub-steps (P5d).
        let (substeps, sub_dt) = if c.numerics.steady_algorithm == SteadyAlgorithm::Explicit {
            (1, dt)
        } else {
            scalar_substeps(
                dt,
                timestep_for(SteadyAlgorithm::Explicit, c, g, &next, &nut),
            )
        };
        for (j, source) in sources.iter().enumerate() {
            let _phase = control.span(Phase::ScalarTransport);
            let d = diffusivity(c, &nut, j);
            let mut concentration = s.concentrations[j].clone();
            let mut buffers = ScalarBuffers::default();
            // Several sub-steps share one flow: gather its faces once.
            let fixed = (substeps > 1
                && c.numerics.transport == crate::case::Advection::LinearUpwind)
                .then(|| transport::FixedRhs::new(g, &next.velocity, &d));
            for _ in 0..substeps {
                advance_scalar(
                    c,
                    g,
                    &mut concentration,
                    &next.velocity,
                    &d,
                    source,
                    sub_dt,
                    &mut next.budgets[j],
                    &mut buffers,
                    fixed.as_ref(),
                );
            }
            next.concentrations.push(concentration);
        }
        // The constituents' own pseudo-time, kept once it can differ from time_s.
        if c.numerics.steady_algorithm != SteadyAlgorithm::Explicit || s.scalar_time_s.is_some() {
            let covered =
                (0..substeps).fold(s.scalar_time_s.unwrap_or(s.time_s), |t, _| t + sub_dt);
            next.scalar_time_s = Some(covered);
        }
    }
    // Preserve the public step function's unchanged trailing constituents when
    // a caller supplies only a prefix of source arrays.
    next.concentrations
        .extend(s.concentrations.iter().skip(sources.len()).cloned());
    next.time_s += dt;
    next.steps += 1;
    // History is borrowed until every fallible gate below has passed.
    {
        let _phase = control.span(Phase::StateValidation);
        validate_with_history(c, g, &next, &s.monitor_history)?;
    }
    if next
        .velocity
        .iter()
        .any(|v| v.abs() > 1e6 * c.flow.reference_speed())
    {
        return Err("CFD-E052: velocity divergence".into());
    }
    for vals in &next.concentrations {
        let scale = vals.iter().copied().fold(0.0, f64::max).max(1e-30);
        if vals.iter().any(|v| *v < -1e-10 * scale) {
            return Err("CFD-E053: transport positivity failure; no clipping applied".into());
        }
    }
    next.monitor_history = std::mem::take(&mut s.monitor_history);
    *s = next;
    Ok(())
}
/// One monitor row of the state: the RMS face velocity, then for each
/// constituent its mass (kg) followed by its receptor values (kg/m3, in
/// receptor order), then with `neutral_rans` the mean k and the mean
/// epsilon over all cells. `weights` are the receptor weights of
/// [`transport::receptor_weights`], in receptor order.
pub fn monitor(c: &Case, g: &Grid, s: &State, weights: &[transport::Weights]) -> Vec<f64> {
    let mut v =
        vec![s.velocity.iter().map(|v| v * v).sum::<f64>().sqrt() / (g.faces.len() as f64).sqrt()];
    for values in &s.concentrations {
        v.push(values.iter().sum::<f64>() * g.volume);
        for w in weights {
            v.push(w.iter().map(|(i, w)| values[*i] * w).sum());
        }
    }
    if c.flow.rans() {
        v.push(s.k.iter().sum::<f64>() / g.count() as f64);
        v.push(s.epsilon.iter().sum::<f64>() / g.count() as f64);
    }
    v
}
/// Largest relative change between the column means of three successive
/// windows of `numerics.monitor_window` rows, each change relative to the
/// largest absolute mean of its column (at least 1e-30). The windows are the
/// first three of the monitor history, which [`run`] keeps at the last three
/// windows. `None` until the history holds three full windows.
pub fn monitor_change(c: &Case, s: &State) -> Option<f64> {
    let w = c.numerics.monitor_window;
    if s.monitor_history.len() < 3 * w {
        return None;
    }
    let mut delta = 0.0f64;
    for col in 0..s.monitor_history[0].len() {
        let mean = |a: usize| {
            s.monitor_history[a * w..(a + 1) * w]
                .iter()
                .map(|v| v[col])
                .sum::<f64>()
                / w as f64
        };
        let means = [mean(0), mean(1), mean(2)];
        let scale = means.iter().map(|x| x.abs()).fold(1e-30, f64::max);
        delta = delta
            .max((means[1] - means[0]).abs() / scale)
            .max((means[2] - means[1]).abs() / scale);
    }
    Some(delta)
}
/// Recomputes the numerical checks of a state from its fields.
///
/// Returns the [`Check`]s, the [`ScalarEvidence`] of each constituent, the
/// normalized momentum residual (`None` for prescribed flow) and the
/// normalized turbulence residual (`None` without `neutral_rans`). Steady
/// checks are included in steady mode only. `sources` and `weights` are the
/// source densities and receptor weights of the case on grid `g`.
pub fn assess(
    c: &Case,
    g: &Grid,
    s: &State,
    sources: &[Vec<f64>],
    weights: &[transport::Weights],
) -> (Vec<Check>, Vec<ScalarEvidence>, Option<f64>, Option<f64>) {
    let mut checks = vec![];
    let mut add = |name: &str, value: f64, threshold: f64| {
        checks.push(Check {
            name: name.into(),
            value: if value.is_finite() { Some(value) } else { None },
            threshold,
            passed: value.is_finite() && value <= threshold,
            method: "application recomputation from current fields".into(),
        })
    };
    let div = g.divergence(&s.velocity);
    let length = if let Flow::NeutralRans {
        reference_height_m, ..
    } = c.flow
    {
        reference_height_m
    } else {
        c.domain
            .size_m
            .iter()
            .copied()
            .fold(f64::INFINITY, f64::min)
    };
    let speed = c.flow.reference_speed();
    let maxdiv = div.iter().map(|v| v.abs()).fold(0.0, f64::max) * length / speed;
    let mut net = 0.0;
    let mut absolute = 0.0;
    for (f, u) in g.faces.iter().zip(&s.velocity) {
        if f.lo.is_some() && f.hi.is_none() {
            net += u * f.area;
            absolute += u.abs() * f.area;
        }
        if f.lo.is_none() && f.hi.is_some() {
            net -= u * f.area;
            absolute += u.abs() * f.area;
        }
    }
    add("local_continuity", maxdiv, 1e-4);
    add(
        "boundary_volume_balance",
        net.abs() / absolute.max(speed * c.domain.size_m[1] * c.domain.size_m[2]),
        1e-5,
    );
    let nut = flow::eddy_viscosity(g, &s.k, &s.epsilon);
    let momentum = if c.flow.prescribed() {
        None
    } else {
        let rhs = flow::momentum_rhs(c, g, &s.velocity, &nut);
        let grad = g.gradient(&s.pressure);
        let residual = rhs
            .iter()
            .zip(grad)
            .map(|(a, b)| (a - b).abs())
            .fold(0.0, f64::max)
            * length
            / (speed * speed);
        if c.run.mode == Mode::Steady {
            add(
                "steady_momentum_equations",
                residual,
                c.numerics.steady_residual_tolerance,
            );
        }
        Some(residual)
    };
    let turbulence = if c.flow.rans() {
        // The residual probe uses the explicit step size for every algorithm,
        // so the reported residual does not depend on the pseudo-time step.
        let dt = 1e-6 * timestep_for(SteadyAlgorithm::Explicit, c, g, s, &nut);
        let mut k = s.k.clone();
        let mut e = s.epsilon.clone();
        flow::turbulence_step(c, g, &s.velocity, &mut k, &mut e, dt);
        let rk = (0..g.count())
            .filter(|i| g.fluid[*i])
            .map(|i| (k[i] - s.k[i]).abs() / dt * length / (speed.powi(3)))
            .fold(0.0, f64::max);
        let re = (0..g.count())
            .filter(|i| g.fluid[*i])
            .map(|i| (e[i] - s.epsilon[i]).abs() / dt * length * length / speed.powi(4))
            .fold(0.0, f64::max);
        let r = rk.max(re);
        if c.run.mode == Mode::Steady {
            add(
                "steady_turbulence_equations",
                r,
                c.numerics.steady_residual_tolerance,
            );
        }
        add("turbulence_floor_events", s.floor_events as f64, 0.0);
        Some(r)
    } else {
        None
    };
    let mut scalars = vec![];
    for (j, sp) in c.constituents.iter().enumerate() {
        let values = &s.concentrations[j];
        let mass = values.iter().sum::<f64>() * g.volume;
        let b = &s.budgets[j];
        let defect = mass - b.initial_kg - b.emitted_kg - b.inflow_kg + b.outflow_kg;
        let scale = (b.initial_kg + b.emitted_kg + b.inflow_kg + b.outflow_kg).max(1e-30);
        let minimum = values
            .iter()
            .enumerate()
            .filter(|(i, _)| g.fluid[*i])
            .map(|(_, v)| *v)
            .fold(f64::INFINITY, f64::min);
        let maximum = values.iter().copied().fold(0.0, f64::max);
        let negative = -values.iter().filter(|v| **v < 0.0).sum::<f64>() * g.volume;
        let rhs = transport::rhs(
            g,
            values,
            &s.velocity,
            &diffusivity(c, &nut, j),
            &sources[j],
            c.numerics.transport,
            |_| 0.0,
        );
        let residual = rhs.values.iter().map(|v| v.abs()).fold(0.0, f64::max) * length
            / (speed * maximum.max(1e-30));
        add(
            &format!("{}.mass_budget", sp.id),
            defect.abs() / scale,
            1e-9,
        );
        add(&format!("{}.negative_mass", sp.id), negative / scale, 1e-12);
        if c.run.mode == Mode::Steady {
            add(
                &format!("{}.steady_equation", sp.id),
                residual,
                c.numerics.steady_residual_tolerance,
            );
            let flux_scale = if rhs.source + rhs.inflow > 0.0 {
                rhs.source + rhs.inflow + rhs.outflow
            } else {
                rhs.outflow.max(b.initial_kg * speed / length)
            }
            .max(1e-30);
            add(
                &format!("{}.steady_mass_balance", sp.id),
                (rhs.source + rhs.inflow - rhs.outflow).abs() / flux_scale,
                1e-6,
            );
        }
        let receptors = c
            .receptors
            .iter()
            .zip(weights)
            .map(|(r, w)| {
                (
                    r.id().to_string(),
                    w.iter().map(|(i, w)| values[*i] * w).sum(),
                )
            })
            .collect();
        scalars.push(ScalarEvidence {
            id: sp.id.clone(),
            mass_kg: mass,
            emitted_kg: b.emitted_kg,
            inflow_kg: b.inflow_kg,
            outflow_kg: b.outflow_kg,
            budget_defect_kg: defect,
            relative_budget_defect: defect.abs() / scale,
            minimum_kg_m3: minimum,
            maximum_kg_m3: maximum,
            negative_mass_kg: negative,
            steady_residual: residual,
            source_rate_kg_s: rhs.source,
            boundary_inflow_rate_kg_s: rhs.inflow,
            boundary_outflow_rate_kg_s: rhs.outflow,
            receptors_kg_m3: receptors,
        });
    }
    if c.run.mode == Mode::Steady {
        add(
            "monitor_stability",
            monitor_change(c, s).unwrap_or(f64::INFINITY),
            c.numerics.steady_monitor_tolerance,
        );
    }
    (checks, scalars, momentum, turbulence)
}
/// Everything a solve returns: the JSON summary, the final accepted state
/// and the geometry evidence. [`output::write_run`](crate::output::write_run)
/// publishes it as a run archive.
pub struct RunResult {
    /// The result record (summary.json).
    pub summary: Summary,
    /// The last accepted state (fields.json, or a checkpoint for a restart).
    pub state: State,
    /// Cell counts, fluid components and mask hash (geometry.json).
    pub geometry: GeometryEvidence,
}
/// Solves a case within the limits of `control`, from the cold-start state or
/// from a `restart` state, and returns the inspectable outcome.
///
/// `Err` means the solve could not start: an invalid case (the error is the
/// serialized [`CheckReport`], as from [`Case::validate`]) or a grid, source,
/// receptor or restart-state failure with its code (`CFD-E028` to
/// `CFD-E044`, `CFD-E050`, `CFD-E051`). Once stepping has begun the result is
/// `Ok`, also when the run was cancelled, ran out of budget or diverged:
/// always read [`Summary::termination`] and [`Summary::assessment`].
///
/// A restart state should come from
/// [`output::read_checkpoint`](crate::output::read_checkpoint), which also
/// checks its physics identity; `run` checks only its dimensions and values.
/// The library does not create a Rayon pool from `run.threads`; run inside
/// `pool.install` when thread accounting matters. Steady runs assess their
/// checks every `numerics.monitor_window` steps and stop when all pass.
///
/// ```
/// use cfd_craft::{case::Case, solver::{self, Control}};
///
/// let case: Case = serde_json::from_str(r#"{
///   "schema_version": "cfd-craft.case/0.1", "name": "tiny",
///   "domain": {"size_m": [4.0, 1.0, 1.0]}, "grid": {"cells": [8, 2, 2]},
///   "boundaries": {"x": "open", "y": "periodic", "z": "periodic"},
///   "flow": {"kind": "prescribed_uniform", "velocity_m_s": [1.0, 0.0, 0.0]},
///   "constituents": [{"id": "tracer", "diffusivity_m2_s": 0.01}],
///   "sources": [{"kind": "point", "id": "S0", "constituent": "tracer",
///                "point_m": [0.5, 0.5, 0.5], "rate_kg_s": 1e-6}],
///   "numerics": {"transport": "linear_upwind", "max_time_step_s": 1.0,
///     "advective_cfl_max": 0.4, "pressure_relative_tolerance": 1e-10,
///     "pressure_max_iterations": 100, "steady_residual_tolerance": 1e-5,
///     "steady_monitor_tolerance": 1e-3, "monitor_window": 10},
///   "run": {"mode": "steady", "end_time_s": 1.0, "max_steps": 5,
///     "wall_time_limit_s": 30.0, "threads": 1, "memory_limit_mib": 64},
///   "output": {"fields": false, "checkpoint": false, "max_total_mib": 4}
/// }"#).unwrap();
///
/// // Five steps cannot reach a steady state: the result is still `Ok`.
/// let result = solver::run(&case, &Control::new(case.run.wall_time_limit_s), None)?;
/// assert_eq!(result.summary.termination, "iteration_limit");
/// assert_eq!(result.summary.assessment, "incomplete");
/// assert_eq!(result.state.steps, 5);
///
/// // Continue from the returned state with a larger step budget.
/// let mut more = case.clone();
/// more.run.max_steps = 2000;
/// let control = Control::new(more.run.wall_time_limit_s);
/// let resumed = solver::run(&more, &control, Some(result.state))?;
/// assert_eq!(resumed.summary.termination, "completed");
/// assert_eq!(resumed.summary.assessment, "steady_discrete_solution");
/// assert!(resumed.summary.checks.iter().all(|c| c.passed));
/// # Ok::<(), String>(())
/// ```
pub fn run(c: &Case, control: &Control, restart: Option<State>) -> Result<RunResult> {
    let _run = control.span(Phase::SolverRun);
    {
        let _phase = control.span(Phase::CaseValidation);
        c.validate()?;
    }
    let g = {
        let _phase = control.span(Phase::GridSetup);
        Grid::build(c)?
    };
    let input_setup = control.span(Phase::InputSetup);
    let sources = transport::source_fields(c, &g)?;
    let weights = c
        .receptors
        .iter()
        .map(|r| transport::receptor_weights(&g, r))
        .collect::<Result<Vec<_>>>()?;
    drop(input_setup);
    let state_setup = control.span(Phase::StateSetup);
    let mut state = restart.unwrap_or_else(|| initial_state(c, &g));
    validate_state(c, &g, &state)?;
    let initial_state_sha256 = hash_bytes(&serde_json::to_vec(&state).map_err(|e| e.to_string())?);
    drop(state_setup);
    let mut termination = "iteration_limit".to_string();
    let mut error = None;
    if state.steps == 0 && !c.flow.prescribed() {
        match pressure::project(
            &g,
            &mut state.velocity,
            &mut state.pressure,
            1.0,
            c.numerics.pressure_relative_tolerance,
            c.numerics.pressure_max_iterations,
            control,
        ) {
            Ok(initial) => {
                state.pressure_iterations += initial.iterations;
                state.pressure.fill(0.0);
                if c.flow.rans() {
                    let _phase = control.span(Phase::Turbulence);
                    state.floor_events += flow::turbulence_step(
                        c,
                        &g,
                        &state.velocity,
                        &mut state.k,
                        &mut state.epsilon,
                        0.0,
                    );
                }
            }
            Err(e) => {
                termination = if e == "cancelled" || e == "wall_time_limit" {
                    e.clone()
                } else {
                    "diverged".into()
                };
                error = Some(e);
            }
        }
    }
    while error.is_none() && state.steps < c.run.max_steps {
        if c.run.mode == Mode::Transient && state.time_s >= c.run.end_time_s * (1.0 - 1e-13) {
            termination = "completed".into();
            break;
        }
        if let Err(e) = control.check() {
            termination = e;
            break;
        }
        let timestep_phase = control.span(Phase::Timestep);
        let nut = flow::eddy_viscosity(&g, &state.k, &state.epsilon);
        if nut
            .iter()
            .any(|v| !v.is_finite() || *v > 100.0 * c.flow.reference_speed() * c.domain.size_m[2])
        {
            termination = "diverged".into();
            error =
                Some("CFD-E054: turbulent viscosity outside the declared numerical regime".into());
            break;
        }
        let mut dt = timestep(c, &g, &state, &nut);
        if c.run.mode == Mode::Transient {
            dt = dt.min(c.run.end_time_s - state.time_s);
        }
        if dt <= 0.0 || !dt.is_finite() {
            termination = "diverged".into();
            error = Some("CFD-E055: the time step is not finite and positive".into());
            break;
        }
        drop(timestep_phase);
        if let Err(e) = step(c, &g, &mut state, &sources, dt, control) {
            termination = if e == "cancelled" || e == "wall_time_limit" {
                e.clone()
            } else {
                "diverged".into()
            };
            error = Some(e);
            break;
        }
        let monitor_phase = control.span(Phase::Monitor);
        state.monitor_history.push(monitor(c, &g, &state, &weights));
        let keep = 3 * c.numerics.monitor_window;
        if state.monitor_history.len() > keep {
            state.monitor_history.remove(0);
        }
        drop(monitor_phase);
        if c.run.mode == Mode::Steady && state.steps.is_multiple_of(c.numerics.monitor_window) {
            let _phase = control.span(Phase::Assessment);
            let (checks, _, _, _) = assess(c, &g, &state, &sources, &weights);
            if checks.iter().all(|x| x.passed) {
                termination = "completed".into();
                break;
            }
        }
    }
    if c.run.mode == Mode::Transient && state.time_s >= c.run.end_time_s * (1.0 - 1e-13) {
        termination = "completed".into();
    }
    let (checks, constituents, momentum_residual, turbulence_residual) = {
        let _phase = control.span(Phase::Assessment);
        assess(c, &g, &state, &sources, &weights)
    };
    let passed = checks.iter().all(|x| x.passed);
    let assessment = if termination == "completed" && passed {
        if c.run.mode == Mode::Steady {
            "steady_discrete_solution"
        } else {
            "transient_interval_completed"
        }
    } else if termination == "completed" {
        "failed_checks"
    } else {
        "incomplete"
    };
    let geo = g.evidence();
    let summary = Summary {
        schema_version: "cfd-craft.result/0.1".into(),
        name: c.name.clone(),
        case_sha256: hash_bytes(&serde_json::to_vec(c).unwrap()),
        physics_sha256: c.physics_hash(),
        initial_state_sha256,
        termination,
        assessment: assessment.into(),
        error,
        model_scope: if c.flow.rans() {
            "neutral_k_epsilon_rough_wall"
        } else if c.flow.prescribed() {
            "prescribed_flow_passive_transport"
        } else {
            "incompressible_laminar"
        }
        .into(),
        experimental_validation: "not_validated; see validation/data-inventory.json".into(),
        steps: state.steps,
        physical_time_s: state.time_s,
        elapsed_s: control.elapsed(),
        pressure_iterations: state.pressure_iterations,
        momentum_solver_iterations: (c.numerics.steady_algorithm != SteadyAlgorithm::Explicit)
            .then_some(state.momentum_solver_iterations),
        turbulent_floor_events: state.floor_events,
        fluid_cells: geo.fluid_cells,
        solid_cells: geo.solid_cells,
        fluid_components: geo.fluid_components,
        mask_sha256: geo.mask_sha256.clone(),
        estimated_peak_mib: c.check().estimated_peak_mib,
        checks,
        constituents,
        velocity_max_m_s: state.velocity.iter().map(|v| v.abs()).fold(0.0, f64::max),
        momentum_residual,
        turbulence_residual,
        receptor_relative_change: monitor_change(c, &state),
        source_sha256: crate::SOURCE_SHA256.into(),
        build_version: format!("{}; {}", env!("CARGO_PKG_VERSION"), crate::RUSTC_VERSION),
        threads: c.run.threads,
    };
    Ok(RunResult {
        summary,
        state,
        geometry: geo,
    })
}
