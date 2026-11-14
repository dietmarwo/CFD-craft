//! Linear mobile-path sampling, analytic refinement and strict geometry support.
use cfd_craft::{
    case::{Block, Case, Flow, Receptor},
    grid::Grid,
    solver::{self, Control},
    transport,
};
use serde_json::json;
fn case(n: usize) -> Case {
    let mut c: Case = serde_json::from_str(include_str!(
        "../../../cases/verification/source-response.json"
    ))
    .unwrap();
    c.domain.size_m = [8.0, 8.0, 1.0];
    c.grid.cells = [n, n, 1];
    c.sources.clear();
    c.receptors.clear();
    c.run.threads = 1;
    c
}
fn route(points: Vec<[f64; 2]>, spacing: f64) -> Receptor {
    Receptor::Path {
        id: "ride".into(),
        polyline_m: points,
        height_m: 0.5,
        sample_spacing_m: spacing,
    }
}
fn sample(g: &Grid, r: &Receptor, values: &[f64]) -> Vec<f64> {
    transport::receptor_path_weights(g, r)
        .unwrap()
        .weights
        .iter()
        .map(|w| w.iter().map(|(i, a)| a * values[*i]).sum())
        .collect()
}
#[test]
fn path_sampling_of_analytic_gaussian_plume_converges_with_grid_refinement() {
    // Gaussian solution of the reduced constant-wind transverse diffusion
    // equation, used here to verify observation interpolation, not the solver's
    // longitudinal-diffusion approximation or atmospheric model.
    let plume = |p: [f64; 3]| {
        1e-6 / (4.0 * std::f64::consts::PI * 0.2 * p[0]).sqrt()
            * (-((p[1] - 4.0).powi(2)) / (4.0 * 0.2 * p[0])).exp()
    };
    let r = route(vec![[2.0, 2.5], [6.0, 5.5]], 0.1);
    let mut errors = vec![];
    for n in [16, 32, 64, 128] {
        let c = case(n);
        let g = Grid::build(&c).unwrap();
        let values: Vec<_> = (0..g.count()).map(|i| plume(g.center(i))).collect();
        let path = transport::receptor_path_weights(&g, &r).unwrap();
        let measured = sample(&g, &r, &values);
        let exact: Vec<_> = path.samples.points_m.iter().map(|p| plume(*p)).collect();
        let error = (measured
            .iter()
            .zip(&exact)
            .map(|(a, b)| (a - b).powi(2))
            .sum::<f64>()
            / exact.iter().map(|v| v * v).sum::<f64>())
        .sqrt();
        errors.push(error);
        for weights in &path.weights {
            assert!((weights.iter().map(|(_, w)| w).sum::<f64>() - 1.0).abs() < 1e-14);
        }
    }
    eprintln!("Gaussian-path relative RMS errors={errors:?}");
    assert!(errors[3] < 0.002);
    for pair in errors.windows(2) {
        assert!((pair[0] / pair[1]).log2() > 1.5);
    }
}
#[test]
fn short_path_mean_converges_to_a_thin_volume_average_around_it() {
    let mut errors = vec![];
    for n in [32, 64, 128] {
        let c = case(n);
        let g = Grid::build(&c).unwrap();
        let h = g.dx[0];
        let path = route(vec![[3.75, 4.0], [4.25, 4.0]], h / 4.0);
        let volume = Receptor::VolumeAverage {
            id: "thin".into(),
            min_m: [3.75, 4.0 - h / 2.0, 0.25],
            max_m: [4.25, 4.0 + h / 2.0, 0.75],
        };
        let values: Vec<_> = (0..g.count())
            .map(|i| {
                let p = g.center(i);
                1e-6 * (2.0 + p[0].sin() + 0.1 * p[1].cos())
            })
            .collect();
        let mean = |r: &Receptor| {
            transport::receptor_weights(&g, r)
                .unwrap()
                .iter()
                .map(|(i, w)| w * values[*i])
                .sum::<f64>()
        };
        errors.push((mean(&path) - mean(&volume)).abs() / mean(&volume));
    }
    eprintln!("short-path/thin-volume relative differences={errors:?}");
    assert!(errors[2] < 0.001);
    for pair in errors.windows(2) {
        assert!((pair[0] / pair[1]).log2() > 1.8);
    }
}
#[test]
fn reversing_a_path_reverses_samples_and_sampling_is_linear() {
    let c = case(32);
    let g = Grid::build(&c).unwrap();
    let points = vec![[1.0, 1.0], [3.0, 4.0], [6.0, 5.0]];
    let r = route(points.clone(), 0.2);
    let reverse = route(points.into_iter().rev().collect(), 0.2);
    let a: Vec<_> = (0..g.count()).map(|i| (0.13 * i as f64).sin()).collect();
    let b: Vec<_> = (0..g.count()).map(|i| (0.17 * i as f64).cos()).collect();
    let combined: Vec<_> = a.iter().zip(&b).map(|(a, b)| 2.0 * a + 3.0 * b).collect();
    let sa = sample(&g, &r, &a);
    let sb = sample(&g, &r, &b);
    let sc = sample(&g, &r, &combined);
    let sr = sample(&g, &reverse, &a);
    assert_eq!(sa.len(), sr.len());
    for (a, b) in sa.iter().zip(sr.iter().rev()) {
        assert!((a - b).abs() < 1e-13);
    }
    for ((a, b), combined) in sa.iter().zip(&sb).zip(&sc) {
        assert!((2.0 * a + 3.0 * b - combined).abs() < 1e-13);
    }
}
#[test]
fn whole_segments_and_through_wall_interpolation_are_rejected() {
    let mut c = case(16);
    c.flow = Flow::Laminar {
        initial_velocity_m_s: [0.0; 3],
        viscosity_m2_s: 0.01,
        acceleration_m_s2: [0.0; 3],
    };
    c.geometry = vec![Block {
        id: "thin-barrier".into(),
        min_m: [3.0, 0.0, 0.0],
        max_m: [3.5, 8.0, 1.0],
        footprint_m: None,
    }];
    let g = Grid::build(&c).unwrap();
    let crossing = route(vec![[1.0, 4.0], [7.0, 4.0]], 100.0);
    assert_eq!(
        transport::path_samples(&crossing).unwrap().points_m.len(),
        2
    );
    assert!(
        transport::receptor_weights(&g, &crossing)
            .unwrap_err()
            .contains("CFD-E087")
    );
    let near = route(vec![[2.8, 4.0], [2.9, 4.0]], 0.1);
    assert!(
        transport::receptor_weights(&g, &near)
            .unwrap_err()
            .contains("CFD-E087")
    );
    c.receptors = vec![crossing];
    let report = cfd_craft::input::full_check(&c).0;
    assert!(
        report
            .diagnostics
            .iter()
            .any(|d| d.code == "CFD-E087" && d.path == "receptors[0]")
    );
}
#[test]
fn paths_have_strict_schema_geometry_and_preallocation_sample_caps() {
    let mut c = case(16);
    c.receptors = vec![route(vec![[1.0, 1.0], [7.0, 1.0]], 1e-12)];
    assert!(
        c.check()
            .diagnostics
            .iter()
            .any(|d| d.code == "CFD-E088" && d.path == "receptors[0].sample_spacing_m")
    );
    let mut value = serde_json::to_value(&c).unwrap();
    value["receptors"][0]["sample_spacing_m"] = json!(1.0);
    value["receptors"][0]["polyline_m"] = json!([[1.0, 1.0], [1.0, 1.0]]);
    let invalid: Case = serde_json::from_value(value).unwrap();
    assert!(
        invalid
            .check()
            .diagnostics
            .iter()
            .any(|d| d.code == "CFD-E086")
    );
    let mut height = case(16);
    let mut invalid_height = route(vec![[1.0, 1.0], [2.0, 1.0]], 0.1);
    if let Receptor::Path { height_m, .. } = &mut invalid_height {
        *height_m = -1.0;
    }
    height.receptors = vec![invalid_height];
    assert!(
        height
            .check()
            .diagnostics
            .iter()
            .any(|d| d.code == "CFD-E086" && d.path == "receptors[0].height_m")
    );
    c.receptors = vec![route(vec![[1.0, 1.0], [7.0, 1.0]], 0.001); 9];
    for (i, r) in c.receptors.iter_mut().enumerate() {
        if let Receptor::Path { id, .. } = r {
            *id = format!("r{i}");
        }
    }
    assert!(
        c.check()
            .diagnostics
            .iter()
            .any(|d| d.code == "CFD-E088" && d.path == "receptors")
    );
}
#[test]
fn returned_path_samples_match_the_returned_field_and_receptor_mean() {
    let mut c: Case =
        serde_json::from_str(include_str!("../../../examples/manual/point-source.json")).unwrap();
    c.receptors.push(Receptor::Path {
        id: "ride".into(),
        polyline_m: vec![[2.0, 1.0], [6.0, 3.0]],
        height_m: 2.0,
        sample_spacing_m: 0.25,
    });
    let r = solver::run(&c, &Control::new(20.0), None).unwrap();
    assert_eq!(r.summary.assessment, "steady_discrete_solution");
    let evidence = &r.summary.constituents[0];
    let g = Grid::build(&c).unwrap();
    let expected = sample(&g, c.receptors.last().unwrap(), &r.state.concentrations[0]);
    assert_eq!(evidence.paths["ride"].concentrations_kg_m3, expected);
    assert_eq!(
        evidence.paths["ride"].mean_kg_m3,
        evidence.receptors_kg_m3["ride"]
    );
    let path = &evidence.paths["ride"];
    let n = path.concentrations_kg_m3.len() - 1;
    let quadrature = (path.concentrations_kg_m3.iter().sum::<f64>()
        - 0.5 * (path.concentrations_kg_m3[0] + path.concentrations_kg_m3[n]))
        / n as f64;
    assert!((quadrature - path.mean_kg_m3).abs() < 1e-20);
}
