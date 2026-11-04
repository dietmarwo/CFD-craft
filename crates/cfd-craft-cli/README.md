# cfd-craft-cli

The native command-line interface of
[CFD-craft](https://github.com/dietmarwo/CFD-craft), installed as `cfd-craft`:

```sh
cargo install cfd-craft-cli --locked
cfd-craft describe
cfd-craft check CASE.json
cfd-craft run CASE.json --output NEW_DIR
cfd-craft report NEW_DIR
```

Every command reads and writes JSON. `run` writes a checksummed archive (case,
summary, geometry, fields, checkpoint) that `report` verifies; `check` reports
coded diagnostics with JSON paths before anything runs; `preview`, `profile`
and `verify` run coarsened previews, profiled runs and a pressure-solver
verification fixture.

The library is [`cfd-craft`](https://crates.io/crates/cfd-craft); the Python
package is [`cfd-craft` on PyPI](https://pypi.org/project/cfd-craft/). Version
0.1.0 is a research prototype: experimental canyon validation and a successful
fine-grid resolution study remain open, and numerical acceptance is not
physical validation. Builds from crates.io use Cargo's default release profile
rather than the repository's thin-LTO profile; numerical results are the same,
timings can differ from the recorded ones. See the
[repository](https://github.com/dietmarwo/CFD-craft) for the user manual and
evidence. MIT licensed.
