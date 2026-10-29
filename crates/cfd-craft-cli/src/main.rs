#![forbid(unsafe_code)]
use cfd_craft::{
    Result,
    case::{Case, hash_bytes},
    grid::Grid,
    output,
    solver::{Control, Summary},
};
use std::{env, fs, path::Path, process::ExitCode};
fn read_case(p: &str) -> Result<Case> {
    serde_json::from_slice(&fs::read(p).map_err(|e| e.to_string())?).map_err(|e| e.to_string())
}
fn host_preflight(c: &Case) -> Result<()> {
    if let Ok(info) = fs::read_to_string("/proc/meminfo")
        && let Some(kib) = info.lines().find_map(|line| {
            line.strip_prefix("MemAvailable:")
                .and_then(|s| s.split_whitespace().next())
                .and_then(|s| s.parse::<f64>().ok())
        })
        && c.check().estimated_peak_mib > 0.8 * kib / 1024.0
    {
        return Err("CFD-E070: estimated memory exceeds 80% of current available host RAM".into());
    }
    Ok(())
}
fn print(v: &impl serde::Serialize) {
    println!("{}", serde_json::to_string_pretty(v).unwrap());
}
fn execute(args: &[String]) -> Result<bool> {
    let command = args.first().map(String::as_str).unwrap_or("help");
    if command == "describe" {
        if args.len() != 1 {
            return Err("describe accepts no options".into());
        }
        print(
            &serde_json::json!({"name":"CFD-craft","version":env!("CARGO_PKG_VERSION"),
            "source_sha256":env!("CFD_SOURCE_SHA"),"compiler":env!("CFD_RUSTC"),
            "physics":["prescribed_uniform","laminar","neutral_rans"],
            "scalar_advection":["linear_upwind","muscl"],"pressure":"matrix_free_ic0_pcg",
            "case_schema":schemars::schema_for!(Case),"result_schema":schemars::schema_for!(Summary),
            "coordinates":"local east, north, up; meteorological wind direction from",
            "pressure_units":"kinematic m2/s2; RANS isotropic 2k/3 absorbed",
            "experimental_validation":"not_validated",
            "limitations":["uniform Cartesian grids","boxes","first-order donor-cell momentum","explicit diffusion","no particles, vegetation, LES, annual statistics or GPU"]}),
        );
        return Ok(true);
    }
    if command == "help" || command == "--help" {
        println!(
            "cfd-craft describe | check CASE | run CASE --output NEW_DIR [--restart CHECKPOINT] | preview CASE --output NEW_DIR [--factor N] | report DIR | verify CASE"
        );
        return Ok(true);
    }
    let p = args.get(1).ok_or("case/path required")?;
    if command == "report" {
        if args.len() != 2 {
            return Err("report accepts one directory".into());
        }
        print(&output::read_verified(Path::new(p))?);
        return Ok(true);
    }
    let mut c = read_case(p)?;
    host_preflight(&c)?;
    if command == "check" {
        if args.len() != 2 {
            return Err("check accepts one case".into());
        }
        let mut report = c.check();
        if report.valid {
            let detail = (|| {
                let g = Grid::build(&c)?;
                cfd_craft::transport::source_fields(&c, &g)?;
                for r in &c.receptors {
                    cfd_craft::transport::receptor_weights(&g, r)?;
                }
                Ok::<_, String>(g.evidence())
            })();
            match detail {
                Ok(g) => {
                    print(&serde_json::json!({"check":report,"geometry":g}));
                    return Ok(true);
                }
                Err(e) => {
                    report.valid = false;
                    report.diagnostics.push(cfd_craft::case::Diagnostic {
                        code: "CFD-E030".into(),
                        severity: "error".into(),
                        path: "geometry/sources/receptors".into(),
                        message: e,
                    });
                }
            }
        }
        print(&serde_json::json!({"check":report}));
        return Ok(false);
    }
    if command == "verify" {
        if args.len() != 2 {
            return Err("verify accepts one case".into());
        }
        let result = cfd_craft::verification::pressure_fixture(&c)?;
        let ok = result["passed"] == true;
        print(&result);
        return Ok(ok);
    }
    if command != "run" && command != "preview" {
        return Err(format!("unknown command {command}"));
    }
    let mut out = None;
    let mut restart = None;
    let mut factor = 2usize;
    let mut i = 2;
    while i < args.len() {
        let value = args.get(i + 1).ok_or("option needs a value")?;
        match args[i].as_str() {
            "--output" if out.is_none() => out = Some(value),
            "--restart" if restart.is_none() => restart = Some(value),
            "--factor" if command == "preview" => {
                factor = value.parse::<usize>().map_err(|e| e.to_string())?
            }
            _ => return Err(format!("unknown/duplicate option {}", args[i])),
        }
        i += 2;
    }
    if command == "preview" {
        if factor < 2 {
            return Err("preview factor must be at least 2".into());
        }
        let original = Grid::build(&c)?.evidence();
        c.name = format!("{}-preview", c.name);
        for a in 0..3 {
            c.grid.cells[a] = (c.grid.cells[a] / factor).max(2);
        }
        let derived = Grid::build(&c)?.evidence();
        if !c.geometry.is_empty()
            && ((derived.solid_volume_m3 - original.solid_volume_m3).abs()
                / original.solid_volume_m3.max(1e-30)
                > 0.2
                || derived.fluid_components != original.fluid_components)
        {
            return Err(
                "preview changes solid volume by >20% or fluid topology; refine explicitly".into(),
            );
        }
    }
    c.validate()?;
    let out = Path::new(out.ok_or("--output NEW_DIR required")?);
    if out.exists() {
        return Err("output destination already exists".into());
    }
    let state = restart
        .map(|p| output::read_checkpoint(&c, Path::new(p)))
        .transpose()?;
    let control = Control::new(c.run.wall_time_limit_s);
    for signal in [signal_hook::consts::SIGINT, signal_hook::consts::SIGTERM] {
        signal_hook::flag::register(signal, control.cancelled.clone())
            .map_err(|e| e.to_string())?;
    }
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(c.run.threads)
        .build()
        .map_err(|e| e.to_string())?;
    let mut result = pool.install(|| cfd_craft::solver::run(&c, &control, state))?;
    result.summary.source_sha256 = env!("CFD_SOURCE_SHA").into();
    result.summary.build_version = format!("{}; {}", env!("CARGO_PKG_VERSION"), env!("CFD_RUSTC"));
    if command == "preview" {
        result.summary.model_scope = format!("preview: {}", result.summary.model_scope);
    }
    output::write_run(&c, &result, out)?;
    let _input_digest = hash_bytes(&fs::read(p).map_err(|e| e.to_string())?);
    let success = matches!(
        result.summary.assessment.as_str(),
        "steady_discrete_solution" | "transient_interval_completed"
    );
    print(&result.summary);
    Ok(success)
}
fn main() -> ExitCode {
    match execute(&env::args().skip(1).collect::<Vec<_>>()) {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::from(2),
        Err(e) => {
            eprintln!("{}", serde_json::json!({"error":e}));
            ExitCode::from(1)
        }
    }
}
