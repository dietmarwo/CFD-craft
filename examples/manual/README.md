# User-manual examples

The case and the programs that the [guide](../../docs/guide/README.md) runs.
Run commands from the repository root, build with the lockfiles and choose new
output names.

```sh
cargo build --release --workspace --locked
cargo build --release --workspace --examples --locked
python -m pip install -r requirements-validation.txt
mkdir -p runs
python scripts/check_docs.py --smoke
```

The last command runs the code blocks of the guide and the READMEs and compares
their outputs; [the developer pages](../../docs/developer/README.md) describe it.
`python validation/manual_examples.py --output NEW_DIRECTORY` still runs these
files as a fixed suite of 11 native steps, and with `--foam-root ROOT` the 8
OpenFOAM steps. Both are API and numerical verification, not experimental
validation.

| File | Used in | Standalone command |
|---|---|---|
| [point-source.json](point-source.json) | [Chapter 1](../../docs/guide/01-first-run.md), [chapter 3](../../docs/guide/03-cli-and-archive.md) and most native chapters | `target/release/cfd-craft run examples/manual/point-source.json --output runs/point` |
| [cli_workflow.py](cli_workflow.py) | [Chapter 11](../../docs/guide/11-python.md#the-whole-native-workflow-in-one-script) | `python examples/manual/cli_workflow.py --output runs/cli` |
| [manual_library.rs](../../crates/cfd-craft/examples/manual_library.rs) | [Chapter 20](../../docs/guide/20-rust-library.md#solve-in-process) | `cargo run --release --locked -p cfd-craft --example manual_library` |
| [manual_control.rs](../../crates/cfd-craft/examples/manual_control.rs) | [Chapter 20](../../docs/guide/20-rust-library.md#cancellation-and-deadlines) | `cargo run --release --locked -p cfd-craft --example manual_control` |
| [manual_checkpoint.rs](../../crates/cfd-craft/examples/manual_checkpoint.rs) | [Chapter 20](../../docs/guide/20-rust-library.md#checkpoint-round-trip) | `cargo run --release --locked -p cfd-craft --example manual_checkpoint -- runs/checkpoint.json` |
| [manual_archive.rs](../../crates/cfd-craft/examples/manual_archive.rs) | [Chapter 20](../../docs/guide/20-rust-library.md#read-a-cli-archive) | `cargo run --release --locked -p cfd-craft --example manual_archive -- runs/point` |
| [openfoam_api.py](openfoam_api.py) | [Chapter 15](../../docs/guide/15-openfoam-first-run.md#use-the-adapter-from-python) | `python examples/manual/openfoam_api.py --foam-root ROOT --output runs/foam-api` |

The OpenFOAM example is optional and needs the pinned Foundation 13 runtime of
[chapter 15](../../docs/guide/15-openfoam-first-run.md). The Rust examples
configure their own Rayon pool; the checkpoint example writes a checkpoint
file, not a run directory.
