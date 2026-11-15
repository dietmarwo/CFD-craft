//! Porous-canopy fixed-point, mass and zero-effect verification.
use cfd_craft::{
    case::Case,
    flow,
    grid::Grid,
    solver::{self, Control},
    vegetation,
};
use serde_json::json;
fn base() -> serde_json::Value {
    let mut v: serde_json::Value = serde_json::from_str(include_str!(
        "../../../cases/verification/periodic-tracer.json"
    ))
    .unwrap();
    v["domain"]["size_m"] = json!([1.0, 1.0, 1.0]);
    v["grid"]["cells"] = json!([4, 4, 4]);
    v["flow"] = json!({"kind":"laminar","initial_velocity_m_s":[1.0,0.0,0.0],"viscosity_m2_s":1e-3,"acceleration_m_s2":[0.08,0.0,0.0]});
    v["sources"] = json!([]);
    v["initial_conditions"] = json!([]);
    v["constituents"] = json!([]);
    v["receptors"] = json!([]);
    v["numerics"]["steady_algorithm"] = json!("implicit_projection");
    v["numerics"]["monitor_window"] = json!(10);
    v["numerics"]["steady_residual_tolerance"] = json!(1e-8);
    v["numerics"]["steady_monitor_tolerance"] = json!(1e-8);
    v["numerics"]["max_time_step_s"] = json!(10.0);
    v["run"]["mode"] = json!("steady");
    v["run"]["max_steps"] = json!(400);
    v["run"]["wall_time_limit_s"] = json!(20.0);
    v["run"]["threads"] = json!(1);
    v["vegetation"] = json!([{"id":"canopy","min_m":[0.0,0.0,0.0],"max_m":[1.0,1.0,1.0],"leaf_area_density_m2_m3":2.0,"drag_coefficient":0.5,"leaf_deposition_velocity_m_s":0.1}]);
    v
}
fn solve(c: &Case) -> solver::RunResult {
    solver::run(c, &Control::new(20.0), None).unwrap()
}
#[test]
fn uniform_canopy_speed_matches_force_drag_balance() {
    let c: Case = serde_json::from_value(base()).unwrap();
    let r = solve(&c);
    assert_eq!(
        r.summary.assessment, "steady_discrete_solution",
        "{:?}",
        r.summary.checks
    );
    let speed = (0.08_f64 / (0.5 * 2.0)).sqrt();
    let g = Grid::build(&c).unwrap();
    let cells = g.cell_velocity(&r.state.velocity);
    let error = cells
        .iter()
        .map(|u| (u[0] - speed).abs())
        .fold(0.0, f64::max);
    eprintln!("uniform canopy speed error={error:.16e}; expected={speed:.16e}");
    assert!(error < 1e-7);
    let e = r.summary.vegetation.unwrap();
    assert!((e.integrated_drag_acceleration_m4_s2[0] + 0.08).abs() < 1e-7);
    assert!((e.drag_power_per_density_m5_s3 - 0.08 * speed).abs() < 1e-7);
}
#[test]
fn porous_block_pressure_drop_equals_integrated_drag() {
    let mut v = base();
    v["domain"]["size_m"] = json!([4.0, 1.0, 1.0]);
    v["grid"]["cells"] = json!([32, 2, 2]);
    v["boundaries"]["x"] = json!("open");
    v["flow"]["acceleration_m_s2"] = json!([0.0, 0.0, 0.0]);
    v["vegetation"][0]["min_m"] = json!([1.0, 0.0, 0.0]);
    v["vegetation"][0]["max_m"] = json!([3.0, 1.0, 1.0]);
    v["vegetation"][0]["drag_coefficient"] = json!(0.2);
    v["run"]["max_steps"] = json!(1200);
    let c: Case = serde_json::from_value(v).unwrap();
    let r = solve(&c);
    assert_eq!(
        r.summary.assessment, "steady_discrete_solution",
        "{:?}",
        r.summary.checks
    );
    let delta = r.state.pressure[0] - r.state.pressure[31];
    let drag = -r
        .summary
        .vegetation
        .unwrap()
        .integrated_drag_acceleration_m4_s2[0];
    eprintln!("porous block pressure drop={delta:.16e}; volume-integrated drag={drag:.16e}");
    assert!((delta - 0.8).abs() < 1e-7);
    assert!((delta - drag).abs() < 1e-7);
}
#[test]
fn uniform_leaf_deposition_matches_exponential_and_mass_ledger() {
    let mut v = base();
    v["flow"] = json!({"kind":"prescribed_uniform","velocity_m_s":[0.0,0.0,0.0]});
    v["numerics"]["steady_algorithm"] = json!("explicit");
    v["numerics"]["max_time_step_s"] = json!(0.02);
    v["run"]["mode"] = json!("transient");
    v["run"]["end_time_s"] = json!(2.0);
    v["constituents"] = json!([{"id":"dust","diffusivity_m2_s":0.0,"particle":{"diameter_m":1e-6,"density_kg_m3":1000.0,"settling_velocity_m_s":0.0}}]);
    v["initial_conditions"] =
        json!([{"kind":"uniform","constituent":"dust","concentration_kg_m3":1e-6}]);
    v["vegetation"][0]["drag_coefficient"] = json!(0.0);
    let c: Case = serde_json::from_value(v).unwrap();
    let r = solve(&c);
    assert_eq!(r.summary.assessment, "transient_interval_completed");
    let expected = 1e-6_f64 * (-2.0_f64 * 0.1 * 2.0).exp();
    let e = &r.summary.constituents[0];
    eprintln!(
        "uniform leaf decay mass={:.16e}; exponential={expected:.16e}; mass defect={:.3e}",
        e.mass_kg, e.relative_budget_defect
    );
    assert!((e.mass_kg - expected).abs() / expected < 2e-6);
    assert!((e.deposited_kg["vegetation"] + e.mass_kg - 1e-6).abs() < 1e-18);
    assert!(e.relative_budget_defect < 1e-12);
}
#[test]
fn zero_lad_preserves_complete_state_and_empty_abl_terms() {
    let c: Case =
        serde_json::from_str(include_str!("../../../cases/verification/empty-abl.json")).unwrap();
    let mut c = c;
    c.run.max_steps = 3;
    c.run.threads = 1;
    let g = Grid::build(&c).unwrap();
    let original = solver::initial_state(&c, &g);
    let mut v = serde_json::to_value(&c).unwrap();
    v["vegetation"] = json!([{"id":"zero","min_m":[0.0,0.0,0.0],"max_m":[18.0,16.0,6.0],"leaf_area_density_m2_m3":0.0,"drag_coefficient":0.9,"leaf_deposition_velocity_m_s":1.0}]);
    let zero: Case = serde_json::from_value(v).unwrap();
    let gz = Grid::build(&zero).unwrap();
    assert_eq!(
        serde_json::to_vec(&original).unwrap(),
        serde_json::to_vec(&solver::initial_state(&zero, &gz)).unwrap()
    );
    let nut = flow::eddy_viscosity(&g, &original.k, &original.epsilon);
    assert_eq!(
        flow::momentum_rhs(&c, &g, &original.velocity, &nut),
        flow::momentum_rhs(&zero, &gz, &original.velocity, &nut)
    );
    let (mut ka, mut ea) = (original.k.clone(), original.epsilon.clone());
    let (mut kb, mut eb) = (ka.clone(), ea.clone());
    let a = flow::turbulence_step(&c, &g, &original.velocity, &mut ka, &mut ea, 0.001);
    let b = flow::turbulence_step(&zero, &gz, &original.velocity, &mut kb, &mut eb, 0.001);
    assert_eq!((ka, ea, a), (kb, eb, b));
    let r = solve(&c);
    let z = solve(&zero);
    assert_eq!(
        serde_json::to_vec(&r.state).unwrap(),
        serde_json::to_vec(&z.state).unwrap()
    );
    assert!(z.summary.vegetation.is_none());
    assert!(!vegetation::active(&zero));
}
#[test]
fn closures_add_exact_published_source_terms_with_same_fine_equations() {
    // Finite-difference a tiny explicit step against independent local source
    // formulas, subtracting the same ambient RANS update, away from walls.
    let mut c: Case =
        serde_json::from_str(include_str!("../../../cases/verification/empty-abl.json")).unwrap();
    c.grid.cells = [4, 2, 8];
    for (name, beta_d, c4, c5) in [("green1992", 4.0, 1.5, 1.5), ("sanz2003", 5.1, 0.9, 0.9)] {
        let mut v = serde_json::to_value(&c).unwrap();
        v["vegetation"] = json!([{"id":"canopy","min_m":[0.0,0.0,0.0],"max_m":[18.0,16.0,6.0],"leaf_area_density_m2_m3":0.2,"drag_coefficient":0.3,"turbulence_closure":name}]);
        let canopy: Case = serde_json::from_value(v).unwrap();
        let g = Grid::build(&c).unwrap();
        let s = solver::initial_state(&c, &g);
        let (mut ka, mut ea) = (s.k.clone(), s.epsilon.clone());
        let (mut kb, mut eb) = (ka.clone(), ea.clone());
        let dt = 1e-8;
        flow::turbulence_step(&c, &g, &s.velocity, &mut ka, &mut ea, dt);
        flow::turbulence_step(&canopy, &g, &s.velocity, &mut kb, &mut eb, dt);
        let velocities = g.cell_velocity(&s.velocity);
        for i in 0..g.count() {
            if g.coord(i)[2] < 2 || g.coord(i)[2] > 5 {
                continue;
            }
            let q = velocities[i].iter().map(|u| u * u).sum::<f64>().sqrt();
            let expected_k = 0.3 * 0.2 * (q.powi(3) - beta_d * q * s.k[i]);
            let expected_e = 0.3
                * 0.2
                * (c4 * q.powi(3) * s.epsilon[i] / s.k[i] - c5 * beta_d * q * s.epsilon[i]);
            assert!(((kb[i] - ka[i]) / dt - expected_k).abs() < 2e-6);
            assert!(((eb[i] - ea[i]) / dt - expected_e).abs() < 2e-6);
        }
    }
}

#[test]
fn steady_flow_through_leaf_block_has_exponential_attenuation_and_refines() {
    let mut errors = vec![];
    for n in [32, 64, 128] {
        let h = 4.0 / n as f64;
        let mut v = base();
        v["domain"]["size_m"] = json!([4.0, 1.0, 1.0]);
        v["grid"]["cells"] = json!([n, 1, 1]);
        v["boundaries"]["x"] = json!("open");
        v["flow"] = json!({"kind":"prescribed_uniform","velocity_m_s":[1.0,0.0,0.0]});
        v["numerics"]["steady_algorithm"] = json!("explicit");
        v["run"]["max_steps"] = json!(15000);
        v["vegetation"][0]["min_m"] = json!([1.0, 0.0, 0.0]);
        v["vegetation"][0]["max_m"] = json!([3.0, 1.0, 1.0]);
        v["vegetation"][0]["drag_coefficient"] = json!(0.0);
        v["vegetation"][0]["leaf_area_density_m2_m3"] = json!(1.0);
        v["vegetation"][0]["leaf_deposition_velocity_m_s"] = json!(0.2);
        v["constituents"] = json!([{"id":"dust","diffusivity_m2_s":0.0,"particle":{"diameter_m":1e-6,"density_kg_m3":1000.0,"settling_velocity_m_s":0.0}}]);
        v["sources"] = json!([{"id":"supply","kind":"volume","constituent":"dust","min_m":[0.0,0.0,0.0],"max_m":[h,1.0,1.0],"rate_kg_s_m3":1e-6/h}]);
        let c: Case = serde_json::from_value(v).unwrap();
        let r = solve(&c);
        assert_eq!(
            r.summary.assessment, "steady_discrete_solution",
            "{:?}",
            r.summary.checks
        );
        let expected = 1e-6 * (-0.4_f64).exp();
        let value = r.state.concentrations[0][n - 1];
        errors.push((value - expected).abs() / expected);
        assert!(r.summary.constituents[0].relative_budget_defect < 1e-12);
    }
    eprintln!("leaf-block exponential relative errors={errors:?}");
    assert!(errors[2] < 0.002);
    for pair in errors.windows(2) {
        assert!((pair[0] / pair[1]).log2() > 0.95);
    }
}
#[test]
fn prescribed_flow_rejects_ignored_drag_but_accepts_leaf_only() {
    let mut v = base();
    v["flow"] = json!({"kind":"prescribed_uniform","velocity_m_s":[1.0,0.0,0.0]});
    v["numerics"]["steady_algorithm"] = json!("explicit");
    let c: Case = serde_json::from_value(v.clone()).unwrap();
    assert!(
        c.check()
            .diagnostics
            .iter()
            .any(|d| d.code == "CFD-E083" && d.path == "vegetation[0].drag_coefficient")
    );
    v["vegetation"][0]["drag_coefficient"] = json!(0.0);
    assert!(serde_json::from_value::<Case>(v).unwrap().check().valid);
}

#[test]
fn transient_canopy_drag_has_declared_first_order_time_refinement() {
    let mut errors = vec![];
    for dt in [0.05, 0.025, 0.0125] {
        let mut v = base();
        v["numerics"]["steady_algorithm"] = json!("explicit");
        v["numerics"]["max_time_step_s"] = json!(dt);
        v["run"]["mode"] = json!("transient");
        v["run"]["end_time_s"] = json!(1.0);
        v["flow"]["acceleration_m_s2"] = json!([0.0, 0.0, 0.0]);
        let c: Case = serde_json::from_value(v).unwrap();
        let r = solve(&c);
        assert_eq!(r.summary.assessment, "transient_interval_completed");
        let g = Grid::build(&c).unwrap();
        errors.push((g.cell_velocity(&r.state.velocity)[0][0] - 0.5).abs());
    }
    eprintln!("canopy transient time errors={errors:?}");
    for pair in errors.windows(2) {
        let order = (pair[0] / pair[1]).log2();
        assert!((0.9..1.1).contains(&order), "{errors:?}");
    }
}
#[test]
fn drag_work_is_exactly_the_discrete_momentum_sink_on_face_dual_volumes() {
    let c: Case = serde_json::from_value(base()).unwrap();
    let g = Grid::build(&c).unwrap();
    let u: Vec<_> = (0..g.faces.len())
        .map(|i| (i as f64 * 0.13).sin())
        .collect();
    let mut empty = c.clone();
    empty.vegetation.clear();
    let base = flow::momentum_rhs(&empty, &g, &u, &vec![0.0; g.count()]);
    let with = flow::momentum_rhs(&c, &g, &u, &vec![0.0; g.count()]);
    let expected: f64 = g
        .faces
        .iter()
        .enumerate()
        .map(|(i, f)| -(with[i] - base[i]) * u[i] * f.area * f.distance)
        .sum();
    let evidence = vegetation::evidence(&c, &g, &u).unwrap();
    assert!((evidence.drag_power_per_density_m5_s3 - expected).abs() < 1e-13);
}

#[test]
fn implicit_canopy_turbulence_drives_the_same_local_equations_as_explicit() {
    let mut c: Case =
        serde_json::from_str(include_str!("../../../cases/verification/empty-abl.json")).unwrap();
    c.grid.cells = [4, 2, 8];
    for closure in ["green1992", "sanz2003"] {
        let mut v = serde_json::to_value(&c).unwrap();
        v["vegetation"] = json!([{"id":"canopy","min_m":[0.0,0.0,0.0],"max_m":[18.0,16.0,6.0],"leaf_area_density_m2_m3":0.2,"drag_coefficient":0.3,"turbulence_closure":closure}]);
        let c: Case = serde_json::from_value(v).unwrap();
        let g = Grid::build(&c).unwrap();
        let state = solver::initial_state(&c, &g);
        let (mut k_exp, mut e_exp) = (state.k.clone(), state.epsilon.clone());
        let (mut k_imp, mut e_imp) = (k_exp.clone(), e_exp.clone());
        let dt = 1e-7;
        flow::turbulence_step(&c, &g, &state.velocity, &mut k_exp, &mut e_exp, dt);
        let info = cfd_craft::turbulence_solve::implicit_step(
            &c,
            &g,
            &state.velocity,
            &mut k_imp,
            &mut e_imp,
            dt,
            &Control::new(10.0),
        )
        .unwrap();
        assert_eq!(info.floor_events, 0);
        for i in 0..g.count() {
            if !(2..=5).contains(&g.coord(i)[2]) {
                continue;
            }
            assert!((k_exp[i] - k_imp[i]).abs() / dt < 2e-5);
            assert!((e_exp[i] - e_imp[i]).abs() / dt < 2e-5);
        }
    }
}
