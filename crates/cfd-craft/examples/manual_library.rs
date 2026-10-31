//! Typed case, bounded in-process solve, source units and receptor lookup.
use cfd_craft::{
    case::Case,
    solver::{self, Control},
};

fn main() -> cfd_craft::Result<()> {
    let mut case: Case = serde_json::from_str(include_str!(
        "../../../cases/verification/source-response.json"
    ))
    .map_err(|e| format!("CFD-U001 manual.library.case: {e}"))?;
    case.run.threads = 1;
    case.validate()?;
    let total_rate: f64 = case.sources.iter().map(|source| source.rate()).sum();
    // The library does not install a Rayon pool from case.run.threads for you.
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(case.run.threads)
        .build()
        .map_err(|e| format!("CFD-U001 manual.library.threads: {e}"))?;
    let control = Control::new(case.run.wall_time_limit_s);
    let run = pool.install(|| solver::run(&case, &control, None))?;
    // Ok(RunResult) can also contain cancellation or an incomplete solve.
    if run.summary.assessment != "steady_discrete_solution" {
        return Err(format!(
            "CFD-U001 manual.library.assessment: {} / {}",
            run.summary.termination, run.summary.assessment
        ));
    }
    let tracer = run
        .summary
        .constituents
        .iter()
        .find(|s| s.id == "tracer")
        .ok_or("CFD-U001 manual.library.constituents.tracer: missing")?;
    let r1 = tracer
        .receptors_kg_m3
        .get("R1")
        .ok_or("CFD-U001 manual.library.receptors.R1: missing")?;
    println!(
        "{}",
        serde_json::json!({
            "passed":true, "assessment":run.summary.assessment,
            "source_total_kg_s":total_rate, "R1_kg_m3":r1,
            "R1_ug_m3":r1*1e9, "objective_max_over_1e_minus_8":
                tracer.receptors_kg_m3.values().copied().fold(0.0,f64::max)/1e-8,
            "steps":run.summary.steps,
            "provenance":"library result; application must supply its own build identity before archive publication"
        })
    );
    Ok(())
}
