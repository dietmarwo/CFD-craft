# CFD-craft for Python

A native Rust research solver for incompressible flow and passive-gas
dispersion, called in-process from Python 3.10 or newer. No NumPy, OpenFOAM or
subprocess is needed.

```bash
pip install cfd-craft
```

```python
import json
from pathlib import Path
import cfd_craft as cfd

case = json.loads(Path("case.json").read_text())
report = cfd.check(case)
if not report["valid"]:
    raise ValueError(report["diagnostics"])
result = cfd.simulate(case)
print(result["termination"], result["assessment"])
print(result["constituents"])
```

`check` runs the native CLI's strict parsing and preflight and returns coded
diagnostics with JSON paths. `simulate` releases the GIL, enforces the case's
work, wall-time and thread limits and returns the same summary schema as the
Rust CLI; incomplete calculations keep their termination and assessment. Use
`cancel_file=PATH` for cooperative cancellation; Ctrl-C stops the solver and
raises `KeyboardInterrupt`. `run.memory_limit_mib` is a preflight estimate,
and the host-memory refusal applies on Linux only.

`python -m cfd_craft describe`, `check CASE.json` and `simulate CASE.json` print
JSON; the `cfd-craft-python` console script does the same. Fields,
checksummed archives, restarts and profiles belong to the Rust CLI
(`cargo install cfd-craft-cli --locked`).

Version 0.1.0 is a research prototype: experimental canyon validation and a
successful fine-grid resolution study remain open, and a numerical acceptance
is not physical validation.

- [Python API, examples and limitations](https://github.com/dietmarwo/CFD-craft/blob/main/docs/PYTHON.md)
- [Repository, user manual and evidence](https://github.com/dietmarwo/CFD-craft)
- [Changelog](https://github.com/dietmarwo/CFD-craft/blob/main/CHANGELOG.md)

MIT licensed.
