# Python

At the end of this chapter you know what the Python binding accepts, returns
and raises, how to cancel it, and how to script the `cfd-craft` command. You
need the binding; the last two sections also need the command and a checkout.

## Setup

The binding is a Rust extension without Python dependencies, for Python 3.10
and newer. Where no wheel exists, pip builds from source with Rust 1.88. The
second block builds the binding of a checkout instead.

```sh
python -m pip install cfd-craft
```

```sh
python -m pip install maturin==1.9.6
maturin build --release --locked --out dist
python -m pip install dist/*.whl
```

An installed package has no checkout, so this block fetches the point-source
case of [chapter 1](01-first-run.md) and makes a directory for outputs:

```python
import os
import urllib.request

URL = "https://raw.githubusercontent.com/dietmarwo/CFD-craft/main/examples/manual/point-source.json"
urllib.request.urlretrieve(URL, "point-source.json")
os.makedirs("runs", exist_ok=True)
```

Outputs on this page are real. They contain no floating-point numbers, so the
documentation check requires an exact match.

## Inputs: dictionary, string or bytes

```python
import json
import math
import cfd_craft as cfd

text = open("point-source.json").read()
case = json.loads(text)
print([cfd.check(value)["valid"] for value in (case, text, text.encode())])
twice = text.replace('"name":', '"name": "first", "name":', 1)
print([d["code"] for d in cfd.check(twice)["diagnostics"]])
case["sources"][0]["rate_kg_s"] = math.nan
try:
    cfd.check(case)
except cfd.CfdError as error:
    print([(d["code"], d["path"]) for d in error.diagnostics])
```

```text
[True, True, True]
['CFD-E000']
[('CFD-P001', 'python.case')]
```

`check` and `simulate` take a dictionary, JSON text or bytes. Text and bytes
reach the native parser unchanged, so it can reject a key that occurs twice
(`CFD-E000`). NaN or infinity in a dictionary raises `CfdError` (`CFD-P001`).

## Errors carry diagnostics

```python
import json
import cfd_craft as cfd

case = json.load(open("point-source.json"))
case["run"]["threads"] = 0
try:
    cfd.simulate(case)
except cfd.CfdError as error:
    print(isinstance(error, ValueError), sorted(error.report))
    print([(d["code"], d["severity"], d["path"]) for d in error.diagnostics])
```

```text
True ['cells', 'diagnostics', 'estimated_output_mib', 'estimated_peak_mib', 'schema_version', 'valid']
[('CFD-E008', 'error', 'run.threads')]
```

For an invalid case `check` returns its report and `simulate` raises
`CfdError`, a `ValueError`, before any work is done. `error.report` is that
report and `error.diagnostics` its findings. Branch on code and path.

## What `check` and `simulate` return

```python
import json
import cfd_craft as cfd

case = json.load(open("point-source.json"))
case["run"]["max_steps"] = 5
result = cfd.simulate(case)
print(result["termination"], result["assessment"], result["steps"])
print(set(result) <= set(cfd.describe()["result_schema"]["properties"]))
```

```text
iteration_limit incomplete 5
True
```

`check` returns the check report; the `cfd-craft check` command wraps it as
`{"check": ..., "geometry": ...}` and adds geometry counts. `simulate` returns
the summary that the command writes as `summary.json`, schema
`cfd-craft.result/0.1`; `describe()["result_schema"]` lists its fields. A run
that stops early is returned, not raised, so test the assessment first.

## Threads, the GIL and concurrent calls

A call releases the GIL while it solves and has its own state and its own
pool of `run.threads` threads. Concurrent calls are safe; limit their number
so the pools fit the cores. `run.memory_limit_mib` bounds an estimate, not
the Python process, and the host-memory refusal (`CFD-E070`) is Linux only.

## Cancel from Python

`simulate(case, cancel_file=PATH)` stops when another thread or process
creates the file (polled at most every 20 ms). Ctrl-C in the main thread also
cancels, then raises `KeyboardInterrupt`. Here the file exists from the start:

```python
import json
from pathlib import Path
import cfd_craft as cfd

case = json.load(open("point-source.json"))
Path("runs/cancel").touch()
result = cfd.simulate(case, cancel_file=Path("runs/cancel"))
print(result["termination"], result["assessment"], result["steps"])
```

```text
cancelled incomplete 0
```

## The console script

`python -m cfd_craft` (also `cfd-craft-python`) has `describe`, `check CASE` and
`simulate CASE [--cancel-file PATH]`.

```bash
python -m cfd_craft check point-source.json > /dev/null
echo "check: exit $?"
python -c "import json; c = json.load(open('point-source.json')); c['run']['max_steps'] = 5; json.dump(c, open('runs/five.json', 'w'))"
python -m cfd_craft simulate runs/five.json > /dev/null || echo "simulate: exit $?"
```

```text
check: exit 0
simulate: exit 2
```

Exit 0 is a valid case or an accepted run, 1 invalid input or an error, 2 a
run without numerical acceptance. The name never hides the `cfd-craft` command.

## Drive the CLI from Python

For fields or an archive, call the command with `subprocess`:

```python
import json
import subprocess

command = ["cfd-craft", "check", "point-source.json"]
checked = subprocess.run(command, capture_output=True, text=True, timeout=20)
body = json.loads(checked.stdout)
if checked.returncode != 0 or not body["check"]["valid"]:
    raise RuntimeError(body["check"]["diagnostics"])
print(checked.returncode, body["check"]["cells"])
```

```text
0 1024
```

Pass the arguments as a list and leave `shell` off. An I/O error exits 1 with
`{"error": ...}` on stderr and no JSON on stdout, so keep both streams.

## The whole native workflow in one script

`examples/manual/cli_workflow.py` does all of this in one script: schemas,
check, run, report, audit, doubled sources, an invalid case, an incomplete
archive, a restart, a preview and a VTK export. Its checks raise explicit
exceptions, so they also hold under `python -O`:

```bash
python examples/manual/cli_workflow.py --output runs/manual-cli > /dev/null
python -O examples/manual/cli_workflow.py --output runs/manual-cli-optimized > /dev/null
```

```python
import json

for name in ("manual-cli", "manual-cli-optimized"):
    report = json.load(open(f"runs/{name}/report.json"))
    print(name, report["passed"], report["resumed_equals_cold"])
```

```text
manual-cli True True
manual-cli-optimized True True
```

## Build identity

Every summary carries `source_sha256` and `build_version`. The binding hashes
its own Rust sources and lockfile with those of the core library, so a wheel
and a checkout build can differ in identity with the same numerics.

## Next

- [Chapter 12](12-studies.md): many runs and study scripts.
- [Python API reference](../reference/python-api.md): every function.
