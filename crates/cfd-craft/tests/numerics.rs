use cfd_craft::{
    case::*,
    grid::{FaceKind, Grid},
    output, pressure,
    solver::{self, Control},
    transport,
};
use std::sync::atomic::Ordering;
fn fixture() -> Case {
    serde_json::from_str(include_str!(
        "../../../cases/verification/periodic-tracer.json"
    ))
    .unwrap()
}
fn zero(c: &mut Case) {
    c.constituents.clear();
    c.initial_conditions.clear();
    c.receptors.clear();
    c.sources.clear();
}
#[test]
fn schema_rejects_unknown_and_duplicate_fields() {
    let mut v = serde_json::to_value(fixture()).unwrap();
    v["flow"]["invented"] = true.into();
    assert!(serde_json::from_value::<Case>(v).is_err());
    assert!(serde_json::from_str::<Case>("{\"name\":\"a\",\"name\":\"b\"}").is_err());
}
#[test]
fn cardinal_winds() {
    let mut c: Case =
        serde_json::from_str(include_str!("../../../cases/canyon/wh1-wind270.json")).unwrap();
    for (degrees, expected) in [
        (0.0, [0., -2., 0.]),
        (90., [-2., 0., 0.]),
        (180., [0., 2., 0.]),
        (270., [2., 0., 0.]),
    ] {
        if let Flow::NeutralRans {
            direction_deg_from, ..
        } = &mut c.flow
        {
            *direction_deg_from = degrees;
        }
        for (x, y) in c.flow.vector(1.0).iter().zip(expected) {
            assert!((x - y).abs() < 1e-12);
        }
    }
}
#[test]
fn incompatible_memory_and_closed_sources_rejected() {
    let mut c = fixture();
    c.run.memory_limit_mib = 1;
    assert!(!c.check().valid);
    c.run.memory_limit_mib = 1024;
    c.run.mode = Mode::Steady;
    c.sources.push(Source::Point {
        id: "S".into(),
        constituent: "tracer".into(),
        point_m: [1., 1., 1.],
        rate_kg_s: 1.,
    });
    assert!(!c.check().valid);
}
#[test]
fn projection_and_weighted_adjoint_identity() {
    let mut c = fixture();
    c.grid.cells = [6, 5, 4];
    zero(&mut c);
    let g = Grid::build(&c).unwrap();
    let p: Vec<_> = (0..g.count()).map(|i| (i as f64 * 0.73).sin()).collect();
    let mut u: Vec<_> = (0..g.faces.len())
        .map(|i| (i as f64 * 0.38).cos())
        .collect();
    let d = g.divergence(&u);
    let grad = g.gradient(&p);
    let lhs = d.iter().zip(&p).map(|(x, y)| x * y * g.volume).sum::<f64>();
    let rhs = g
        .faces
        .iter()
        .zip(&u)
        .zip(grad)
        .map(|((f, v), p)| f.area * f.distance * v * p)
        .sum::<f64>();
    assert!((lhs + rhs).abs() < 1e-11);
    let mut pressure = vec![0.; g.count()];
    pressure::project(
        &g,
        &mut u,
        &mut pressure,
        0.1,
        1e-12,
        2000,
        &Control::new(20.),
    )
    .unwrap();
    assert!(g.divergence(&u).iter().all(|v| v.abs() < 1e-10));
}
#[test]
fn pressure_has_one_gauge_per_closed_component() {
    let mut c = fixture();
    zero(&mut c);
    c.grid.cells = [8, 4, 4];
    c.domain.size_m = [1.; 3];
    c.flow = Flow::PrescribedUniform {
        velocity_m_s: [0.; 3],
    };
    c.boundaries.x = Boundary::Wall;
    c.geometry.push(Block {
        id: "barrier".into(),
        min_m: [0.375, 0., 0.],
        max_m: [0.625, 1., 1.],
    });
    // Use projected flow for masked geometry.
    c.flow = Flow::Laminar {
        initial_velocity_m_s: [0.; 3],
        viscosity_m2_s: 0.1,
        acceleration_m_s2: [0.; 3],
    };
    let g = Grid::build(&c).unwrap();
    assert_eq!(g.components.len(), 2);
    let mut b = vec![0.; g.count()];
    for component in &g.components {
        b[component[0]] = 1.;
        b[component[1]] = -1.;
    }
    let (x, _) = pressure::solve(&g, &b, 1e-11, 2000, &Control::new(20.)).unwrap();
    for component in &g.components {
        assert!(component.iter().map(|i| x[*i]).sum::<f64>().abs() < 1e-10);
    }
    b[g.components[0][0]] += 1.;
    assert!(pressure::solve(&g, &b, 1e-11, 2000, &Control::new(20.)).is_err());
}
#[test]
fn pressure_open_outlet_is_anchored() {
    let mut c = fixture();
    zero(&mut c);
    c.grid.cells = [5, 4, 4];
    c.boundaries.x = Boundary::Open;
    let g = Grid::build(&c).unwrap();
    assert_eq!(g.anchored, vec![true]);
    let b = vec![1.; g.count()];
    let (x, info) = pressure::solve(&g, &b, 1e-11, 2000, &Control::new(20.)).unwrap();
    assert!(info.relative_residual < 1e-10);
    assert!(x.iter().all(|v| v.is_finite()));
}

#[test]
fn closed_pressure_checks_the_compatible_rhs() {
    let mut c = fixture();
    zero(&mut c);
    c.grid.cells = [8, 4, 4];
    let g = Grid::build(&c).unwrap();
    let b: Vec<_> = (0..g.count())
        .map(|i| {
            1e-12 * (2.0 * std::f64::consts::PI * g.center(i)[0] / c.domain.size_m[0]).sin() + 1e-16
        })
        .collect();
    // The 1e-16 offset is round-off of unit-sized flux terms, so it is compatible
    // relative to that scale (not relative to the 1e-12 signal alone).
    let terms = vec![1.0; g.count()];
    let (x, info) =
        pressure::solve_scaled(&g, &b, Some(&terms), 1e-11, 1200, &Control::new(20.)).unwrap();
    assert!(info.relative_residual < 1e-10);
    let mut rhs = b.clone();
    pressure::center_nullspaces(&g, &mut rhs);
    let mut ax = vec![0.; g.count()];
    pressure::apply(&g, &x, &mut ax);
    assert!(ax.iter().zip(rhs).all(|(a, b)| (a - b).abs() < 1e-22));
}
#[test]
fn continuum_poisson_second_order() {
    let mut errors = vec![];
    for n in [8, 16, 32] {
        let mut c = fixture();
        zero(&mut c);
        c.grid.cells = [n, 2, 2];
        c.domain.size_m = [1.; 3];
        let g = Grid::build(&c).unwrap();
        let exact: Vec<_> = (0..g.count())
            .map(|i| (2. * std::f64::consts::PI * g.center(i)[0]).sin())
            .collect();
        let b: Vec<_> = exact
            .iter()
            .map(|v| 4. * std::f64::consts::PI.powi(2) * v)
            .collect();
        let (p, _) = pressure::solve(&g, &b, 1e-12, 1000, &Control::new(20.)).unwrap();
        errors.push(
            p.iter()
                .zip(exact)
                .map(|(a, b)| (a - b).powi(2))
                .sum::<f64>()
                .sqrt()
                / (g.count() as f64).sqrt(),
        );
    }
    assert!((errors[1] / errors[2]).log2() > 1.9);
    assert!((errors[0] / errors[1]).log2() > 1.9);
}
#[test]
fn explicit_matrix_oracle_matches_operator() {
    let mut c = fixture();
    zero(&mut c);
    c.grid.cells = [4, 3, 2];
    let g = Grid::build(&c).unwrap();
    let x: Vec<_> = (0..g.count()).map(|i| (i as f64).cos()).collect();
    let mut y = vec![0.; g.count()];
    pressure::apply(&g, &x, &mut y);
    for i in 0..g.count() {
        let q = g.coord(i);
        let mut oracle = 0.;
        for a in 0..3 {
            for side in [-1isize, 1] {
                let mut p = q;
                p[a] = (q[a] as isize + side).rem_euclid(g.n[a] as isize) as usize;
                oracle += (x[i] - x[Grid::index(g.n, p)]) / g.dx[a].powi(2);
            }
        }
        assert!((y[i] - oracle).abs() < 1e-12);
    }
}
#[test]
fn source_integrals_and_solid_rejection() {
    let mut c = fixture();
    c.initial_conditions.clear();
    c.sources = vec![
        Source::Line {
            id: "L".into(),
            constituent: "tracer".into(),
            from_m: [1., 1., 1.],
            to_m: [5., 4., 1.],
            rate_kg_s_m: 2.,
        },
        Source::Volume {
            id: "V".into(),
            constituent: "tracer".into(),
            min_m: [7.1, 1.1, 1.1],
            max_m: [8.1, 3.1, 4.1],
            rate_kg_s_m3: 3.,
        },
    ];
    let g = Grid::build(&c).unwrap();
    let s = transport::source_fields(&c, &g).unwrap();
    assert!((s[0].iter().sum::<f64>() * g.volume - 28.).abs() < 1e-12);
    c.flow = Flow::Laminar {
        initial_velocity_m_s: [0.; 3],
        viscosity_m2_s: 0.1,
        acceleration_m_s2: [0.; 3],
    };
    c.geometry.push(Block {
        id: "solid".into(),
        min_m: [1., 1., 0.],
        max_m: [3., 3., 3.],
    });
    let g = Grid::build(&c).unwrap();
    assert!(transport::source_fields(&c, &g).is_err());
}
#[test]
fn receptor_cannot_interpolate_through_wall() {
    let mut c = fixture();
    c.flow = Flow::Laminar {
        initial_velocity_m_s: [0.; 3],
        viscosity_m2_s: 0.1,
        acceleration_m_s2: [0.; 3],
    };
    c.geometry.push(Block {
        id: "solid".into(),
        min_m: [2., 0., 0.],
        max_m: [3., 6., 6.],
    });
    let g = Grid::build(&c).unwrap();
    let r = Receptor::Point {
        id: "wall".into(),
        point_m: [1.99, 3., 3.],
    };
    assert!(transport::receptor_weights(&g, &r).is_err());
}
#[test]
fn scalar_mass_positivity_and_linear_superposition() {
    let mut c = fixture();
    c.grid.cells = [12, 6, 6];
    c.numerics.transport = Advection::LinearUpwind;
    c.run.end_time_s = 0.5;
    let g = Grid::build(&c).unwrap();
    let s = solver::initial_state(&c, &g);
    let source = vec![vec![0.; g.count()]];
    let r = solver::run(&c, &Control::new(20.), Some(s.clone())).unwrap();
    assert_eq!(r.summary.assessment, "transient_interval_completed");
    assert!(r.summary.constituents[0].relative_budget_defect < 1e-12);
    assert!(r.state.concentrations[0].iter().all(|v| *v >= 0.));
    let mut doubled = s.clone();
    for x in &mut doubled.concentrations[0] {
        *x *= 2.;
    }
    doubled.budgets[0].initial_kg *= 2.;
    let rr = solver::run(&c, &Control::new(20.), Some(doubled)).unwrap();
    for (a, b) in r.state.concentrations[0]
        .iter()
        .zip(rr.state.concentrations[0].iter())
    {
        assert!((2. * a - b).abs() < 1e-20);
    }
    let mut state = s.clone();
    let saved = state.clone();
    let ctrl = Control::new(20.);
    ctrl.cancelled.store(true, Ordering::Relaxed);
    assert!(solver::step(&c, &g, &mut state, &source, 0.1, &ctrl).is_err());
    assert_eq!(state.concentrations, saved.concentrations);
}
#[test]
fn checkpoint_resume_and_corruption() {
    let mut c = fixture();
    c.grid.cells = [8, 4, 4];
    c.numerics.max_time_step_s = 0.05;
    c.run.end_time_s = 0.5;
    let full = solver::run(&c, &Control::new(20.), None).unwrap();
    // Interrupt after an accepted step, without changing the requested physical endpoint
    // (which would alter a clipped final timestep).
    let mut half = c.clone();
    half.run.max_steps = 5;
    let first = solver::run(&half, &Control::new(20.), None).unwrap();
    let path =
        std::env::temp_dir().join(format!("cfd-checkpoint-test-{}.json", std::process::id()));
    std::fs::write(
        &path,
        output::checkpoint_bytes(&half, &first.state).unwrap(),
    )
    .unwrap();
    let restored = output::read_checkpoint(&c, &path).unwrap();
    let resumed = solver::run(&c, &Control::new(20.), Some(restored)).unwrap();
    assert_eq!(full.state.concentrations, resumed.state.concentrations);
    assert_eq!(full.state.velocity, resumed.state.velocity);
    assert_ne!(
        full.summary.initial_state_sha256,
        resumed.summary.initial_state_sha256
    );
    let mut bad = c.clone();
    bad.grid.cells[0] += 1;
    assert!(output::read_checkpoint(&bad, &path).is_err());
    let mut bytes = std::fs::read(&path).unwrap();
    bytes[40] ^= 1;
    std::fs::write(&path, bytes).unwrap();
    assert!(output::read_checkpoint(&c, &path).is_err());
    std::fs::remove_file(path).unwrap();
}
#[test]
fn poiseuille_reaches_analytic_profile() {
    let mut c: Case =
        serde_json::from_str(include_str!("../../../cases/verification/poiseuille.json")).unwrap();
    c.grid.cells = [2, 2, 12];
    c.run.end_time_s = 15.;
    c.output.fields = false;
    let r = solver::run(&c, &Control::new(30.), None).unwrap();
    assert_eq!(r.summary.assessment, "transient_interval_completed");
    let g = Grid::build(&c).unwrap();
    let v = g.cell_velocity(&r.state.velocity);
    let error = (0..g.count())
        .map(|i| {
            let z = g.center(i)[2];
            (v[i][0] - 5. * z * (1. - z)).abs()
        })
        .fold(0.0, f64::max);
    // First cell-centered no-slip ghost treatment has O(h^2) wall error.
    assert!(error < 0.012, "profile error={error}");
}
#[test]
fn a_checker_detects_corrupted_field() {
    let c = fixture();
    let g = Grid::build(&c).unwrap();
    let mut s = solver::initial_state(&c, &g);
    let sources = transport::source_fields(&c, &g).unwrap();
    let weights = c
        .receptors
        .iter()
        .map(|r| transport::receptor_weights(&g, r).unwrap())
        .collect::<Vec<_>>();
    s.concentrations[0][0] += 1.;
    let (checks, _, _, _) = solver::assess(&c, &g, &s, &sources, &weights);
    assert!(
        checks
            .iter()
            .any(|x| x.name == "tracer.mass_budget" && !x.passed)
    );
    let fi = g
        .faces
        .iter()
        .position(|f| f.kind == FaceKind::Interior)
        .unwrap();
    s.velocity[fi] += 1.;
    let (checks, _, _, _) = solver::assess(&c, &g, &s, &sources, &weights);
    assert!(
        checks
            .iter()
            .any(|x| x.name == "local_continuity" && !x.passed)
    );
}

#[test]
fn couette_has_linear_velocity() {
    let mut c: Case =
        serde_json::from_str(include_str!("../../../cases/verification/couette.json")).unwrap();
    c.grid.cells = [2, 2, 12];
    c.run.end_time_s = 15.;
    let r = solver::run(&c, &Control::new(30.), None).unwrap();
    let g = Grid::build(&c).unwrap();
    let u = g.cell_velocity(&r.state.velocity);
    let error = (0..g.count())
        .map(|i| (u[i][0] - g.center(i)[2]).abs())
        .fold(0.0, f64::max);
    assert!(error < 1e-5, "Couette error={error}");
}

#[test]
fn a_steady_source_in_a_sealed_component_is_rejected() {
    let mut c = fixture();
    c.initial_conditions.clear();
    c.boundaries.x = Boundary::Open;
    c.flow = Flow::Laminar {
        initial_velocity_m_s: [1., 0., 0.],
        viscosity_m2_s: 0.1,
        acceleration_m_s2: [0.; 3],
    };
    c.run.mode = Mode::Steady;
    c.geometry = vec![
        Block {
            id: "left".into(),
            min_m: [2., 0., 0.],
            max_m: [2.5, 6., 6.],
        },
        Block {
            id: "right".into(),
            min_m: [4., 0., 0.],
            max_m: [4.5, 6., 6.],
        },
    ];
    c.sources = vec![Source::Point {
        id: "sealed".into(),
        constituent: "tracer".into(),
        point_m: [3., 3., 3.],
        rate_kg_s: 1.,
    }];
    let g = Grid::build(&c).unwrap();
    assert!(
        transport::source_fields(&c, &g)
            .unwrap_err()
            .contains("CFD-E043")
    );
}

#[test]
fn accumulated_mass_cannot_masquerade_as_steady_transport() {
    let mut c = fixture();
    c.initial_conditions.clear();
    c.boundaries.x = Boundary::Open;
    c.flow = Flow::PrescribedUniform {
        velocity_m_s: [0.; 3],
    };
    c.run.mode = Mode::Steady;
    let g = Grid::build(&c).unwrap();
    let mut s = solver::initial_state(&c, &g);
    s.concentrations[0].fill(1e15);
    s.budgets[0].initial_kg = 1e15 * g.count() as f64 * g.volume;
    let mut sources = vec![vec![0.; g.count()]];
    sources[0][0] = 1.;
    let (checks, _, _, _) = solver::assess(&c, &g, &s, &sources, &[]);
    assert!(
        checks
            .iter()
            .any(|x| x.name == "tracer.steady_equation" && x.passed)
    );
    assert!(
        checks
            .iter()
            .any(|x| x.name == "tracer.steady_mass_balance" && !x.passed)
    );
}
