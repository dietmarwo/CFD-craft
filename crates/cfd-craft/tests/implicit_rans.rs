//! Stages P5c and P5d: the implicit steady iteration with RANS and with
//! constituents.
use cfd_craft::{
    case::*,
    flow,
    grid::{FaceKind, Grid},
    momentum_solve::Stencil,
    solver::{Control, State, run},
    turbulence_solve,
};

fn load(path: &str) -> Case {
    let path = format!("{}/../../cases/{path}", env!("CARGO_MANIFEST_DIR"));
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

/// The development canyon without constituents, in steady mode.
fn canyon(algorithm: SteadyAlgorithm) -> Case {
    let mut c = load("canyon/wh1-wind270.json");
    c.constituents.clear();
    c.sources.clear();
    c.receptors.clear();
    c.initial_conditions.clear();
    c.run.threads = 1;
    c.output.fields = false;
    c.output.checkpoint = false;
    c.numerics.steady_algorithm = algorithm;
    c
}

fn developed(c: &Case, steps: usize) -> State {
    let mut c = c.clone();
    c.numerics.steady_algorithm = SteadyAlgorithm::Explicit;
    c.run.max_steps = steps;
    run(&c, &Control::new(120.0), None).unwrap().state
}

#[test]
fn rans_rules_allow_only_the_implicit_projection_algorithm() {
    let codes = |c: &Case| {
        c.check()
            .diagnostics
            .into_iter()
            .filter(|d| d.path == "numerics.steady_algorithm")
            .map(|d| d.code)
            .collect::<Vec<_>>()
    };
    let c = canyon(SteadyAlgorithm::ImplicitProjection);
    assert!(codes(&c).is_empty(), "{:?}", codes(&c));
    let c = canyon(SteadyAlgorithm::ImplicitViscous);
    assert_eq!(codes(&c), ["CFD-E047"]);
    let mut prescribed = load("verification/periodic-tracer.json");
    prescribed.run.mode = Mode::Steady;
    prescribed.constituents.clear();
    prescribed.sources.clear();
    prescribed.receptors.clear();
    prescribed.initial_conditions.clear();
    prescribed.numerics.steady_algorithm = SteadyAlgorithm::ImplicitProjection;
    assert_eq!(codes(&prescribed), ["CFD-E047"]);
}

// With u = 0 the advection and wall-function stresses are quadratic in a small
// correction, so A − I/Δτ must equal minus the variation of the momentum
// right-hand side. nut varies along one axis and the correction has no
// component along it, so the explicit cross term is zero too.
#[test]
fn the_rans_matrix_is_the_linear_part_of_the_momentum_right_hand_side() {
    let mut c = load("verification/empty-abl.json");
    c.grid.cells = [6, 4, 8];
    c.run.mode = Mode::Steady;
    c.numerics.steady_algorithm = SteadyAlgorithm::ImplicitProjection;
    let g = Grid::build(&c).unwrap();
    let stencil = Stencil::build(&c, &g);
    let dt = 0.3;
    // Not enforced: inflow faces stay at zero too, so nothing advects δ.
    let base = vec![0.0; g.faces.len()];
    for (varying, components) in [(2usize, [0usize, 1]), (0, [2, 2])] {
        let nut: Vec<_> = (0..g.count())
            .map(|i| {
                let s = g.coord(i)[varying];
                0.01 + 0.004 * s as f64 + 0.002 * (s as f64).powi(2)
            })
            .collect();
        let matrix = stencil.implicit_matrix_rans(&c, &g, &base, &nut, dt);
        let scale = 1e-7;
        let delta: Vec<_> = (0..g.faces.len())
            .map(|i| {
                if stencil.unknown[i] && components.contains(&g.faces[i].axis) {
                    (1.3 * i as f64).cos()
                } else {
                    0.0
                }
            })
            .collect();
        let shifted: Vec<_> = base
            .iter()
            .zip(&delta)
            .map(|(a, b)| a + scale * b)
            .collect();
        let r0 = flow::momentum_rhs(&c, &g, &base, &nut);
        let r1 = flow::momentum_rhs(&c, &g, &shifted, &nut);
        let mut actual = vec![0.0; g.faces.len()];
        matrix.apply(&stencil, &delta, &mut actual);
        // Rows of the other components see δ only as an advecting velocity
        // (of the constant upper-boundary stress ghost), which the Picard
        // matrix omits by design; they are not compared.
        let worst = (0..g.faces.len())
            .filter(|i| stencil.unknown[*i] && components.contains(&g.faces[*i].axis))
            .map(|i| {
                let expected = -(r1[i] - r0[i]) / scale;
                let a = actual[i] - delta[i] / dt;
                (a - expected).abs() / (1.0 + expected.abs())
            })
            .fold(0.0, f64::max);
        assert!(worst <= 1e-5, "nut along axis {varying}: {worst}");
    }
}

#[test]
fn the_rans_matrix_is_an_m_matrix_with_lagged_wall_functions() {
    let c = canyon(SteadyAlgorithm::ImplicitProjection);
    let g = Grid::build(&c).unwrap();
    let state = developed(&c, 40);
    let nut = flow::eddy_viscosity(&g, &state.k, &state.epsilon);
    let stencil = Stencil::build(&c, &g);
    let dt = 0.5;
    let m = stencil.implicit_matrix_rans(&c, &g, &state.velocity, &nut, dt);
    let u = &state.velocity;
    for fi in (0..g.faces.len()).filter(|i| stencil.unknown[*i]) {
        let off: f64 = m.off[fi].iter().flatten().sum();
        assert!(m.diagonal[fi] > 0.0, "face {fi}");
        assert!(m.off[fi].iter().flatten().all(|v| *v <= 0.0), "face {fi}");
        // Row sums: 1/Δτ plus the control-volume divergence of the frozen
        // advecting velocities, plus nonnegative terms from prescribed
        // neighbors and wall-function ghosts (B ≤ 1).
        let divergence: f64 = (0..3)
            .map(|d| {
                let [lo, hi] = stencil.advecting[fi][d].map(|[a, b]| 0.5 * (u[a] + u[b]));
                (hi - lo) / stencil.spacing[d]
            })
            .sum();
        assert!(
            m.diagonal[fi] + off >= 1.0 / dt + divergence - 1e-10 * m.diagonal[fi],
            "face {fi}: {} {off} {divergence}",
            m.diagonal[fi]
        );
    }
}

// For a vanishing pseudo-time step the implicit k–ε step and the explicit
// step both advance by Δτ times the same residual.
#[test]
fn small_implicit_turbulence_steps_follow_the_explicit_residual() {
    let c = canyon(SteadyAlgorithm::ImplicitProjection);
    let g = Grid::build(&c).unwrap();
    let state = developed(&c, 30);
    let dt = 1e-7;
    let (mut ke, mut ee) = (state.k.clone(), state.epsilon.clone());
    let floors = flow::turbulence_step(&c, &g, &state.velocity, &mut ke, &mut ee, dt);
    let (mut ki, mut ei) = (state.k.clone(), state.epsilon.clone());
    let info = turbulence_solve::implicit_step(
        &c,
        &g,
        &state.velocity,
        &mut ki,
        &mut ei,
        dt,
        &Control::new(60.0),
    )
    .unwrap();
    assert_eq!((floors, info.floor_events), (0, 0));
    let compare = |old: &[f64], a: &[f64], b: &[f64], name: &str| {
        let scale = (0..g.count())
            .filter(|i| g.fluid[*i])
            .map(|i| (a[i] - old[i]).abs())
            .fold(0.0, f64::max);
        assert!(scale > 0.0);
        for i in (0..g.count()).filter(|i| g.fluid[*i]) {
            let (x, y) = (a[i] - old[i], b[i] - old[i]);
            assert!((x - y).abs() <= 1e-4 * scale, "{name} cell {i}: {x} vs {y}");
        }
    };
    compare(&state.k, &ke, &ki, "k");
    compare(&state.epsilon, &ee, &ei, "epsilon");
    // Solid cells are untouched.
    for i in (0..g.count()).filter(|i| !g.fluid[*i]) {
        assert_eq!(ki[i].to_bits(), state.k[i].to_bits());
        assert_eq!(ei[i].to_bits(), state.epsilon[i].to_bits());
    }
}

#[test]
fn implicit_rans_canyons_restart_bit_for_bit() {
    let mut c = canyon(SteadyAlgorithm::ImplicitProjection);
    c.numerics.momentum_advection = MomentumAdvection::LimitedUpwind;
    c.numerics.momentum_limiter = Some(MomentumLimiter::VanLeer);
    c.run.max_steps = 6;
    let whole = run(&c, &Control::new(120.0), None).unwrap();
    c.run.max_steps = 3;
    let first = run(&c, &Control::new(120.0), None).unwrap().state;
    c.run.max_steps = 6;
    let resumed = run(&c, &Control::new(120.0), Some(first)).unwrap();
    let bits = |v: &[f64]| v.iter().map(|x| x.to_bits()).collect::<Vec<_>>();
    assert_eq!(bits(&whole.state.velocity), bits(&resumed.state.velocity));
    assert_eq!(bits(&whole.state.pressure), bits(&resumed.state.pressure));
    assert_eq!(bits(&whole.state.k), bits(&resumed.state.k));
    assert_eq!(bits(&whole.state.epsilon), bits(&resumed.state.epsilon));
    assert_eq!(whole.state.floor_events, resumed.state.floor_events);
    assert_eq!(
        whole.state.momentum_solver_iterations,
        resumed.state.momentum_solver_iterations
    );
}

#[test]
fn the_implicit_rans_iteration_profiles_its_turbulence_solves() {
    let mut c = canyon(SteadyAlgorithm::ImplicitProjection);
    c.run.max_steps = 4;
    let control = Control::new(120.0).with_profiling();
    run(&c, &control, None).unwrap();
    let profile = control.profile().unwrap().unwrap();
    let solve = &profile.phases["turbulence_solve"];
    assert_eq!(solve.calls, 4);
    assert!(solve.work_units >= 4);
    assert!(solve.work_units <= 2 * turbulence_solve::TURBULENCE_MAX_ITERATIONS as u64 * 4);
    assert_eq!(solve.operator_applications, 2 * solve.work_units);
    // The wall faces of the canyon carry no momentum equation.
    let g = Grid::build(&c).unwrap();
    assert!(g.faces.iter().any(|f| f.kind == FaceKind::Wall));
}

/// The development canyon with its tracer.
fn canyon_with_tracer(algorithm: SteadyAlgorithm) -> Case {
    let mut c = load("canyon/wh1-wind270.json");
    c.run.threads = 1;
    c.output.fields = false;
    c.output.checkpoint = false;
    c.numerics.steady_algorithm = algorithm;
    c
}

#[test]
fn scalar_substeps_cover_the_pseudo_time_step_up_to_the_cap() {
    use cfd_craft::solver::{SCALAR_SUBSTEPS_MAX, scalar_substeps};
    assert_eq!(scalar_substeps(0.3, 0.5), (1, 0.3));
    assert_eq!(scalar_substeps(0.5, 0.5), (1, 0.5));
    let (n, dt) = scalar_substeps(1.25, 0.5);
    assert_eq!(n, 3);
    assert!((dt - 1.25 / 3.0).abs() <= 1e-15);
    assert_eq!(scalar_substeps(100.0, 0.5), (SCALAR_SUBSTEPS_MAX, 0.5));
    assert_eq!(SCALAR_SUBSTEPS_MAX, 16);
}

#[test]
fn implicit_steady_scalars_keep_mass_positivity_and_superposition() {
    for algorithm in [
        SteadyAlgorithm::ImplicitProjection,
        SteadyAlgorithm::ImplicitViscous,
    ] {
        // implicit_viscous needs laminar flow: use the canyon geometry laminar.
        let mut c = canyon_with_tracer(algorithm);
        if algorithm == SteadyAlgorithm::ImplicitViscous {
            c.flow = Flow::Laminar {
                viscosity_m2_s: 0.01,
                acceleration_m_s2: [0.0, 0.0, 0.0],
                initial_velocity_m_s: [0.5, 0.0, 0.0],
            };
            c.boundaries.z = Boundary::Wall;
        }
        let errors: Vec<_> = c
            .check()
            .diagnostics
            .into_iter()
            .filter(|d| d.severity == "error")
            .map(|d| d.code)
            .collect();
        assert!(errors.is_empty(), "{algorithm:?}: {errors:?}");
        c.run.max_steps = 25;
        let r = run(&c, &Control::new(120.0), None).unwrap();
        let s = &r.summary.constituents[0];
        assert!(s.relative_budget_defect < 1e-12, "{algorithm:?}: {s:?}");
        assert!(s.emitted_kg > 0.0 && s.negative_mass_kg == 0.0);
        let g = Grid::build(&c).unwrap();
        assert!(
            (0..g.count())
                .filter(|i| g.fluid[*i])
                .all(|i| r.state.concentrations[0][i] >= 0.0)
        );
        // The flow does not depend on the constituents, so doubling the
        // emission doubles every concentration.
        let mut doubled = c.clone();
        let Source::Line { rate_kg_s_m, .. } = &mut doubled.sources[0] else {
            panic!("line source expected");
        };
        *rate_kg_s_m *= 2.0;
        let rr = run(&doubled, &Control::new(120.0), None).unwrap();
        let scale = r.state.concentrations[0]
            .iter()
            .copied()
            .fold(0.0, f64::max);
        for (a, b) in r.state.concentrations[0]
            .iter()
            .zip(&rr.state.concentrations[0])
        {
            assert!((2.0 * a - b).abs() <= 1e-12 * scale, "{algorithm:?}");
        }
        assert_eq!(r.state.velocity, rr.state.velocity);
    }
}

#[test]
fn implicit_canyons_with_constituents_restart_bit_for_bit() {
    let mut c = canyon_with_tracer(SteadyAlgorithm::ImplicitProjection);
    c.run.max_steps = 6;
    let whole = run(&c, &Control::new(120.0), None).unwrap();
    c.run.max_steps = 3;
    let first = run(&c, &Control::new(120.0), None).unwrap().state;
    c.run.max_steps = 6;
    let resumed = run(&c, &Control::new(120.0), Some(first)).unwrap();
    let bits = |v: &[f64]| v.iter().map(|x| x.to_bits()).collect::<Vec<_>>();
    assert_eq!(
        bits(&whole.state.concentrations[0]),
        bits(&resumed.state.concentrations[0])
    );
    let (a, b) = (&whole.state.budgets[0], &resumed.state.budgets[0]);
    for (x, y) in [
        (a.emitted_kg, b.emitted_kg),
        (a.inflow_kg, b.inflow_kg),
        (a.outflow_kg, b.outflow_kg),
    ] {
        assert_eq!(x.to_bits(), y.to_bits());
    }
}

// When the sub-step cap binds, the constituents cover less pseudo-time than
// the flow; the state records it, and the emitted mass is the rate times it.
#[test]
fn the_state_records_the_constituents_pseudo_time() {
    let mut c = canyon_with_tracer(SteadyAlgorithm::ImplicitProjection);
    c.numerics.max_time_step_s = 100.0;
    c.run.max_steps = 25;
    let r = run(&c, &Control::new(120.0), None).unwrap();
    let scalar = r.state.scalar_time_s.unwrap();
    assert!(
        scalar > 0.0 && scalar < r.state.time_s,
        "{scalar} {}",
        r.state.time_s
    );
    let Source::Line {
        from_m,
        to_m,
        rate_kg_s_m,
        ..
    } = &c.sources[0]
    else {
        panic!("line source expected");
    };
    let length = (0..3)
        .map(|a| (to_m[a] - from_m[a]).powi(2))
        .sum::<f64>()
        .sqrt();
    let emitted = r.state.budgets[0].emitted_kg;
    assert!((emitted - rate_kg_s_m * length * scalar).abs() <= 1e-12 * emitted);
    let text = serde_json::to_string(&r.state).unwrap();
    assert!(text.contains("scalar_time_s"));
    // Explicit runs keep their bytes: no separate scalar time.
    let mut explicit = canyon_with_tracer(SteadyAlgorithm::Explicit);
    explicit.run.max_steps = 3;
    let e = run(&explicit, &Control::new(60.0), None).unwrap();
    assert_eq!(e.state.scalar_time_s, None);
    assert!(
        !serde_json::to_string(&e.state)
            .unwrap()
            .contains("scalar_time_s")
    );
}
