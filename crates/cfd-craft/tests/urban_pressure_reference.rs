//! Independent dense-reference and failure-path checks of masked pressure.
// Explicit indices keep the dense pivoted reference independent and readable.
#![allow(clippy::needless_range_loop)]
use cfd_craft::{
    case::{Block, Boundary, Case, Flow, PressurePreconditioner},
    grid::{FaceKind, Grid},
    pressure,
    solver::Control,
};
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};

fn base(n: [usize; 3], open: bool) -> Case {
    let mut c: Case =
        serde_json::from_str(include_str!("../../../cases/verification/lid-cavity.json")).unwrap();
    c.grid.cells = n;
    c.domain.size_m = n.map(|v| v as f64);
    c.moving_walls.clear();
    c.boundaries.x = if open { Boundary::Open } else { Boundary::Wall };
    c.boundaries.y = Boundary::Wall;
    if let Flow::Laminar {
        initial_velocity_m_s,
        ..
    } = &mut c.flow
    {
        *initial_velocity_m_s = [1., 0., 0.];
    }
    c.numerics.pressure_preconditioner = PressurePreconditioner::Multigrid;
    c
}
fn block(id: &str, min_m: [f64; 3], max_m: [f64; 3]) -> Block {
    Block {
        id: id.into(),
        min_m,
        max_m,
        footprint_m: None,
    }
}
fn center(g: &Grid, x: &mut [f64]) {
    for (cells, anchored) in g.components.iter().zip(&g.anchored) {
        if !anchored {
            let mean = cells.iter().map(|&i| x[i]).sum::<f64>() / cells.len() as f64;
            for &i in cells {
                x[i] -= mean;
            }
        }
    }
}

// Assemble the reference matrix directly from face energies. This does not
// call pressure::apply, Grid::gradient/divergence or the preconditioner.
fn dense_matrix(g: &Grid) -> Vec<Vec<f64>> {
    let mut a = vec![vec![0.; g.count()]; g.count()];
    for f in &g.faces {
        let w = f.area / f.distance / g.volume;
        match f.kind {
            FaceKind::Interior => {
                let (i, j) = (f.lo.unwrap(), f.hi.unwrap());
                a[i][i] += w;
                a[j][j] += w;
                a[i][j] -= w;
                a[j][i] -= w;
            }
            FaceKind::Outlet => {
                let i = f.lo.or(f.hi).unwrap();
                a[i][i] += w;
            }
            _ => {}
        }
    }
    a
}
fn product(a: &[Vec<f64>], x: &[f64]) -> Vec<f64> {
    a.iter()
        .map(|row| row.iter().zip(x).map(|(a, b)| a * b).sum())
        .collect()
}
fn pivot_reference(g: &Grid, a: &[Vec<f64>], b: &[f64]) -> Vec<f64> {
    let gauges: Vec<_> = g
        .components
        .iter()
        .zip(&g.anchored)
        .filter(|(_, anchored)| !**anchored)
        .map(|(c, _)| c[0])
        .collect();
    let active: Vec<_> = (0..g.count())
        .filter(|i| g.fluid[*i] && !gauges.contains(i))
        .collect();
    let n = active.len();
    let mut matrix: Vec<Vec<_>> = active
        .iter()
        .map(|&i| active.iter().map(|&j| a[i][j]).collect())
        .collect();
    let mut rhs: Vec<_> = active.iter().map(|&i| b[i]).collect();
    for k in 0..n {
        let pivot = (k..n)
            .max_by(|&i, &j| matrix[i][k].abs().total_cmp(&matrix[j][k].abs()))
            .unwrap();
        matrix.swap(k, pivot);
        rhs.swap(k, pivot);
        assert!(matrix[k][k].abs() > 1e-14);
        for i in k + 1..n {
            let t = matrix[i][k] / matrix[k][k];
            for j in k + 1..n {
                matrix[i][j] -= t * matrix[k][j];
            }
            rhs[i] -= t * rhs[k];
            matrix[i][k] = 0.;
        }
    }
    let mut solution = vec![0.; n];
    for i in (0..n).rev() {
        let tail = (i + 1..n).map(|j| matrix[i][j] * solution[j]).sum::<f64>();
        solution[i] = (rhs[i] - tail) / matrix[i][i];
    }
    let mut x = vec![0.; g.count()];
    for (i, &cell) in active.iter().enumerate() {
        x[cell] = solution[i];
    }
    center(g, &mut x);
    x
}
fn check_reference(g: &Grid) {
    let a = dense_matrix(g);
    let mut exact: Vec<_> = (0..g.count())
        .map(|i| {
            if g.fluid[i] {
                (0.19 * i as f64).sin()
            } else {
                0.
            }
        })
        .collect();
    center(g, &mut exact);
    let b = product(&a, &exact);
    let reference = pivot_reference(g, &a, &b);
    let (solved, info) = pressure::solve(g, &b, 1e-13, 2000, &Control::new(20.)).unwrap();
    assert!(info.relative_residual < 2e-12);
    for ((actual, dense), expected) in solved.iter().zip(reference).zip(exact) {
        assert!((actual - dense).abs() < 2e-10, "{actual} != {dense}");
        assert!((actual - expected).abs() < 2e-10);
    }
}

#[test]
fn mixed_outlet_anchored_and_inlet_only_sealed_components_match_pivoted_reference() {
    let mut c = base([9, 2, 5], true);
    c.geometry = vec![block("full-barrier", [3., 0., 0.], [4., 2., 5.])];
    let g = Grid::build(&c).unwrap();
    assert_eq!(g.anchored, vec![false, true]);
    assert!(g.components.iter().any(|v| v.len() > 32));
    check_reference(&g);
    assert!(pressure::multigrid_stats(&g).unwrap().level_cells.len() > 1);
}

#[test]
fn isolated_sealed_singleton_has_no_unknown_and_matches_independent_reference() {
    let mut c = base([7, 3, 5], true);
    c.geometry = vec![
        block("left", [2., 1., 2.], [3., 2., 3.]),
        block("right", [4., 1., 2.], [5., 2., 3.]),
        block("front", [3., 0., 2.], [4., 1., 3.]),
        block("back", [3., 2., 2.], [4., 3., 3.]),
        block("floor", [3., 1., 1.], [4., 2., 2.]),
        block("roof", [3., 1., 3.], [4., 2., 4.]),
    ];
    let g = Grid::build(&c).unwrap();
    let singleton = Grid::index(g.n, [3, 1, 2]);
    assert!(g.components.iter().any(|r| r == &[singleton]));
    assert!(!g.anchored[g.component[singleton]]);
    assert!(g.anchored.iter().any(|v| *v));
    check_reference(&g);
    let mut incompatible = vec![0.; g.count()];
    incompatible[singleton] = 1e-30;
    assert!(
        pressure::solve(&g, &incompatible, 1e-13, 2000, &Control::new(20.))
            .unwrap_err()
            .contains("CFD-E031")
    );
}

#[test]
fn changed_masked_face_weights_rebuild_once_and_preserve_the_reference_equation() {
    let mut c = base([9, 2, 5], true);
    c.geometry = vec![block("obstacle", [3., 0., 1.], [4., 2., 4.])];
    let mut g = Grid::build(&c).unwrap();
    let control = Control::new(20.).with_profiling();
    for changed in [false, false, true, false] {
        if changed {
            for (i, f) in g.faces.iter_mut().enumerate() {
                if matches!(f.kind, FaceKind::Interior | FaceKind::Outlet) {
                    f.area *= 0.75 + (i % 7) as f64 * 0.05;
                }
            }
        }
        let a = dense_matrix(&g);
        let exact: Vec<_> = (0..g.count())
            .map(|i| {
                if g.fluid[i] {
                    (0.37 * i as f64).cos()
                } else {
                    0.
                }
            })
            .collect();
        let b = product(&a, &exact);
        let (actual, _) = pressure::solve(&g, &b, 1e-13, 2000, &control).unwrap();
        let dense = pivot_reference(&g, &a, &b);
        assert!(actual.iter().zip(dense).all(|(a, b)| (a - b).abs() < 2e-10));
    }
    let profile = control.profile().unwrap().unwrap();
    assert_eq!(profile.phases["pressure_multigrid_setup"].calls, 2);
    assert_eq!(
        profile.phases["pressure_solve"]
            .multigrid
            .as_ref()
            .unwrap()
            .hierarchy_builds,
        2
    );
}

#[test]
fn masked_cancellation_and_iteration_limit_never_commit_partial_projection() {
    let mut c = base([20, 4, 20], false);
    c.geometry = vec![block("obstacle", [8., 1., 4.], [11., 3., 14.])];
    let g = Grid::build(&c).unwrap();
    let initial_u: Vec<_> = g
        .faces
        .iter()
        .enumerate()
        .map(|(i, f)| {
            if f.kind == FaceKind::Interior {
                (0.7 * i as f64).sin()
            } else {
                0.
            }
        })
        .collect();
    let initial_p = vec![0.; g.count()];
    let (mut u, mut p) = (initial_u.clone(), initial_p.clone());
    let polls = Arc::new(AtomicUsize::new(0));
    let counter = polls.clone();
    let control = Control::with_poll(20., move || {
        if counter.fetch_add(1, Ordering::SeqCst) >= 3 {
            Err("cancelled".into())
        } else {
            Ok(())
        }
    });
    let error = pressure::project(&g, &mut u, &mut p, 0.1, 1e-13, 2000, &control).unwrap_err();
    assert_eq!(error, "cancelled");
    assert_eq!(u, initial_u);
    assert_eq!(p, initial_p);
    let error =
        pressure::project(&g, &mut u, &mut p, 0.1, 1e-13, 1, &Control::new(20.)).unwrap_err();
    assert!(error.contains("CFD-E033"));
    assert_eq!(u, initial_u);
    assert_eq!(p, initial_p);
}
