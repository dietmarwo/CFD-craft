#![forbid(unsafe_code)]
use cfd_craft::{
    Result,
    case::{Case, CheckReport, Diagnostic, hash_bytes},
    grid::Grid,
    output,
    solver::{Control, Summary},
};
use std::{
    env, fs,
    io::{self, Write},
    path::Path,
    process::ExitCode,
};

/// Outcome of a command, mapped to the documented exit codes.
enum Outcome {
    /// 0: the request succeeded (valid case, passed assessment, verified archive).
    Success,
    /// 1: invalid input; a JSON report has been printed on stdout.
    Invalid,
    /// 2: a completed execution whose numerical evidence is incomplete or failed.
    Incomplete,
}

fn diagnostic(code: &str, path: &str, message: impl Into<String>) -> Diagnostic {
    Diagnostic {
        code: code.into(),
        severity: "error".into(),
        path: path.into(),
        message: message.into(),
    }
}

/// Splits "CFD-E040: message" into its code and message.
fn coded(e: &str, default: &str) -> (String, String) {
    match e.split_once(": ") {
        Some((code, rest)) if code.starts_with("CFD-") => (code.into(), rest.into()),
        _ => (default.into(), e.into()),
    }
}

fn invalid_report(diagnostics: Vec<Diagnostic>) -> CheckReport {
    CheckReport {
        schema_version: "cfd-craft.check/0.1".into(),
        valid: false,
        cells: 0,
        estimated_peak_mib: 0.0,
        estimated_output_mib: 0.0,
        diagnostics,
    }
}

/// Reads a case. A parse failure becomes a CFD-E000 diagnostic with the JSON path
/// of the offending element.
fn read_case(p: &str) -> Result<std::result::Result<(Vec<u8>, Case), CheckReport>> {
    let bytes = fs::read(p).map_err(|e| format!("cannot read case {p}: {e}"))?;
    let mut de = serde_json::Deserializer::from_slice(&bytes);
    match serde_path_to_error::deserialize::<_, Case>(&mut de) {
        Ok(c) => match de.end() {
            Ok(()) => Ok(Ok((bytes, c))),
            Err(e) => Ok(Err(invalid_report(vec![diagnostic(
                "CFD-E000",
                "",
                e.to_string(),
            )]))),
        },
        Err(e) => {
            let path = e.path().to_string();
            Ok(Err(invalid_report(vec![diagnostic(
                "CFD-E000",
                if path == "." { "" } else { &path },
                e.into_inner().to_string(),
            )])))
        }
    }
}

/// Available host memory in MiB, where the platform reports it.
fn available_mib() -> Option<f64> {
    let info = fs::read_to_string("/proc/meminfo").ok()?;
    info.lines().find_map(|line| {
        line.strip_prefix("MemAvailable:")
            .and_then(|s| s.split_whitespace().next())
            .and_then(|s| s.parse::<f64>().ok())
            .map(|kib| kib / 1024.0)
    })
}

/// Case checks plus the grid, source and receptor checks that need the built grid.
/// Every source and receptor is checked, so all problems are reported at once.
fn full_check(c: &Case) -> (CheckReport, Option<serde_json::Value>) {
    let mut report = c.check();
    if let Some(mib) = available_mib()
        && report.estimated_peak_mib > 0.8 * mib
    {
        report.diagnostics.push(Diagnostic {
            code: "CFD-W070".into(),
            severity: "warning".into(),
            path: "run.memory_limit_mib".into(),
            message: format!(
                "The estimated peak of {:.0} MiB exceeds 80 % of the {mib:.0} MiB this host has available; run refuses it here.",
                report.estimated_peak_mib
            ),
        });
    }
    if !report.valid {
        return (report, None);
    }
    let g = match Grid::build(c) {
        Ok(g) => g,
        Err(e) => {
            let (code, message) = coded(&e, "CFD-E030");
            let path = c
                .geometry
                .iter()
                .position(|b| message.contains(&format!("box {} ", b.id)))
                .map_or("geometry".to_string(), |i| format!("geometry[{i}]"));
            report.valid = false;
            report.diagnostics.push(diagnostic(&code, &path, message));
            return (report, None);
        }
    };
    for (i, s) in c.sources.iter().enumerate() {
        let mut one = c.clone();
        one.sources = vec![s.clone()];
        if let Err(e) = cfd_craft::transport::source_fields(&one, &g) {
            let (code, message) = coded(&e, "CFD-E040");
            report.valid = false;
            report
                .diagnostics
                .push(diagnostic(&code, &format!("sources[{i}]"), message));
        }
    }
    for (i, r) in c.receptors.iter().enumerate() {
        if let Err(e) = cfd_craft::transport::receptor_weights(&g, r) {
            let (code, message) = coded(&e, "CFD-E042");
            report.valid = false;
            report
                .diagnostics
                .push(diagnostic(&code, &format!("receptors[{i}]"), message));
        }
    }
    let geometry = serde_json::to_value(g.evidence()).ok();
    (report, geometry)
}

/// Prints JSON to stdout. A closed stdout (for example `| head`) is not an error.
fn print(v: &impl serde::Serialize) -> Result<()> {
    let text = serde_json::to_string_pretty(v).map_err(|e| e.to_string())?;
    match writeln!(io::stdout().lock(), "{text}") {
        Err(e) if e.kind() != io::ErrorKind::BrokenPipe => Err(e.to_string()),
        _ => Ok(()),
    }
}

fn describe() -> Result<()> {
    print(&serde_json::json!({
        "name":"CFD-craft","version":env!("CARGO_PKG_VERSION"),
        "source_sha256":env!("CFD_SOURCE_SHA"),"compiler":env!("CFD_RUSTC"),
        "physics":["prescribed_uniform","laminar","neutral_rans"],
        "scalar_advection":["linear_upwind","muscl"],"pressure":"matrix_free_ic0_pcg",
        "case_schema":schemars::schema_for!(Case),"result_schema":schemars::schema_for!(Summary),
        "coordinates":"local east, north, up; meteorological wind direction from",
        "pressure_units":"kinematic m2/s2; RANS isotropic 2k/3 absorbed",
        "exit_codes":{"0":"success: valid case, passed numerical assessment or verified archive",
            "1":"invalid input or an execution/I/O error; check reports are printed on stdout",
            "2":"completed execution with incomplete or failed numerical evidence"},
        "experimental_validation":"not_validated",
        "limitations":["uniform Cartesian grids","boxes","first-order donor-cell momentum","explicit diffusion","no particles, vegetation, LES, annual statistics or GPU"]
    }))
}

fn execute(args: &[String]) -> Result<Outcome> {
    let command = args.first().map(String::as_str).unwrap_or("help");
    if command == "describe" {
        if args.len() != 1 {
            return Err("describe accepts no options".into());
        }
        describe()?;
        return Ok(Outcome::Success);
    }
    if command == "help" || command == "--help" {
        print(&serde_json::json!({"usage":
            "cfd-craft describe | check CASE | run CASE --output NEW_DIR [--restart CHECKPOINT] | preview CASE --output NEW_DIR [--factor N] | report DIR | verify CASE"}))?;
        return Ok(Outcome::Success);
    }
    let p = args.get(1).ok_or("case/path required")?;
    if command == "report" {
        if args.len() != 2 {
            return Err("report accepts one directory".into());
        }
        print(&output::read_verified(Path::new(p))?)?;
        return Ok(Outcome::Success);
    }
    if !matches!(command, "check" | "verify" | "run" | "preview") {
        return Err(format!("unknown command {command}"));
    }
    let (input, mut c) = match read_case(p)? {
        Ok(v) => v,
        Err(report) => {
            print(&serde_json::json!({ "check": report }))?;
            return Ok(Outcome::Invalid);
        }
    };
    if command == "check" {
        if args.len() != 2 {
            return Err("check accepts one case".into());
        }
        let (report, geometry) = full_check(&c);
        let valid = report.valid;
        match geometry {
            Some(g) => print(&serde_json::json!({"check":report,"geometry":g}))?,
            None => print(&serde_json::json!({ "check": report }))?,
        }
        return Ok(if valid {
            Outcome::Success
        } else {
            Outcome::Invalid
        });
    }
    if command == "verify" {
        if args.len() != 2 {
            return Err("verify accepts one case".into());
        }
        let result = cfd_craft::verification::pressure_fixture(&c)?;
        let ok = result["passed"] == true;
        print(&result)?;
        return Ok(if ok {
            Outcome::Success
        } else {
            Outcome::Incomplete
        });
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
        c = preview_case(&c, factor)?;
    }
    let (mut report, _) = full_check(&c);
    if let Some(w) = report.diagnostics.iter_mut().find(|d| d.code == "CFD-W070") {
        w.code = "CFD-E070".into();
        w.severity = "error".into();
        report.valid = false;
    }
    if !report.valid {
        print(&serde_json::json!({ "check": report }))?;
        return Ok(Outcome::Invalid);
    }
    let out = Path::new(out.ok_or("--output NEW_DIR required")?);
    let state = restart
        .map(|p| output::read_checkpoint(&c, Path::new(p)))
        .transpose()?;
    // Claim the output directory before solving: a missing parent or an occupied
    // destination fails here, not after the work is done.
    output::create_run_dir(out)?;
    let solved = solve(&c, state);
    let result = match solved {
        Ok(r) => r,
        Err(e) => {
            let _ = fs::remove_dir(out);
            return Err(e);
        }
    };
    let mut result = result;
    if command == "preview" {
        result.summary.model_scope = format!("preview: {}", result.summary.model_scope);
    }
    let omitted = output::write_run(&c, &result, out, &hash_bytes(&input))?;
    let success = omitted.is_empty()
        && matches!(
            result.summary.assessment.as_str(),
            "steady_discrete_solution" | "transient_interval_completed"
        );
    print(&result.summary)?;
    if !omitted.is_empty() {
        eprintln!(
            "{}",
            serde_json::json!({"error":"CFD-E061: artifacts omitted because the output budget was exceeded","omitted":omitted})
        );
    }
    Ok(if success {
        Outcome::Success
    } else {
        Outcome::Incomplete
    })
}

fn solve(
    c: &Case,
    state: Option<cfd_craft::solver::State>,
) -> Result<cfd_craft::solver::RunResult> {
    let control = Control::new(c.run.wall_time_limit_s);
    for signal in [signal_hook::consts::SIGINT, signal_hook::consts::SIGTERM] {
        signal_hook::flag::register(signal, control.cancelled.clone())
            .map_err(|e| e.to_string())?;
    }
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(c.run.threads)
        .build()
        .map_err(|e| e.to_string())?;
    let mut result = pool.install(|| cfd_craft::solver::run(c, &control, state))?;
    result.summary.source_sha256 = env!("CFD_SOURCE_SHA").into();
    result.summary.build_version = format!("{}; {}", env!("CARGO_PKG_VERSION"), env!("CFD_RUSTC"));
    Ok(result)
}

/// The same case on a grid coarsened by `factor`. The coarse case is checked before
/// the original grid is built, and the original is only built when it fits its budget.
fn preview_case(c: &Case, factor: usize) -> Result<Case> {
    let mut coarse = c.clone();
    coarse.name = format!("{}-preview", c.name);
    for a in 0..3 {
        coarse.grid.cells[a] = (c.grid.cells[a] / factor).max(2);
    }
    let derived = Grid::build(&coarse)?.evidence();
    if c.geometry.is_empty() {
        return Ok(coarse);
    }
    let original_solid = solid_volume(c);
    let volume_change =
        (derived.solid_volume_m3 - original_solid).abs() / original_solid.max(1e-30);
    let topology_changed = c.check().valid
        && Grid::build(c).map(|g| g.evidence().fluid_components)? != derived.fluid_components;
    if volume_change > 0.2 || topology_changed {
        return Err(
            "preview changes solid volume by >20% or fluid topology; refine explicitly".into(),
        );
    }
    Ok(coarse)
}

/// Solid volume of the full-resolution grid, counted without allocating it.
fn solid_volume(c: &Case) -> f64 {
    let n = c.grid.cells;
    let dx: [f64; 3] = std::array::from_fn(|a| c.domain.size_m[a] / n[a] as f64);
    let mut solid = 0usize;
    for k in 0..n[2] {
        let z = (k as f64 + 0.5) * dx[2];
        let layer: Vec<_> = c
            .geometry
            .iter()
            .filter(|b| z >= b.min_m[2] && z < b.max_m[2])
            .collect();
        if layer.is_empty() {
            continue;
        }
        for j in 0..n[1] {
            let y = (j as f64 + 0.5) * dx[1];
            for i in 0..n[0] {
                let x = (i as f64 + 0.5) * dx[0];
                if layer
                    .iter()
                    .any(|b| x >= b.min_m[0] && x < b.max_m[0] && y >= b.min_m[1] && y < b.max_m[1])
                {
                    solid += 1;
                }
            }
        }
    }
    solid as f64 * dx.iter().product::<f64>()
}

fn main() -> ExitCode {
    match execute(&env::args().skip(1).collect::<Vec<_>>()) {
        Ok(Outcome::Success) => ExitCode::SUCCESS,
        Ok(Outcome::Invalid) => ExitCode::from(1),
        Ok(Outcome::Incomplete) => ExitCode::from(2),
        Err(e) => {
            eprintln!("{}", serde_json::json!({"error":e}));
            ExitCode::from(1)
        }
    }
}
