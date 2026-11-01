//! Stages P4/P5a: implicit pseudo-time operators and their contracts.
use cfd_craft::{
    case::*,
    flow,
    grid::{FaceKind, Grid},
    momentum_solve::Stencil,
    solver::{Control, run},
};

fn load(name: &str) -> Case {
    let path = format!(
        "{}/../../cases/verification/{name}",
        env!("CARGO_MANIFEST_DIR")
    );
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn with_viscosity(c: &Case, nu: f64) -> Case {
    let mut c = c.clone();
    if let Flow::Laminar { viscosity_m2_s, .. } = &mut c.flow {
        *viscosity_m2_s = nu;
    }
    c
}

// The viscous part of the production right-hand side, isolated by difference.
fn viscous_rhs(c: &Case, g: &Grid, u: &[f64]) -> Vec<f64> {
    let zero = vec![0.0; g.count()];
    let with = flow::momentum_rhs(c, g, u, &zero);
    let without = flow::momentum_rhs(&with_viscosity(c, 0.0), g, u, &zero);
    with.iter().zip(without).map(|(a, b)| a - b).collect()
}

fn cases() -> Vec<(&'static str, Case)> {
    let mut cavity = load("lid-cavity.json");
    cavity.grid.cells = [7, 3, 6];
    let mut masked = cavity.clone();
    masked.geometry.push(Block {
        id: "step".into(),
        min_m: [0.4, 0.0, 0.0],
        max_m: [0.7, 1.0, 0.35],
    });
    let mut open = load("poiseuille.json");
    open.boundaries.x = Boundary::Open;
    if let Flow::Laminar {
        initial_velocity_m_s,
        ..
    } = &mut open.flow
    {
        *initial_velocity_m_s = [0.4, 0.0, 0.0];
    }
    let mut slip = cavity.clone();
    slip.boundaries.z = Boundary::Slip;
    slip.moving_walls.clear();
    vec![
        ("cavity", cavity),
        ("masked", masked),
        ("open", open),
        ("slip", slip),
        ("couette", load("couette.json")),
        ("poiseuille", load("poiseuille.json")),
    ]
}

#[test]
fn the_stencil_is_the_linear_part_of_the_viscous_right_hand_side() {
    for (name, c) in cases() {
        let g = Grid::build(&c).unwrap();
        let stencil = Stencil::build(&c, &g);
        let mut u: Vec<_> = (0..g.faces.len())
            .map(|i| (0.37 * i as f64).sin())
            .collect();
        g.enforce_velocity(&c, &mut u);
        let delta: Vec<_> = (0..g.faces.len())
            .map(|i| {
                if stencil.unknown[i] {
                    (1.7 * i as f64).cos()
                } else {
                    0.0
                }
            })
            .collect();
        let shifted: Vec<_> = u.iter().zip(&delta).map(|(a, b)| a + b).collect();
        let expected: Vec<_> = viscous_rhs(&c, &g, &shifted)
            .iter()
            .zip(viscous_rhs(&c, &g, &u))
            .map(|(a, b)| a - b)
            .collect();
        let mut actual = vec![0.0; g.faces.len()];
        stencil.viscous(c.flow.viscosity(), &delta, &mut actual);
        let scale = expected.iter().map(|v| v.abs()).fold(1.0, f64::max);
        for (i, (a, b)) in actual.iter().zip(&expected).enumerate() {
            assert!(
                (a - b).abs() <= 1e-12 * scale,
                "{name} face {i} {:?}: {a} vs {b}",
                g.faces[i].kind
            );
        }
        // Prescribed faces carry no equation.
        for (f, a) in g.faces.iter().zip(&actual) {
            if !matches!(f.kind, FaceKind::Interior | FaceKind::Outlet) {
                assert_eq!(*a, 0.0, "{name}");
            }
        }
    }
}

#[test]
fn the_viscous_correction_operator_is_symmetric_and_negative_definite() {
    for (name, c) in cases() {
        let g = Grid::build(&c).unwrap();
        let s = Stencil::build(&c, &g);
        let vector = |k: f64| -> Vec<f64> {
            (0..g.faces.len())
                .map(|i| {
                    if s.unknown[i] {
                        (k * i as f64).sin() + 0.1
                    } else {
                        0.0
                    }
                })
                .collect()
        };
        let (x, y) = (vector(0.91), vector(2.3));
        let (mut lx, mut ly) = (vec![0.0; x.len()], vec![0.0; y.len()]);
        s.viscous(0.01, &x, &mut lx);
        s.viscous(0.01, &y, &mut ly);
        let dot = |a: &[f64], b: &[f64]| a.iter().zip(b).map(|(p, q)| p * q).sum::<f64>();
        let (xly, ylx) = (dot(&x, &ly), dot(&y, &lx));
        assert!(
            (xly - ylx).abs() <= 1e-12 * xly.abs().max(1.0),
            "{name}: {xly} {ylx}"
        );
        assert!(dot(&x, &lx) < 0.0, "{name}");
        let diagonal = s.viscous_diagonal(0.01);
        let mut basis = vec![0.0; x.len()];
        let mut out = vec![0.0; x.len()];
        for i in (0..x.len()).filter(|i| s.unknown[*i]).step_by(7) {
            basis[i] = 1.0;
            s.viscous(0.01, &basis, &mut out);
            assert!(
                (out[i] - diagonal[i]).abs() <= 1e-12 * diagonal[i].abs(),
                "{name}"
            );
            basis[i] = 0.0;
        }
    }
}

#[test]
fn implicit_pseudo_time_rules_are_coded_diagnostics() {
    let codes = |c: &Case| {
        c.check()
            .diagnostics
            .into_iter()
            .filter(|d| d.path == "numerics.steady_algorithm")
            .map(|d| d.code)
            .collect::<Vec<_>>()
    };
    let mut c = load("lid-cavity.json");
    c.numerics.steady_algorithm = SteadyAlgorithm::ImplicitViscous;
    assert_eq!(codes(&c), ["CFD-E045"]);
    c.run.mode = Mode::Steady;
    assert!(codes(&c).is_empty());
    let mut tracer = load("periodic-tracer.json");
    tracer.run.mode = Mode::Steady;
    tracer.numerics.steady_algorithm = SteadyAlgorithm::ImplicitViscous;
    // Constituents are allowed since P5d; prescribed flow is still rejected.
    assert_eq!(codes(&tracer), ["CFD-E047"]);
    let mut rans = load("empty-abl.json");
    rans.run.mode = Mode::Steady;
    rans.numerics.steady_algorithm = SteadyAlgorithm::ImplicitViscous;
    assert!(codes(&rans).contains(&"CFD-E047".to_string()));
    let text = serde_json::to_string(&load("lid-cavity.json")).unwrap();
    assert!(!text.contains("steady_algorithm"));
}

fn steady_cavity(algorithm: SteadyAlgorithm) -> Case {
    let mut c = load("lid-cavity.json");
    c.grid.cells = [12, 2, 12];
    c.run.mode = Mode::Steady;
    c.run.threads = 1;
    c.numerics.steady_algorithm = algorithm;
    c
}

#[test]
fn implicit_viscous_cavities_restart_bit_for_bit() {
    for (scheme, limiter) in [
        (MomentumAdvection::DonorCell, None),
        (
            MomentumAdvection::LimitedUpwind,
            Some(MomentumLimiter::VanLeer),
        ),
    ] {
        let mut c = steady_cavity(SteadyAlgorithm::ImplicitViscous);
        c.numerics.momentum_advection = scheme;
        c.numerics.momentum_limiter = limiter;
        c.run.max_steps = 6;
        let whole = run(&c, &Control::new(60.0), None).unwrap();
        c.run.max_steps = 3;
        let first = run(&c, &Control::new(60.0), None).unwrap().state;
        assert!(first.momentum_solver_iterations > 0);
        c.run.max_steps = 6;
        let resumed = run(&c, &Control::new(60.0), Some(first)).unwrap();
        let bits = |v: &[f64]| v.iter().map(|x| x.to_bits()).collect::<Vec<_>>();
        assert_eq!(bits(&whole.state.velocity), bits(&resumed.state.velocity));
        assert_eq!(bits(&whole.state.pressure), bits(&resumed.state.pressure));
        assert_eq!(
            whole.state.momentum_solver_iterations,
            resumed.state.momentum_solver_iterations
        );
        assert_eq!(
            whole.summary.momentum_solver_iterations,
            Some(whole.state.momentum_solver_iterations)
        );
    }
    // Explicit runs neither do nor report inner work.
    let mut c = steady_cavity(SteadyAlgorithm::Explicit);
    c.run.max_steps = 3;
    let explicit = run(&c, &Control::new(60.0), None).unwrap();
    assert_eq!(explicit.state.momentum_solver_iterations, 0);
    assert_eq!(explicit.summary.momentum_solver_iterations, None);
    assert!(
        !serde_json::to_string(&explicit.state)
            .unwrap()
            .contains("momentum_solver_iterations")
    );
}

#[test]
fn implicit_viscous_steps_follow_the_advective_limit_only() {
    let explicit = steady_cavity(SteadyAlgorithm::Explicit);
    let implicit = steady_cavity(SteadyAlgorithm::ImplicitViscous);
    let g = Grid::build(&explicit).unwrap();
    let mut state = cfd_craft::solver::initial_state(&explicit, &g);
    for (f, v) in g.faces.iter().zip(&mut state.velocity) {
        if f.kind == FaceKind::Interior {
            *v = 0.3;
        }
    }
    let nut = vec![0.0; g.count()];
    let adv: f64 = 0.3 * 12.0 + 0.3 * 2.0 + 0.3 * 12.0;
    let dt = cfd_craft::solver::timestep(&implicit, &g, &state, &nut);
    assert!((dt - (0.4 / adv).min(0.1)).abs() <= 1e-14 * dt, "{dt}");
    assert!(cfd_craft::solver::timestep(&explicit, &g, &state, &nut) < dt);
}

// ---- Stage P5a: implicit steady iteration ----

fn periodic_vortex() -> (Case, Grid, Vec<f64>) {
    let mut c = load("poiseuille.json");
    c.grid.cells = [8, 2, 8];
    c.boundaries.z = Boundary::Periodic;
    let g = Grid::build(&c).unwrap();
    // A sampled Taylor-Green field is discretely divergence-free on the MAC grid.
    let tau = std::f64::consts::TAU;
    let u = g
        .faces
        .iter()
        .map(|f| {
            let (x, z) = (tau * f.center[0] + 0.3, tau * f.center[2] + 0.7);
            match f.axis {
                0 => x.sin() * z.cos() + 0.4,
                2 => -x.cos() * z.sin(),
                _ => 0.0,
            }
        })
        .collect();
    (c, g, u)
}

#[test]
fn the_implicit_matrix_is_consistent_and_diagonally_dominant() {
    let (c, g, u) = periodic_vortex();
    let s = Stencil::build(&c, &g);
    let dt = 0.05;
    let m = s.implicit_matrix(&u, 0.01, dt);
    // Without divergence, constants are in the kernel of advection and diffusion.
    let ones = vec![1.0; g.faces.len()];
    let mut out = vec![0.0; ones.len()];
    m.apply(&s, &ones, &mut out);
    for (i, v) in out.iter().enumerate() {
        assert!((v - 1.0 / dt).abs() <= 1e-10 / dt, "face {i}: {v}");
    }
    // An M-matrix: positive diagonal, nonpositive couplings, dominance by 1/dt.
    for fi in (0..g.faces.len()).filter(|i| s.unknown[*i]) {
        let off: f64 = m.off[fi].iter().flatten().sum();
        assert!(m.off[fi].iter().flatten().all(|v| *v <= 0.0));
        assert!(m.diagonal[fi] + off >= 1.0 / dt * (1.0 - 1e-10));
    }
    // A bounded wall case keeps positivity and dominance.
    let mut cavity = load("lid-cavity.json");
    cavity.grid.cells = [8, 2, 8];
    let g = Grid::build(&cavity).unwrap();
    let s = Stencil::build(&cavity, &g);
    let mut v: Vec<_> = (0..g.faces.len()).map(|i| (0.3 * i as f64).sin()).collect();
    g.enforce_velocity(&cavity, &mut v);
    let m = s.implicit_matrix(&v, 0.01, dt);
    for fi in (0..g.faces.len()).filter(|i| s.unknown[*i]) {
        assert!(m.diagonal[fi] > 0.0 && m.off[fi].iter().flatten().all(|v| *v <= 0.0));
    }
}

#[test]
fn the_implicit_matrix_matches_frozen_flux_first_order_upwind() {
    // Independent plain-array assembly on the periodic grid: A x = x/dt +
    // div(U_frozen * x_upwind) - nu L x, with MAC-averaged advecting velocities.
    let (c, g, u) = periodic_vortex();
    let s = Stencil::build(&c, &g);
    let (nu, dt) = (0.01, 0.05);
    let m = s.implicit_matrix(&u, nu, dt);
    let x: Vec<_> = (0..g.faces.len()).map(|i| (1.1 * i as f64).cos()).collect();
    let mut ax = vec![0.0; x.len()];
    m.apply(&s, &x, &mut ax);
    let at = |axis: usize, q: [isize; 3]| g.face_at(&c, axis, q).unwrap();
    for (fi, f) in g.faces.iter().enumerate() {
        let a = f.axis;
        let q = f.coord.map(|v| v as isize);
        let mut expected = x[fi] / dt;
        for d in 0..3 {
            let h = g.dx[d];
            let step = |k: isize| {
                let mut r = q;
                r[d] += k;
                r
            };
            let (lo, hi) = (at(a, step(-1)), at(a, step(1)));
            expected -= nu * (x[hi] + x[lo] - 2.0 * x[fi]) / (h * h);
            let advect = |k: isize| -> f64 {
                // CV face between the a-faces at step(k-1) and step(k) in d.
                if d == a {
                    let mut r = q;
                    r[a] += k - 1;
                    let mut r2 = r;
                    r2[a] += 1;
                    0.5 * (u[at(a, r)] + u[at(a, r2)])
                } else {
                    let mut r = q;
                    r[d] += k;
                    let mut r2 = r;
                    r2[a] -= 1;
                    0.5 * (u[at(d, r)] + u[at(d, r2)])
                }
            };
            let (u_lo, u_hi) = (advect(0), advect(1));
            let flux_hi = if u_hi >= 0.0 {
                u_hi * x[fi]
            } else {
                u_hi * x[hi]
            };
            let flux_lo = if u_lo >= 0.0 {
                u_lo * x[lo]
            } else {
                u_lo * x[fi]
            };
            expected += (flux_hi - flux_lo) / h;
        }
        assert!(
            (ax[fi] - expected).abs() <= 1e-10 * expected.abs().max(1.0),
            "face {fi} axis {a}: {} vs {expected}",
            ax[fi]
        );
    }
}

#[test]
fn the_inner_solve_reaches_its_relative_tolerance() {
    let (c, g, u) = periodic_vortex();
    let s = Stencil::build(&c, &g);
    let m = s.implicit_matrix(&u, 0.01, 0.2);
    let b: Vec<_> = (0..g.faces.len()).map(|i| (0.7 * i as f64).sin()).collect();
    let (x, info) =
        cfd_craft::momentum_solve::solve_implicit(&s, &m, &b, &Control::new(10.0)).unwrap();
    assert!(
        info.iterations > 0
            && info.iterations <= cfd_craft::momentum_solve::BICGSTAB_MAX_ITERATIONS
    );
    assert!(
        info.relative_residual <= cfd_craft::momentum_solve::BICGSTAB_RELATIVE_TOLERANCE,
        "{info:?}"
    );
    assert!(x.iter().all(|v| v.is_finite()));
}

#[test]
fn implicit_projection_cavities_restart_bit_for_bit_and_ramp_deterministically() {
    for (scheme, limiter) in [
        (MomentumAdvection::DonorCell, None),
        (
            MomentumAdvection::LimitedUpwind,
            Some(MomentumLimiter::VanLeer),
        ),
    ] {
        let mut c = steady_cavity(SteadyAlgorithm::ImplicitProjection);
        c.numerics.momentum_advection = scheme;
        c.numerics.momentum_limiter = limiter;
        c.run.max_steps = 6;
        let whole = run(&c, &Control::new(60.0), None).unwrap();
        c.run.max_steps = 3;
        let first = run(&c, &Control::new(60.0), None).unwrap().state;
        c.run.max_steps = 6;
        let resumed = run(&c, &Control::new(60.0), Some(first)).unwrap();
        let bits = |v: &[f64]| v.iter().map(|x| x.to_bits()).collect::<Vec<_>>();
        assert_eq!(bits(&whole.state.velocity), bits(&resumed.state.velocity));
        assert_eq!(bits(&whole.state.pressure), bits(&resumed.state.pressure));
        assert_eq!(whole.state.time_s.to_bits(), resumed.state.time_s.to_bits());
        assert_eq!(
            whole.state.momentum_solver_iterations,
            resumed.state.momentum_solver_iterations
        );
        assert!(whole.state.momentum_solver_iterations >= 6);
    }
    let c = steady_cavity(SteadyAlgorithm::ImplicitProjection);
    let g = Grid::build(&c).unwrap();
    let mut state = cfd_craft::solver::initial_state(&c, &g);
    for (f, v) in g.faces.iter().zip(&mut state.velocity) {
        if f.kind == FaceKind::Interior {
            *v = 0.5;
        }
    }
    let nut = vec![0.0; g.count()];
    let rate = 0.5 * 12.0 + 0.5 * 2.0 + 0.5 * 12.0;
    for steps in [0, 1, 5] {
        state.steps = steps;
        let dt = cfd_craft::solver::timestep(&c, &g, &state, &nut);
        let cfl = cfd_craft::momentum_solve::ramp_cfl(steps);
        // The ramp saturates at the predeclared cap.
        assert_eq!(
            cfd_craft::momentum_solve::ramp_cfl(steps + 9),
            5.0f64.min(1.2f64.powi(steps as i32 + 9))
        );
        assert_eq!(cfl, 1.0 * 1.2f64.powi(steps as i32));
        assert!((dt - (cfl / rate).min(0.1)).abs() <= 1e-14, "{steps}: {dt}");
    }
}

fn open_channel() -> Case {
    let mut c = load("poiseuille.json");
    c.grid.cells = [10, 2, 6];
    c.domain.size_m = [2.0, 0.2, 0.5];
    c.boundaries.x = Boundary::Open;
    if let Flow::Laminar {
        initial_velocity_m_s,
        viscosity_m2_s,
        acceleration_m_s2,
    } = &mut c.flow
    {
        *initial_velocity_m_s = [0.4, 0.0, 0.0];
        *viscosity_m2_s = 0.01;
        *acceleration_m_s2 = [0.0; 3];
    }
    c.run.mode = Mode::Steady;
    c.run.threads = 1;
    c
}

// The outlet momentum cell lies half outside the domain: its outer advecting
// velocity is the outlet face's own (zero-gradient), never a velocity sampled
// elsewhere in the grid.
#[test]
fn implicit_matrix_rows_at_an_outlet_use_only_adjacent_velocities() {
    let c = open_channel();
    let g = Grid::build(&c).unwrap();
    let s = Stencil::build(&c, &g);
    let mut u: Vec<_> = (0..g.faces.len())
        .map(|i| 0.4 + 0.05 * (0.9 * i as f64).sin())
        .collect();
    g.enforce_velocity(&c, &mut u);
    let outlets: Vec<_> = (0..g.faces.len())
        .filter(|i| g.faces[*i].kind == FaceKind::Outlet)
        .collect();
    assert!(!outlets.is_empty());
    let reference = s.implicit_matrix(&u, 0.01, 0.1);
    // Perturb every face that is not adjacent to an outlet's momentum cell.
    let near = |j: usize| {
        let f = &g.faces[j];
        outlets.iter().any(|&o| {
            let q = &g.faces[o];
            (0..3).all(|k| (f.center[k] - q.center[k]).abs() <= g.dx[k] * 1.01)
        })
    };
    let mut far = u.clone();
    for (j, v) in far.iter_mut().enumerate() {
        if !near(j) && g.faces[j].kind == FaceKind::Interior {
            *v += 3.0;
        }
    }
    let changed = s.implicit_matrix(&far, 0.01, 0.1);
    for &o in &outlets {
        assert_eq!(reference.diagonal[o], changed.diagonal[o], "outlet {o}");
        assert_eq!(reference.off[o], changed.off[o], "outlet {o}");
    }
    // The outer control-volume face advects with the outlet velocity itself.
    for &o in &outlets {
        let f = &g.faces[o];
        let side = usize::from(f.hi.is_none());
        assert_eq!(s.advecting[o][f.axis][side], [o, o]);
    }
}

// One cell on a periodic axis is a two-dimensional run: the y-invariant flow of
// the two-cell span, with the same outer iterations and the same fields on
// every plane (up to the round-off of the pressure solves).
#[test]
fn a_one_cell_periodic_span_reproduces_the_two_cell_span() {
    for algorithm in [
        SteadyAlgorithm::Explicit,
        SteadyAlgorithm::ImplicitProjection,
    ] {
        let mut one = steady_cavity(algorithm);
        one.numerics.momentum_advection = MomentumAdvection::LimitedUpwind;
        one.numerics.momentum_limiter = Some(MomentumLimiter::VanLeer);
        // Converged close to round-off, so the two runs' different pressure-solver
        // round-off cannot show through the steady tolerance.
        one.numerics.steady_residual_tolerance = 1e-10;
        one.numerics.steady_monitor_tolerance = 1e-9;
        one.run.max_steps = 100_000;
        let mut two = one.clone();
        two.grid.cells[1] = 2;
        one.grid.cells[1] = 1;
        assert!(
            one.check()
                .diagnostics
                .iter()
                .all(|d| d.severity != "error")
        );
        let mut wall = one.clone();
        wall.boundaries.y = Boundary::Wall;
        assert!(
            wall.check()
                .diagnostics
                .iter()
                .any(|d| d.code == "CFD-E004" && d.path == "grid.cells[1]")
        );
        let a = run(&one, &Control::new(120.0), None).unwrap();
        let b = run(&two, &Control::new(120.0), None).unwrap();
        assert_eq!(a.summary.assessment, "steady_discrete_solution");
        assert_eq!(a.summary.assessment, b.summary.assessment);
        assert_eq!(a.summary.steps, b.summary.steps, "{algorithm:?}");
        let (g1, g2) = (Grid::build(&one).unwrap(), Grid::build(&two).unwrap());
        let mut compared = 0;
        let mut worst = 0.0f64;
        for (f2, v2) in g2.faces.iter().zip(&b.state.velocity) {
            let [x, _, z] = f2.coord;
            let j = g1
                .faces
                .iter()
                .position(|f| f.axis == f2.axis && f.coord == [x, 0, z])
                .unwrap();
            let v1 = a.state.velocity[j];
            if f2.axis == 1 {
                assert!(v1.abs() <= 1e-12 && v2.abs() <= 1e-12);
            } else {
                worst = worst.max((v1 - v2).abs());
                compared += 1;
            }
        }
        assert!(compared > 0 && worst <= 1e-10, "{algorithm:?}: {worst:e}");
    }
}
