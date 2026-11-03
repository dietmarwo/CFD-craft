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
    // Cargo puts its normalized lockfile inside a packaged crate. A checkout
    // uses the workspace lockfile. Never traverse unrelated sibling sources.
    let local = root.join("Cargo.lock");
    let lock = if local.is_file() {
        local
    } else {
        root.join("../../Cargo.lock")
    };
    println!("cargo:rerun-if-changed={}", lock.display());
    let bytes = fs::read(&lock).expect("committed or packaged Cargo.lock");
    hash.update((bytes.len() as u64).to_le_bytes());
    hash.update(bytes);
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
