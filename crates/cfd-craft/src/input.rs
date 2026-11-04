//! Shared strict JSON parsing and complete case preflight for all interfaces.
use crate::{
    case::{Case, CheckReport, Diagnostic},
    grid::{GeometryEvidence, Grid},
};
use std::fs;
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
pub fn parse_case(bytes: &[u8]) -> std::result::Result<Case, CheckReport> {
    let mut de = serde_json::Deserializer::from_slice(bytes);
    match serde_path_to_error::deserialize::<_, Case>(&mut de) {
        Ok(c) => match de.end() {
            Ok(()) => Ok(c),
            Err(e) => Err(invalid_report(vec![diagnostic(
                "CFD-E000",
                "",
                e.to_string(),
            )])),
        },
        Err(e) => {
            let path = e.path().to_string();
            Err(invalid_report(vec![diagnostic(
                "CFD-E000",
                if path == "." { "" } else { &path },
                e.into_inner().to_string(),
            )]))
        }
    }
}

/// Available host memory in MiB, where the platform reports it.
pub fn available_mib() -> Option<f64> {
    let info = fs::read_to_string("/proc/meminfo").ok()?;
    info.lines().find_map(|line| {
        line.strip_prefix("MemAvailable:")
            .and_then(|s| s.split_whitespace().next())
            .and_then(|s| s.parse::<f64>().ok())
            .map(|kib| kib / 1024.0)
    })
}

/// Case checks plus the grid, source and receptor checks that need the built grid.
/// Every source and receptor is checked, so all problems are reported at once. When the
/// estimated peak does not fit this host (CFD-W070), the grid is not built and its checks
/// are skipped, so a check never allocates what the host cannot hold.
pub fn full_check(c: &Case) -> (CheckReport, Option<GeometryEvidence>) {
    let mut report = c.check();
    if let Some(mib) = available_mib()
        && report.estimated_peak_mib > 0.8 * mib
    {
        report.diagnostics.push(Diagnostic {
            code: "CFD-W070".into(),
            severity: "warning".into(),
            path: "run.memory_limit_mib".into(),
            message: format!(
                "The estimated peak of {:.0} MiB exceeds 80 % of the {mib:.0} MiB this host has available; run refuses it here. The grid, source and receptor checks were skipped.",
                report.estimated_peak_mib
            ),
        });
        return (report, None);
    }
    if !report.valid {
        return (report, None);
    }
    let g = match Grid::build(c) {
        Ok(g) => g,
        Err(e) => {
            let (code, message) = coded(&e, "CFD-E030");
            // Box errors start with the element path, for example "geometry[3] (box b) ...".
            let path = message
                .split_once(' ')
                .map(|(p, _)| p)
                .filter(|p| p.starts_with("geometry["))
                .unwrap_or("geometry")
                .to_string();
            report.valid = false;
            report.diagnostics.push(diagnostic(&code, &path, message));
            return (report, None);
        }
    };
    for (i, s) in c.sources.iter().enumerate() {
        let mut one = c.clone();
        one.sources = vec![s.clone()];
        if let Err(e) = crate::transport::source_fields(&one, &g) {
            let (code, message) = coded(&e, "CFD-E040");
            report.valid = false;
            report
                .diagnostics
                .push(diagnostic(&code, &format!("sources[{i}]"), message));
        }
    }
    for (i, r) in c.receptors.iter().enumerate() {
        if let Err(e) = crate::transport::receptor_weights(&g, r) {
            let (code, message) = coded(&e, "CFD-E042");
            report.valid = false;
            report
                .diagnostics
                .push(diagnostic(&code, &format!("receptors[{i}]"), message));
        }
    }
    (report, Some(g.evidence()))
}

/// `run` refuses what `check` only warns about: a peak that does not fit this host.
pub fn refuse_host_memory(report: &mut CheckReport) {
    if let Some(w) = report.diagnostics.iter_mut().find(|d| d.code == "CFD-W070") {
        w.code = "CFD-E070".into();
        w.severity = "error".into();
        report.valid = false;
    }
}
