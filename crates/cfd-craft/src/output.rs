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
    let bytes = fs::read(path).map_err(|e| e.to_string())?;
    if bytes.len() > c.run.memory_limit_mib.saturating_mul(1048576) / 2 {
        return Err("checkpoint exceeds import budget".into());
    }
    let v: Checkpoint = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
    if v.schema_version != "cfd-craft.checkpoint/0.1"
        || v.physics_sha256 != c.physics_hash()
        || hash_bytes(v.payload.as_bytes()) != v.payload_sha256
    {
        return Err("CFD-E060: checkpoint identity or checksum mismatch".into());
    }
    let s: State = serde_json::from_str(&v.payload).map_err(|e| e.to_string())?;
    let g = Grid::build(c)?;
    validate_state(c, &g, &s)?;
    if s.steps > c.run.max_steps
        || (c.run.mode == crate::case::Mode::Transient
            && s.time_s > c.run.end_time_s * (1.0 + 1e-12))
    {
        return Err("checkpoint lies beyond requested work/physical horizon".into());
    }
    Ok(s)
}
pub fn write_run(c: &Case, r: &RunResult, out: &Path) -> Result<()> {
    fs::create_dir(out).map_err(|e| format!("Output must be a new directory: {e}"))?;
    let mut files = BTreeMap::new();
    let mut total = 0usize;
    let mut put = |name: &str, bytes: Vec<u8>| -> Result<()> {
        total = total
            .checked_add(bytes.len())
            .ok_or("output length overflow")?;
        if total > c.output.max_total_mib.saturating_mul(1048576) {
            return Err("CFD-E061: actual output exceeded budget".into());
        }
        atomic_write(&out.join(name), &bytes)?;
        files.insert(name.to_string(), hash_bytes(&bytes));
        Ok(())
    };
    put("case.json", serde_json::to_vec_pretty(c).unwrap())?;
    put(
        "summary.json",
        serde_json::to_vec_pretty(&r.summary).unwrap(),
    )?;
    put(
        "geometry.json",
        serde_json::to_vec_pretty(&r.geometry).unwrap(),
    )?;
    let mut probes = String::from("constituent,receptor,concentration_kg_m3\n");
    for s in &r.summary.constituents {
        for (name, value) in &s.receptors_kg_m3 {
            // JSON-quoted strings are valid CSV quoted fields except escaped quotes; identifiers exclude controls in check.
            probes.push_str(&format!("{},{},{:.17e}\n", csv(&s.id), csv(name), value));
        }
    }
    put("probes.csv", probes.into_bytes())?;
    if c.output.fields {
        put("fields.json", serde_json::to_vec(&r.state).unwrap())?;
    }
    if c.output.checkpoint {
        put("checkpoint.json", checkpoint_bytes(c, &r.state)?)?;
    }
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let executable_sha256 = hash_bytes(&fs::read(executable).map_err(|e| e.to_string())?);
    let manifest = serde_json::to_vec_pretty(&serde_json::json!({
        "schema_version":"cfd-craft.manifest/0.1","files":files,
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
        .map_err(|e| e.to_string())
}
fn csv(s: &str) -> String {
    format!("\"{}\"", s.replace('"', "\"\""))
}
pub fn read_verified(out: &Path) -> Result<Summary> {
    let marker: serde_json::Value =
        serde_json::from_slice(&fs::read(out.join("complete.json")).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    let m = fs::read(out.join("manifest.json")).map_err(|e| e.to_string())?;
    if marker["manifest_sha256"].as_str() != Some(&hash_bytes(&m)) {
        return Err("manifest checksum mismatch".into());
    }
    let manifest: serde_json::Value = serde_json::from_slice(&m).map_err(|e| e.to_string())?;
    let files = manifest["files"]
        .as_object()
        .ok_or("invalid manifest files")?;
    if !files.contains_key("summary.json") || !files.contains_key("case.json") {
        return Err("missing required manifest records".into());
    }
    for (name, sha) in files {
        if !matches!(
            name.as_str(),
            "summary.json"
                | "case.json"
                | "geometry.json"
                | "probes.csv"
                | "fields.json"
                | "checkpoint.json"
        ) {
            return Err("unknown artifact name".into());
        }
        let path = out.join(name);
        if fs::symlink_metadata(&path)
            .map_err(|e| e.to_string())?
            .file_type()
            .is_symlink()
        {
            return Err("symlink artifact rejected".into());
        }
        if sha.as_str() != Some(&hash_bytes(&fs::read(path).map_err(|e| e.to_string())?)) {
            return Err(format!("{name}: checksum mismatch"));
        }
    }
    serde_json::from_slice(&fs::read(out.join("summary.json")).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())
}
