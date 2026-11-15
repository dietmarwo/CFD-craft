//! Independent acceptance, immutability and linearity controls for R3.
use cfd_craft::{
    case::{
        Advection, Case, Constituent, Flow, Initial, ParticleBin, Receptor, Source, Vegetation,
    },
    grid::{FaceKind, Grid},
    mobile_response::{PreparedFlow, flow_state_hash},
    solver::{self, Control, RunResult},
};
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};

fn case() -> Case {
    let mut c: Case = serde_json::from_str(include_str!(
        "../../../cases/verification/source-response.json"
    ))
    .unwrap();
    c.name = "frozen-flow-reference".into();
    c.domain.size_m = [4.0, 2.0, 1.0];
    c.grid.cells = [16, 8, 1];
    c.flow = Flow::Laminar {
        initial_velocity_m_s: [1.0, 0.0, 0.0],
        viscosity_m2_s: 0.02,
        acceleration_m_s2: [0.0; 3],
    };
    c.constituents[0].diffusivity_m2_s = 0.06;
    c.sources = vec![
        Source::Point {
            id: "street-a".into(),
            constituent: "tracer".into(),
            point_m: [0.75, 0.5, 0.5],
            rate_kg_s: 1e-7,
        },
        Source::Point {
            id: "street-b".into(),
            constituent: "tracer".into(),
            point_m: [0.75, 1.5, 0.5],
            rate_kg_s: 1e-7,
        },
    ];
    c.receptors = vec![
        Receptor::Path {
            id: "ride".into(),
            polyline_m: vec![[2.0, 0.25], [2.0, 1.75]],
            height_m: 0.5,
            sample_spacing_m: 0.25,
        },
        Receptor::Point {
            id: "station".into(),
            point_m: [2.0, 1.0, 0.5],
        },
    ];
    c.numerics.monitor_window = 10;
    c.numerics.steady_residual_tolerance = 1e-7;
    c.numerics.steady_monitor_tolerance = 1e-7;
    c.run.max_steps = 12000;
    c.run.wall_time_limit_s = 20.0;
    c.run.threads = 1;
    c.output.checkpoint = false;
    c
}
fn accepted(result: &RunResult) {
    assert_eq!(
        result.summary.termination, "completed",
        "{:?}",
        result.summary.error
    );
    assert_eq!(
        result.summary.assessment, "steady_discrete_solution",
        "{:?}",
        result.summary.checks
    );
    assert!(result.summary.checks.iter().all(|check| check.passed));
}
fn response(prepared: &PreparedFlow, c: &Case) -> RunResult {
    let result = prepared.run(c, &Control::new(20.0)).unwrap();
    accepted(&result);
    let evidence = result.summary.frozen_flow.as_ref().unwrap();
    assert_eq!(evidence.response_flow_updates, 0);
    assert_eq!(evidence.native_flow_solves, 1);
    assert_eq!(result.state.pressure_iterations, 0);
    assert_eq!(result.state.momentum_solver_iterations, 0);
    assert_eq!(
        flow_state_hash(&result.state),
        flow_state_hash(&prepared.result.state)
    );
    result
}
fn preparation_result(c: &Case) -> RunResult {
    let input = PreparedFlow::preparation_case(c).unwrap();
    let result = solver::run(&input, &Control::new(20.0), None).unwrap();
    accepted(&result);
    result
}
fn rejected(result: cfd_craft::Result<PreparedFlow>, code: &str) {
    match result {
        Ok(_) => panic!("invalid flow preparation was admitted"),
        Err(error) => assert!(error.contains(code), "{error}"),
    }
}

#[test]
fn one_real_laminar_preparation_supports_cold_columns_and_independent_truth() {
    let c = case();
    let prepared = PreparedFlow::prepare(&c, &Control::new(20.0)).unwrap();
    accepted(&prepared.result);
    assert!(
        prepared.case().sources.is_empty()
            && prepared.case().constituents.is_empty()
            && prepared.case().receptors.is_empty()
    );
    let before = flow_state_hash(&prepared.result.state);
    let mut a = c.clone();
    a.sources.retain(|s| s.id() == "street-a");
    let mut b = c.clone();
    b.sources.retain(|s| s.id() == "street-b");
    let ra = response(&prepared, &a);
    let rb = response(&prepared, &b);
    let mut combined = c.clone();
    for source in &mut combined.sources {
        if let Source::Point { id, rate_kg_s, .. } = source {
            *rate_kg_s *= if id == "street-a" { 1.3 } else { 0.7 };
        }
    }
    let truth = response(&prepared, &combined);
    let scale = truth.state.concentrations[0]
        .iter()
        .copied()
        .fold(0.0, f64::max);
    let error = truth.state.concentrations[0]
        .iter()
        .zip(&ra.state.concentrations[0])
        .zip(&rb.state.concentrations[0])
        .map(|((truth, a), b)| (truth - 1.3 * a - 0.7 * b).abs())
        .fold(0.0, f64::max)
        / scale;
    eprintln!("frozen-flow independent combined truth max-normalized error={error:.16e}");
    assert!(error < 1e-5);
    assert_eq!(before, flow_state_hash(&prepared.result.state));
    for r in [&ra, &rb, &truth] {
        let scalar = &r.summary.constituents[0];
        let path = &scalar.paths["ride"];
        let sample = path
            .points_m
            .iter()
            .position(|p| *p == [2.0, 1.0, 0.5])
            .unwrap();
        assert_eq!(
            path.concentrations_kg_m3[sample],
            scalar.receptors_kg_m3["station"]
        );
        assert!((path.mean_kg_m3 - scalar.receptors_kg_m3["ride"]).abs() < 1e-18);
        assert!(scalar.relative_budget_defect < 1e-12);
    }
}

#[test]
fn coincident_street_sources_produce_genuinely_collinear_frozen_columns() {
    let mut c = case();
    c.sources[1] = Source::Point {
        id: "street-b".into(),
        constituent: "tracer".into(),
        point_m: [0.75, 0.5, 0.5],
        rate_kg_s: 1e-7,
    };
    let prepared = PreparedFlow::prepare(&c, &Control::new(20.0)).unwrap();
    let mut a = c.clone();
    a.sources.retain(|s| s.id() == "street-a");
    let mut b = c.clone();
    b.sources.retain(|s| s.id() == "street-b");
    let ra = response(&prepared, &a);
    let rb = response(&prepared, &b);
    assert_eq!(ra.state.concentrations, rb.state.concentrations);
    assert_eq!(
        ra.summary.constituents[0].paths["ride"].concentrations_kg_m3,
        rb.summary.constituents[0].paths["ride"].concentrations_kg_m3
    );
}

#[test]
fn response_rejects_changed_flow_nonlinear_transport_and_initial_mass() {
    let c = case();
    let prepared = PreparedFlow::prepare(&c, &Control::new(20.0)).unwrap();
    let mut changed = c.clone();
    if let Flow::Laminar {
        initial_velocity_m_s,
        ..
    } = &mut changed.flow
    {
        *initial_velocity_m_s = [0.9, 0.0, 0.0];
    }
    assert!(
        prepared
            .run(&changed, &Control::new(20.0))
            .err()
            .expect("response must be rejected")
            .contains("CFD-E089")
    );
    changed = c.clone();
    changed.numerics.transport = Advection::Muscl;
    assert!(
        prepared
            .run(&changed, &Control::new(20.0))
            .err()
            .expect("response must be rejected")
            .contains("CFD-E089")
    );
    changed = c.clone();
    changed.initial_conditions.push(Initial::Uniform {
        constituent: "tracer".into(),
        concentration_kg_m3: 1e-6,
    });
    assert!(
        prepared
            .run(&changed, &Control::new(20.0))
            .err()
            .expect("response must be rejected")
            .contains("CFD-E089")
    );
    rejected(
        PreparedFlow::prepare(&changed, &Control::new(20.0)),
        "CFD-E089",
    );
    rejected(
        PreparedFlow::from_accepted(&changed, preparation_result(&c)),
        "CFD-E089",
    );
    let mut nonlinear = c.clone();
    nonlinear.numerics.transport = Advection::Muscl;
    let mut flow_only = nonlinear.clone();
    flow_only.constituents.clear();
    flow_only.sources.clear();
    flow_only.initial_conditions.clear();
    flow_only.receptors.clear();
    let flow = solver::run(&flow_only, &Control::new(20.0), None).unwrap();
    accepted(&flow);
    rejected(PreparedFlow::from_accepted(&nonlinear, flow), "CFD-E089");
}

#[test]
fn preparation_rejects_failed_stopping_status_or_tampered_claims_and_fields() {
    let c = case();
    let mut result = preparation_result(&c);
    result.summary.termination = "wall_time_limit".into();
    rejected(PreparedFlow::from_accepted(&c, result), "CFD-E089");
    let mut result = preparation_result(&c);
    result.summary.checks[0].passed = false;
    rejected(PreparedFlow::from_accepted(&c, result), "CFD-E089");
    let mut result = preparation_result(&c);
    result.summary.source_sha256 = "0".repeat(64);
    rejected(PreparedFlow::from_accepted(&c, result), "CFD-E089");
    let mut result = preparation_result(&c);
    let flow_case = PreparedFlow::preparation_case(&c).unwrap();
    let g = Grid::build(&flow_case).unwrap();
    let f = g
        .faces
        .iter()
        .position(|f| f.kind == FaceKind::Interior)
        .unwrap();
    result.state.velocity[f] += 0.1;
    rejected(PreparedFlow::from_accepted(&c, result), "CFD-E089");
    let mut short = PreparedFlow::preparation_case(&c).unwrap();
    short.run.max_steps = 1;
    let failed = solver::run(&short, &Control::new(20.0), None).unwrap();
    assert_ne!(failed.summary.assessment, "steady_discrete_solution");
    rejected(PreparedFlow::from_accepted(&c, failed), "CFD-E089");
}

#[test]
fn frozen_responses_keep_partial_work_and_immutable_flow_under_stop_controls() {
    let c = case();
    let prepared = PreparedFlow::prepare(&c, &Control::new(20.0)).unwrap();
    let before = flow_state_hash(&prepared.result.state);
    let control = Control::new(20.0);
    control.cancelled.store(true, Ordering::Relaxed);
    assert_eq!(
        prepared
            .run(&c, &control)
            .err()
            .expect("response must be rejected"),
        "cancelled"
    );
    let calls = Arc::new(AtomicUsize::new(0));
    let counter = calls.clone();
    let control = Control::with_poll(20.0, move || {
        if counter.fetch_add(1, Ordering::SeqCst) >= 4 {
            Err("cancelled".into())
        } else {
            Ok(())
        }
    });
    let partial = prepared.run(&c, &control).unwrap();
    assert_eq!(partial.summary.termination, "cancelled");
    assert_eq!(partial.summary.assessment, "incomplete");
    assert!(partial.state.steps > 0 && partial.state.steps <= 4);
    assert_eq!(flow_state_hash(&partial.state), before);
    assert_eq!(
        partial
            .summary
            .frozen_flow
            .as_ref()
            .unwrap()
            .response_flow_updates,
        0
    );
    let mut limited = c.clone();
    limited.run.max_steps = 1;
    let partial = prepared.run(&limited, &Control::new(20.0)).unwrap();
    assert_eq!(partial.summary.termination, "iteration_limit");
    assert_eq!(partial.state.steps, 1);
    assert_eq!(flow_state_hash(&partial.state), before);
    assert_eq!(flow_state_hash(&prepared.result.state), before);
}

#[test]
fn particle_deposition_and_multiple_constituents_use_the_same_accepted_flow() {
    let mut c = case();
    c.constituents[0].particle = Some(ParticleBin {
        diameter_m: 1e-6,
        density_kg_m3: 1000.0,
        settling_velocity_m_s: Some(0.0),
        ground_deposition_velocity_m_s: 0.0,
        roof_deposition_velocity_m_s: 0.0,
    });
    c.constituents.push(Constituent {
        id: "gas2".into(),
        diffusivity_m2_s: 0.03,
        particle: None,
    });
    c.sources.push(Source::Point {
        id: "gas-source".into(),
        constituent: "gas2".into(),
        point_m: [0.75, 1.0, 0.5],
        rate_kg_s: 1e-7,
    });
    c.vegetation = vec![Vegetation {
        id: "leaves".into(),
        min_m: [0.0; 3],
        max_m: [4.0, 2.0, 1.0],
        leaf_area_density_m2_m3: 1.0,
        drag_coefficient: 0.0,
        leaf_deposition_velocity_m_s: 0.2,
        turbulence_closure: Default::default(),
    }];
    let prepared = PreparedFlow::prepare(&c, &Control::new(20.0)).unwrap();
    let result = response(&prepared, &c);
    let particle = &result.summary.constituents[0];
    assert!(particle.deposited_kg["vegetation"] > 0.0);
    assert!(particle.relative_budget_defect < 1e-12);
    let gas = &result.summary.constituents[1];
    assert!(gas.deposited_kg.is_empty());
    assert!(gas.mass_kg > 0.0);
    assert!(gas.relative_budget_defect < 1e-12);
}
