//! Independent mask, pressure and projection controls for U1/U3.
use cfd_craft::{
    case::*,
    grid::{FaceKind, Grid},
    pressure,
    solver::Control,
};
fn case() -> Case {
    let mut c: Case =
        serde_json::from_str(include_str!("../../../cases/verification/lid-cavity.json")).unwrap();
    c.grid.cells = [12, 4, 10];
    c.domain.size_m = [12., 4., 10.];
    c.moving_walls.clear();
    c.numerics.pressure_preconditioner = PressurePreconditioner::Multigrid;
    c
}
fn block(id: &str, lo: [f64; 3], hi: [f64; 3]) -> Block {
    Block {
        id: id.into(),
        min_m: lo,
        max_m: hi,
        footprint_m: None,
    }
}
#[test]
fn polygon_prisms_reproduce_boxes_and_ninety_degree_rotation() {
    let mut c = case();
    c.geometry = vec![block("p", [3., 1., 0.], [7., 3., 6.])];
    let g = Grid::build(&c).unwrap();
    let hash = c.physics_hash();
    c.geometry[0].footprint_m = Some(vec![[3., 1.], [7., 1.], [7., 3.], [3., 3.]]);
    assert_eq!(g.fluid, Grid::build(&c).unwrap().fluid);
    assert_ne!(hash, c.physics_hash());
    c.geometry[0].footprint_m.as_mut().unwrap().rotate_left(1);
    assert_eq!(g.fluid, Grid::build(&c).unwrap().fluid);
    // Actual 90-degree spatial rotation about (5,2), compared to its box.
    let mut rotated = case();
    rotated.geometry = vec![block("rotated", [4., 0., 0.], [6., 4., 6.])];
    let equivalent_box = Grid::build(&rotated).unwrap();
    rotated.geometry[0].footprint_m = Some(vec![[6., 0.], [6., 4.], [4., 4.], [4., 0.]]);
    assert_eq!(equivalent_box.fluid, Grid::build(&rotated).unwrap().fluid);
    assert_eq!(c.geometry[0].volume(), 48.);
    assert_eq!(
        Grid::mask_topology(&c).unwrap().solid_cells,
        g.evidence().solid_cells
    );
}
#[test]
fn pressure_gauges_masked_barriers_pockets_outlets_and_thin_passages() {
    for open in [false, true] {
        for passage in [false, true] {
            let mut c = case();
            c.boundaries.x = if open { Boundary::Open } else { Boundary::Wall };
            if let Flow::Laminar {
                initial_velocity_m_s,
                ..
            } = &mut c.flow
            {
                *initial_velocity_m_s = [1., 0., 0.];
            }
            c.geometry = vec![block(
                "barrier",
                [5., 0., 0.],
                [6., 4., if passage { 9. } else { 10. }],
            )];
            let g = Grid::build(&c).unwrap();
            assert_eq!(g.components.len(), if passage { 1 } else { 2 });
            let mut exact: Vec<_> = (0..g.count())
                .map(|i| {
                    if g.fluid[i] {
                        (0.37 * i as f64).sin()
                    } else {
                        0.
                    }
                })
                .collect();
            pressure::center_nullspaces(&g, &mut exact);
            // RHS from the independent grid divergence/gradient, not pressure::apply.
            let rhs: Vec<_> = g
                .divergence(&g.gradient(&exact))
                .iter()
                .map(|v| -v)
                .collect();
            let (p, info) = pressure::solve(&g, &rhs, 1e-12, 1200, &Control::new(20.)).unwrap();
            assert!(info.relative_residual <= 1.1e-11);
            assert!(p.iter().zip(&exact).all(|(a, b)| (a - b).abs() < 1e-8));
            let mut u = g.gradient(&exact);
            let mut pp = vec![0.; g.count()];
            pressure::project(&g, &mut u, &mut pp, 0.1, 1e-12, 1200, &Control::new(20.)).unwrap();
            assert!(u.iter().all(|v| v.abs() < 1e-8));
            // IC0 solves the same equation with componentwise gauges.
            c.numerics.pressure_preconditioner = PressurePreconditioner::Ic0;
            let old = Grid::build(&c).unwrap();
            let (q, _) = pressure::solve(&old, &rhs, 1e-12, 1200, &Control::new(20.)).unwrap();
            assert!(p.iter().zip(q).all(|(a, b)| (a - b).abs() < 1e-8));
            if !passage && !open {
                let mut bad = rhs.clone();
                let i = g.components[0][0];
                bad[i] += 1.;
                assert!(
                    pressure::solve(&g, &bad, 1e-12, 1200, &Control::new(20.))
                        .unwrap_err()
                        .contains("CFD-E031")
                );
            }
        }
    }
}
#[test]
fn underresolved_passages_and_invalid_polygons_have_coded_paths() {
    let mut c = case();
    c.geometry = vec![
        block("left", [2., 0., 0.], [4., 4., 6.]),
        block("right", [5., 0., 0.], [7., 4., 6.]),
    ];
    c.geometry_min_passage_cells = Some(3);
    assert!(
        c.check()
            .diagnostics
            .iter()
            .any(|d| d.code == "CFD-W011" && d.path == "geometry_min_passage_cells")
    );
    // The scan is bounded at ten million cells. A request above that bound is
    // reported as not evaluated; it does not pass silently.
    let mut large = c.clone();
    large.grid.cells = [360, 240, 120];
    let warnings: Vec<_> = large
        .check()
        .diagnostics
        .into_iter()
        .filter(|d| d.code == "CFD-W011")
        .collect();
    assert_eq!(warnings.len(), 1);
    assert_eq!(warnings[0].path, "geometry_min_passage_cells");
    assert!(warnings[0].message.contains("not evaluated"));
    large.geometry.clear();
    assert!(
        large
            .check()
            .diagnostics
            .iter()
            .all(|d| d.code != "CFD-W011")
    );
    c.geometry[0].footprint_m = Some(vec![[2., 0.], [4., 4.], [2., 4.], [4., 0.]]);
    assert!(
        c.check()
            .diagnostics
            .iter()
            .any(|d| d.code == "CFD-E084" && d.path == "geometry[0].footprint_m")
    );
}
#[test]
fn masked_projection_respects_all_solid_faces() {
    let mut c = case();
    c.geometry = vec![block("obstacle", [4., 1., 2.], [8., 3., 6.])];
    let g = Grid::build(&c).unwrap();
    let mut u: Vec<_> = g
        .faces
        .iter()
        .enumerate()
        .map(|(i, f)| {
            if f.kind == FaceKind::Interior {
                (i as f64 * 0.17).sin()
            } else {
                0.
            }
        })
        .collect();
    let mut p = vec![0.; g.count()];
    pressure::project(&g, &mut u, &mut p, 1., 1e-12, 2000, &Control::new(20.)).unwrap();
    assert!(g.divergence(&u).iter().all(|v| v.abs() < 1e-9));
    assert!(
        g.faces
            .iter()
            .zip(u)
            .all(|(f, v)| f.kind != FaceKind::Wall || v == 0.)
    );
}

#[test]
fn declared_building_roughness_leaves_the_empty_abl_terms_identical() {
    use cfd_craft::{flow, solver};
    let mut c: Case =
        serde_json::from_str(include_str!("../../../cases/verification/empty-abl.json")).unwrap();
    for n in [[8, 2, 8], [16, 2, 16]] {
        c.grid.cells = n;
        let g = Grid::build(&c).unwrap();
        let initial = solver::initial_state(&c, &g);
        let nut = flow::eddy_viscosity(&g, &initial.k, &initial.epsilon);
        let before = flow::momentum_rhs(&c, &g, &initial.velocity, &nut);
        let before_p = flow::production(&c, &g, &initial.velocity, &nut, &initial.k);
        let hash = c.physics_hash();
        c.building_roughness_m = Some(0.003);
        assert_ne!(hash, c.physics_hash());
        let after = flow::momentum_rhs(&c, &g, &initial.velocity, &nut);
        assert_eq!(
            serde_json::to_vec(&before).unwrap(),
            serde_json::to_vec(&after).unwrap()
        );
        let after_p = flow::production(&c, &g, &initial.velocity, &nut, &initial.k);
        assert_eq!(
            serde_json::to_vec(&before_p).unwrap(),
            serde_json::to_vec(&after_p).unwrap()
        );
        c.building_roughness_m = None;
    }
}

#[test]
fn declared_building_roughness_enters_building_wall_functions_and_not_the_ground() {
    use cfd_craft::{flow, solver};
    // dx = [1, 1, 0.5] and flow.roughness_m = 0.01: the legacy recipe gives
    // z0 = min(0.01, 0.001 dx) = 0.001 on vertical building walls.
    let mut c: Case =
        serde_json::from_str(include_str!("../../../cases/canyon/wh1-wind225.json")).unwrap();
    let g = Grid::build(&c).unwrap();
    let s = solver::initial_state(&c, &g);
    let nut = flow::eddy_viscosity(&g, &s.k, &s.epsilon);
    // One wall face each: the west side of the west building above the ground
    // layer, and an open ground cell away from the buildings.
    let wall = Grid::index(g.n, [4, 8, 1]);
    let ground = Grid::index(g.n, [1, 1, 0]);
    let wall_faces = |i: usize| {
        (0..3)
            .flat_map(|d| (0..2).map(move |side| (d, side)))
            .filter(|(d, side)| g.faces[g.cell_faces[i][*d][*side]].kind == FaceKind::Wall)
            .collect::<Vec<_>>()
    };
    assert_eq!(wall_faces(wall), vec![(0, 1)]);
    assert_eq!(wall_faces(ground), vec![(2, 0)]);
    let (legacy_p, legacy_e) = flow::production(&c, &g, &s.velocity, &nut, &s.k);
    let legacy_rhs = flow::momentum_rhs(&c, &g, &s.velocity, &nut);
    assert!(legacy_p[wall] > 0.0);
    // Declaring the value the legacy recipe uses on this wall changes nothing there.
    c.building_roughness_m = Some(0.001);
    let (same_p, same_e) = flow::production(&c, &g, &s.velocity, &nut, &s.k);
    assert_eq!(same_p[wall].to_bits(), legacy_p[wall].to_bits());
    assert_eq!(same_e[wall], legacy_e[wall]);
    // A tenfold roughness follows the logarithmic wall law at the half-cell
    // distance: u*^2 ~ ln(d/z0)^-2 and both wall terms ~ 1/d, with d = dx/2 + z0.
    c.building_roughness_m = Some(0.01);
    let (p, e) = flow::production(&c, &g, &s.velocity, &nut, &s.k);
    let (old, new) = (0.5 + 0.001_f64, 0.5 + 0.01_f64);
    let stress = ((old / 0.001).ln() / (new / 0.01).ln()).powi(2);
    assert!((p[wall] / legacy_p[wall] - stress * old / new).abs() < 1e-12);
    assert!((e[wall].unwrap() / legacy_e[wall].unwrap() - old / new).abs() < 1e-12);
    assert_eq!(p[ground].to_bits(), legacy_p[ground].to_bits());
    assert_eq!(e[ground], legacy_e[ground]);
    // The same roughness reaches the momentum wall stress of that building face.
    let rhs = flow::momentum_rhs(&c, &g, &s.velocity, &nut);
    let changed = g
        .faces
        .iter()
        .enumerate()
        .filter(|(i, _)| rhs[*i] != legacy_rhs[*i])
        .count();
    assert!(changed > 0);
    let tangential = g.cell_faces[wall][1][0];
    assert_ne!(rhs[tangential], legacy_rhs[tangential]);
}
