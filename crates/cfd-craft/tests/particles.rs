//! Aerosol verification against analytic columns and conservative budgets.
use cfd_craft::{
    case::{Case, ParticleBin},
    grid::Grid,
    solver::{self, Control},
    transport,
};
use serde_json::json;

fn column(n: usize, end: f64, periodic: bool) -> Case {
    let mut v: serde_json::Value = serde_json::from_str(include_str!(
        "../../../cases/verification/periodic-tracer.json"
    ))
    .unwrap();
    v["name"] = json!("particle-column");
    v["domain"]["size_m"] = json!([1.0, 1.0, 1.0]);
    v["grid"]["cells"] = json!([2, 2, n]);
    v["boundaries"]["z"] = json!(if periodic { "periodic" } else { "wall" });
    v["flow"]["velocity_m_s"] = json!([0.0, 0.0, 0.0]);
    v["initial_conditions"] = json!([]);
    v["receptors"] = json!([]);
    v["constituents"][0]["diffusivity_m2_s"] = json!(0.0);
    v["constituents"][0]["particle"] =
        json!({"diameter_m":1e-6,"density_kg_m3":1000.0,"settling_velocity_m_s":0.2});
    v["numerics"]["transport"] = json!("linear_upwind");
    v["numerics"]["max_time_step_s"] = json!(0.1);
    v["run"]["end_time_s"] = json!(end);
    v["run"]["threads"] = json!(1);
    serde_json::from_value(v).unwrap()
}
fn with_field(c: &Case, f: impl Fn(f64) -> f64) -> solver::State {
    let g = Grid::build(c).unwrap();
    let mut s = solver::initial_state(c, &g);
    for (i, value) in s.concentrations[0].iter_mut().enumerate() {
        *value = f(g.center(i)[2]);
    }
    s.budgets[0].initial_kg = s.concentrations[0].iter().sum::<f64>() * g.volume;
    s
}
fn run(c: &Case, s: solver::State) -> solver::RunResult {
    let r = solver::run(c, &Control::new(20.0), Some(s)).unwrap();
    assert_eq!(
        r.summary.assessment, "transient_interval_completed",
        "{:?}",
        r.summary.checks
    );
    r
}
#[test]
fn stokes_cunningham_formula_units_and_validity() {
    let mut c = column(16, 1.0, false);
    let p = c.constituents[0].particle.as_mut().unwrap();
    p.settling_velocity_m_s = None;
    let diameter = 1e-6_f64;
    let kn = 2.0 * 6.6e-8 / diameter;
    let expected = (1000.0 - 1.204)
        * 9.80665
        * diameter.powi(2)
        * (1.0 + kn * (1.257 + 0.4 * (-1.1 / kn).exp()))
        / (18.0 * 1.81e-5);
    assert!((p.settling_speed() - expected).abs() < 1e-18);
    assert!(expected > 3e-5 && expected < 4e-5);
    assert!((p.aerodynamic_diameter_m() - diameter).abs() < 1e-20);
    p.diameter_m = 1e-4;
    assert!(c.check().diagnostics.iter().any(
        |d| d.code == "CFD-E081" && d.path == "constituents[0].particle.settling_velocity_m_s"
    ));
}
#[test]
fn settling_layer_centroid_and_ground_arrival_close_mass() {
    let c = column(80, 1.0, false);
    let r = run(
        &c,
        with_field(&c, |z| if (0.7..0.8).contains(&z) { 1.0 } else { 0.0 }),
    );
    let g = Grid::build(&c).unwrap();
    let m = r.summary.constituents[0].mass_kg;
    let center = r.state.concentrations[0]
        .iter()
        .enumerate()
        .map(|(i, v)| v * g.center(i)[2] * g.volume)
        .sum::<f64>()
        / m;
    assert!((center - 0.55).abs() < 2e-4, "{center}");
    let c = column(80, 6.0, false);
    let r = run(
        &c,
        with_field(&c, |z| if (0.7..0.8).contains(&z) { 1.0 } else { 0.0 }),
    );
    let e = &r.summary.constituents[0];
    assert!(e.deposited_kg["ground"] > 0.0999, "{e:?}");
    eprintln!(
        "deposited after 6 s = {:.16e} kg; airborne = {:.16e}; relative budget = {:.3e}",
        e.deposited_kg["ground"], e.mass_kg, e.relative_budget_defect
    );
    assert!(e.relative_budget_defect < 1e-12);
    assert!(e.minimum_kg_m3 >= 0.0);
    assert_eq!(r.summary.particulate_matter["PM2.5"].mass_kg, e.mass_kg);
}
#[test]
fn conservative_settling_converges_at_first_order_and_superposes() {
    let mut errors = vec![];
    for n in [32, 64, 128] {
        let c = column(n, 0.35, true);
        let f = |z: f64| 1.0 + 0.2 * (std::f64::consts::TAU * z).sin();
        let r = run(&c, with_field(&c, f));
        let g = Grid::build(&c).unwrap();
        let err = r.state.concentrations[0]
            .iter()
            .enumerate()
            .map(|(i, v)| (v - f(g.center(i)[2] + 0.2 * 0.35)).abs())
            .sum::<f64>()
            / g.count() as f64;
        errors.push(err);
        assert!(r.summary.constituents[0].relative_budget_defect < 1e-12);
        if n == 32 {
            let twice = run(&c, with_field(&c, |z| 2.0 * f(z)));
            assert!(
                r.state.concentrations[0]
                    .iter()
                    .zip(&twice.state.concentrations[0])
                    .all(|(a, b)| (2.0 * a - b).abs() < 1e-13)
            );
        }
    }
    eprintln!("periodic settling L1 errors = {errors:?}");
    for e in errors.windows(2) {
        assert!((e[0] / e[1]).log2() > 0.9, "{errors:?}");
    }
}
#[test]
fn roof_flux_and_budget_are_separate_from_ground_and_outflow() {
    let mut c = column(16, 1.0, false);
    // Geometry is forbidden for a prescribed flow, so construct an incompressible
    // laminar zero-flow fixture with a complete bottom solid layer.
    let mut v = serde_json::to_value(&c).unwrap();
    v["flow"] =
        json!({"kind":"laminar","initial_velocity_m_s":[0.0,0.0,0.0],"viscosity_m2_s":1e-5});
    v["geometry"] = json!([{"id":"roof","min_m":[0.0,0.0,0.0],"max_m":[1.0,1.0,0.5]}]);
    c = serde_json::from_value(v).unwrap();
    let g = Grid::build(&c).unwrap();
    let values: Vec<_> = g.fluid.iter().map(|f| if *f { 1.0 } else { 0.0 }).collect();
    let mut rhs = vec![0.0; g.count()];
    let (out, dep) = transport::particle_terms(
        &c,
        &g,
        c.constituents[0].particle.as_ref().unwrap(),
        &values,
        &mut rhs,
    );
    assert_eq!(out, 0.0);
    assert!((dep["roof"] - 0.2).abs() < 1e-15);
    assert!(!dep.contains_key("ground"));
    assert!((rhs.iter().sum::<f64>() * g.volume + dep["roof"]).abs() < 1e-15);
}
#[test]
fn exponential_settling_diffusion_interior_residual_refines() {
    let mut errors = vec![];
    for n in [32, 64, 128] {
        let c = column(n, 1.0, false);
        let g = Grid::build(&c).unwrap();
        let diffusion = 0.1;
        let p = c.constituents[0].particle.as_ref().unwrap();
        let values: Vec<_> = (0..g.count())
            .map(|i| (-p.settling_speed() * g.center(i)[2] / diffusion).exp())
            .collect();
        let mut rhs = transport::rhs(
            &g,
            &values,
            &vec![0.0; g.faces.len()],
            &vec![diffusion; g.count()],
            &vec![0.0; g.count()],
            c.numerics.transport,
            |_| 0.0,
        )
        .values;
        transport::particle_terms(&c, &g, p, &values, &mut rhs);
        let err = rhs
            .iter()
            .enumerate()
            .filter(|(i, _)| {
                let k = g.coord(*i)[2];
                k > 0 && k < n - 1
            })
            .map(|(_, r)| r.abs())
            .fold(0.0, f64::max);
        errors.push(err);
    }
    for e in errors.windows(2) {
        assert!((e[0] / e[1]).log2() > 0.9, "{errors:?}");
    }
}
#[test]
fn settling_cfl_is_respected_and_checkpoint_preserves_deposition() {
    let c = column(32, 1.0, false);
    let g = Grid::build(&c).unwrap();
    let s = with_field(&c, |_| 1.0);
    let dt = solver::timestep(&c, &g, &s, &vec![0.0; g.count()]);
    assert!(dt * 0.2 / g.dx[2] <= 0.4);
    let r = run(&c, s);
    let bytes = cfd_craft::output::checkpoint_bytes(&c, &r.state).unwrap();
    let path = std::env::temp_dir().join(format!(
        "cfd-particle-checkpoint-{}.json",
        std::process::id()
    ));
    std::fs::write(&path, &bytes).unwrap();
    let restored = cfd_craft::output::read_checkpoint(&c, &path).unwrap();
    std::fs::remove_file(path).unwrap();
    assert_eq!(
        serde_json::to_value(&restored.budgets).unwrap(),
        serde_json::to_value(&r.state.budgets).unwrap()
    );
    let mut longer = c.clone();
    longer.run.end_time_s = 2.0;
    let resumed = run(&longer, restored);
    let whole = run(&longer, with_field(&longer, |_| 1.0));
    assert_eq!(
        serde_json::to_value(&resumed.state.budgets).unwrap(),
        serde_json::to_value(&whole.state.budgets).unwrap()
    );
    assert_eq!(resumed.state.concentrations, whole.state.concentrations);
    let p: ParticleBin =
        serde_json::from_value(json!({"diameter_m":1e-6,"density_kg_m3":1000.0})).unwrap();
    assert!(p.settling_speed() > 0.0);
}

#[test]
fn uniform_wind_plume_tilts_at_settling_to_wind_speed_ratio() {
    let mut c = column(80, 0.3, false);
    c.grid.cells = [80, 2, 80];
    let mut v = serde_json::to_value(c).unwrap();
    v["flow"]["velocity_m_s"] = json!([0.3, 0.0, 0.0]);
    let c: Case = serde_json::from_value(v).unwrap();
    let g = Grid::build(&c).unwrap();
    let mut state = solver::initial_state(&c, &g);
    for (i, value) in state.concentrations[0].iter_mut().enumerate() {
        let p = g.center(i);
        *value = (-((p[0] - 0.3).powi(2) + (p[2] - 0.6).powi(2)) / (2.0 * 0.04_f64.powi(2))).exp();
    }
    state.budgets[0].initial_kg = state.concentrations[0].iter().sum::<f64>() * g.volume;
    let result = run(&c, state);
    let values = &result.state.concentrations[0];
    let mass = values.iter().sum::<f64>();
    let center = |axis: usize| {
        values
            .iter()
            .enumerate()
            .map(|(i, v)| v * g.center(i)[axis])
            .sum::<f64>()
            / mass
    };
    let (x, z) = (center(0), center(2));
    eprintln!("wind plume centroid=({x:.16e},{z:.16e}); expected=(0.39,0.54)");
    assert!((x - 0.39).abs() < 2e-4 && (z - 0.54).abs() < 2e-4);
    assert!(((0.6 - z) / (x - 0.3) - 0.2 / 0.3).abs() < 2e-3);
}

#[test]
fn settling_exits_an_open_lower_boundary_even_with_zero_air_normal_speed() {
    let mut c = column(64, 1.0, false);
    c.boundaries.z = cfd_craft::case::Boundary::Open;
    let r = run(&c, with_field(&c, |_| 1.0));
    let evidence = &r.summary.constituents[0];
    assert!((evidence.outflow_kg - 0.2).abs() < 1e-9);
    assert!(evidence.deposited_kg.is_empty());
    assert!(evidence.relative_budget_defect < 1e-12);
}

#[test]
fn one_cell_periodic_vertical_drift_preserves_existing_rhs_bits() {
    let c = column(1, 1.0, true);
    let g = Grid::build(&c).unwrap();
    let concentrations = vec![1e100; g.count()];
    let mut rhs = vec![1e-20; g.count()];
    let expected: Vec<_> = rhs.iter().map(|v: &f64| v.to_bits()).collect();
    let (outflow, deposited) = transport::particle_terms(
        &c,
        &g,
        c.constituents[0].particle.as_ref().unwrap(),
        &concentrations,
        &mut rhs,
    );
    assert_eq!(
        rhs.iter().map(|v| v.to_bits()).collect::<Vec<_>>(),
        expected
    );
    assert_eq!(outflow, 0.);
    assert!(deposited.is_empty());
}

#[test]
fn steady_source_settling_diffusion_column_matches_complete_analytic_profile() {
    // Frozen continuum-error gates: relative RMS < 0.02 on 64 cells,
    // maximum point error / maximum analytic concentration < 0.05,
    // and adjacent-grid observed RMS order at least 0.75.
    let (settling, diffusion, deposition, source_density, source_bottom) =
        (0.2_f64, 0.1_f64, 0.1_f64, 4e-6_f64, 0.75_f64);
    let total_rate = source_density * (1.0 - source_bottom);
    let c0 = total_rate / (settling + deposition);
    let below = |z: f64| {
        total_rate / settling + (c0 - total_rate / settling) * (-settling * z / diffusion).exp()
    };
    let particular = |z: f64| {
        source_density / settling * (1.0 - z) + source_density * diffusion / settling.powi(2)
    };
    let analytic = |z: f64| {
        if z <= source_bottom {
            below(z)
        } else {
            particular(z)
                + (below(source_bottom) - particular(source_bottom))
                    * (-settling * (z - source_bottom) / diffusion).exp()
        }
    };
    let mut errors = vec![];
    for n in [16, 32, 64] {
        let mut c = column(n, 1.0, false);
        c.grid.cells = [1, 1, n];
        c.run.mode = cfd_craft::case::Mode::Steady;
        c.run.max_steps = 400000;
        c.run.wall_time_limit_s = 30.0;
        c.numerics.monitor_window = 20;
        c.numerics.steady_residual_tolerance = 1e-7;
        c.numerics.steady_monitor_tolerance = 1e-7;
        c.constituents[0].diffusivity_m2_s = diffusion;
        c.constituents[0]
            .particle
            .as_mut()
            .unwrap()
            .ground_deposition_velocity_m_s = deposition;
        c.sources = vec![cfd_craft::case::Source::Volume {
            id: "upper-supply".into(),
            constituent: "tracer".into(),
            min_m: [0.0, 0.0, source_bottom],
            max_m: [1.0, 1.0, 1.0],
            rate_kg_s_m3: source_density,
        }];
        assert!(cfd_craft::input::full_check(&c).0.valid);
        let result = solver::run(&c, &Control::new(30.0), None).unwrap();
        assert_eq!(
            result.summary.assessment, "steady_discrete_solution",
            "n={n}: {:?}, {:?}",
            result.summary.error, result.summary.checks
        );
        let grid = Grid::build(&c).unwrap();
        let exact: Vec<_> = (0..grid.count())
            .map(|i| analytic(grid.center(i)[2]))
            .collect();
        let norm = exact.iter().map(|v| v * v).sum::<f64>();
        let error = (result.state.concentrations[0]
            .iter()
            .zip(&exact)
            .map(|(a, b)| (a - b).powi(2))
            .sum::<f64>()
            / norm)
            .sqrt();
        let max = exact.iter().copied().fold(0.0, f64::max);
        let maximum_error = result.state.concentrations[0]
            .iter()
            .zip(&exact)
            .map(|(a, b)| (a - b).abs() / max)
            .fold(0.0, f64::max);
        errors.push(error);
        let scalar = &result.summary.constituents[0];
        assert!(scalar.relative_budget_defect < 1e-11);
        assert!((scalar.deposition_rate_kg_s["ground"] - total_rate).abs() / total_rate < 1.1e-6);
        assert_eq!(scalar.boundary_outflow_rate_kg_s, 0.0);
        assert!(scalar.minimum_kg_m3 >= 0.0);
        eprintln!(
            "complete steady particle column n={n}: relative RMS={error:.16e}, maxrelative={maximum_error:.16e}, steps={}, time={:.3}s, budget={:.3e}",
            result.summary.steps, result.summary.elapsed_s, scalar.relative_budget_defect
        );
        if n == 64 {
            assert!(error < 0.02 && maximum_error < 0.05);
        }
    }
    for pair in errors.windows(2) {
        assert!((pair[0] / pair[1]).log2() > 0.75, "{errors:?}");
    }
}
#[test]
fn steady_particle_sources_need_a_represented_sink_in_their_own_component() {
    let mut c = column(8, 1.0, true);
    c.grid.cells = [8, 1, 8];
    c.flow = cfd_craft::case::Flow::Laminar {
        initial_velocity_m_s: [0.0; 3],
        viscosity_m2_s: 1e-3,
        acceleration_m_s2: [0.0; 3],
    };
    c.run.mode = cfd_craft::case::Mode::Steady;
    c.constituents[0]
        .particle
        .as_mut()
        .unwrap()
        .settling_velocity_m_s = Some(0.0);
    let mut value = serde_json::to_value(&c).unwrap();
    value["geometry"] = json!([{"id":"left-seal","min_m":[0.25,0.0,0.0],"max_m":[0.375,1.0,1.0]},{"id":"right-seal","min_m":[0.625,0.0,0.0],"max_m":[0.75,1.0,1.0]}]);
    value["sources"] = json!([{"id":"source","kind":"point","constituent":"tracer","point_m":[0.5,0.5,0.5],"rate_kg_s":1e-6}]);
    value["vegetation"] = json!([{"id":"outside-pocket","min_m":[0.0,0.0,0.0],"max_m":[0.2,1.0,1.0],"leaf_area_density_m2_m3":1.0,"drag_coefficient":0.0,"leaf_deposition_velocity_m_s":0.1}]);
    let wrong: Case = serde_json::from_value(value.clone()).unwrap();
    assert!(wrong.check().valid);
    let grid = Grid::build(&wrong).unwrap();
    assert_eq!(grid.components.len(), 2);
    assert!(
        transport::source_fields(&wrong, &grid)
            .unwrap_err()
            .contains("CFD-E043")
    );
    value["vegetation"][0]["min_m"] = json!([0.4, 0.0, 0.0]);
    value["vegetation"][0]["max_m"] = json!([0.6, 1.0, 1.0]);
    let correct: Case = serde_json::from_value(value.clone()).unwrap();
    assert!(transport::source_fields(&correct, &Grid::build(&correct).unwrap()).is_ok());
    value["vegetation"][0]["min_m"] = json!([0.45, 0.0, 0.0]);
    value["vegetation"][0]["max_m"] = json!([0.46, 1.0, 1.0]);
    let unresolved: Case = serde_json::from_value(value.clone()).unwrap();
    assert!(
        transport::source_fields(&unresolved, &Grid::build(&unresolved).unwrap())
            .unwrap_err()
            .contains("CFD-E043")
    );
    value["constituents"][0]
        .as_object_mut()
        .unwrap()
        .remove("particle");
    let gas: Case = serde_json::from_value(value).unwrap();
    assert!(gas.check().diagnostics.iter().any(|d| d.code == "CFD-E020"));
}
#[test]
fn periodic_wrap_solid_surface_is_roof_not_ground() {
    let mut c = column(8, 1.0, true);
    c.flow = cfd_craft::case::Flow::Laminar {
        initial_velocity_m_s: [0.0; 3],
        viscosity_m2_s: 1e-3,
        acceleration_m_s2: [0.0; 3],
    };
    let mut value = serde_json::to_value(&c).unwrap();
    value["geometry"] =
        json!([{"id":"periodic-upper-solid","min_m":[0.0,0.0,0.5],"max_m":[1.0,1.0,1.0]}]);
    value["constituents"][0]["particle"]["ground_deposition_velocity_m_s"] = json!(0.3);
    value["constituents"][0]["particle"]["roof_deposition_velocity_m_s"] = json!(0.1);
    let c: Case = serde_json::from_value(value).unwrap();
    let g = Grid::build(&c).unwrap();
    let values: Vec<_> = g.fluid.iter().map(|f| if *f { 1.0 } else { 0.0 }).collect();
    let mut rhs = vec![0.0; g.count()];
    let (_, rates) = transport::particle_terms(
        &c,
        &g,
        c.constituents[0].particle.as_ref().unwrap(),
        &values,
        &mut rhs,
    );
    assert_eq!(rates.len(), 1);
    assert!((rates["roof"] - 0.3).abs() < 1e-15);
    assert!(!rates.contains_key("ground"));
}
#[test]
fn near_buoyant_aerodynamic_diameter_is_not_clipped_to_a_fixed_lower_bound() {
    let particle: ParticleBin =
        serde_json::from_value(json!({"diameter_m":1e-8,"density_kg_m3":1.25})).unwrap();
    let diameter = particle.aerodynamic_diameter_m();
    assert!(diameter > 0.0 && diameter < 1e-12, "{diameter}");
}
#[test]
fn particulate_sums_select_bins_by_aerodynamic_diameter_and_exclude_gases() {
    // Geometric and aerodynamic diameters fall on different sides of a cutoff
    // for "dense" (2.0 um geometric, 3.2 um aerodynamic) and "light" (12 um
    // geometric, 8.5 um aerodynamic), so a sum by geometric diameter fails.
    let mut v = serde_json::to_value(column(4, 0.05, true)).unwrap();
    let bins = [
        ("fine", 1e-6, 1000.0, 1e-9),
        ("dense", 2e-6, 2500.0, 2e-9),
        ("light", 1.2e-5, 500.0, 4e-9),
        ("coarse", 1.2e-5, 1000.0, 8e-9),
    ];
    let mut constituents: Vec<_> = bins
        .iter()
        .map(|(id, diameter, density, _)| {
            json!({"id":id,"diffusivity_m2_s":0.0,
                "particle":{"diameter_m":diameter,"density_kg_m3":density}})
        })
        .collect();
    constituents.push(json!({"id":"gas","diffusivity_m2_s":0.0}));
    v["constituents"] = json!(constituents);
    let mut initial: Vec<_> = bins
        .iter()
        .map(|(id, _, _, level)| json!({"kind":"uniform","constituent":id,"concentration_kg_m3":level}))
        .collect();
    initial.push(json!({"kind":"uniform","constituent":"gas","concentration_kg_m3":1.6e-8}));
    v["initial_conditions"] = json!(initial);
    v["sources"] = json!([]);
    v["receptors"] = json!([{"kind":"point","id":"station","point_m":[0.5,0.5,0.5]}]);
    let c: Case = serde_json::from_value(v).unwrap();
    let r = solver::run(&c, &Control::new(20.0), None).unwrap();
    assert_eq!(r.summary.assessment, "transient_interval_completed");
    // Independent Newton solution of d_a^2 Cc(d_a) (1000 - rho_air) = d^2 Cc(d) (rho - rho_air).
    let slip = |d: f64| {
        let kn = 2.0 * 6.6e-8 / d;
        1.0 + kn * (1.257 + 0.4 * (-1.1 / kn).exp())
    };
    let aerodynamic = |d: f64, density: f64| {
        let target = (density - 1.204) / (1000.0 - 1.204) * d * d * slip(d);
        let mut x = d * (density / 1000.0_f64).sqrt();
        for _ in 0..60 {
            let h = 1e-7 * x;
            let slope = ((x + h).powi(2) * slip(x + h) - (x - h).powi(2) * slip(x - h)) / (2.0 * h);
            x -= (x * x * slip(x) - target) / slope;
        }
        x
    };
    let expected = [1.0e-6, 3.21e-6, 8.46e-6, 1.2e-5];
    for (((id, d, density, _), scalar), rough) in
        bins.iter().zip(&r.summary.constituents).zip(expected)
    {
        let reported = scalar.aerodynamic_diameter_m.unwrap();
        assert!(
            (reported / aerodynamic(*d, *density) - 1.0).abs() < 1e-9,
            "{id}"
        );
        assert!((reported / rough - 1.0).abs() < 2e-3, "{id}: {reported}");
    }
    assert!(r.summary.constituents[4].aerodynamic_diameter_m.is_none());
    let pm = &r.summary.particulate_matter;
    assert_eq!(pm.keys().collect::<Vec<_>>(), ["PM10", "PM2.5"]);
    let close = |a: f64, b: f64| (a - b).abs() <= 1e-12 * b;
    // The unit domain makes airborne mass equal to the uniform concentration.
    assert!(close(pm["PM2.5"].mass_kg, 1e-9));
    assert!(close(pm["PM10"].mass_kg, 7e-9));
    assert!(close(pm["PM2.5"].receptors_kg_m3["station"], 1e-9));
    assert!(close(pm["PM10"].receptors_kg_m3["station"], 7e-9));
}
