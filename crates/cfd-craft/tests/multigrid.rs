//! End-to-end checks for the optional preconditioner with unchanged fine gates.
use cfd_craft::{
    case::*,
    grid::Grid,
    pressure,
    solver::{self, Control},
};
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
fn case(n: [usize; 3], boundary: Boundary) -> Case {
    let mut c: Case =
        serde_json::from_str(include_str!("../../../cases/verification/lid-cavity.json")).unwrap();
    c.grid.cells = n;
    c.moving_walls.clear();
    c.boundaries.x = boundary;
    c.numerics.pressure_preconditioner = PressurePreconditioner::Multigrid;
    if let Flow::Laminar {
        initial_velocity_m_s,
        ..
    } = &mut c.flow
    {
        *initial_velocity_m_s = [1.0, 0.0, 0.0];
    }
    c
}
#[test]
fn default_serialization_and_physics_hash_remain_compatible() {
    let text = include_str!("../../../cases/verification/lid-cavity.json");
    let mut c: Case = serde_json::from_str(text).unwrap();
    let old: serde_json::Value = serde_json::from_str(text).unwrap();
    assert_eq!(serde_json::to_value(&c).unwrap(), old);
    let hash = c.physics_hash();
    c.numerics.pressure_preconditioner = PressurePreconditioner::Ic0;
    assert_eq!(hash, c.physics_hash());
    c.numerics.pressure_preconditioner = PressurePreconditioner::Multigrid;
    assert_ne!(hash, c.physics_hash());
    let mut v = serde_json::to_value(c).unwrap();
    v["numerics"]["pressure_preconditioner"] = "unknown".into();
    assert!(serde_json::from_value::<Case>(v).is_err());
}
#[test]
fn masks_fail_explicitly_and_preflight_accounts_for_hierarchy_storage() {
    let mut c = case([12, 2, 12], Boundary::Wall);
    let mg = c.check().estimated_peak_mib;
    c.numerics.pressure_preconditioner = PressurePreconditioner::Ic0;
    assert!(c.check().estimated_peak_mib < mg);
    c.numerics.pressure_preconditioner = PressurePreconditioner::Multigrid;
    c.geometry.push(Block {
        id: "solid".into(),
        min_m: [0.4, 0.0, 0.4],
        max_m: [0.6, 1.0, 0.6],
    });
    let r = c.check();
    assert!(!r.valid);
    assert!(
        r.diagnostics
            .iter()
            .any(|d| d.code == "CFD-E034" && d.path == "numerics.pressure_preconditioner")
    );
}
#[test]
fn strong_anisotropy_between_coarsened_axes_is_a_check_warning() {
    let warned = |c: &Case| {
        c.check()
            .diagnostics
            .iter()
            .any(|d| d.code == "CFD-W004" && d.path == "numerics.pressure_preconditioner")
    };
    // Equal spacing, and the two-cell span axis that is never coarsened.
    assert!(!warned(&case([48, 2, 48], Boundary::Wall)));
    let mut c = case([64, 2, 64], Boundary::Wall);
    c.domain.size_m = [1.0, 0.1, 0.2];
    assert!(!warned(&c)); // z:x weight ratio 25
    c.domain.size_m = [1.0, 0.1, 0.1];
    assert!(warned(&c)); // ratio 100
    assert!(c.check().valid);
    // A coarsened span axis of eight cells, 64 times weaker than x and z.
    let mut c = case([64, 8, 64], Boundary::Wall);
    c.domain.size_m = [1.0, 1.0, 1.0];
    assert!(warned(&c));
    c.numerics.pressure_preconditioner = PressurePreconditioner::Ic0;
    assert!(!warned(&c));
}
#[test]
fn manufactured_pressure_and_projection_match_independent_gradient_divergence() {
    for boundary in [Boundary::Wall, Boundary::Periodic, Boundary::Open] {
        for n in [[9, 2, 7], [8, 5, 6], [2, 2, 2]] {
            let c = case(n, boundary);
            let g = Grid::build(&c).unwrap();
            let mut exact: Vec<_> = (0..g.count()).map(|i| (0.37 * i as f64).sin()).collect();
            pressure::center_nullspaces(&g, &mut exact);
            let b: Vec<_> = g
                .divergence(&g.gradient(&exact))
                .iter()
                .map(|v| -v)
                .collect();
            let (x, info) = pressure::solve(&g, &b, 1e-12, 2000, &Control::new(20.0)).unwrap();
            assert!(info.relative_residual <= 1.1e-11);
            assert!(x.iter().zip(&exact).all(|(a, b)| (a - b).abs() < 1e-9));
            let dt = 0.125;
            let mut u = g.gradient(&exact);
            let mut p = vec![0.0; g.count()];
            pressure::project(&g, &mut u, &mut p, dt, 1e-12, 2000, &Control::new(20.0)).unwrap();
            assert!(u.iter().all(|v| v.abs() < 1e-8));
            assert!(p.iter().zip(&exact).all(|(a, b)| (a - b / dt).abs() < 1e-8));
            assert!(g.divergence(&u).iter().all(|v| v.abs() < 1e-7));
        }
    }
}
#[test]
fn continuous_periodic_poisson_retains_second_order_accuracy() {
    let mut errors = vec![];
    for nx in [12, 24, 48] {
        let c = case([nx, 2, 4], Boundary::Periodic);
        let g = Grid::build(&c).unwrap();
        let exact: Vec<_> = (0..g.count())
            .map(|i| (2.0 * std::f64::consts::PI * g.center(i)[0]).sin())
            .collect();
        let rhs: Vec<_> = exact
            .iter()
            .map(|v| 4.0 * std::f64::consts::PI.powi(2) * v)
            .collect();
        let (x, _) = pressure::solve(&g, &rhs, 1e-12, 2000, &Control::new(20.0)).unwrap();
        errors.push(
            (x.iter()
                .zip(exact)
                .map(|(a, b)| (a - b).powi(2))
                .sum::<f64>()
                / g.count() as f64)
                .sqrt(),
        );
    }
    for e in errors.windows(2) {
        assert!((e[0] / e[1]).log2() > 1.99);
    }
}
#[test]
fn compatible_closed_rhs_and_incompatible_flux_keep_the_existing_contract() {
    let g = Grid::build(&case([9, 2, 7], Boundary::Wall)).unwrap();
    let mut b: Vec<_> = (0..g.count()).map(|i| (i as f64 * 0.3).cos()).collect();
    pressure::center_nullspaces(&g, &mut b);
    for v in &mut b {
        *v += 1e-11;
    }
    pressure::solve(&g, &b, 1e-12, 2000, &Control::new(20.0)).unwrap();
    for v in &mut b {
        *v += 0.1;
    }
    assert!(
        pressure::solve(&g, &b, 1e-12, 2000, &Control::new(20.0))
            .unwrap_err()
            .contains("CFD-E031")
    );
}
#[test]
fn setup_is_reused_and_changed_face_coefficients_rebuild_before_solving() {
    let mut g = Grid::build(&case([9, 2, 7], Boundary::Open)).unwrap();
    let control = Control::new(20.0).with_profiling();
    let exact: Vec<_> = (0..g.count()).map(|i| (0.37 * i as f64).sin()).collect();
    for changed in [false, false, true, false] {
        if changed {
            for (i, f) in g.faces.iter_mut().enumerate() {
                f.area *= 1.0 + (i % 7) as f64 * 0.025;
            }
        }
        let mut b = vec![0.0; g.count()];
        pressure::apply(&g, &exact, &mut b);
        let (x, info) = pressure::solve(&g, &b, 1e-12, 2000, &control).unwrap();
        assert!(info.relative_residual < 1.1e-11);
        assert!(x.iter().zip(&exact).all(|(a, b)| (a - b).abs() < 1e-9));
    }
    let profile = control.profile().unwrap().unwrap();
    assert_eq!(profile.phases["pressure_multigrid_setup"].calls, 2);
    let p = &profile.phases["pressure_solve"];
    let w = p.multigrid.as_ref().unwrap();
    assert_eq!(w.hierarchy_builds, 2);
    assert_eq!(w.cycles, p.preconditioner_applications);
    assert_eq!(w.coarse_solves, w.cycles);
    let stats = pressure::multigrid_stats(&g).unwrap();
    let smoothed = stats.level_cells[..stats.level_cells.len() - 1]
        .iter()
        .sum::<usize>() as u64;
    assert_eq!(w.smoothing_cell_updates, 4 * smoothed * w.cycles);
    assert_eq!(w.residual_cell_updates, smoothed * w.cycles);
    assert_eq!(w.restriction_cell_updates, w.residual_cell_updates);
    assert_eq!(w.prolongation_cell_updates, w.residual_cell_updates);
    assert!(pressure::multigrid_stats(&g).unwrap().allocated_bytes > 0);
}
#[test]
fn a_poll_callback_can_read_multigrid_statistics_during_a_solve() {
    // The solve holds the hierarchy while it polls; statistics must not wait for it.
    let g = Grid::build(&case([17, 2, 13], Boundary::Wall)).unwrap();
    let seen = Arc::new(AtomicUsize::new(0));
    let (probe, counter) = (g.clone(), seen.clone());
    let control = Control::with_poll(30.0, move || {
        if pressure::multigrid_stats(&probe).is_some() {
            counter.fetch_add(1, Ordering::Relaxed);
        }
        Ok(())
    });
    let mut b: Vec<_> = (0..g.count()).map(|i| (0.61 * i as f64).sin()).collect();
    pressure::center_nullspaces(&g, &mut b);
    let (done, result) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let _ = done.send(pressure::solve(&g, &b, 1e-12, 200, &control).map(|r| r.1));
    });
    let info = result
        .recv_timeout(std::time::Duration::from_secs(30))
        .expect("the solve finished instead of waiting on its own lock")
        .unwrap();
    assert!(info.iterations > 0);
    assert!(seen.load(Ordering::Relaxed) > 0);
}
#[test]
fn reused_hierarchies_follow_small_interior_and_outlet_weight_changes() {
    let base = case([9, 2, 7], Boundary::Open);
    let mut g = Grid::build(&base).unwrap();
    let control = Control::new(20.0).with_profiling();
    let solve = |g: &Grid| {
        let exact: Vec<_> = (0..g.count()).map(|i| (0.37 * i as f64).sin()).collect();
        let mut b = vec![0.0; g.count()];
        pressure::apply(g, &exact, &mut b);
        pressure::solve(g, &b, 1e-12, 2000, &control).unwrap();
    };
    solve(&g); // build
    solve(&g); // reuse
    let find = |g: &Grid, kind| g.faces.iter().position(|f| f.kind == kind).unwrap();
    let wall = find(&g, cfd_craft::grid::FaceKind::Wall);
    g.faces[wall].area *= 2.0; // walls carry no pressure weight
    solve(&g); // reuse
    let interior = find(&g, cfd_craft::grid::FaceKind::Interior);
    g.faces[interior].distance *= 1.0 + 1e-15; // a few-ulp weight change
    solve(&g); // rebuild
    let outlet = find(&g, cfd_craft::grid::FaceKind::Outlet);
    g.faces[outlet].area *= 2.0;
    solve(&g); // rebuild
    solve(&g); // reuse
    let builds = control.profile().unwrap().unwrap().phases["pressure_solve"]
        .multigrid
        .as_ref()
        .unwrap()
        .hierarchy_builds;
    assert_eq!(builds, 3);
}
#[test]
fn cancellation_and_iteration_limits_leave_the_whole_step_unchanged() {
    let c = case([24, 2, 24], Boundary::Wall);
    let g = Grid::build(&c).unwrap();
    let before = solver::initial_state(&c, &g);
    let mut s = before.clone();
    let polls = Arc::new(AtomicUsize::new(0));
    let count = polls.clone();
    let control = Control::with_poll(20.0, move || {
        if count.fetch_add(1, Ordering::SeqCst) >= 2 {
            Err("cancelled".into())
        } else {
            Ok(())
        }
    });
    let sources = vec![];
    let err = solver::step(&c, &g, &mut s, &sources, 0.001, &control).unwrap_err();
    assert_eq!(err, "cancelled");
    assert_eq!(
        serde_json::to_value(&s).unwrap(),
        serde_json::to_value(&before).unwrap()
    );
    let mut c = c;
    c.numerics.pressure_max_iterations = 1;
    let err = solver::step(&c, &g, &mut s, &sources, 0.001, &Control::new(20.0)).unwrap_err();
    assert!(err.contains("CFD-E033"));
    assert_eq!(
        serde_json::to_value(&s).unwrap(),
        serde_json::to_value(&before).unwrap()
    );
}
