//! Stage V: test the unchanged production donor-cell operator, not a model of it.
use cfd_craft::{case::*, flow, grid::Grid};
use std::f64::consts::TAU;

const PHASES: [[f64; 2]; 8] = [
    [0.137, 0.271],
    [0.419, 1.103],
    [1.337, 0.593],
    [2.017, 1.771],
    [2.693, 2.291],
    [3.349, 0.887],
    [4.123, 3.517],
    [5.071, 4.237],
];

fn periodic(n: usize) -> Case {
    let mut c: Case =
        serde_json::from_str(include_str!("../../../cases/verification/poiseuille.json")).unwrap();
    c.grid.cells = [n, 2, n];
    c.boundaries.z = Boundary::Periodic;
    c.run.threads = 1;
    c
}

// Test-only entry point: isolate advection without changing the production loop
// that interleaves advection and viscosity. Build the valid grid before calling.
fn advection(c: &Case, g: &Grid, velocity: &[f64]) -> Vec<f64> {
    let mut inviscid = c.clone();
    if let Flow::Laminar {
        viscosity_m2_s,
        acceleration_m_s2,
        ..
    } = &mut inviscid.flow
    {
        *viscosity_m2_s = 0.0;
        *acceleration_m_s2 = [0.0; 3];
    } else {
        panic!("laminar fixture required");
    }
    flow::momentum_rhs(&inviscid, g, velocity, &vec![0.0; g.count()])
}

fn slope(errors: &[f64]) -> f64 {
    let x: Vec<_> = [32.0_f64, 64.0, 128.0, 256.0]
        .map(|n| (1.0 / n).ln())
        .to_vec();
    let y: Vec<_> = errors.iter().map(|e| e.ln()).collect();
    let xm = x.iter().sum::<f64>() / 4.0;
    let ym = y.iter().sum::<f64>() / 4.0;
    x.iter()
        .zip(&y)
        .map(|(x, y)| (x - xm) * (y - ym))
        .sum::<f64>()
        / x.iter().map(|x| (x - xm).powi(2)).sum::<f64>()
}

#[test]
fn donor_cell_operator_is_first_order_at_eight_phases() {
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(1)
        .build()
        .unwrap();
    pool.install(|| {
        let mut l1_orders = vec![];
        for phase in PHASES {
            let mut norms = vec![];
            for n in [32, 64, 128, 256] {
                let c = periodic(n);
                let g = Grid::build(&c).unwrap();
                let velocity: Vec<_> = g
                    .faces
                    .iter()
                    .map(|f| {
                        let x = TAU * f.center[0] + phase[0];
                        let z = TAU * f.center[2] + phase[1];
                        match f.axis {
                            0 => x.sin() * z.cos(),
                            2 => -x.cos() * z.sin(),
                            _ => 0.0,
                        }
                    })
                    .collect();
                let rhs = advection(&c, &g, &velocity);
                let mut errors = vec![];
                for (f, value) in g.faces.iter().zip(rhs) {
                    if f.axis == 1 {
                        continue;
                    }
                    let angle = TAU * f.center[f.axis] + phase[usize::from(f.axis == 2)];
                    let exact = -0.5 * TAU * (2.0 * angle).sin();
                    errors.push((value - exact).abs());
                }
                let count = errors.len() as f64;
                let norm = [
                    errors.iter().sum::<f64>() / count,
                    (errors.iter().map(|v| v * v).sum::<f64>() / count).sqrt(),
                    errors.iter().copied().fold(0.0, f64::max),
                ];
                assert!(norm.iter().all(|e| e.is_finite() && *e > 0.0));
                norms.push(norm);
            }
            let orders: Vec<_> = (0..3)
                .map(|a| slope(&norms.iter().map(|n| n[a]).collect::<Vec<_>>()))
                .collect();
            l1_orders.push(orders[0]);
            println!(
                "MOMENTUM_OPERATOR_BASELINE {}",
                serde_json::json!({
                    "phase": phase, "grids": [32,64,128,256], "norms_l1_l2_linf": norms,
                    "orders_l1_l2_linf": orders
                })
            );
        }
        let mean = l1_orders.iter().sum::<f64>() / 8.0;
        assert!(
            (0.8..1.2).contains(&mean),
            "donor-cell mean L1 order {mean}"
        );
    });
}

#[test]
fn a_solid_barrier_insulates_near_side_momentum() {
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(1)
        .build()
        .unwrap();
    pool.install(|| {
        let mut c = periodic(16);
        c.geometry.push(Block {
            id: "barrier".into(),
            min_m: [0.5, 0.0, 0.0],
            max_m: [0.625, 1.0, 1.0],
        });
        let g = Grid::build(&c).unwrap();
        let mut u: Vec<_> = g.faces.iter().map(|f| (TAU * f.center[2]).sin()).collect();
        g.enforce_velocity(&c, &mut u);
        let reference = advection(&c, &g, &u);
        let mut far = u.clone();
        for (f, value) in g.faces.iter().zip(&mut far) {
            if f.center[0] > 0.625 && f.center[0] < 0.875 {
                *value += 0.731;
            }
        }
        g.enforce_velocity(&c, &mut far);
        let changed = advection(&c, &g, &far);
        let near: Vec<_> = g
            .faces
            .iter()
            .enumerate()
            .filter(|(_, f)| f.center[0] >= 0.375 && f.center[0] < 0.5)
            .map(|(i, _)| i)
            .collect();
        assert!(!near.is_empty());
        assert!(
            near.iter()
                .all(|&i| reference[i].to_bits() == changed[i].to_bits())
        );
        let mut local = u.clone();
        local[near[0]] += 0.731;
        let local_rhs = advection(&c, &g, &local);
        assert!(
            near.iter()
                .any(|&i| reference[i].to_bits() != local_rhs[i].to_bits())
        );
    });
}
