// Temporary kernel timing harness (not committed).
use cfd_craft::{case::*, flow, grid::Grid, momentum_solve::Stencil, solver, transport};
use std::time::Instant;
fn main() {
    let path = std::env::args().nth(1).unwrap();
    let mut c: Case = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    c.numerics.steady_algorithm = SteadyAlgorithm::ImplicitProjection;
    c.run.threads = 1;
    rayon::ThreadPoolBuilder::new()
        .num_threads(1)
        .build_global()
        .unwrap();
    let g = Grid::build(&c).unwrap();
    let mut s = solver::initial_state(&c, &g);
    c.run.max_steps = 60;
    s = solver::run(&c, &solver::Control::new(60.0), Some(s))
        .unwrap()
        .state;
    let nut = flow::eddy_viscosity(&g, &s.k, &s.epsilon);
    let u = &s.velocity;
    let n = 200;
    let time = |name: &str, f: &mut dyn FnMut()| {
        f();
        let mut best = f64::INFINITY;
        for _ in 0..15 {
            let t = Instant::now();
            for _ in 0..n / 10 {
                f();
            }
            best = best.min(t.elapsed().as_secs_f64() / (n / 10) as f64);
        }
        println!("{name:28} {:8.1} us", best * 1e6);
    };
    time("momentum_rhs", &mut || {
        std::hint::black_box(flow::momentum_rhs(&c, &g, u, &nut));
    });
    time("cell_velocity", &mut || {
        std::hint::black_box(g.cell_velocity(u));
    });
    time("eddy_viscosity", &mut || {
        std::hint::black_box(flow::eddy_viscosity(&g, &s.k, &s.epsilon));
    });
    time("production", &mut || {
        std::hint::black_box(flow::production(&c, &g, u, &nut, &s.k));
    });
    let st = Stencil::build(&c, &g);
    time("implicit_matrix_rans", &mut || {
        std::hint::black_box(st.implicit_matrix_rans(&c, &g, u, &nut, 0.1));
    });
    time("implicit_matrix(lam)", &mut || {
        std::hint::black_box(st.implicit_matrix(u, 1e-5, 0.1));
    });
    let m = st.implicit_matrix_rans(&c, &g, u, &nut, 0.1);
    let mut y = vec![0.0; u.len()];
    time("matrix.apply", &mut || {
        m.apply(&st, u, &mut y);
        std::hint::black_box(&y);
    });
    let d = vec![0.02; g.count()];
    let src = vec![0.0; g.count()];
    time("transport::rhs", &mut || {
        std::hint::black_box(transport::rhs(
            &g,
            &s.k,
            u,
            &d,
            &src,
            Advection::LinearUpwind,
            |_| 0.0,
        ));
    });
    let mut k2 = s.k.clone();
    let mut e2 = s.epsilon.clone();
    time("turbulence implicit_step", &mut || {
        k2.copy_from_slice(&s.k);
        e2.copy_from_slice(&s.epsilon);
        std::hint::black_box(
            cfd_craft::turbulence_solve::implicit_step(
                &c,
                &g,
                u,
                &mut k2,
                &mut e2,
                0.1,
                &solver::Control::new(60.0),
            )
            .unwrap(),
        );
    });
    time("transport::rhs inlet k", &mut || {
        std::hint::black_box(transport::rhs(
            &g,
            &s.k,
            u,
            &d,
            &src,
            Advection::LinearUpwind,
            |f| c.flow.turbulence(f.center[2]).0,
        ));
    });
    time("flow.turbulence x1000", &mut || {
        for i in 0..1000 {
            std::hint::black_box(c.flow.turbulence(i as f64 * 0.001));
        }
    });
    time("wall_ghost-heavy: momentum_rhs lam", &mut || {
        let mut cl = c.clone();
        cl.flow = Flow::Laminar {
            initial_velocity_m_s: [1.0, 0.0, 0.0],
            viscosity_m2_s: 1e-5,
            acceleration_m_s2: [0.0; 3],
        };
        std::hint::black_box(flow::momentum_rhs(&cl, &g, u, &nut));
    });
    time("gradient", &mut || {
        std::hint::black_box(g.gradient(&s.pressure));
    });
}
