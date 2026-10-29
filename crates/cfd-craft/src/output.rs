use crate::{
    Result,
    case::{Case, hash_bytes},
    grid::Grid,
    solver::{RunResult, State, Summary, validate_state},
};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::Write,
    path::Path,
};
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Checkpoint {
    schema_version: String,
    physics_sha256: String,
    payload_sha256: String,
    payload: String,
}
pub fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    let tmp = path.with_extension("partial");
    let mut f = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&tmp)
        .map_err(|e| e.to_string())?;
    f.write_all(bytes)
        .and_then(|()| f.sync_all())
        .map_err(|e| e.to_string())?;
    fs::rename(tmp, path).map_err(|e| e.to_string())
}
pub fn checkpoint_bytes(c: &Case, s: &State) -> Result<Vec<u8>> {
    let payload = serde_json::to_string(s).map_err(|e| e.to_string())?;
    serde_json::to_vec(&Checkpoint {
        schema_version: "cfd-craft.checkpoint/0.1".into(),
        physics_sha256: c.physics_hash(),
        payload_sha256: hash_bytes(payload.as_bytes()),
        payload,
    })
    .map_err(|e| e.to_string())
}
pub fn read_checkpoint(c: &Case, path: &Path) -> Result<State> {
    let unreadable = |e: String| format!("CFD-E065: checkpoint {}: {e}", path.display());
    let bytes = fs::read(path).map_err(|e| unreadable(e.to_string()))?;
    if bytes.len() > c.run.memory_limit_mib.saturating_mul(1048576) / 2 {
        return Err(unreadable(
            "larger than half of run.memory_limit_mib, the import budget".into(),
        ));
    }
    let v: Checkpoint = serde_json::from_slice(&bytes).map_err(|e| unreadable(e.to_string()))?;
    if v.schema_version != "cfd-craft.checkpoint/0.1"
        || v.physics_sha256 != c.physics_hash()
        || hash_bytes(v.payload.as_bytes()) != v.payload_sha256
    {
        return Err("CFD-E060: checkpoint identity or checksum mismatch".into());
    }
    let s: State = serde_json::from_str(&v.payload).map_err(|e| unreadable(e.to_string()))?;
    let g = Grid::build(c)?;
    validate_state(c, &g, &s)?;
    if s.steps > c.run.max_steps
        || (c.run.mode == crate::case::Mode::Transient
            && s.time_s > c.run.end_time_s * (1.0 + 1e-12))
    {
        return Err(
            "CFD-E066: the checkpoint lies beyond run.max_steps or run.end_time_s of the case"
                .into(),
        );
    }
    Ok(s)
}
/// Creates the run directory. A missing parent or an existing destination (including a
/// dangling symlink) is an error, so the solve never starts without a place for its results.
pub fn create_run_dir(out: &Path) -> Result<()> {
    if fs::symlink_metadata(out).is_ok() {
        return Err(format!("CFD-E062: output {} already exists", out.display()));
    }
    fs::create_dir(out).map_err(|e| match e.kind() {
        std::io::ErrorKind::NotFound => format!(
            "CFD-E063: the parent directory of output {} does not exist",
            out.display()
        ),
        _ => format!("CFD-E063: cannot create output {}: {e}", out.display()),
    })
}

/// Writes the artifacts into the run directory made by [`create_run_dir`]. The small
/// artifacts are always written; fields and checkpoint are omitted, and listed in the
/// manifest, when they would exceed the output budget. Returns the omitted names.
pub fn write_run(c: &Case, r: &RunResult, out: &Path, input_sha256: &str) -> Result<Vec<String>> {
    let budget = c.output.max_total_mib.saturating_mul(1048576);
    let mut files = BTreeMap::new();
    let mut omitted = BTreeMap::new();
    let mut total = 0usize;
    let mut put = |name: &str, bytes: Vec<u8>, optional: bool| -> Result<()> {
        let next = total
            .checked_add(bytes.len())
            .ok_or("output length overflow")?;
        if optional && next > budget {
            omitted.insert(
                name.to_string(),
                format!(
                    "CFD-E061: {} bytes would exceed the output budget of {} MiB",
                    bytes.len(),
                    c.output.max_total_mib
                ),
            );
            return Ok(());
        }
        total = next;
        atomic_write(&out.join(name), &bytes)?;
        files.insert(name.to_string(), hash_bytes(&bytes));
        Ok(())
    };
    put("case.json", serde_json::to_vec_pretty(c).unwrap(), false)?;
    put(
        "summary.json",
        serde_json::to_vec_pretty(&r.summary).unwrap(),
        false,
    )?;
    put(
        "geometry.json",
        serde_json::to_vec_pretty(&r.geometry).unwrap(),
        false,
    )?;
    let mut probes = String::from("constituent,receptor,concentration_kg_m3\n");
    for s in &r.summary.constituents {
        for (name, value) in &s.receptors_kg_m3 {
            // JSON-quoted strings are valid CSV quoted fields except escaped quotes; identifiers exclude controls in check.
            probes.push_str(&format!("{},{},{:.17e}\n", csv(&s.id), csv(name), value));
        }
    }
    put("probes.csv", probes.into_bytes(), false)?;
    if c.output.fields {
        put("fields.json", serde_json::to_vec(&r.state).unwrap(), true)?;
    }
    if c.output.checkpoint {
        put("checkpoint.json", checkpoint_bytes(c, &r.state)?, true)?;
    }
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let executable_sha256 = hash_bytes(&fs::read(executable).map_err(|e| e.to_string())?);
    let omitted_names: Vec<String> = omitted.keys().cloned().collect();
    let manifest = serde_json::to_vec_pretty(&serde_json::json!({
        "schema_version":MANIFEST_SCHEMA,"files":files,"omitted":omitted,
        "input_case_sha256":input_sha256,
        "source_sha256":r.summary.source_sha256,"version":r.summary.build_version,
        "initial_state_sha256":r.summary.initial_state_sha256,
        "executable_sha256":executable_sha256,
        "bytes_before_manifest":total,"threads":c.run.threads,
        "architecture":std::env::consts::ARCH,"os":std::env::consts::OS
    }))
    .unwrap();
    atomic_write(&out.join("manifest.json"), &manifest)?;
    atomic_write(
        &out.join("complete.json"),
        &serde_json::to_vec(&serde_json::json!({"manifest_sha256":hash_bytes(&manifest)})).unwrap(),
    )?;
    File::open(out)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())?;
    Ok(omitted_names)
}
const MANIFEST_SCHEMA: &str = "cfd-craft.manifest/0.1";
const ARTIFACTS: [&str; 6] = [
    "summary.json",
    "case.json",
    "geometry.json",
    "probes.csv",
    "fields.json",
    "checkpoint.json",
];
fn csv(s: &str) -> String {
    format!("\"{}\"", s.replace('"', "\"\""))
}
fn read_regular(path: &Path) -> Result<Vec<u8>> {
    let meta = fs::symlink_metadata(path).map_err(|e| format!("{}: {e}", path.display()))?;
    if !meta.file_type().is_file() {
        return Err(format!("{}: not a regular file", path.display()));
    }
    fs::read(path).map_err(|e| format!("{}: {e}", path.display()))
}
/// Verifies a run directory: completion marker, manifest, every listed artifact, no
/// unlisted entries, the artifacts the case requested, and the identities that the
/// summary, case and manifest share.
/// A verified archive: its summary and the artifacts the manifest lists as omitted.
pub struct Verified {
    pub summary: Summary,
    pub omitted: Vec<String>,
}

/// Verifies a run directory. Errors are not coded here; the CLI reports them as CFD-E064.
pub fn read_verified(out: &Path) -> Result<Verified> {
    let marker: serde_json::Value =
        serde_json::from_slice(&read_regular(&out.join("complete.json"))?)
            .map_err(|e| format!("complete.json: {e}"))?;
    let m = read_regular(&out.join("manifest.json"))?;
    if marker["manifest_sha256"].as_str() != Some(&hash_bytes(&m)) {
        return Err("manifest checksum mismatch".into());
    }
    let manifest: serde_json::Value =
        serde_json::from_slice(&m).map_err(|e| format!("manifest.json: {e}"))?;
    if manifest["schema_version"] != MANIFEST_SCHEMA {
        return Err("manifest.json: unsupported schema_version".into());
    }
    let files = manifest["files"]
        .as_object()
        .ok_or("invalid manifest files")?;
    let omitted = manifest
        .get("omitted")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();
    for name in ["summary.json", "case.json", "geometry.json", "probes.csv"] {
        if !files.contains_key(name) {
            return Err(format!("manifest lacks required artifact {name}"));
        }
    }
    for (name, sha) in files {
        if !ARTIFACTS.contains(&name.as_str()) {
            return Err(format!("unknown artifact name {name}"));
        }
        if sha.as_str() != Some(&hash_bytes(&read_regular(&out.join(name))?)) {
            return Err(format!("{name}: checksum mismatch"));
        }
    }
    for entry in fs::read_dir(out).map_err(|e| e.to_string())? {
        let name = entry.map_err(|e| e.to_string())?.file_name();
        let name = name.to_string_lossy();
        if name != "manifest.json" && name != "complete.json" && !files.contains_key(&*name) {
            return Err(format!("unlisted entry {name} in the run directory"));
        }
    }
    let case: Case = serde_json::from_slice(&read_regular(&out.join("case.json"))?)
        .map_err(|e| format!("case.json: {e}"))?;
    for (wanted, name) in [
        (case.output.fields, "fields.json"),
        (case.output.checkpoint, "checkpoint.json"),
    ] {
        if wanted && !files.contains_key(name) && !omitted.contains_key(name) {
            return Err(format!("{name} was requested by the case but is missing"));
        }
    }
    let summary: Summary = serde_json::from_slice(&read_regular(&out.join("summary.json"))?)
        .map_err(|e| format!("summary.json: {e}"))?;
    if summary.case_sha256 != hash_bytes(&serde_json::to_vec(&case).unwrap())
        || summary.physics_sha256 != case.physics_hash()
    {
        return Err("summary.json does not describe case.json".into());
    }
    if manifest["initial_state_sha256"] != summary.initial_state_sha256.as_str()
        || manifest["source_sha256"] != summary.source_sha256.as_str()
    {
        return Err("manifest.json and summary.json disagree on identity".into());
    }
    Ok(Verified {
        summary,
        omitted: omitted.keys().cloned().collect(),
    })
}
