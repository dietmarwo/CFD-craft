//! Shared rough-RHS pressure harness, also compiled on the recorded baseline.
use cfd_craft::{
    Result,
    case::{Case, hash_bytes},
    grid::Grid,
    pressure,
    solver::Control,
};
use serde_json::{Value, json};
use std::{fs::OpenOptions, io::Write, time::Instant};
fn require(ok: bool, field: &str, message: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(format!("CFD-B006 pressure_suite.{field}: {message}"))
    }
}
fn identity() -> String {
    let mut bytes = Vec::new();
    for part in [
        include_bytes!("../src/multigrid.rs").as_slice(),
        include_bytes!("../src/multigrid/line.rs").as_slice(),
        include_bytes!("../src/pressure.rs").as_slice(),
        include_bytes!("../src/grid.rs").as_slice(),
        include_bytes!("../src/case.rs").as_slice(),
        include_bytes!("../src/solver.rs").as_slice(),
        include_bytes!("../src/profiling.rs").as_slice(),
        include_bytes!("../src/flow.rs").as_slice(),
        include_bytes!("../src/transport.rs").as_slice(),
        include_bytes!("../src/output.rs").as_slice(),
        include_bytes!("../src/verification.rs").as_slice(),
        include_bytes!("../src/lib.rs").as_slice(),
        include_bytes!("../Cargo.toml").as_slice(),
        include_bytes!("../../../Cargo.toml").as_slice(),
        include_bytes!("../../../Cargo.lock").as_slice(),
        include_bytes!("pressure_probe.rs").as_slice(),
    ] {
        bytes.extend_from_slice(&(part.len() as u64).to_le_bytes());
        bytes.extend_from_slice(part);
    }
    hash_bytes(&bytes)
}
fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    require(args.len() == 6, "arguments", "CASE REPEATS TOL MAX OUTPUT")?;
    let repeats = args[2].parse::<usize>().map_err(|e| e.to_string())?;
    let tol = args[3].parse::<f64>().map_err(|e| e.to_string())?;
    let max = args[4].parse::<usize>().map_err(|e| e.to_string())?;
    require(
        (2..=10).contains(&repeats) && tol.is_finite() && tol > 0.0 && (1..=10000).contains(&max),
        "limits",
        "invalid repeats/tolerance/iteration budget",
    )?;
    let mut case: Case =
        serde_json::from_str(&std::fs::read_to_string(&args[1]).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    case.run.threads = 1;
    case.validate()?;
    require(
        case.numerics.pressure_relative_tolerance == tol
            && case.numerics.pressure_max_iterations == max,
        "limits",
        "case and requested solve limits differ",
    )?;
    let g = Grid::build(&case)?;
    let mut exact: Vec<_> = (0..g.count())
        .map(|i| (0.73 * i as f64).sin() + 0.3 * (0.17 * i as f64).cos())
        .collect();
    pressure::center_nullspaces(&g, &mut exact);
    let mut rhs = vec![0.0; g.count()];
    pressure::apply(&g, &exact, &mut rhs);
    let mut samples = Vec::new();
    let mut result = Value::Null;
    let mut first = None;
    for _ in 0..repeats {
        let control = Control::new(180.0).with_profiling();
        let start = Instant::now();
        let solved = pressure::solve(&g, &rhs, tol, max, &control);
        let wall = start.elapsed().as_secs_f64();
        let profile = control.profile()?.expect("profile enabled");
        match solved {
            Ok((values, info)) => {
                let rms = (values
                    .iter()
                    .zip(&exact)
                    .map(|(a, b)| (a - b).powi(2))
                    .sum::<f64>()
                    / values.len() as f64)
                    .sqrt();
                require(
                    values.iter().all(|v| v.is_finite()) && rms.is_finite(),
                    "values",
                    "nonfinite result",
                )?;
                let signature =
                    hash_bytes(&serde_json::to_vec(&values).map_err(|e| e.to_string())?);
                let initial = first.get_or_insert_with(|| signature.clone());
                require(
                    *initial == signature,
                    "repetitions",
                    "results changed between cold/reused solves",
                )?;
                samples.push(json!({"wall_s":wall,"iterations":info.iterations,"true_relative_residual":info.relative_residual,
                    "rms_error":rms,"result_sha256":signature,"profile":profile,"error":null}));
                result = json!({"values":values,"result_sha256":signature});
            }
            Err(error) => {
                samples.push(json!({"wall_s":wall,"profile":profile,"error":error}));
                break;
            }
        }
    }
    let passed = samples.len() == repeats && samples.iter().all(|v| v["error"].is_null());
    let report = json!({"schema_version":"cfd-craft.anisotropic-pressure/0.1","case":case,
        "source_sha256":identity(),"threads":1,"repetitions":repeats,"tolerance":tol,"max_iterations":max,
        "samples":samples,"result":result,"hierarchy":pressure::multigrid_stats(&g),"passed":passed,
        "meaning":"rough manufactured pressure; fixed accuracy, cold/reused timers include phase profiling; not accepted flow or physical validation"});
    let mut out = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&args[5])
        .map_err(|e| e.to_string())?;
    out.write_all(
        serde_json::to_string(&report)
            .map_err(|e| e.to_string())?
            .as_bytes(),
    )
    .map_err(|e| e.to_string())?;
    println!(
        "{}",
        json!({"passed":passed,"source_sha256":report["source_sha256"]})
    );
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        let e = if e.starts_with("CFD-") {
            e
        } else {
            format!("CFD-B006 pressure_suite.execution: {e}")
        };
        eprintln!("{e}");
        std::process::exit(1);
    }
}
