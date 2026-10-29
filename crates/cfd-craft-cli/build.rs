use sha2::{Digest, Sha256};
use std::{fs, path::Path, process::Command};
fn collect(path: &Path, files: &mut Vec<std::path::PathBuf>) {
    for entry in fs::read_dir(path).unwrap() {
        let p = entry.unwrap().path();
        if p.is_dir() {
            collect(&p, files)
        } else if p.extension().is_some_and(|e| e == "rs" || e == "toml") {
            files.push(p);
        }
    }
}
fn main() {
    let root = Path::new("../..");
    let mut paths = vec![];
    collect(&root.join("crates"), &mut paths);
    paths.push(root.join("Cargo.toml"));
    if root.join("Cargo.lock").exists() {
        paths.push(root.join("Cargo.lock"));
    }
    paths.sort();
    let mut hash = Sha256::new();
    for p in paths {
        println!("cargo:rerun-if-changed={}", p.display());
        hash.update(p.strip_prefix(root).unwrap().to_string_lossy().as_bytes());
        hash.update(fs::read(p).unwrap());
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
