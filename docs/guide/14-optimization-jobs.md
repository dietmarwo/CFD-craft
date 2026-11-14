# Optimization jobs

<!-- check: jobs -->
<!-- check: timeout=900 -->

This chapter runs the solver as jobs of `optimization-run`, the runner of the separate optimization-jobs project: once as a plain command, and once through the optional fcmaes application worker with an evaluation, a BiteOpt retry and a Gaussian-process surrogate job. You need Rust, a checkout, the worker crate built with its own lockfile and `optimization-run` built from the pinned optimization-jobs revision.

The standalone solver does not depend on optimization-jobs. The command launcher and the worker live in `integrations/` of the checkout; the job and result protocols are those of optimization-jobs, unchanged.

## Setup

Run all commands from the root of a checkout. Build the solver and the worker; the worker crate is outside the core workspace and has its own lockfile:

```sh
cargo build --release --locked
cargo build --release --locked --manifest-path integrations/fcmaes-cfd-worker/Cargo.toml
python -m pip install -r requirements-validation.txt
```

The worker pins its two dependencies to exact revisions: fcmaes-rust `f764a7516f41bf2d88009b156daa70bf0a5445c1` and the optimization-jobs job API `12f9d573ade24f57c282dcf9eb7ad7025cfe51bf`. Build `optimization-run` from that same optimization-jobs revision (0.4.0 plus later documentation and tutorials), next to the checkout, as the CI job `runner-integration` does:

```sh
git clone https://github.com/dietmarwo/optimization-jobs ../optimization-jobs
git -C ../optimization-jobs checkout 12f9d573ade24f57c282dcf9eb7ad7025cfe51bf
cargo build --release --locked --manifest-path ../optimization-jobs/Cargo.toml -p optimization-runner
```

The commands on this page then name the runner as `../optimization-jobs/target/release/optimization-run`; any other location works when given as `--runner`.

```bash
mkdir -p runs
```

## The application worker

```bash
integrations/fcmaes-cfd-worker/target/release/fcmaes-cfd-worker describe > runs/worker-description.json
```

```python
import json

d = json.load(open("runs/worker-description.json"))
print(sorted(x["profile"] for x in d["examples"]))
```

The worker registers one model, `app.cfd.source-allocation`, version 1. It consumes a hashed case and requires prescribed flow, exactly three sources with equal positive base rates, one constituent and at least one receptor. Its built-in example uses `cases/verification/source-response.json`.

It exposes two box-bounded parameters, `x0` and `x1` in [0.1, 1.4]. The three source multipliers are `x0`, `x1` and `3 - x0 - x1`; the third lies in [0.2, 2.8], so every source stays positive and the total emission is preserved for equal base rates. The objective is the largest receptor concentration divided by 1e-8 kg/m3. Lesson F1 of [chapter 13](13-optimization-lessons.md) solves the same problem as a linear program.

Each evaluation is one full in-process CFD run. It must end as `steady_discrete_solution`; any incomplete calculation returns an error to the optimizer, never a large number. The job's deadline and cancellation reach the solver through its `Control`. Prescribed transport is serial per evaluation; the SDK decides how many evaluations run at once.

## Run the four jobs

```bash
python integrations/run_jobs.py \
  --runner ../optimization-jobs/target/release/optimization-run \
  --output runs/jobs > /dev/null
```

```python
import json

r = json.load(open("runs/jobs/report.json"))
print("passed:", r["passed"])
print("command job:", r["command_result"]["state"])
for profile in ["fcmaes.evaluate/1", "fcmaes.retry/1", "fcmaes.surrogate/1"]:
    execution = r[profile]["execution"]
    work = execution["known_work_lower_bound"]
    print(
        profile,
        execution["state"],
        "failed",
        work["failed_evaluations"],
        "cancelled",
        work["cancelled_evaluations"],
    )
```

`--binary` and `--worker` default to the release builds of the checkout. The script makes a local foreground node in `runs/jobs/node` and submits four jobs:

1. A command job (`execution.command/0.1`): a 12 x 6 x 6 copy of `periodic-tracer.json`, run by the CLI through the launcher, with the case, the launcher and the solver binary staged as hashed inputs.
2. `fcmaes.evaluate/1`: the original layout and one more point.
3. `fcmaes.retry/1`: BiteOpt with a hard cap of 24 new evaluations and a recheck of the best point.
4. `fcmaes.surrogate/1`: the experimental GP surrogate, also 24 evaluations with a recheck.

It checks terminal states, that every requested task completed, that the failed and canceled evaluation counters are present and zero, and the runner's result manifests. It does not take a zero exit of the runner as proof that a job completed. The job files it writes (`command.json`, and `fcmaes.json` for the optimizer jobs, each overwriting the previous one) are the inputs to inspect; do not reconstruct their fields from memory.

**Recorded values.** The [native verification record](../evidence/native-verification.md#optimizer-integration) (the record gives no date) reports a run with `optimization-run` built at `12f9d57`: all three optimizer jobs completed, retry and GP each used 24 new CFD evaluations and one recheck with no failed or canceled evaluations, and the objectives were 1.8682465 for the original layout and 1.8657713 and 1.6799143 for the BiteOpt and GP selections (largest receptor concentration over 1e-8 kg/m3). Each value is an accepted steady discrete solution; none is an experimental result, and one small seeded run does not rank BiteOpt against GP.

## The command launcher

`integrations/launch_command.py` is the program a command job runs. The runner creates the declared output parent directories before launch, but the CLI refuses an existing run directory. The launcher therefore runs `cfd-craft run case.json --output simulation` in a fresh child directory and then copies `simulation/summary.json` to the flat output the job declares. An empty prepared parent does not switch off the CLI's overwrite protection.

On SIGTERM or SIGINT (a runner deadline or a cancellation) the launcher forwards the signal to the solver and waits, so the canceled summary is still collected. Its handlers are installed before the solver starts; a signal that arrives during start-up is delivered once the solver exists.

## What a job result is not

An `execution.command/0.1` envelope describes a process and the outputs it collected. An `optimization.job/0.1` envelope also names a registered optimizer worker and a versioned payload profile. A completed command state is not an optimization claim, and an optimizer's best-found and rechecked value is neither a CFD archive nor a calibrated posterior nor an experimental claim. Where a physical result is needed, attach separate CFD evidence (a native run archive, [chapter 4](04-reading-a-result.md)).

Keep objective calls, SDK rechecks, failed and canceled work and CFD steps apart when you report cost. The worker runs CFD for every evaluation; reusing a response matrix ([chapter 12](12-studies.md)) is a different technique with its own fixed-flow and linear-transport assumptions.

## Campaigns

The command and optimizer files written by `run_jobs.py` are ordinary `execution.command/0.1` and `optimization.job/0.1` envelopes, so [experiment-craft](https://github.com/dietmarwo/experiment-craft) can schedule them as dependent campaign steps without a new CFD protocol or server. experiment-craft owns placement, dependencies and transfer; CFD-craft owns cases and CFD evidence. `command.json` names the Python interpreter that ran `run_jobs.py` as `argv[0]`; replace it with the interpreter of the target node when reusing the file.

Not tested in this release: a full multi-node CFD campaign, remote machine commissioning and transfer of large fields.

## A task for an agent

> Build the optional worker with its lockfile. Register it on a new local foreground optimization-jobs node, then run `integrations/run_jobs.py`. Use `cases/verification/source-response.json`; keep geometry, source support, total integrated emission and receptor IDs fixed.
>
> Confirm that the case is a consumed, hashed input, that the CFD callback respects cancellation, and that every accepted objective comes from a checked steady simulation. Compare the original layout, BiteOpt and GP selected values with equal budgets of 24 new calls per optimizer. Count new evaluations, failed and canceled calls and rechecks separately, and retain failures.
>
> Treat this as an integration demonstration, not a statistical ranking. Preserve the optimization result contract and attach separate CFD evidence where a physical result is needed. Report concentrations in kg/m3 and micrograms/m3, keep numerical checks apart from physical validation, and use fresh output directories.

For a new application, define the objective and the conservation constraints before choosing an optimizer. Do not reward a lower concentration obtained by moving a sensor, changing the source inventory or lowering numerical fidelity.

## Next

- [Chapter 15](15-openfoam-first-run.md): Part IV, the OpenFOAM backend, starting with install and a first cavity.
- [Chapter 13](13-optimization-lessons.md): the same allocation problem solved as a linear program.
