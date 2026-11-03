//! The library entry points the CLI and the Python binding share: strict case
//! parsing and preflight (`cfd_craft::input`) and the build identity that a
//! bare `solver::run` result carries.
use cfd_craft::{input, solver};

const TRACER: &str = include_str!("../../../cases/verification/periodic-tracer.json");

fn first_code(report: &cfd_craft::case::CheckReport) -> (&str, &str) {
    let d = &report.diagnostics[0];
    (d.code.as_str(), d.path.as_str())
}

#[test]
fn parse_case_is_strict_and_reports_json_paths() {
    let case = input::parse_case(TRACER.as_bytes()).expect("valid fixture");
    assert!(input::full_check(&case).0.valid);

    let trailing = format!("{TRACER} {{}}");
    let report = input::parse_case(trailing.as_bytes()).unwrap_err();
    assert!(!report.valid);
    assert_eq!(first_code(&report), ("CFD-E000", ""));

    let mut value: serde_json::Value = serde_json::from_str(TRACER).unwrap();
    value["run"]["unexpected"] = serde_json::json!(1);
    let report = input::parse_case(value.to_string().as_bytes()).unwrap_err();
    assert_eq!(first_code(&report).0, "CFD-E000");
    assert!(first_code(&report).1.starts_with("run"), "{report:?}");

    let duplicate = TRACER.replacen("{", "{\"name\": \"a\", ", 1);
    let report = input::parse_case(duplicate.as_bytes()).unwrap_err();
    assert_eq!(first_code(&report).0, "CFD-E000");
}

#[test]
fn full_check_rejects_invalid_budgets_with_their_paths() {
    let mut case = input::parse_case(TRACER.as_bytes()).unwrap();
    case.run.threads = 0;
    let (report, _) = input::full_check(&case);
    assert!(!report.valid);
    assert!(
        report
            .diagnostics
            .iter()
            .any(|d| d.code == "CFD-E008" && d.path == "run.threads"),
        "{report:?}"
    );
}

#[test]
fn a_bare_library_run_identifies_the_core_build() {
    let mut case = input::parse_case(TRACER.as_bytes()).unwrap();
    case.run.max_steps = 2;
    case.run.threads = 1;
    let control = solver::Control::new(case.run.wall_time_limit_s);
    let result = solver::run(&case, &control, None).expect("bounded run");
    let summary = result.summary;
    assert_eq!(summary.source_sha256, cfd_craft::SOURCE_SHA256);
    assert_eq!(summary.source_sha256.len(), 64);
    assert!(summary.build_version.starts_with(env!("CARGO_PKG_VERSION")));
    assert!(summary.build_version.ends_with(cfd_craft::RUSTC_VERSION));
}
