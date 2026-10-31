use cfd_craft::{
    case::Case,
    solver::{self, Control},
};
use std::{path::Path, sync::atomic::Ordering};

fn case(path: &str) -> Case {
    serde_json::from_slice(
        &std::fs::read(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../..")
                .join(path),
        )
        .unwrap(),
    )
    .unwrap()
}

#[test]
fn profiling_preserves_laminar_rans_and_scalar_states_exactly() {
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(1)
        .build()
        .unwrap();
    for path in [
        "cases/verification/lid-cavity.json",
        "cases/canyon/wh1-wind270.json",
        "cases/verification/periodic-tracer.json",
    ] {
        let mut c = case(path);
        c.run.max_steps = 3;
        c.run.threads = 1;
        if path.contains("canyon") {
            c.grid.cells = [18, 16, 12];
        }
        let plain = pool
            .install(|| solver::run(&c, &Control::new(60.0), None))
            .unwrap();
        let control = Control::new(60.0).with_profiling();
        let measured = pool.install(|| solver::run(&c, &control, None)).unwrap();
        assert_eq!(
            serde_json::to_vec(&plain.state).unwrap(),
            serde_json::to_vec(&measured.state).unwrap()
        );
        assert_eq!(plain.summary.assessment, measured.summary.assessment);
        assert_eq!(
            serde_json::to_vec(&plain.summary.checks).unwrap(),
            serde_json::to_vec(&measured.summary.checks).unwrap()
        );
        let p = control.profile().unwrap().unwrap();
        assert_eq!(p.phases["step"].calls, measured.state.steps as u64);
        assert_eq!(
            p.phases.get("pressure_solve").map_or(0, |p| p.work_units),
            measured.state.pressure_iterations as u64
        );
        if path.contains("canyon") {
            assert_eq!(p.phases["turbulence"].calls, 4);
        }
        if !c.constituents.is_empty() {
            assert_eq!(
                p.phases["scalar_transport"].calls,
                3 * c.constituents.len() as u64
            );
        }
        assert!(p.accounted_exclusive_s <= p.elapsed_s);
    }
}

#[test]
fn failed_pressure_work_is_retained_without_a_committed_step() {
    let mut c = case("cases/verification/lid-cavity.json");
    c.numerics.pressure_max_iterations = 1;
    c.run.max_steps = 1;
    let control = Control::new(60.0).with_profiling();
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(1)
        .build()
        .unwrap();
    let r = pool.install(|| solver::run(&c, &control, None)).unwrap();
    assert_eq!(r.state.steps, 0);
    assert_eq!(r.state.pressure_iterations, 0);
    assert_eq!(r.summary.assessment, "incomplete");
    assert!(r.summary.error.unwrap().contains("CFD-E033"));
    let p = control.profile().unwrap().unwrap();
    assert_eq!(p.phases["step"].calls, 1);
    assert_eq!(p.phases["pressure_solve"].calls, 2);
    assert_eq!(p.phases["pressure_solve"].work_units, 1);
    assert_eq!(p.phases["pressure_factor_setup"].calls, 1);
}

#[test]
fn cancellation_closes_spans_and_disabled_control_has_no_profile() {
    let mut c = case("cases/verification/periodic-tracer.json");
    c.grid.cells = [4, 4, 4];
    let control = Control::new(30.0).with_profiling();
    control.cancelled.store(true, Ordering::Relaxed);
    let r = solver::run(&c, &control, None).unwrap();
    assert_eq!(r.summary.termination, "cancelled");
    let p = control.profile().unwrap().unwrap();
    assert!(!p.phases.contains_key("step"));
    assert_eq!(p.phases["solver_run"].calls, 1);
    assert!(Control::new(30.0).profile().unwrap().is_none());
}
