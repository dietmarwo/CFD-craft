# Checkpoint and restart

At the end of this chapter you have stopped a run by its step budget, resumed
it from the checkpoint and shown that the resumed fields equal those of an
uninterrupted run, byte for byte. You need the `cfd-craft` command and a
checkout ([chapter 3](03-cli-and-archive.md)).

## Setup

Commands run from the root of a checkout with `cfd-craft` on `PATH`. The case
is the transient tracer cloud `periodic-tracer.json`: 20 steps to 2 s. The
setup writes `runs/full.json` and `runs/partial.json`, limited to five steps.

```bash
mkdir -p runs
```

```python
import json

case = json.load(open("cases/verification/periodic-tracer.json"))
case["name"] = "tracer-full"
case["run"]["threads"] = 1
json.dump(case, open("runs/full.json", "w"), indent=2)
case["name"] = "tracer-partial"
case["run"]["max_steps"] = 5
json.dump(case, open("runs/partial.json", "w"), indent=2)
```

Outputs on this page are real. They contain no floating-point numbers, so the
documentation check requires an exact match.

## Stop by work, then resume

```bash
cfd-craft run runs/partial.json --output runs/partial > /dev/null || echo "partial: exit $?"
cfd-craft report runs/partial > /dev/null
echo "report: exit $?"
cfd-craft run runs/full.json --restart runs/partial/checkpoint.json \
  --output runs/resumed > /dev/null
echo "resumed: exit $?"
python -c "import json; s = json.load(open('runs/resumed/summary.json')); print(s['steps'], s['termination'], s['assessment'])"
```

```text
partial: exit 2
report: exit 0
resumed: exit 0
20 completed transient_interval_completed
```

The first run stops at its step limit and exits 2. Its archive is intact, so
`report` exits 0, and it contains `checkpoint.json` because the case sets
`output.checkpoint`. The third command continues the full case from that
checkpoint at step 5, ends at step 20 and is numerically accepted. The step
count of a resumed run includes the steps before the checkpoint.

`--restart` takes a checkpoint file, not a run directory. The new run gets a
new output directory, and the stopped archive stays as it is.

## Is the resumed run the same run?

Run the full case without interruption and compare.

```bash
cfd-craft run runs/partial.json --output runs/partial > /dev/null || true
cfd-craft run runs/full.json --restart runs/partial/checkpoint.json \
  --output runs/resumed > /dev/null
cfd-craft run runs/full.json --output runs/cold > /dev/null
```

```python
import json
from pathlib import Path

resumed, cold = Path("runs/resumed"), Path("runs/cold")
print((resumed / "fields.json").read_bytes() == (cold / "fields.json").read_bytes())
first = json.loads((resumed / "summary.json").read_text())
second = json.loads((cold / "summary.json").read_text())
print(first["physics_sha256"] == second["physics_sha256"])
print(first["initial_state_sha256"] != second["initial_state_sha256"])
```

```text
True
True
True
```

The final fields are identical in every byte: a restart replays the same
arithmetic. The two results solve the same physics and still record different
initial states. `initial_state_sha256` is in the summary and the manifest of
every run, so a result that started from a checkpoint can always be told from
one that started cold. Keep the parent checkpoint if the start of a run must
be reproducible. Byte equality is measured here on one host with one build:
test it on your platform, as this block does.

## What a checkpoint fits

A checkpoint carries the physics hash of [chapter 2](02-case-file.md) and a
checksum of its state. The hash covers grid, flow, sources, receptors and
numerics, not `name`, `run` or `output`. A checkpoint therefore continues
under another budget, thread count or output policy, and under nothing else:

```python
import json

case = json.load(open("runs/full.json"))
case["numerics"]["transport"] = "linear_upwind"
json.dump(case, open("runs/other-scheme.json", "w"), indent=2)
```

```bash
cfd-craft run runs/partial.json --output runs/partial > /dev/null || true
cfd-craft run runs/full.json --output runs/cold > /dev/null
cfd-craft run runs/other-scheme.json --restart runs/partial/checkpoint.json \
  --output runs/other 2> runs/other.err || echo "exit $?"
grep -o "CFD-E[0-9]*" runs/other.err
cfd-craft run runs/partial.json --restart runs/cold/checkpoint.json \
  --output runs/beyond 2> runs/beyond.err || echo "exit $?"
grep -o "CFD-E[0-9]*" runs/beyond.err
```

```text
exit 1
CFD-E060
exit 1
CFD-E066
```

`CFD-E060` rejects a checkpoint whose identity or checksum does not match the
case: here another transport scheme, and likewise another grid. `CFD-E066`
rejects a checkpoint that lies beyond `run.max_steps` of the case, or beyond
`run.end_time_s` in transient mode: here the final state of the full run
offered to the five-step case. Both exit 1 and write nothing. `CFD-E065`
reports a checkpoint that cannot be read or exceeds half the memory budget.

## Why the endpoint stays fixed

The partial case changed `run.max_steps` and kept `run.end_time_s`, on
purpose. The last step of a transient run is shortened to land exactly on the
endpoint. With a shorter endpoint instead of a smaller step budget, the
partial run would shorten its last step there, and the resumed run would take
different steps from the uninterrupted one: a valid run of the same physics,
but not an exact replay. To test replay, interrupt by work.

## Next

- [Chapter 9](09-opt-in-numerics.md): opt-in numerics for flow.
- [Result contract](../result-contract.md): the identities a run records.
