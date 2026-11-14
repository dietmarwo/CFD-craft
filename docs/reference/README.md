# Reference

Look-up pages. They state facts and do not teach; the guide does that.

Three pages and two blocks of the command line page are generated from the code by
[`scripts/generate_reference.py`](https://github.com/dietmarwo/CFD-craft/blob/main/scripts/generate_reference.py)
(`--check` fails when a committed page differs from the current build, and when
a `CFD-` code in the Rust or Python sources is missing from the diagnostics
catalog). Do not edit generated text by hand.

| Page | Made how | What it holds |
|---|---|---|
| [Case schema](case-schema.md) | generated from `cfd-craft describe` | Every field of a case file: type, required or default, description |
| [Result schema](result-schema.md) | generated from `describe` | Fields of `summary.json` and of the phase profile |
| [Python API](python-api.md) | generated from the docstrings | `describe`, `check`, `simulate`, `CfdError` and the console script |
| [Command line](cli.md) | hand-written, with two generated blocks | Each `cfd-craft` command: inputs, outputs, exit codes |
| [Units and conventions](units-and-conventions.md) | hand-written | Units, coordinates, wind direction, array ordering |
| [Scripts](scripts.md) | hand-written | The Python tools: arguments and exit codes |

Reference pages that live one level up:

- [Diagnostics](../diagnostics.md): the code catalog.
- [Result contract](../result-contract.md): status words, files of a run, what `report` checks.
- [Model cards](../model-cards/README.md): model scope and evidence.

The Rust API is on [docs.rs](https://docs.rs/cfd-craft).
