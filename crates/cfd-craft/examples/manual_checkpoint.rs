//! Same-endpoint, work-limited checkpoint/restart compared with a cold solve.
use cfd_craft::{
    case::Case,
    output,
    solver::{self, Control},
};
use std::{fs, io::Write, path::PathBuf};

fn main() -> cfd_craft::Result<()> {
    let path = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or("CFD-U001 manual.checkpoint.output: pass a new checkpoint file path")?;
    if fs::symlink_metadata(&path).is_ok() {
        return Err("CFD-U001 manual.checkpoint.output: path must be new".into());
    }
    let mut case: Case = serde_json::from_str(include_str!(
        "../../../cases/verification/periodic-tracer.json"
    ))
    .map_err(|e| format!("CFD-U001 manual.checkpoint.case: {e}"))?;
    case.run.threads = 1;
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(1)
        .build()
        .map_err(|e| format!("CFD-U001 manual.checkpoint.threads: {e}"))?;
    let mut interrupted = case.clone();
    interrupted.run.max_steps = 5; // Keep the final physical endpoint unchanged.
    let partial = pool.install(|| solver::run(&interrupted, &Control::new(120.0), None))?;
    if partial.summary.termination != "iteration_limit" || partial.state.steps != 5 {
        return Err(
            "CFD-U001 manual.checkpoint.partial: expected five-step incomplete state".into(),
        );
    }
    let bytes = output::checkpoint_bytes(&interrupted, &partial.state)?;
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
        .map_err(|e| format!("CFD-U001 manual.checkpoint.output: {e}"))?;
    file.write_all(&bytes)
        .and_then(|()| file.sync_all())
        .map_err(|e| format!("CFD-U001 manual.checkpoint.output: {e}"))?;
    drop(file);
    let state = output::read_checkpoint(&case, &path)?;
    let resumed = pool.install(|| solver::run(&case, &Control::new(120.0), Some(state)))?;
    let cold = pool.install(|| solver::run(&case, &Control::new(120.0), None))?;
    if resumed.summary.assessment != "transient_interval_completed"
        || serde_json::to_vec(&resumed.state).unwrap() != serde_json::to_vec(&cold.state).unwrap()
    {
        return Err(
            "CFD-U001 manual.checkpoint.replay: resumed state differs from cold state".into(),
        );
    }
    // The same final state, but a different starting state: the identities differ.
    if resumed.summary.initial_state_sha256 == cold.summary.initial_state_sha256 {
        return Err(
            "CFD-U001 manual.checkpoint.initial_state: resumed run reports the cold start".into(),
        );
    }
    println!(
        "{}",
        serde_json::json!({"passed":true,"partial_steps":partial.state.steps,
        "final_steps":resumed.state.steps,"final_time_s":resumed.state.time_s,
        "same_state_as_cold":true,"initial_state_id_differs":true})
    );
    Ok(())
}
