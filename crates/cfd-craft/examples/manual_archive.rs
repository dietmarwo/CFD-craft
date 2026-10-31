//! Verify a native CLI archive using the Rust reader, keeping status separate.
use cfd_craft::output;
use std::path::PathBuf;

fn main() -> cfd_craft::Result<()> {
    let path = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or("CFD-U001 manual.archive.path: pass a native run directory")?;
    let verified =
        output::read_verified(&path).map_err(|e| format!("CFD-U001 manual.archive.path: {e}"))?;
    let summary = verified.summary;
    let accepted = matches!(
        summary.assessment.as_str(),
        "steady_discrete_solution" | "transient_interval_completed"
    );
    println!(
        "{}",
        serde_json::json!({"archive_consistent":true,
        "numerically_accepted":accepted,"assessment":summary.assessment,
        "termination":summary.termination,"omitted":verified.omitted,
        "source_sha256":summary.source_sha256,
        "experimental_validation":summary.experimental_validation})
    );
    Ok(())
}
