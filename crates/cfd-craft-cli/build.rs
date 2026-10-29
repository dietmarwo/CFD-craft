//! Embeds a fingerprint of the workspace sources and the compiler version.
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};
fn collect(path: &Path, files: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(path) else {
        return;
    };
    for entry in entries.flatten() {
        let p = entry.path();
        if p.is_dir() {
            collect(&p, files)
        } else if p.extension().is_some_and(|e| e == "rs" || e == "toml") {
            files.push(p);
        }
    }
}
fn main() {
    // The workspace root, independent of the directory cargo runs the script from.
    let manifest = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap());
    let root = manifest.join("../..");
    let mut paths = vec![];
    collect(&root.join("crates"), &mut paths);
    for name in ["Cargo.toml", "Cargo.lock"] {
        if root.join(name).exists() {
            paths.push(root.join(name));
        }
    }
    paths.sort();
    // A directory makes cargo rerun this script when any file below it changes,
    // including files added after the last build.
    println!("cargo:rerun-if-changed={}", root.join("crates").display());
    println!(
        "cargo:rerun-if-changed={}",
        root.join("Cargo.toml").display()
    );
    println!(
        "cargo:rerun-if-changed={}",
        root.join("Cargo.lock").display()
    );
    let mut hash = Sha256::new();
    for p in paths {
        // Length-prefixed, '/'-separated relative path, then length-prefixed contents.
        let name = p
            .strip_prefix(&root)
            .unwrap()
            .components()
            .map(|c| c.as_os_str().to_string_lossy())
            .collect::<Vec<_>>()
            .join("/");
        let bytes = fs::read(&p).unwrap();
        hash.update((name.len() as u64).to_le_bytes());
        hash.update(name.as_bytes());
        hash.update((bytes.len() as u64).to_le_bytes());
        hash.update(&bytes);
    }
    println!("cargo:rustc-env=CFD_SOURCE_SHA={:x}", hash.finalize());
    let rustc = Command::new(std::env::var("RUSTC").unwrap_or("rustc".into()))
        .arg("--version")
        .output()
        .unwrap();
    println!(
        "cargo:rustc-env=CFD_RUSTC={}",
        String::from_utf8_lossy(&rustc.stdout).trim()
    );
}
