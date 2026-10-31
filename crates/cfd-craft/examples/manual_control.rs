//! Two cooperative cancellation mechanisms; incomplete results remain inspectable.
use cfd_craft::{
    case::Case,
    solver::{self, Control},
};
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};

fn main() -> cfd_craft::Result<()> {
    let mut case: Case = serde_json::from_str(include_str!(
        "../../../cases/verification/source-response.json"
    ))
    .map_err(|e| format!("CFD-U001 manual.control.case: {e}"))?;
    case.run.threads = 1;
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(1)
        .build()
        .map_err(|e| format!("CFD-U001 manual.control.threads: {e}"))?;
    let control = Control::new(case.run.wall_time_limit_s);
    control.cancelled.store(true, Ordering::Relaxed);
    let queued = pool.install(|| solver::run(&case, &control, None))?;
    let polls = Arc::new(AtomicUsize::new(0));
    let observed = polls.clone();
    // A real job worker would call its deadline/cancellation checkpoint here.
    let external = Control::with_poll(case.run.wall_time_limit_s, move || {
        if observed.fetch_add(1, Ordering::Relaxed) >= 8 {
            Err("cancelled".into())
        } else {
            Ok(())
        }
    });
    let running = pool.install(|| solver::run(&case, &external, None))?;
    for result in [&queued, &running] {
        if result.summary.termination != "cancelled" || result.summary.assessment != "incomplete" {
            return Err("CFD-U001 manual.control.assessment: expected cancelled/incomplete".into());
        }
    }
    println!(
        "{}",
        serde_json::json!({"passed":true,"queued_steps":queued.state.steps,
        "external_steps":running.state.steps,"polls":polls.load(Ordering::Relaxed),
        "termination":running.summary.termination,"assessment":running.summary.assessment})
    );
    Ok(())
}
