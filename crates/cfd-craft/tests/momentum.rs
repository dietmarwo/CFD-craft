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

// ---- Stage P3a: second-order flux-form momentum advection ----

const SCHEMES: [(&str, MomentumAdvection, Option<MomentumLimiter>); 4] = [
    (
        "second_order_upwind",
        MomentumAdvection::SecondOrderUpwind,
        None,
    ),
    (
        "van_albada",
        MomentumAdvection::LimitedUpwind,
        Some(MomentumLimiter::VanAlbada),
    ),
    (
        "van_leer",
        MomentumAdvection::LimitedUpwind,
        Some(MomentumLimiter::VanLeer),
    ),
    (
        "monotonized_central",
        MomentumAdvection::LimitedUpwind,
        Some(MomentumLimiter::MonotonizedCentral),
    ),
];

fn with_scheme(mut c: Case, scheme: MomentumAdvection, limiter: Option<MomentumLimiter>) -> Case {
    c.numerics.momentum_advection = scheme;
    c.numerics.momentum_limiter = limiter;
    assert!(c.validate().is_ok(), "{:?}", c.check().diagnostics);
    c
}

fn vortex(g: &Grid, phase: [f64; 2]) -> Vec<f64> {
    g.faces
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
        .collect()
}

#[test]
fn second_order_schemes_meet_the_predeclared_operator_orders() {
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(1)
        .build()
        .unwrap();
    pool.install(|| {
        for (name, scheme, limiter) in SCHEMES {
            let mut per_phase = vec![];
            for phase in PHASES {
                let mut norms = vec![];
                for n in [32, 64, 128, 256] {
                    let c = with_scheme(periodic(n), scheme, limiter);
                    let g = Grid::build(&c).unwrap();
                    let rhs = advection(&c, &g, &vortex(&g, phase));
                    let errors: Vec<_> = g
                        .faces
                        .iter()
                        .zip(rhs)
                        .filter(|(f, _)| f.axis != 1)
                        .map(|(f, value)| {
                            let angle = TAU * f.center[f.axis] + phase[usize::from(f.axis == 2)];
                            (value + 0.5 * TAU * (2.0 * angle).sin()).abs()
                        })
                        .collect();
                    let count = errors.len() as f64;
                    norms.push([
                        errors.iter().sum::<f64>() / count,
                        (errors.iter().map(|v| v * v).sum::<f64>() / count).sqrt(),
                        errors.iter().copied().fold(0.0, f64::max),
                    ]);
                }
                let orders: Vec<_> = (0..3)
                    .map(|k| slope(&norms.iter().map(|n| n[k]).collect::<Vec<_>>()))
                    .collect();
                println!(
                    "MOMENTUM_OPERATOR_P3A {}",
                    serde_json::json!({"scheme": name, "phase": phase, "norms_l1_l2_linf": norms,
                        "orders_l1_l2_linf": orders})
                );
                per_phase.push(orders);
            }
            let l1: Vec<_> = per_phase.iter().map(|o| o[0]).collect();
            let mean = l1.iter().sum::<f64>() / l1.len() as f64;
            let min = l1.iter().copied().fold(f64::INFINITY, f64::min);
            if scheme == MomentumAdvection::SecondOrderUpwind {
                // Predeclared: every phase >= 1.9 in L1, L2 and max norm.
                for orders in &per_phase {
                    assert!(orders.iter().all(|o| *o >= 1.9), "{name}: {orders:?}");
                }
            } else {
                // Predeclared: mean L1 >= 1.8 and every phase >= 1.6.
                assert!(mean >= 1.8 && min >= 1.6, "{name}: mean {mean}, min {min}");
            }
        }
    });
}

// Momentum of every component is conserved to round-off in a periodic box,
// for any (not necessarily divergence-free) field, because each control-volume
// face carries one flux shared by its two momentum cells.
#[test]
fn flux_form_advection_conserves_periodic_momentum() {
    let c = periodic(12);
    let g = Grid::build(&c).unwrap();
    let u: Vec<_> = (0..g.faces.len())
        .map(|i| (0.37 * i as f64).sin() + 0.3 * (1.3 * i as f64).cos())
        .collect();
    for reconstruction in [
        flow::Reconstruction::FirstOrder,
        flow::Reconstruction::SecondOrder,
        flow::Reconstruction::VanAlbada,
        flow::Reconstruction::VanLeer,
        flow::Reconstruction::MonotonizedCentral,
    ] {
        let rhs = flow::flux_form_advection(&c, &g, &u, &vec![0.0; g.count()], reconstruction);
        for axis in 0..3 {
            let (sum, scale) = g
                .faces
                .iter()
                .zip(&rhs)
                .filter(|(f, _)| f.axis == axis)
                .fold((0.0, 0.0), |(s, a), (_, r)| (s + r, a + r.abs()));
            assert!(
                sum.abs() <= 1e-13 * scale.max(1.0),
                "{reconstruction:?} axis {axis}: {sum} of {scale}"
            );
        }
    }
}

// An independent fully periodic implementation with plain array indexing.
fn periodic_reference(
    n: [usize; 3],
    h: [f64; 3],
    u: &[Vec<f64>; 3],
    reconstruction: flow::Reconstruction,
) -> [Vec<f64>; 3] {
    let idx = |p: [isize; 3]| -> usize {
        let w: [usize; 3] = std::array::from_fn(|k| p[k].rem_euclid(n[k] as isize) as usize);
        (w[2] * n[1] + w[1]) * n[0] + w[0]
    };
    let unit = |k: usize, s: isize| -> [isize; 3] {
        let mut e = [0; 3];
        e[k] = s;
        e
    };
    let add = |p: [isize; 3], e: [isize; 3]| -> [isize; 3] { std::array::from_fn(|k| p[k] + e[k]) };
    let face_value = |phi_u: f64, phi_uu: f64, phi_d: f64| {
        phi_u + 0.5 * reconstruction.slope(phi_u - phi_uu, phi_d - phi_u)
    };
    // u[a][idx(p)]: velocity on the a-face at the low side of cell p.
    std::array::from_fn(|a| {
        let mut out = vec![0.0; n.iter().product()];
        for k in 0..n[2] as isize {
            for j in 0..n[1] as isize {
                for i in 0..n[0] as isize {
                    let p = [i, j, k];
                    let mut total = 0.0;
                    for d in 0..3 {
                        // Flux at the CV face above sample p (in d).
                        let flux = |p: [isize; 3]| -> f64 {
                            let ua = |q: [isize; 3]| u[a][idx(q)];
                            if d == a {
                                // cell p: faces p (low) and p + e_a (high)
                                let adv = 0.5 * (ua(p) + ua(add(p, unit(a, 1))));
                                let (up, down, far) = if adv >= 0.0 {
                                    (p, add(p, unit(a, 1)), add(p, unit(a, -1)))
                                } else {
                                    (add(p, unit(a, 1)), p, add(p, unit(a, 2)))
                                };
                                adv * face_value(ua(up), ua(far), ua(down))
                            } else {
                                let ud = |q: [isize; 3]| u[d][idx(q)];
                                let top = add(p, unit(d, 1));
                                let adv = 0.5 * (ud(top) + ud(add(top, unit(a, -1))));
                                let (up, down, far) = if adv >= 0.0 {
                                    (p, top, add(p, unit(d, -1)))
                                } else {
                                    (top, p, add(p, unit(d, 2)))
                                };
                                adv * face_value(ua(up), ua(far), ua(down))
                            }
                        };
                        let low = if d == a {
                            flux(add(p, unit(a, -1)))
                        } else {
                            flux(add(p, unit(d, -1)))
                        };
                        total -= (flux(p) - low) / h[d];
                    }
                    out[idx(p)] = total;
                }
            }
        }
        out
    })
}

#[test]
fn flux_form_matches_an_independent_periodic_reference() {
    let mut c = periodic(6);
    c.grid.cells = [6, 5, 7];
    c.domain.size_m = [1.3, 0.7, 1.9];
    c.boundaries.x = Boundary::Periodic;
    c.boundaries.y = Boundary::Periodic;
    let g = Grid::build(&c).unwrap();
    let u: Vec<_> = (0..g.faces.len())
        .map(|i| (0.61 * i as f64).sin() - 0.2 + 0.4 * (2.3 * i as f64).cos())
        .collect();
    let n = g.n;
    let split: [Vec<f64>; 3] = std::array::from_fn(|a| {
        let mut out = vec![0.0; n.iter().product()];
        for (f, v) in g.faces.iter().zip(&u) {
            if f.axis == a {
                out[Grid::index(n, f.coord)] = *v;
            }
        }
        out
    });
    for reconstruction in [
        flow::Reconstruction::FirstOrder,
        flow::Reconstruction::SecondOrder,
        flow::Reconstruction::VanAlbada,
        flow::Reconstruction::VanLeer,
        flow::Reconstruction::MonotonizedCentral,
    ] {
        let rhs = flow::flux_form_advection(&c, &g, &u, &vec![0.0; g.count()], reconstruction);
        let expected = periodic_reference(n, g.dx, &split, reconstruction);
        for (f, value) in g.faces.iter().zip(&rhs) {
            let reference = expected[f.axis][Grid::index(n, f.coord)];
            assert!(
                (value - reference).abs() <= 1e-12 * reference.abs().max(1.0),
                "{reconstruction:?} face {:?} axis {}: {value} vs {reference}",
                f.coord,
                f.axis
            );
        }
    }
}

#[test]
fn second_order_schemes_keep_a_solid_barrier_insulating() {
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(1)
        .build()
        .unwrap();
    pool.install(|| {
        for (name, scheme, limiter) in SCHEMES {
            let mut c = with_scheme(periodic(16), scheme, limiter);
            c.geometry.push(Block {
                id: "barrier".into(),
                min_m: [0.5, 0.0, 0.0],
                max_m: [0.625, 1.0, 1.0],
            });
            let g = Grid::build(&c).unwrap();
            let mut u: Vec<_> = g
                .faces
                .iter()
                .map(|f| (TAU * f.center[2]).sin() + 0.3)
                .collect();
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
            assert!(
                near.iter()
                    .all(|&i| reference[i].to_bits() == changed[i].to_bits()),
                "{name}"
            );
            let mut local = u.clone();
            local[near[0]] += 0.731;
            let local_rhs = advection(&c, &g, &local);
            assert!(
                near.iter()
                    .any(|&i| reference[i].to_bits() != local_rhs[i].to_bits()),
                "{name}: sensitivity control"
            );
        }
    });
}

// A shear flow u(z) has no advective contribution in any scheme.
#[test]
fn shear_flows_have_no_advective_contribution() {
    for name in ["poiseuille.json", "couette.json"] {
        let path = format!(
            "{}/../../cases/verification/{name}",
            env!("CARGO_MANIFEST_DIR")
        );
        let base: Case = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        let g = Grid::build(&base).unwrap();
        let mut u: Vec<_> = g
            .faces
            .iter()
            .map(|f| {
                if f.axis == 0 {
                    (3.0 * f.center[2]).sin()
                } else {
                    0.0
                }
            })
            .collect();
        g.enforce_velocity(&base, &mut u);
        let donor = flow::momentum_rhs(&base, &g, &u, &vec![0.0; g.count()]);
        for (scheme_name, scheme, limiter) in SCHEMES {
            let c = with_scheme(base.clone(), scheme, limiter);
            let adv = advection(&c, &g, &u);
            assert!(adv.iter().all(|v| *v == 0.0), "{name} {scheme_name}");
            let rhs = flow::momentum_rhs(&c, &g, &u, &vec![0.0; g.count()]);
            for (a, b) in rhs.iter().zip(&donor) {
                assert!(
                    (a - b).abs() <= 1e-14 * b.abs().max(1.0),
                    "{name} {scheme_name}"
                );
            }
        }
    }
}

#[test]
fn limiter_and_open_boundary_rules_are_coded_diagnostics() {
    let codes = |c: &Case| {
        c.check()
            .diagnostics
            .into_iter()
            .map(|d| (d.code, d.path))
            .collect::<Vec<_>>()
    };
    let mut c = periodic(8);
    c.numerics.momentum_advection = MomentumAdvection::LimitedUpwind;
    assert!(codes(&c).contains(&("CFD-E037".into(), "numerics.momentum_limiter".into())));
    c.numerics.momentum_advection = MomentumAdvection::SecondOrderUpwind;
    c.numerics.momentum_limiter = Some(MomentumLimiter::VanLeer);
    assert!(codes(&c).contains(&("CFD-E037".into(), "numerics.momentum_limiter".into())));
    c.numerics.momentum_limiter = None;
    assert!(codes(&c).is_empty(), "{:?}", codes(&c));
    c.boundaries.x = Boundary::Open;
    if let Flow::Laminar {
        initial_velocity_m_s,
        ..
    } = &mut c.flow
    {
        *initial_velocity_m_s = [1.0, 0.0, 0.0];
    }
    assert!(codes(&c).contains(&("CFD-E038".into(), "numerics.momentum_advection".into())));
    let path = format!(
        "{}/../../cases/verification/empty-abl.json",
        env!("CARGO_MANIFEST_DIR")
    );
    let mut rans: Case = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    rans.numerics.momentum_advection = MomentumAdvection::SecondOrderUpwind;
    assert!(codes(&rans).contains(&("CFD-E039".into(), "numerics.momentum_advection".into())));
    // Defaults are not serialized, so existing case hashes are unchanged.
    let text = serde_json::to_string(&periodic(8)).unwrap();
    assert!(!text.contains("momentum_advection") && !text.contains("momentum_limiter"));
}

#[test]
fn a_second_order_cavity_restarts_bit_for_bit() {
    use cfd_craft::solver::{Control, run};
    let path = format!(
        "{}/../../cases/verification/lid-cavity.json",
        env!("CARGO_MANIFEST_DIR")
    );
    let base: Case = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    for (name, scheme, limiter) in SCHEMES {
        let mut c = with_scheme(base.clone(), scheme, limiter);
        c.grid.cells = [12, 2, 12];
        c.run.mode = Mode::Steady;
        c.run.threads = 1;
        c.run.max_steps = 6;
        let whole = run(&c, &Control::new(60.0), None).unwrap().state;
        c.run.max_steps = 3;
        let first = run(&c, &Control::new(60.0), None).unwrap().state;
        c.run.max_steps = 6;
        let resumed = run(&c, &Control::new(60.0), Some(first)).unwrap().state;
        assert_eq!(whole.steps, 6);
        let bits = |v: &[f64]| v.iter().map(|x| x.to_bits()).collect::<Vec<_>>();
        assert_eq!(bits(&whole.velocity), bits(&resumed.velocity), "{name}");
        assert_eq!(bits(&whole.pressure), bits(&resumed.pressure), "{name}");
    }
}
