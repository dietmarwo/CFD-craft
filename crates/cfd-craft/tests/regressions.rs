//! Tests for diagnostics, estimates, geometry, archives, boundary classification and an
//! independently assembled pressure reference.
use cfd_craft::{
    case::*,
    flow,
    grid::{FaceKind, Grid},
    output, pressure, solver,
    solver::Control,
};

fn tracer() -> Case {
    serde_json::from_str(include_str!(
        "../../../cases/verification/periodic-tracer.json"
    ))
    .unwrap()
}
fn canyon() -> Case {
    serde_json::from_str(include_str!("../../../cases/canyon/wh1-wind270.json")).unwrap()
}
fn codes(c: &Case) -> Vec<(String, String)> {
    c.check()
        .diagnostics
        .into_iter()
        .map(|d| (d.code, d.path))
        .collect()
}

#[test]
fn a_small_incompatible_closed_rhs_is_rejected() {
    let mut c = tracer();
    c.constituents.clear();
    c.initial_conditions.clear();
    c.receptors.clear();
    c.grid.cells = [8, 4, 4];
    let g = Grid::build(&c).unwrap();
    assert_eq!(g.anchored, vec![false]);
    // A one-signed right-hand side has no solution in a closed component, however small.
    for scale in [1e-12, 1.0] {
        let b = vec![scale; g.count()];
        let e = pressure::solve(&g, &b, 1e-11, 2000, &Control::new(20.0)).unwrap_err();
        assert!(e.contains("CFD-E031"), "{scale}: {e}");
    }
    // A small compatible right-hand side is still solved.
    let mut b: Vec<f64> = (0..g.count()).map(|i| 1e-12 * (i % 7) as f64).collect();
    let mean = b.iter().sum::<f64>() / b.len() as f64;
    b.iter_mut().for_each(|v| *v -= mean);
    let (x, info) = pressure::solve(&g, &b, 1e-10, 2000, &Control::new(20.0)).unwrap();
    let mut ax = vec![0.0; g.count()];
    pressure::apply(&g, &x, &mut ax);
    let res = ax
        .iter()
        .zip(&b)
        .map(|(a, b)| (a - b).powi(2))
        .sum::<f64>()
        .sqrt()
        / b.iter().map(|v| v * v).sum::<f64>().sqrt();
    assert!(res < 1e-8 && info.relative_residual < 1e-8, "{res}");
}

#[test]
fn a_canyon_floor_cell_averages_its_wall_faces() {
    let mut c = canyon();
    c.grid.cells = [18, 16, 12];
    let g = Grid::build(&c).unwrap();
    let mut s = solver::initial_state(&c, &g);
    let u = s.velocity.clone();
    flow::turbulence_step(&c, &g, &u, &mut s.k, &mut s.epsilon, 0.0);
    // The canyon floor cell at x = 6.5 m touches both buildings and the ground.
    let i = Grid::index(g.n, [6, 8, 0]);
    let walls: Vec<(usize, usize)> = (0..3)
        .flat_map(|d| (0..2).map(move |side| (d, side)))
        .filter(|&(d, side)| g.faces[g.cell_faces[i][d][side]].kind == FaceKind::Wall)
        .collect();
    assert_eq!(walls, vec![(0, 0), (0, 1), (2, 0)]);
    let k = s.k[i];
    let law = |distance: f64| 0.09f64.powf(0.75) * k.powf(1.5) / (0.4 * distance);
    let Flow::NeutralRans { roughness_m, .. } = c.flow else {
        unreachable!()
    };
    let building = law(0.5 * g.dx[0] + roughness_m.min(0.001 * g.dx[0]));
    let ground = law(0.5 * g.dx[2] + roughness_m);
    let mean = (2.0 * building + ground) / 3.0;
    assert!(
        (s.epsilon[i] - mean).abs() <= 1e-12 * mean,
        "stored {} expected mean {mean} (ground law {ground}, building law {building})",
        s.epsilon[i]
    );
}

#[test]
fn laminar_flow_rejects_the_rans_open_top() {
    let mut c: Case =
        serde_json::from_str(include_str!("../../../cases/verification/poiseuille.json")).unwrap();
    c.boundaries.z = Boundary::GroundOpenTop;
    assert!(codes(&c).contains(&("CFD-E023".into(), "boundaries.z".into())));
}

#[test]
fn a_box_without_cell_centers_is_rejected() {
    let mut c = canyon();
    c.geometry.push(Block {
        id: "thin".into(),
        min_m: [10.0, 3.0, 0.0],
        max_m: [10.01, 13.0, 1.0],
    });
    assert!(c.check().valid);
    let e = Grid::build(&c).unwrap_err();
    assert!(e.starts_with("CFD-E028") && e.contains("thin"), "{e}");
    let mut ok = canyon();
    ok.grid.cells = [18, 16, 12];
    let g = Grid::build(&ok).unwrap();
    assert_eq!(g.evidence().box_cells["west"], 20);
}

#[test]
fn diagnostics_name_the_element_and_field() {
    let mut c = canyon();
    c.geometry[1].max_m[2] = 20.0;
    c.numerics.advective_cfl_max = 0.6;
    c.sources[0] = Source::Volume {
        id: "inverted".into(),
        constituent: "tracer".into(),
        min_m: [6.0, 4.0, 0.1],
        max_m: [5.0, 5.0, 0.2],
        rate_kg_s_m3: 1.0,
    };
    let d = codes(&c);
    assert!(
        d.contains(&("CFD-E014".into(), "geometry[1]".into())),
        "{d:?}"
    );
    assert!(d.contains(&("CFD-E010".into(), "numerics.advective_cfl_max".into())));
    assert!(d.contains(&("CFD-E017".into(), "sources[0]".into())));
    // A declared positive rate is not reported as negative because the box is inverted.
    assert!(!d.iter().any(|(code, _)| code == "CFD-E016"), "{d:?}");
    // One resolution warning per box, each naming its box.
    let w: Vec<_> = codes(&canyon())
        .into_iter()
        .filter(|(code, _)| code == "CFD-W001")
        .map(|(_, path)| path)
        .collect();
    assert_eq!(
        w,
        vec!["geometry[0]".to_string(), "geometry[1]".to_string()]
    );
}

#[test]
fn domain_size_and_blockage_follow_the_guideline_warnings() {
    let c = canyon();
    let d = codes(&c);
    // 10 m of building length in a 16 m x 6 m section is far above 3 % blockage,
    // and the 6 m domain top is 5 H above the 1 m buildings.
    assert!(d.contains(&("CFD-W002".into(), "geometry".into())), "{d:?}");
    let clearance = |d: &[(String, String)]| -> Vec<String> {
        d.iter()
            .filter(|(code, _)| code == "CFD-W003")
            .map(|(_, path)| path.clone())
            .collect()
    };
    // 10 H behind the buildings along x and 3 H at each side along y.
    assert_eq!(
        clearance(&d),
        vec![
            "domain.size_m[0]".to_string(),
            "domain.size_m[1]".to_string()
        ]
    );
    // Slip and wall sides need lateral clearance too; periodic sides repeat the buildings.
    for side in [Boundary::Slip, Boundary::Wall, Boundary::Periodic] {
        let mut c = canyon();
        c.boundaries.y = side;
        let found = clearance(&codes(&c)).contains(&"domain.size_m[1]".to_string());
        assert_eq!(found, side != Boundary::Periodic, "{side:?}");
    }
}

#[test]
fn the_mask_topology_matches_the_built_grid() {
    let mut cases = vec![canyon(), tracer()];
    cases[0].grid.cells = [18, 16, 12];
    // A wall across x splits a closed box in two, unless x is periodic.
    for periodic in [false, true] {
        let mut c = tracer();
        c.constituents.clear();
        c.initial_conditions.clear();
        c.receptors.clear();
        c.grid.cells = [12, 6, 6];
        c.boundaries.x = if periodic {
            Boundary::Periodic
        } else {
            Boundary::Wall
        };
        c.flow = Flow::Laminar {
            initial_velocity_m_s: [0.0; 3],
            viscosity_m2_s: 0.01,
            acceleration_m_s2: [0.0; 3],
        };
        c.geometry.push(Block {
            id: "wall".into(),
            min_m: [5.0, 0.0, 0.0],
            max_m: [7.0, c.domain.size_m[1], c.domain.size_m[2]],
        });
        cases.push(c);
    }
    let mut components = vec![];
    for c in &cases {
        let g = Grid::build(c).unwrap().evidence();
        let t = Grid::mask_topology(c).unwrap();
        assert_eq!(t.fluid_components, g.fluid_components, "{}", c.name);
        assert_eq!(t.solid_cells, g.solid_cells, "{}", c.name);
        assert!((t.solid_volume_m3 - g.solid_volume_m3).abs() <= 1e-12 * g.solid_volume_m3);
        components.push(t.fluid_components);
    }
    assert_eq!(components, vec![1, 1, 2, 1]);
}

#[test]
fn an_empty_box_error_names_its_index() {
    let mut c = canyon();
    // "we st" begins with the ID of box "west"; the error must still name the new box.
    c.geometry.push(Block {
        id: "we st".into(),
        min_m: [10.0, 3.0, 0.0],
        max_m: [10.01, 13.0, 1.0],
    });
    let e = Grid::build(&c).unwrap_err();
    assert!(e.starts_with("CFD-E028: geometry[2] (box we st)"), "{e}");
}

#[test]
fn a_restart_with_mass_in_a_solid_cell_is_rejected() {
    let mut c = canyon();
    c.grid.cells = [18, 16, 12];
    c.run.max_steps = 2;
    let r = solver::run(&c, &Control::new(60.0), None).unwrap();
    let g = Grid::build(&c).unwrap();
    let solid = (0..g.count()).find(|i| !g.fluid[*i]).unwrap();
    assert!(r.state.concentrations[0][solid] == 0.0);
    let mut state = r.state.clone();
    state.concentrations[0][solid] = 1e-9;
    let path = std::env::temp_dir().join(format!("cfd-solid-mass-{}.json", std::process::id()));
    std::fs::write(&path, output::checkpoint_bytes(&c, &state).unwrap()).unwrap();
    let mut longer = c.clone();
    longer.run.max_steps = 4;
    let e = output::read_checkpoint(&longer, &path).err().unwrap();
    std::fs::remove_file(&path).unwrap();
    assert!(e.starts_with("CFD-E051") && e.contains("solid"), "{e}");
}

#[test]
fn artifacts_over_budget_are_omitted_and_listed() {
    let mut c = tracer();
    c.grid.cells = [8, 4, 4];
    c.run.end_time_s = 0.2;
    c.output.fields = true;
    c.output.checkpoint = true;
    let mut r = solver::run(&c, &Control::new(20.0), None).unwrap();
    // Write past the check: a zero budget leaves room for the required artifacts only.
    // The output budget is not physics, so only the case hash changes.
    c.output.max_total_mib = 0;
    r.summary.case_sha256 = hash_bytes(&serde_json::to_vec(&c).unwrap());
    let out = std::env::temp_dir().join(format!("cfd-omitted-{}", std::process::id()));
    output::create_run_dir(&out).unwrap();
    let omitted = output::write_run(&c, &r, &out, "input").unwrap();
    let verified = output::read_verified(&out);
    let present = out.join("fields.json").exists() || out.join("checkpoint.json").exists();
    std::fs::remove_dir_all(&out).unwrap();
    assert_eq!(omitted, vec!["checkpoint.json", "fields.json"]);
    assert!(!present);
    assert_eq!(verified.unwrap().omitted, omitted);
}

#[test]
fn the_output_estimate_counts_receptors_and_history() {
    let mut c = tracer();
    c.output.fields = true;
    c.output.checkpoint = true;
    let base = c.check().estimated_output_mib;
    let receptor = c.receptors[0].clone();
    for i in 0..25_000 {
        let mut r = receptor.clone();
        match &mut r {
            Receptor::Point { id, .. } | Receptor::VolumeAverage { id, .. } => {
                *id = format!("p{i}")
            }
        }
        c.receptors.push(r);
    }
    // A full monitor history carries 25,000 values per row, in fields and checkpoint;
    // each value takes at least 20 bytes of JSON text.
    let rows = (3 * c.numerics.monitor_window).min(c.run.max_steps) as f64;
    let history_mib = 2.0 * 20.0 * rows * 25_000.0 / 1048576.0;
    let report = c.check();
    assert!(
        report.estimated_output_mib > base + history_mib,
        "{} vs {base} + {history_mib}",
        report.estimated_output_mib
    );
    assert!(report.estimated_peak_mib > 8.0 * rows * 25_000.0 / 1048576.0);
}

#[test]
fn the_output_estimate_counts_constituents() {
    let mut c = tracer();
    let one = c.check().estimated_output_mib;
    let species = c.constituents[0].clone();
    for i in 0..15 {
        let mut s = species.clone();
        s.id = format!("extra{i}");
        c.constituents.push(s);
    }
    assert!(c.check().estimated_output_mib > 2.5 * (one - 2.0) + 2.0);
}

/// Boundary faces of one side of the domain, by kind.
fn side_kinds(g: &Grid, axis: usize, high: bool) -> Vec<FaceKind> {
    let mut kinds: Vec<FaceKind> = g
        .faces
        .iter()
        .filter(|f| f.axis == axis && f.coord[axis] == if high { g.n[axis] } else { 0 })
        .filter(|f| f.kind != FaceKind::Blocked)
        .map(|f| f.kind)
        .collect();
    kinds.dedup();
    kinds
}

#[test]
fn an_oblique_wind_classifies_its_inlets_and_outlets() {
    use FaceKind::{Inlet, Outlet, Slip};
    // Meteorological direction is where the wind comes from, clockwise from north.
    for (degrees, x, y) in [
        (270.0, [Inlet, Outlet], [Slip, Slip]),
        (225.0, [Inlet, Outlet], [Inlet, Outlet]),
        (45.0, [Outlet, Inlet], [Outlet, Inlet]),
        (135.0, [Outlet, Inlet], [Inlet, Outlet]),
    ] {
        let mut c = canyon();
        c.grid.cells = [18, 16, 12];
        let Flow::NeutralRans {
            direction_deg_from, ..
        } = &mut c.flow
        else {
            unreachable!()
        };
        *direction_deg_from = degrees;
        let g = Grid::build(&c).unwrap();
        for (axis, expected) in [(0, x), (1, y)] {
            for (side, kind) in expected.iter().enumerate() {
                assert_eq!(
                    side_kinds(&g, axis, side == 1),
                    vec![*kind],
                    "{degrees} deg, axis {axis}, side {side}"
                );
            }
        }
    }
}

/// Dense Gaussian elimination with partial pivoting, for small reference systems.
fn dense_solve(mut a: Vec<Vec<f64>>, mut b: Vec<f64>) -> Vec<f64> {
    let n = b.len();
    for k in 0..n {
        let p = (k..n)
            .max_by(|&i, &j| a[i][k].abs().total_cmp(&a[j][k].abs()))
            .unwrap();
        a.swap(k, p);
        b.swap(k, p);
        let (top, bottom) = a.split_at_mut(k + 1);
        let pivot = &top[k];
        for (offset, row) in bottom.iter_mut().enumerate() {
            let f = row[k] / pivot[k];
            for (x, p) in row[k..].iter_mut().zip(&pivot[k..]) {
                *x -= f * p;
            }
            b[k + 1 + offset] -= f * b[k];
        }
    }
    let mut x = vec![0.0; n];
    for k in (0..n).rev() {
        let s: f64 = (k + 1..n).map(|j| a[k][j] * x[j]).sum();
        x[k] = (b[k] - s) / a[k][k];
    }
    x
}

#[test]
fn the_masked_pressure_operator_matches_an_assembled_reference() {
    // A RANS street with a sealed 2x2x2 pocket inside a hollow box: one component
    // anchored by its outlet and one closed component with a gauge.
    for periodic_y in [false, true] {
        let mut c = canyon();
        c.constituents.clear();
        c.sources.clear();
        c.receptors.clear();
        c.initial_conditions.clear();
        c.domain.size_m = [10.0, 6.0, 5.0];
        c.grid.cells = [10, 6, 5];
        if periodic_y {
            c.boundaries.y = Boundary::Periodic;
        }
        let shell = [
            ([3.0, 1.0, 0.0], [7.0, 5.0, 1.0]),
            ([3.0, 1.0, 3.0], [7.0, 5.0, 4.0]),
            ([3.0, 1.0, 1.0], [4.0, 5.0, 3.0]),
            ([6.0, 1.0, 1.0], [7.0, 5.0, 3.0]),
            ([4.0, 1.0, 1.0], [6.0, 2.0, 3.0]),
            ([4.0, 4.0, 1.0], [6.0, 5.0, 3.0]),
        ];
        c.geometry = shell
            .iter()
            .enumerate()
            .map(|(i, (lo, hi))| Block {
                id: format!("shell{i}"),
                min_m: *lo,
                max_m: *hi,
            })
            .collect();
        let g = Grid::build(&c).unwrap();
        assert_eq!(g.anchored.len(), 2);
        assert_eq!(g.anchored.iter().filter(|a| !**a).count(), 1);
        // Assemble from the mask and the boundary semantics alone, without the face list:
        // fluid neighbors couple with 1/dx^2; an open face with outflow is a Dirichlet
        // face at half a cell (2/dx^2); walls, slip, inlets and solids add nothing.
        let fluid: Vec<usize> = (0..g.count()).filter(|i| g.fluid[*i]).collect();
        let row: std::collections::HashMap<usize, usize> =
            fluid.iter().enumerate().map(|(r, i)| (*i, r)).collect();
        let m = fluid.len();
        let mut a = vec![vec![0.0; m]; m];
        for (r, &i) in fluid.iter().enumerate() {
            let q = g.coord(i);
            for axis in 0..3 {
                let h2 = g.dx[axis] * g.dx[axis];
                for step in [-1isize, 1] {
                    let t = q[axis] as isize + step;
                    let inside = (0..g.n[axis] as isize).contains(&t);
                    if !inside && c.boundaries.at(axis) != Boundary::Periodic {
                        if c.boundaries.at(axis) == Boundary::Open {
                            let z = g.center(i)[2];
                            let outward = c.flow.vector(z)[axis] * step as f64;
                            if outward > 1e-12 {
                                a[r][r] += 2.0 / h2;
                            }
                        }
                        continue;
                    }
                    let mut p = q;
                    p[axis] = t.rem_euclid(g.n[axis] as isize) as usize;
                    let j = Grid::index(g.n, p);
                    if let Some(&s) = row.get(&j) {
                        a[r][r] += 1.0 / h2;
                        a[r][s] -= 1.0 / h2;
                    }
                }
            }
        }
        // Products agree on a nonsmooth field.
        let x: Vec<f64> = (0..g.count())
            .map(|i| ((7 * i) % 13) as f64 - 6.0)
            .collect();
        let mut y = vec![0.0; g.count()];
        pressure::apply(&g, &x, &mut y);
        let scale = y.iter().map(|v| v.abs()).fold(0.0, f64::max);
        for (r, &i) in fluid.iter().enumerate() {
            let reference: f64 = fluid.iter().enumerate().map(|(s, &j)| a[r][s] * x[j]).sum();
            assert!((y[i] - reference).abs() <= 1e-12 * scale, "{i}");
        }
        // Solutions agree: a compatible right-hand side, the closed component's gauge
        // fixed by one pinned cell, then both solutions centered there.
        let mut b: Vec<f64> = (0..g.count())
            .map(|i| {
                if g.fluid[i] {
                    (i as f64 * 0.37).sin()
                } else {
                    0.0
                }
            })
            .collect();
        let closed = g.anchored.iter().position(|a| !*a).unwrap();
        let members = &g.components[closed];
        let mean = members.iter().map(|i| b[*i]).sum::<f64>() / members.len() as f64;
        members.iter().for_each(|i| b[*i] -= mean);
        let (x, info) = pressure::solve(&g, &b, 1e-14, 5000, &Control::new(20.0)).unwrap();
        assert!(
            info.relative_residual <= 1e-13,
            "{}",
            info.relative_residual
        );
        let pin = row[&members[0]];
        let mut ar = a.clone();
        ar[pin] = vec![0.0; m];
        ar[pin][pin] = 1.0;
        let mut br: Vec<f64> = fluid.iter().map(|i| b[*i]).collect();
        br[pin] = 0.0;
        let mut reference = dense_solve(ar, br);
        let rmean = members.iter().map(|i| reference[row[i]]).sum::<f64>() / members.len() as f64;
        members.iter().for_each(|i| reference[row[i]] -= rmean);
        let mut solved: Vec<f64> = fluid.iter().map(|i| x[*i]).collect();
        let smean = members.iter().map(|i| solved[row[i]]).sum::<f64>() / members.len() as f64;
        members.iter().for_each(|i| solved[row[i]] -= smean);
        let norm = reference.iter().map(|v| v * v).sum::<f64>().sqrt();
        let error = solved
            .iter()
            .zip(&reference)
            .map(|(a, b)| (a - b).powi(2))
            .sum::<f64>()
            .sqrt();
        assert!(
            error <= 1e-10 * norm,
            "periodic_y {periodic_y}: {error} vs {norm}"
        );
    }
}

#[test]
fn cancellation_inside_pressure_preserves_the_entire_step_and_history() {
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    let mut c = canyon();
    c.grid.cells = [18, 16, 12];
    let g = Grid::build(&c).unwrap();
    let mut state = solver::initial_state(&c, &g);
    state.monitor_history = vec![vec![1.25, 2.5], vec![3.75, 5.0]];
    let before = serde_json::to_vec(&state).unwrap();
    let sources = cfd_craft::transport::source_fields(&c, &g).unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = calls.clone();
    let control = Control::with_poll(20.0, move || {
        if observed.fetch_add(1, Ordering::SeqCst) == 0 {
            Ok(())
        } else {
            Err("cancelled".into())
        }
    });
    let error = solver::step(&c, &g, &mut state, &sources, 0.001, &control).unwrap_err();
    assert_eq!(error, "cancelled");
    assert!(calls.load(Ordering::SeqCst) >= 2);
    assert_eq!(serde_json::to_vec(&state).unwrap(), before);
}

#[test]
fn invalid_history_is_checked_without_moving_it_out_of_a_failed_step() {
    let mut c = tracer();
    c.grid.cells = [8, 4, 4];
    let g = Grid::build(&c).unwrap();
    let mut state = solver::initial_state(&c, &g);
    state.monitor_history = vec![vec![f64::NAN]];
    let before = serde_json::to_vec(&state).unwrap();
    let bits = state.monitor_history[0][0].to_bits();
    let sources = cfd_craft::transport::source_fields(&c, &g).unwrap();
    let error = solver::step(&c, &g, &mut state, &sources, 0.001, &Control::new(20.0)).unwrap_err();
    assert!(error.contains("CFD-E051"));
    assert_eq!(state.monitor_history[0][0].to_bits(), bits);
    assert_eq!(serde_json::to_vec(&state).unwrap(), before);
}

#[test]
fn a_late_positivity_failure_preserves_history_and_all_state_fields() {
    let mut c = tracer();
    c.grid.cells = [8, 4, 4];
    c.numerics.transport = Advection::LinearUpwind;
    let g = Grid::build(&c).unwrap();
    let mut state = solver::initial_state(&c, &g);
    state.concentrations[0].fill(0.0);
    state.concentrations[0][0] = 1.0;
    state.monitor_history = vec![vec![1.25, 2.5]];
    let before = serde_json::to_vec(&state).unwrap();
    let sources = vec![vec![0.0; g.count()]];
    let error =
        solver::step(&c, &g, &mut state, &sources, 1000.0, &Control::new(20.0)).unwrap_err();
    assert!(error.contains("CFD-E053"), "{error}");
    assert_eq!(serde_json::to_vec(&state).unwrap(), before);
}

#[test]
fn a_successful_step_keeps_history_and_unsupplied_constituents() {
    let mut c = tracer();
    c.grid.cells = [8, 4, 4];
    let g = Grid::build(&c).unwrap();
    let mut state = solver::initial_state(&c, &g);
    state.monitor_history = vec![vec![1.25, 2.5]];
    let concentrations = state.concentrations.clone();
    let history = state.monitor_history.clone();
    solver::step(&c, &g, &mut state, &[], 0.001, &Control::new(20.0)).unwrap();
    assert_eq!(state.concentrations, concentrations);
    assert_eq!(state.monitor_history, history);
    assert_eq!(state.steps, 1);
}

// Bit patterns of the RANS stencils, recorded from the merged implementation before
// the neighbor lookups were shared. The fields are perturbed so that every
// gradient, cross-stress and wall branch carries a distinct value; a change to
// the arithmetic or to the neighbor/face selection changes the signature.
fn stencil_signature(c: &Case) -> String {
    let g = Grid::build(c).unwrap();
    let s = solver::initial_state(c, &g);
    let mut u: Vec<f64> = s
        .velocity
        .iter()
        .enumerate()
        .map(|(i, v)| v + 0.05 * (0.37 * i as f64).sin())
        .collect();
    g.enforce_velocity(c, &mut u);
    let wave = |values: &[f64], w: f64| -> Vec<f64> {
        values
            .iter()
            .enumerate()
            .map(|(i, v)| v * (1.0 + 0.3 * (w * i as f64).cos()))
            .collect()
    };
    let k = wave(&s.k, 0.11);
    let eps = wave(&s.epsilon, 0.23);
    let nut = flow::eddy_viscosity(&g, &k, &eps);
    let momentum = flow::momentum_rhs(c, &g, &u, &nut);
    let (production, walls) = flow::production(c, &g, &u, &nut, &k);
    let (mut k2, mut eps2) = (k.clone(), eps.clone());
    let floors = flow::turbulence_step(c, &g, &u, &mut k2, &mut eps2, 1e-3);
    let mut bytes = Vec::new();
    for values in [&momentum, &production, &k2, &eps2] {
        bytes.extend(values.len().to_le_bytes());
        for v in values {
            bytes.extend(v.to_bits().to_le_bytes());
        }
    }
    for wall in &walls {
        bytes.extend(wall.map_or(u64::MAX, f64::to_bits).to_le_bytes());
    }
    bytes.extend(floors.to_le_bytes());
    assert!(walls.iter().any(Option::is_some) && production.iter().any(|v| *v != 0.0));
    hash_bytes(&bytes)
}

#[test]
fn rans_stencils_keep_their_recorded_bits() {
    let mut open = canyon();
    open.grid.cells = [18, 6, 12];
    let mut periodic = canyon();
    periodic.grid.cells = [18, 2, 12];
    periodic.boundaries.y = Boundary::Periodic;
    // Recorded from 402a150 with this function; update only with a reviewed
    // change to the RANS discretization.
    for (c, expected) in [
        (
            open,
            "e00ac47243809ffee7c118e3d96bb4fbca6a3b95c5ecc394361f3c31f9ea1e8d",
        ),
        (
            periodic,
            "bf8f2cb8552595b9d8c1829251bda9cf5767e173262daeb5776884107bd578df",
        ),
    ] {
        assert_eq!(stencil_signature(&c), expected);
    }
}

#[test]
fn a_step_advances_the_counters_it_was_given() {
    let c = canyon();
    let g = Grid::build(&c).unwrap();
    let sources = cfd_craft::transport::source_fields(&c, &g).unwrap();
    let fresh = solver::initial_state(&c, &g);
    let nut = flow::eddy_viscosity(&g, &fresh.k, &fresh.epsilon);
    let dt = solver::timestep(&c, &g, &fresh, &nut);
    let mut first = fresh.clone();
    solver::step(&c, &g, &mut first, &sources, dt, &Control::new(60.0)).unwrap();
    // The counters do not influence the fields, so a continued state adds the same work.
    let mut continued = fresh;
    continued.steps = 5;
    continued.time_s = 2.5;
    continued.pressure_iterations = 7;
    continued.floor_events = 3;
    solver::step(&c, &g, &mut continued, &sources, dt, &Control::new(60.0)).unwrap();
    assert!(first.pressure_iterations > 0);
    assert_eq!(continued.steps, 6);
    assert_eq!(continued.time_s, 2.5 + dt);
    assert_eq!(continued.pressure_iterations, 7 + first.pressure_iterations);
    assert_eq!(continued.floor_events, 3 + first.floor_events);
    assert_eq!(continued.velocity, first.velocity);
    assert_eq!(continued.concentrations, first.concentrations);
}

#[test]
fn the_memory_estimate_includes_the_pressure_workspace() {
    // At one million cells the per-cell workspace of the pressure solve (about
    // 130 MiB here) separates the estimate from an 1100 MiB allowance.
    let mut c = tracer();
    c.grid.cells = [100, 100, 100];
    for (limit, rejected) in [(1100, true), (1250, false)] {
        c.run.memory_limit_mib = limit;
        let rejected_now = codes(&c).iter().any(|(code, _)| code == "CFD-E006");
        assert_eq!(rejected_now, rejected, "{limit} MiB");
    }
}
