# Native Python interface

`cfd-craft` is an optional Rust extension for Python 3.10 and newer. It adds no
Python or OpenFOAM dependency to the Rust engine. Install a release from PyPI:

```sh
python -m pip install cfd-craft
```

Wheels exist for CPython 3.10+ (stable ABI) on Linux x86_64, Windows x64 and
macOS x86_64 and arm64; elsewhere pip builds the source distribution, which
needs Rust 1.88 or newer. To build from a checkout instead:

```sh
python -m pip install maturin==1.9.6
maturin build --release --locked --out dist
python -m pip install dist/*.whl
```

## Check and simulate

An installed package has no repository checkout, so this example downloads the
manual's [point-source case](../examples/manual/point-source.json) (prescribed
flow, one tracer, one downstream volume receptor) from GitHub:

```python
import json
import urllib.request
from pathlib import Path
import cfd_craft as cfd

URL = (
    "https://raw.githubusercontent.com/dietmarwo/CFD-craft/main/"
    "examples/manual/point-source.json"
)
local = Path("point-source.json")
if not local.exists():
    with urllib.request.urlopen(URL, timeout=30) as response:
        local.write_bytes(response.read())
case = json.loads(local.read_text())
report = cfd.check(case)
if not report["valid"]:
    raise ValueError(report["diagnostics"])
result = cfd.simulate(case)
print(result["termination"], result["assessment"])
tracer = next(c for c in result["constituents"] if c["id"] == "tracer")
print(tracer["receptors_kg_m3"]["R_down"] * 1e9, "micrograms/m3")
```

The downloaded copy is reused on later runs; edit it, or a copy of it, to
change the case. In a checkout, load `examples/manual/point-source.json` or any
case under `cases/` directly.

Inputs may be dictionaries, JSON strings or bytes. Raw bytes preserve duplicate
keys for native rejection. Unknown fields, trailing JSON and invalid budgets are
rejected. `CfdError.diagnostics` holds native diagnostics with codes and field
paths. Dictionary inputs use strict JSON serialization: NaN, infinity or a value
JSON cannot represent is rejected as `CFD-P001 python.case`.

`check` returns the native preflight report (validity and coded diagnostics).
It runs the CLI's checks but omits the CLI's geometry evidence and its
`{"check": ...}` wrapper, so `cfd-craft-python check` prints a different shape
from native `cfd-craft check`.

`simulate` returns the native summary schema from `describe()["result_schema"]`.
The summary retains all checks, actual work, termination, assessment and
`experimental_validation`. Only `steady_discrete_solution` and
`transient_interval_completed` are accepted numerical assessments. A numerical
assessment is not physical validation. Cancelled, timed-out and iteration-limited
runs retain their incomplete summaries.

Calls release the GIL during solving. Each call owns its state and a Rayon pool
bounded by `run.threads`; limit outer concurrency as well to avoid
oversubscription. `simulate(case, cancel_file=Path("cancel"))` polls for a
cancellation file (at most every 20 ms). Ctrl-C in the main Python thread
cancels and joins the worker, then raises `KeyboardInterrupt`. Wall time, steps
and threads are enforced as in the CLI. `run.memory_limit_mib` is a preflight
estimate calibrated on the CLI process, not a limit on the Python process; the
host-memory refusal reads `/proc/meminfo` and so applies on Linux only.
Concurrent calls pass preflight independently. Returning large field arrays is
outside this API.

`python -m cfd_craft` (also `cfd-craft-python`) supports `describe`, `check CASE`
and `simulate CASE [--cancel-file PATH]`. Exit codes are 0 for success, 1 for
invalid input/execution errors and 2 for incomplete numerical evidence.

Use the Rust CLI (`cargo install cfd-craft-cli --locked`) for checksummed
archives, fields, restarts, preview and profiles. Existing subprocess workflows
remain valid. The Python console script has a separate name so installing both
interfaces cannot hide the native archive CLI.

## Build identity and acceptance

The Rust core, CLI and binding fingerprint their own Rust sources, manifest and
build script plus the lockfile they build with: a packaged crate (and the
binding's own workspace) its own `Cargo.lock`; a checkout crate the root
workspace's `Cargo.toml` and `Cargo.lock`. The CLI and binding identities
combine their own fingerprint with the core's. Source and packaged builds can
therefore have different identities. Numerical fields are compared
independently of build identity and elapsed time. `cfd_craft.__version__` is
the installed distribution version; `cfd_craft._native.__version__` the
binding's Cargo version.

`validation/check_installed.py` exercises strict parsing, diagnostics,
concurrent call identity, incomplete work, cancellation by file and by Ctrl-C
during a long run (each must stop it within seconds), and the installed console
script. `--binary PATH` also compares numerical summaries with the Rust CLI.
Run the checker with `python -I` from outside the checkout, normally and under
`-O`. The release workflow runs it for every wheel on CPython 3.10 and 3.14 and
for the source distribution; see [Releasing](developer/releasing.md).
