# CFD-craft for Python

A native Rust research solver for incompressible flow and passive-gas dispersion.
Python 3.10 or newer; no NumPy, OpenFOAM or subprocess is required by this binding.
This is experimental research software; canyon physical validation remains open.

After publication: `python -m pip install cfd-craft==0.1.0`.
Before publication, install a prepared wheel with `python -m pip install PATH.whl`.

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

`simulate` releases the GIL and honors the case's work, wall-time, memory and
thread limits. It returns the same summary schema as the Rust CLI. Incomplete
calculations retain their termination and assessment. Use `cancel_file=PATH`
for cooperative cancellation; Ctrl-C stops the worker and raises KeyboardInterrupt.

`python -m cfd_craft describe`, `check CASE.json` and `simulate CASE.json` provide
JSON output. The distinct `cfd-craft-python` console script does the same.
Use the Rust `cfd-craft` CLI for fields, checksummed archives, restarts and profiles;
it is distributed separately as `cfd-craft-cli` on crates.io.

[API, examples and limitations](https://github.com/dietmarwo/CFD-craft/blob/main/docs/PYTHON.md).
