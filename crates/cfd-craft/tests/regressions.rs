//! Regression tests for defects found in review of 0.1.0.
use cfd_craft::{
    case::*,
    flow,
    grid::{FaceKind, Grid},
    pressure, solver,
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
    assert!(
        d.iter()
            .any(|(code, path)| code == "CFD-W003" && path == "domain.size_m")
    );
    assert!(
        !d.iter()
            .any(|(code, path)| code == "CFD-W003" && path == "domain.size_m[2]")
    );
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
