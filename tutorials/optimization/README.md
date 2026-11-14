# Optimization with CFD-craft

These lessons use the actual CFD solver and independently inspect its returned
fields. They connect simulator structure to solver choice, then test whether a
selected design survives conditions or fidelity that were withheld from search.

| Chapter | Main lesson | Optimization route |
|---|---|---|
| [F1 — source allocation](F1-allocation.md) | A fixed linear transport problem exposes an LP | Native LP, BiteOpt and native GP worker |
| [F2 — sensor selection](F2-sensors.md) | Coverage and identifiability are different | Native bounded MIP, exhaustive check and greedy baseline |
| [F3 — coupled flow](F3-coupled-flow.md) | Accepted coarse solves may support no fine-grid design | Bounded coupled-flow callback, sampling and BiteOpt |

Use the shared [setup and prompt catalog](https://github.com/dietmarwo/optimization-jobs/blob/main/tutorials/simulators/README.md).
Build `cfd-craft`; F1 also needs the optional `fcmaes-cfd-worker` and the shared
`optimization-run` binary. Native LP/MIP and optimization bindings are installed
as Python packages. From this checkout:

```bash
python tutorials/optimization/run.py F1 --output /tmp/cfd-f1
python tutorials/optimization/run.py F2 --output /tmp/cfd-f2
python tutorials/optimization/run.py F3 --output /tmp/cfd-f3
python -m unittest discover -s tutorials/optimization -p 'test_*.py'
python -O -m unittest discover -s tutorials/optimization -p 'test_*.py'
```

Use a new directory per run. All native cases, stdout/stderr, summaries and
fields are retained; the aggregate `summary.json` records rejected solves.
Checks remain active under `python -O`. `passed` reports completion of the
chapter's checks, while `supported_at_requested_fidelity` in F3 reports the
separate scientific design gate. Neither is physical validation of a real site.

F1/F2 use prescribed flow and serial scalar transport. `--threads` does not
magically parallelize that transport; these chapters explicitly use one thread.
F3 exercises coupled momentum and pressure with the requested threads. The
existing source-allocation worker is not a coupled-flow worker; F3 runs through
a Python callback or an existing trusted command job.

See [validation notes](../../docs/evidence/optimization-lessons.md) and the
[X1 campaign](https://github.com/dietmarwo/experiment-craft/blob/main/examples/campaigns/simulators/README.md)
for sealed evidence, complete-run accounting and CPU-layout comparisons.
