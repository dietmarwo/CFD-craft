//! Regression tests for defects found in review of 0.1.0.
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
