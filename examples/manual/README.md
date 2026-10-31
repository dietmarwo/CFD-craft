# User-manual examples

Start with [the manual](../../docs/USER_MANUAL.md). Run commands from the
repository root, build with the lockfiles and choose new output names.

```sh
cargo build --release --workspace --locked
cargo build --release --workspace --examples --locked
python -m pip install -r requirements-validation.txt
mkdir -p runs
python validation/manual_examples.py --output runs/manual-examples
```

The small suite executes actual native CLI, Rust and Python calls. It verifies
source-rate units, linear source scaling, named receptor reads, cancelled and
incomplete results, unchanged physical endpoint on restart, exact resumed/cold
state equality, preview and VTK output. An incomplete native archive is read
successfully without becoming numerically accepted. The Python workflow is
run normally and under -O. This is API/numerical verification, not experimental
qualification. `manual.<field>` failures carry CFD-U001 and preserve logs.

| File | Standalone command |
|---|---|
| [point-source.json](point-source.json) | `target/release/cfd-craft run examples/manual/point-source.json --output runs/point` |
| [cli_workflow.py](cli_workflow.py) | `python examples/manual/cli_workflow.py --output runs/cli` |
| [manual_library.rs](../../crates/cfd-craft/examples/manual_library.rs) | `cargo run --release --locked -p cfd-craft --example manual_library` |
| [manual_control.rs](../../crates/cfd-craft/examples/manual_control.rs) | `cargo run --release --locked -p cfd-craft --example manual_control` |
| [manual_checkpoint.rs](../../crates/cfd-craft/examples/manual_checkpoint.rs) | `cargo run --release --locked -p cfd-craft --example manual_checkpoint -- runs/checkpoint.json` |
| [manual_archive.rs](../../crates/cfd-craft/examples/manual_archive.rs) | `cargo run --release --locked -p cfd-craft --example manual_archive -- runs/point` |
| [openfoam_api.py](openfoam_api.py) | `python examples/manual/openfoam_api.py --foam-root /path/to/openfoam13 --output runs/foam-api` |

The OpenFOAM example is separate and optional. It runs a bounded Foundation-13
cavity using the real source-checkout adapter API, with prepare/run/verify and
numerical assessment. Install the pinned runtime as described in
[OPENFOAM.md](../../integrations/OPENFOAM.md). It does not use the native run
schema, and its result must be inspected with the external verifier.

The Rust library examples configure their own Rayon pool. A bare solver result
has no CLI source/compiler fingerprint added by the caller; see the manual's
provenance section before publishing application archives. The checkpoint demo
writes a checkpoint file only, not a complete native run directory.
