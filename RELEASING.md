# Release preparation: 0.1.0

The native solver is a research prototype. Experimental canyon validation,
measured-data access and successful finer-grid/domain evidence remain open.
An experimental package release does not claim physical qualification.

The manifests and workflows prepare a release; they do not assert that packages
have been published. The repository's full CI remains a prerequisite. Run all
checks from a clean checkout with committed lockfiles. Do not rewrite historical
measurement versions or relax scientific acceptance thresholds for packaging.

## Local acceptance

```sh
python scripts/check_release.py --version 0.1.0
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --release --workspace --locked
python -m pip install maturin==1.9.6
maturin build --release --locked --out dist
python -m pip install dist/*.whl
python -I validation/check_installed.py --output installed.json
python -I -O validation/check_installed.py --output installed-optimized.json
diff installed.json installed-optimized.json
maturin sdist --out dist
python scripts/check_sdist.py dist/*.tar.gz --output release-check/sdist
```

Use Python 3.12 for the release scripts. Also run the installed checker from a
directory outside the checkout. The sdist script does this in a fresh environment.
The extracted sdist contains its own source, lockfiles and installed checker.

Use current stable Cargo for multi-crate packaging:

```sh
cargo +stable package --workspace --locked
```

This stages the mutually dependent workspace crates before verification. Older
Cargo versions may try to resolve the unpublished dependency on crates.io;
that packaging-tool limitation does not change the engine MSRV.
The `.crate` files contain normalized manifests, licenses, package readmes and
buildable sources. Fixture-based regression suites run from the repository;
the crate archives are verified with Cargo's independent build step.

## Build matrix and publication

`.github/workflows/release.yml` is manual. Dispatch with `version=0.1.0` and
`publish=false` first. It runs the full existing CI, Cargo package verification,
sdist round-trip and installed acceptance for Linux x86_64, macOS arm64 and
Windows x86_64 on Python 3.10, 3.12 and 3.14. Linux wheels use manylinux2014.
The ABI3 tag is a compatibility claim to test, not evidence of every platform.
Download the source, wheel and acceptance artifacts and review the logs.

For publication, the repository owner must configure:

- PyPI's pending trusted publisher for `cfd-craft`, owner `dietmarwo`, repository
  `CFD-craft`, workflow `release.yml`, GitHub environment `pypi`.
- A `crates-io` GitHub environment with `CARGO_REGISTRY_TOKEN`, scoped to the
  intended packages. Reserve/check ownership at release time; availability checks
  do not reserve registry names.

Commit the reviewed changes and lockfiles, tag that commit `v0.1.0`, push it,
then dispatch **that tag** with `publish=true`. The workflow refuses publication
from a branch or mismatching version, and uploads only after all prerequisite
jobs pass. PyPI uses short-lived OIDC credentials. Crates are published in order:
cfd-craft, cfd-craft-cli. Cargo waits for index visibility between uploads.

Publication is not atomic across registries. If an upload partially succeeds,
inspect registry versions before continuing; do not bump or republish blindly.
After publication, smoke-test fresh `pip install` and `cargo install --locked`
from the registries. Create the GitHub release using [RELEASE_NOTES.md](RELEASE_NOTES.md)
and attach artifacts/checksums. A local candidate bundle is not a published release.

## Provenance and scope

Record commit, toolchain, archive SHA-256 and installed acceptance reports.
Packaged Cargo.lock files are normalized by Cargo and can differ from workspace
lockfiles. Build identities correctly reflect the selected file. Numerical
comparisons exclude elapsed time and build provenance, not failed simulations.
Optional integrations remain source packages, with independent lockfiles and
checks. MIT project licensing does not relicense dependencies or reference data.
