# cfd-craft

The core library of [CFD-craft](https://github.com/dietmarwo/CFD-craft): a
bounded CPU research solver for incompressible Cartesian flow and passive-gas
dispersion, built to be driven and checked by agents.

- Staggered finite volumes with matrix-free pressure projection (IC(0) or
  multigrid), laminar flow and one neutral k–epsilon package, explicit or
  implicit steady pseudo-time.
- Passive transport with point, line and volume sources and receptors.
- Strict case and result schemas, explicit work, time, memory and output
  budgets, cooperative cancellation and independent result checks.

```toml
[dependencies]
cfd-craft = "0.1"
```

The command-line interface (fields, checksummed run archives, restarts,
profiles) is the [`cfd-craft-cli`](https://crates.io/crates/cfd-craft-cli)
crate (`cargo install cfd-craft-cli --locked`); the Python package is
[`cfd-craft` on PyPI](https://pypi.org/project/cfd-craft/).

Version 0.1.0 is a research prototype. A numerically accepted run is not an
experimentally validated prediction. Experimental canyon validation (blocked by
access to raw benchmark data) and a successful fine-grid resolution study
remain open.

- [The Rust library](https://dietmarwo.github.io/CFD-craft/guide/20-rust-library.html):
  solve in process, cancellation, checkpoints, reading a CLI archive
- [Result contract](https://dietmarwo.github.io/CFD-craft/result-contract.html)
- [Documentation](https://dietmarwo.github.io/CFD-craft/): guide, reference,
  model cards and evidence
- [Repository](https://github.com/dietmarwo/CFD-craft)

MIT licensed.
