//! Bounded deterministic probes. Timings exclude JSON serialization and hashing.
use cfd_craft::{
    Result,
    case::{Advection, Case, hash_bytes},
    flow,
    grid::Grid,
    pressure,
    solver::{self, Control},
    transport,
};
use serde::Serialize;
use serde_json::{Value, json};
use std::{fs::OpenOptions, hint::black_box, io::Write, time::Instant};

fn require(ok: bool, field: &str, message: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(format!("CFD-B001 benchmark.{field}: {message}"))
    }
}
fn number(text: &str, field: &str, high: usize) -> Result<usize> {
    let value = text
        .parse::<usize>()
        .map_err(|_| format!("CFD-B001 benchmark.{field}: expected an integer"))?;
    require((1..=high).contains(&value), field, "integer outside bounds")?;
    Ok(value)
}
fn signature<T: Serialize>(value: &T) -> String {
    hash_bytes(&serde_json::to_vec(value).expect("finite probe result"))
}
fn finite(values: &[f64], field: &str) -> Result<()> {
    require(
        values.iter().all(|v| v.is_finite()),
        field,
        "nonfinite result",
    )
}
fn source_identity() -> String {
    let mut bytes = Vec::new();
    for part in [
        include_bytes!("../src/pressure.rs").as_slice(),
        include_bytes!("../src/grid.rs").as_slice(),
        include_bytes!("../src/flow.rs").as_slice(),
        include_bytes!("../src/transport.rs").as_slice(),
        include_bytes!("../src/solver.rs").as_slice(),
        include_bytes!("../src/case.rs").as_slice(),
        include_bytes!("../src/output.rs").as_slice(),
        include_bytes!("../src/verification.rs").as_slice(),
        include_bytes!("../src/lib.rs").as_slice(),
        include_bytes!("../Cargo.toml").as_slice(),
        include_bytes!("../../../Cargo.toml").as_slice(),
        include_bytes!("../../../Cargo.lock").as_slice(),
        include_bytes!("performance_probe.rs").as_slice(),
    ] {
        bytes.extend_from_slice(&(part.len() as u64).to_le_bytes());
        bytes.extend_from_slice(part);
    }
    hash_bytes(&bytes)
}
fn timed<T>(times: &mut Vec<f64>, work: impl FnOnce() -> Result<T>) -> Result<T> {
    let began = Instant::now();
    let value = work()?;
    times.push(began.elapsed().as_secs_f64());
    Ok(black_box(value))
}
fn probe(c: &Case, mode: &str, repeats: usize, steps: usize) -> Result<Value> {
    let control = Control::new(180.0);
    let began = Instant::now();
    let g = Grid::build(c)?;
    let setup_s = began.elapsed().as_secs_f64();
    let initial = solver::initial_state(c, &g);
    let nut = flow::eddy_viscosity(&g, &initial.k, &initial.epsilon);
    let sources = transport::source_fields(c, &g)?;
    let weights = c
        .receptors
        .iter()
        .map(|r| transport::receptor_weights(&g, r))
        .collect::<Result<Vec<_>>>()?;
    let mut exact: Vec<_> = (0..g.count())
        .map(|i| {
            let p = g.center(i);
            if g.fluid[i] {
                (2.0 * std::f64::consts::PI * p[0] / c.domain.size_m[0]).sin()
                    + 0.3 * (4.0 * std::f64::consts::PI * p[2] / c.domain.size_m[2]).cos()
            } else {
                0.0
            }
        })
        .collect();
    pressure::center_nullspaces(&g, &mut exact);
    let mut rhs = vec![0.0; g.count()];
    pressure::apply(&g, &exact, &mut rhs);
    let scalar: Vec<_> = (0..g.count())
        .map(|i| {
            if g.fluid[i] {
                1.0 + 0.2 * (i as f64 * 0.17).sin()
            } else {
                0.0
            }
        })
        .collect();
    let d: Vec<_> = nut.iter().map(|v| c.flow.viscosity() + v).collect();
    let zeros = vec![0.0; g.count()];
    let mut times = Vec::new();
    let mut result = Value::Null;
    let mut first_signature = None;
    for _ in 0..repeats {
        control.check()?;
        result = match mode {
            "setup" => {
                let other = timed(&mut times, || Grid::build(c))?;
                json!({"cells":other.count(), "faces":other.faces.len()})
            }
            "pressure" => {
                let (x, info) = timed(&mut times, || {
                    pressure::solve(&g, &rhs, 1e-11, 10000, &control)
                })?;
                let error = x
                    .iter()
                    .zip(&exact)
                    .map(|(a, b)| (a - b).powi(2))
                    .sum::<f64>()
                    / g.count() as f64;
                finite(&x, "result.pressure")?;
                require(
                    error.is_finite() && info.relative_residual.is_finite(),
                    "result.pressure",
                    "nonfinite assessment",
                )?;
                json!({"values":x, "iterations":info.iterations,
                    "true_relative_residual":info.relative_residual,
                    "rms_manufactured_error":error.sqrt()})
            }
            "momentum" => {
                let values = timed(&mut times, || {
                    Ok(flow::momentum_rhs(c, &g, &initial.velocity, &nut))
                })?;
                finite(&values, "result.momentum")?;
                json!({"values":values})
            }
            "production" => {
                let (values, walls) = timed(&mut times, || {
                    Ok(flow::production(c, &g, &initial.velocity, &nut, &initial.k))
                })?;
                finite(&values, "result.production")?;
                require(
                    walls.iter().flatten().all(|v| v.is_finite()),
                    "result.walls",
                    "nonfinite result",
                )?;
                // Cells without a wall value are listed by index, not as JSON null,
                // so that null never stands for a valid result.
                let wall_cells: Vec<usize> =
                    (0..walls.len()).filter(|&i| walls[i].is_some()).collect();
                let wall_values: Vec<f64> = walls.iter().flatten().copied().collect();
                json!({"values":values,"wall_cells":wall_cells,"wall_values":wall_values})
            }
            "transport" => {
                let values = timed(&mut times, || {
                    Ok(transport::rhs(
                        &g,
                        &scalar,
                        &initial.velocity,
                        &d,
                        &zeros,
                        Advection::Muscl,
                        |_| 0.0,
                    ))
                })?;
                finite(&values.values, "result.transport")?;
                finite(
                    &[values.source, values.inflow, values.outflow],
                    "result.budgets",
                )?;
                json!({"values":values.values,"source":values.source,"inflow":values.inflow,"outflow":values.outflow})
            }
            "steps" => {
                let mut state = initial.clone();
                timed(&mut times, || {
                    for _ in 0..steps {
                        let viscosity = flow::eddy_viscosity(&g, &state.k, &state.epsilon);
                        let dt = solver::timestep(c, &g, &state, &viscosity);
                        solver::step(c, &g, &mut state, &sources, dt, &control)?;
                        // Exercise the same bounded history that the run loop owns.
                        state
                            .monitor_history
                            .push(solver::monitor(c, &g, &state, &weights));
                        if state.monitor_history.len() > 3 * c.numerics.monitor_window {
                            state.monitor_history.remove(0);
                        }
                    }
                    Ok(())
                })?;
                solver::validate_state(c, &g, &state)?;
                json!({"state":state})
            }
            _ => return Err("CFD-B001 benchmark.mode: unsupported probe".into()),
        };
        // Every repetition repeats the same work from the same input, so the cold
        // first result and every warm result must be identical (outside timing).
        let current = signature(&result);
        let first = first_signature.get_or_insert_with(|| current.clone());
        require(
            *first == current,
            "result.repetitions",
            "repetitions returned different results",
        )?;
    }
    Ok(json!({"schema_version":"cfd-craft.native-performance/0.1",
        "source_sha256":source_identity(),"case_sha256":signature(c),
        "case":c,"mode":mode,"repetitions":repeats,"requested_steps":steps,
        "threads":c.run.threads,"cells":g.count(),"faces":g.faces.len(),
        "grid_setup_s":setup_s,"wall_s":times,"result_sha256":signature(&result),
        "result":result,"physical_qualification":false,
        "meaning":"fixed work/kernel cost, not a converged or physically qualified CFD archive"}))
}
fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    require(
        args.len() == 8,
        "arguments",
        "CASE MODE REPEATS STEPS THREADS json OUTPUT",
    )?;
    let repeats = number(&args[3], "repetitions", 1000)?;
    let steps = number(&args[4], "steps", 1000)?;
    let threads = number(&args[5], "threads", 64)?;
    // An explicit format token prevents accidental invocation with a shifted argument list.
    require(args[6] == "json", "format", "expected json")?;
    let text =
        std::fs::read_to_string(&args[1]).map_err(|e| format!("CFD-B001 benchmark.case: {e}"))?;
    let mut c: Case =
        serde_json::from_str(&text).map_err(|e| format!("CFD-B001 benchmark.case: {e}"))?;
    c.run.threads = threads;
    c.validate()
        .map_err(|e| format!("CFD-B001 benchmark.case: invalid case: {e}"))?;
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .build()
        .map_err(|e| format!("CFD-B001 benchmark.threads: {e}"))?;
    let report = pool.install(|| probe(&c, &args[2], repeats, steps))?;
    let mut out = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&args[7])
        .map_err(|e| format!("CFD-B001 benchmark.output: {e}"))?;
    out.write_all(
        serde_json::to_string(&report)
            .map_err(|e| e.to_string())?
            .as_bytes(),
    )
    .map_err(|e| format!("CFD-B001 benchmark.output: {e}"))?;
    println!(
        "{}",
        json!({"source_sha256":report["source_sha256"],"wall_s":report["wall_s"],"result_sha256":report["result_sha256"]})
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
