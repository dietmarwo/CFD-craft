# Native Python interface

`cfd-craft` 0.1.0 is an optional Rust extension for Python 3.10 and newer.
It is prepared for PyPI; preparation does not mean publication has occurred.
The binding workspace uses Rust 1.88 and maturin 1.9.6. It adds no Python or
OpenFOAM dependency to the Rust engine.

## Install

Before publication, from the repository root:

```sh
python -m pip install maturin==1.9.6
maturin build --release --locked --out dist
python -m pip install dist/*.whl
```

After publication: `python -m pip install cfd-craft==0.1.0`.
Compatible wheels need no Rust installation. Building from the sdist needs Rust.

## Check and simulate

```python
import json
from pathlib import Path
import cfd_craft as cfd

case = json.loads(Path("cases/verification/periodic-tracer.json").read_text())
case["run"]["threads"] = 1
report = cfd.check(case)
if not report["valid"]:
    raise ValueError(report["diagnostics"])
result = cfd.simulate(case)
print(result["termination"], result["assessment"])
print(result["constituents"][0]["receptors_kg_m3"])
```

Inputs may be dictionaries, JSON strings or bytes. Raw bytes preserve duplicate
keys for native rejection. Unknown fields, trailing JSON and invalid budgets are
rejected. `CfdError.diagnostics` holds native diagnostics with codes and field paths.
Dictionary inputs use strict JSON serialization (`allow_nan=False`).

`simulate` returns the native summary schema from `describe()["result_schema"]`.
The summary retains all checks, actual work, termination, assessment and
`experimental_validation`. Only `steady_discrete_solution` and
`transient_interval_completed` are accepted numerical assessments. A numerical
assessment is not physical validation. Cancelled, timed-out and iteration-limited
runs retain their incomplete summaries.

Calls release the GIL during solving. Each call owns its state and a Rayon pool
bounded by `run.threads`; limit outer concurrency as well to avoid oversubscription.
`simulate(case, cancel_file=Path("cancel"))` polls for a cancellation file.
Ctrl-C in the main Python thread cancels and joins the worker, then raises
`KeyboardInterrupt`. The same preflight estimates and host-memory refusal as the
native CLI apply. Returning large field arrays is outside this initial API.

`python -m cfd_craft` (also `cfd-craft-python`) supports `describe`, `check CASE`
and `simulate CASE [--cancel-file PATH]`. Exit codes are 0 for success, 1 for
invalid input/execution errors and 2 for incomplete numerical evidence.

Use the separately installed Rust CLI for checksummed archives, fields, restarts,
preview and profiles. Existing subprocess workflows remain valid. The Python
console script has a separate name so installing both interfaces cannot hide the
native archive CLI.

## Build identity and acceptance

The Rust core, CLI and binding fingerprint their own Rust sources, manifests,
build scripts and selected lockfile. CLI/binding identities combine their own
fingerprint with the core's. A packaged crate uses its normalized Cargo.lock;
a checkout uses its workspace lockfile. Source and packaged builds may therefore
have different identities. Numerical fields are compared independently of build
identity and elapsed time. The Python wrapper version is the binding version.

`validation/check_installed.py` exercises strict parsing, diagnostics, concurrent
call identity, incomplete work, cancellation and installed console scripts.
`--binary PATH` also compares numerical summaries with the Rust CLI. Run the
checker with `python -I` from outside the checkout, normally and under `-O`.
`scripts/check_sdist.py` rebuilds an extracted source archive and repeats acceptance
in a fresh environment. The release workflow additionally tests Linux x86_64,
macOS arm64 and Windows x86_64 wheels on Python 3.10, 3.12 and 3.14; local Linux
checks alone do not establish those other-platform results.
