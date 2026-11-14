# Releasing

One tag publishes every registry artifact with the workspace version:

| Registry | Package | Workflow |
|---|---|---|
| PyPI | `cfd-craft` (abi3 wheels for Linux x86_64, Windows x64, macOS x86_64 and arm64, plus the source distribution) | `python-release.yml` |
| crates.io / docs.rs | `cfd-craft`, `cfd-craft-cli` (binary `cfd-craft`) | `publish-crates.yml` |

The Python binding (`bindings/python`, Rust 1.88) and the optional
`fcmaes-cfd-worker` are separate workspaces with `publish = false`. The version
is set in `[workspace.package]` of `Cargo.toml`, in `[package]` of
`bindings/python/Cargo.toml` and in `pyproject.toml`;
`scripts/package_version.py` fails when they disagree (Cargo's `0.2.0-dev.1`
equals Python's `0.2.0.dev1`). `scripts/check_release.py` adds the crate
checks: publishable members inheriting the version, a description, a README and
a LICENSE identical to the root one, versioned path dependencies, and the
version recorded in every lockfile that contains a CFD-craft crate. Both report
failures as `CFD-R001 release.<field>`. Publication is irreversible: never
reuse a version. MIT project licensing does not relicense dependencies or
reference data.

A package release is not physical qualification. 0.1.0 is a research
prototype: experimental canyon validation (blocked by access to raw benchmark
data) and a successful fine-grid resolution study remain open.

## One-time setup

1. Create a GitHub environment named `release`. Restrict its deployment
   branches and tags to `v*` tags and, if releases should need approval, add a
   required reviewer: the environment holds the crates.io token.
2. PyPI: create a pending Trusted Publisher for project `cfd-craft`: owner
   `dietmarwo`, repository `CFD-craft`, workflow `python-release.yml`,
   environment `release`. The first tag then creates the project.
3. crates.io: the first version must be published with an API token, because
   crates.io accepts a Trusted Publisher only for an existing crate. On
   crates.io, Account Settings → API Tokens, create a token with the scopes
   `publish-new` and `publish-update`, restricted to `cfd-craft*`, with a short
   expiry, and add it as the secret `CARGO_REGISTRY_TOKEN` of the `release`
   environment. The tag then publishes `cfd-craft` and `cfd-craft-cli` in that
   order, skipping versions already on crates.io, so rerunning the job
   completes a partial upload. A tag run without a token and without Trusted
   Publishing fails instead of skipping. After the first upload, delete the
   secret, revoke the token, configure a Trusted Publisher for each crate
   (owner `dietmarwo`, repository `CFD-craft`, workflow `publish-crates.yml`,
   environment `release`) and set the repository variable
   `CRATES_IO_TRUSTED_PUBLISHING` to `true`.

## Qualification before a release

From a clean checkout with committed lockfiles:

1. Run fmt, clippy, the Rust tests and the Python CLI tests in normal and
   optimized mode; `python3 scripts/check_release.py`.
2. Reproduce the analytic flow/transport, cavity, independent sparse-reference
   and empty-ABL results.
3. Reproduce the canonical canyon smoke and sensitivity cases. Keep every
   failed refinement case.
4. Record the actual executable and source fingerprints, compiler,
   initial-state identity and dependency versions.
5. Check the input/output schemas and all documented examples.
6. Build and test the optional worker independently and check actual runner
   result states.
7. Package the crates and the Python distribution:

```sh
cargo publish -p cfd-craft -p cfd-craft-cli --dry-run --locked
python -m pip install maturin==1.9.6
maturin build --release --locked --out dist
python -m venv /tmp/cfd-check && /tmp/cfd-check/bin/python -m pip install dist/*.whl
cd /tmp && /tmp/cfd-check/bin/python -I /path/to/CFD-craft/validation/check_installed.py --output installed.json
```

The dry run packages both crates and builds each from its own archive (current
stable Cargo stages the unpublished dependency); CI runs `cargo package
--workspace --locked` on every push. A packaged crate carries its own normalized
`Cargo.lock`, so its source fingerprint differs from a checkout build's. Builds
from crates.io use Cargo's default release profile instead of the workspace's
thin-LTO profile: numerical results are the same, timings can differ from
[validation/RESULTS.md](docs/evidence/native-verification.md).

`publish-crates.yml` runs the Rust checks and the dry run on pull requests that
touch the crates and on every tag. `python-release.yml` builds the four wheels
and the source distribution and runs `validation/check_installed.py` outside the
checkout on CPython 3.10 and 3.14, normally and under `-O`, on pull requests
that touch the packaging, manually and on tags; only a tag publishes.

Before a physically validated canyon release, additionally acquire authorized
measured data, reconstruct the exact setup, freeze the sample/threshold
protocol before held-out evaluation, and obtain successful grid/domain studies
with uncertainty appropriate to the claimed effect.

## Tag and publish

Merge the release pull request, then GitHub → Releases → Draft a new release →
new tag `vX.Y.Z` on `main` → publish. The tag push starts `python-release.yml`
and `publish-crates.yml`; both refuse a tag that does not equal `v` plus the
version. From a computer:

```bash
version="$(python3 scripts/package_version.py)"
git tag -a "v$version" -m "Release CFD-craft $version"
git push origin "v$version"
```

Hosted macOS arm64 runners are sometimes unavailable: a job then waits, is
cancelled after about 15 minutes without running a step, and the publish job
that depends on it is skipped. `retry-runner-shortage.yml` notices such a run
and reruns its failed jobs, up to three attempts in total. It leaves real
failures and runs cancelled by a person alone. If the last attempt still
finds no runner, rerun the failed jobs by hand (Actions → the run → Re-run
failed jobs); never re-tag.

Publication is not atomic across registries. If one workflow fails, inspect
the registry versions and rerun only that workflow; never bump or republish a
version blindly.

## Post-release verification

```bash
python -m venv /tmp/cfd-craft-check
/tmp/cfd-craft-check/bin/python -m pip install cfd-craft
cd /tmp && /tmp/cfd-craft-check/bin/python -I /path/to/CFD-craft/validation/check_installed.py --output installed.json
cargo install cfd-craft-cli --version "$version" --locked && cfd-craft describe
```

Check the PyPI page (its description is `python/README.md`), the crate pages
and docs.rs.
