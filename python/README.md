# CFD-craft for Python
<!-- check: rel=1e-4 -->

A native Rust research solver for incompressible flow and passive-gas
dispersion, called in-process from Python 3.10 or newer. No NumPy, OpenFOAM or
subprocess is needed.

```sh
python -m pip install cfd-craft
```

The example loads the small
[point-source case](https://github.com/dietmarwo/CFD-craft/blob/main/examples/manual/point-source.json)
of the guide (prescribed flow, one tracer, one downstream receptor) directly
from GitHub:

```python
import json
import urllib.request
import cfd_craft as cfd

URL = (
    "https://raw.githubusercontent.com/dietmarwo/CFD-craft/main/"
    "examples/manual/point-source.json"
)
with urllib.request.urlopen(URL, timeout=30) as response:
    case = json.load(response)
report = cfd.check(case)
if not report["valid"]:
    raise ValueError(report["diagnostics"])
result = cfd.simulate(case)
print(result["termination"], result["assessment"])
tracer = next(c for c in result["constituents"] if c["id"] == "tracer")
print(f"{tracer['receptors_kg_m3']['R_down'] * 1e9:.6g} micrograms/m3")
```

```text
completed steady_discrete_solution
17.8118 micrograms/m3
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

To keep a local copy, download it once (for example
`curl -O https://raw.githubusercontent.com/dietmarwo/CFD-craft/main/examples/manual/point-source.json`)
and load it with `case = json.loads(Path("point-source.json").read_text())`
after `from pathlib import Path`. `check` and `simulate` also accept a JSON
string or bytes.

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

Version 0.1.1 is a research prototype. A numerically accepted run is not an
experimentally validated prediction. Experimental canyon validation and a
successful fine-grid resolution study remain open.

- [First run](https://dietmarwo.github.io/CFD-craft/guide/01-first-run.html)
- [Python: inputs, errors, cancellation, threads](https://dietmarwo.github.io/CFD-craft/guide/11-python.html)
- [Python API reference](https://dietmarwo.github.io/CFD-craft/reference/python-api.html)
- [Documentation](https://dietmarwo.github.io/CFD-craft/) and
  [repository](https://github.com/dietmarwo/CFD-craft)
- [Changelog](https://github.com/dietmarwo/CFD-craft/blob/main/CHANGELOG.md)

MIT licensed.
