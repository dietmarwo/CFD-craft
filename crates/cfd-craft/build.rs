//! Fingerprint only this package's sources; works in a checkout or .crate.
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};
fn collect(path: &Path, files: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(path).expect("source directory") {
        let p = entry.expect("source entry").path();
        if p.is_dir() {
            collect(&p, files);
        } else if p.extension().is_some_and(|e| e == "rs") {
            files.push(p);
        }
    }
}
/// True when `workspace` is the CFD-craft root workspace that lists this crate.
fn is_root_workspace(workspace: &Path, root: &Path) -> bool {
    let Ok(manifest) = fs::read_to_string(workspace.join("Cargo.toml")) else {
        return false;
    };
    let member = format!(
        "crates/{}",
        root.file_name().unwrap_or_default().to_string_lossy()
    );
    manifest.contains("[workspace]")
        && manifest.contains(&format!("\"{member}\""))
        && workspace.join("Cargo.lock").is_file()
}
fn main() {
    let root = PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let mut files = vec![root.join("Cargo.toml"), root.join("build.rs")];
    collect(&root.join("src"), &mut files);
    files.sort();
    println!("cargo:rerun-if-changed=src");
    let mut hash = Sha256::new();
    for p in files {
        println!("cargo:rerun-if-changed={}", p.display());
        let name = p
            .strip_prefix(&root)
            .unwrap()
            .components()
            .map(|c| c.as_os_str().to_string_lossy())
            .collect::<Vec<_>>()
            .join("/");
        let bytes = fs::read(&p).expect("source bytes");
        hash.update((name.len() as u64).to_le_bytes());
        hash.update(name.as_bytes());
        hash.update((bytes.len() as u64).to_le_bytes());
        hash.update(bytes);
    }
    // A packaged crate (or the separate binding workspace) carries its own
    // lockfile. In a checkout the crate belongs to the root workspace, whose
    // manifest (dependency features, release profile) and lockfile are part
    // of the build, so both are hashed. Anything else is hashed as "no lock"
    // rather than read from an unrelated directory.
    let local = root.join("Cargo.lock");
    let workspace = root.join("../..");
    let inputs = if local.is_file() {
        vec![local]
    } else if is_root_workspace(&workspace, &root) {
        vec![workspace.join("Cargo.toml"), workspace.join("Cargo.lock")]
    } else {
        Vec::new()
    };
    if inputs.is_empty() {
        hash.update(b"no-lockfile");
    }
    for p in inputs {
        println!("cargo:rerun-if-changed={}", p.display());
        let bytes = fs::read(&p).expect("workspace manifest or lockfile");
        hash.update((bytes.len() as u64).to_le_bytes());
        hash.update(bytes);
    }
    println!("cargo:rustc-env=CFD_SOURCE_SHA={:x}", hash.finalize());
    let output = Command::new(std::env::var_os("RUSTC").unwrap())
        .arg("--version")
        .output()
        .unwrap();
    assert!(output.status.success());
    println!(
        "cargo:rustc-env=CFD_RUSTC={}",
        String::from_utf8(output.stdout).unwrap().trim()
    );
}
