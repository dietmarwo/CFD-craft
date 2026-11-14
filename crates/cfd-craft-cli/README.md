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
package is [`cfd-craft` on PyPI](https://pypi.org/project/cfd-craft/). Builds
from crates.io use Cargo's default release profile rather than the
repository's thin-LTO profile; numerical results are the same, timings can
differ from the recorded ones.

Version 0.1.1 is a research prototype. A numerically accepted run is not an
experimentally validated prediction. Experimental canyon validation and a
successful fine-grid resolution study remain open.

- [The command line and the run archive](https://dietmarwo.github.io/CFD-craft/guide/03-cli-and-archive.html)
- [Command line reference](https://dietmarwo.github.io/CFD-craft/reference/cli.html)
- [Diagnostics](https://dietmarwo.github.io/CFD-craft/diagnostics.html)
- [Documentation](https://dietmarwo.github.io/CFD-craft/) and
  [repository](https://github.com/dietmarwo/CFD-craft)

MIT licensed.
