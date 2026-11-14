# Before you spend compute
<!-- check: rel=1e-4 -->

At the end of this chapter you can estimate a run before it starts, bound it,
try it on a coarser grid, and stop it without losing the result. You need the
`cfd-craft` command and a checkout ([chapter 3](03-cli-and-archive.md)).

## Setup

Commands run from the root of a checkout with `cfd-craft` on `PATH`. The setup
writes the steady cavity of [chapter 6](06-flow-cavity.md) and a copy with a
wall-time limit of one second.

```bash
mkdir -p runs
```

```python
import json

case = json.load(open("cases/verification/lid-cavity.json"))
case["name"] = "cavity-steady"
case["run"]["mode"] = "steady"
case["run"]["threads"] = 1
json.dump(case, open("runs/cavity-steady.json", "w"), indent=2)
case["name"] = "cavity-1s"
case["run"]["wall_time_limit_s"] = 1
json.dump(case, open("runs/cavity-1s.json", "w"), indent=2)
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## What `check` estimates

`check` counts the cells and estimates the peak memory of the run and the size
of its output directory, both in MiB, without building any field.

```bash
cfd-craft check runs/cavity-steady.json > runs/check.json
```

```python
import json

report = json.load(open("runs/check.json"))["check"]
print(report["valid"], report["cells"])
peak, output = report["estimated_peak_mib"], report["estimated_output_mib"]
print(f"peak {peak:.3g} MiB, output {output:.3g} MiB")
```

```text
True 1152
peak 26.2 MiB, output 2.35 MiB
```

A case whose estimate exceeds its own budget is invalid. Lower the memory
budget of the cavity to 8 MiB:

```python
case = json.load(open("runs/cavity-steady.json"))
case["run"]["memory_limit_mib"] = 8
json.dump(case, open("runs/cavity-small.json", "w"), indent=2)
```

```bash
cfd-craft check runs/cavity-small.json > runs/small.json || echo "exit $?"
python -c "import json; print([(d['code'], d['path']) for d in json.load(open('runs/small.json'))['check']['diagnostics']])"
```

```text
exit 1
[('CFD-E006', 'run.memory_limit_mib')]
```

An output estimate above `output.max_total_mib` is rejected the same way
(`CFD-E007`). `run` also refuses a case whose estimate exceeds 80 percent of
the memory available on this host (`CFD-E070`); `check` then only warns
(`CFD-W070`) and skips the checks that need the grid.

## Budgets are part of the case

| Field | What it bounds |
|---|---|
| `run.max_steps` | Time steps, or outer iterations of an implicit steady run |
| `run.wall_time_limit_s` | Wall time of the solve, at most seven days |
| `run.threads` | Worker threads |
| `run.memory_limit_mib` | The estimated peak memory, tested before the run |
| `output.max_total_mib` | The estimated and the actual size of the run directory |
| `output.fields`, `output.checkpoint` | Whether the two large files are written at all |

Every case states all of them, so there is no unbounded run. Fields or a
checkpoint that would exceed the output budget after all are left out and
listed in the manifest, and the run exits 2 with `CFD-E061`.

## Preview on a coarser grid

`preview` runs the case with every cell count divided by 2, or by `--factor N`.

```bash
cfd-craft preview examples/manual/point-source.json --output runs/preview > /dev/null
```

```python
import json

s = json.load(open("runs/preview/summary.json"))
tracer = next(c for c in s["constituents"] if c["id"] == "tracer")
print(s["name"], s["fluid_cells"], s["assessment"])
print(s["model_scope"])
print(f"R_down = {tracer['receptors_kg_m3']['R_down'] * 1e9:.6g} micrograms/m3")
```

```text
manual-point-source-preview 128 steady_discrete_solution
preview: prescribed_flow_passive_transport
R_down = 16.3951 micrograms/m3
```

The preview has 128 cells where the case has 1,024. Its name ends in
`-preview` and its `model_scope` starts with `preview:`, so it cannot be
mistaken for the real run. Its receptor reads 16.4 where the full grid gives
17.8 micrograms/m3: a preview tests the workflow, not the accuracy of the
full grid. An axis keeps at least two cells; a one-cell axis stays at one.

## When a preview is refused

Coarsening can destroy a geometry. Halve the grid of the street-canyon case of
[chapter 10](10-street-canyon.md):

```bash
cfd-craft preview cases/canyon/wh1-wind270.json --factor 2 \
  --output runs/preview-canyon > runs/refused.json || echo "exit $?"
python -c "import json; print(*[(d['code'], d['path']) for d in json.load(open('runs/refused.json'))['check']['diagnostics'] if d['severity'] == 'error'], sep='\n')"
```

```text
exit 1
('CFD-E040', 'sources[0]')
('CFD-E042', 'receptors[0]')
('CFD-E042', 'receptors[1]')
('CFD-E042', 'receptors[2]')
('CFD-E042', 'receptors[3]')
```

On the coarse grid the buildings fill the street, so the line source
(`CFD-E040`) and all four receptors (`CFD-E042`) lie in solid cells. The
preview exits 1 with the check report and writes nothing. It is also refused
when coarsening changes the solid volume by more than 20 percent or the number
of separate fluid regions (`CFD-E072`), or when the original mask is too large
to count on this host (`CFD-E073`). A refusal describes the coarse geometry.

## Stop on a time limit

```bash
cfd-craft run runs/cavity-1s.json --output runs/limited > /dev/null || echo "exit $?"
python -c "import json; s = json.load(open('runs/limited/summary.json')); print(s['termination'], s['assessment'])"
```

```text
exit 2
wall_time_limit incomplete
```

After one second the solver stops, writes the complete archive of the last
accepted state and exits 2. A step limit does the same with `iteration_limit`.

## Cancel a run

Ctrl-C (SIGINT) or SIGTERM cancels a run: the solver stops at the next safe
point. Here `timeout` from GNU coreutils sends SIGINT after one second:

```bash
timeout --preserve-status -s INT 1 \
  cfd-craft run runs/cavity-steady.json --output runs/cancelled > /dev/null || echo "exit $?"
cfd-craft report runs/cancelled > /dev/null
echo "report: exit $?"
python -c "import json; s = json.load(open('runs/cancelled/summary.json')); print(s['termination'], s['assessment'])"
```

```text
exit 2
report: exit 0
cancelled incomplete
```

The run ends as `cancelled / incomplete` and exits 2. Its archive is complete
and verified, with a checkpoint ([chapter 8](08-checkpoint-restart.md)). From
Python, `cfd.simulate(case, cancel_file=PATH)` does the same
([chapter 11](11-python.md)).

## Threads

The command and the Python binding build a pool of exactly `run.threads`
threads per run. Keep runs times threads within the number of cores.

## Next

- [Chapter 8](08-checkpoint-restart.md): continue a stopped run.
- [Diagnostics](../diagnostics.md): all codes named here.
