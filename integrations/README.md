# Existing-runner and fcmaes integration

The standalone solver stays independent of optimization-jobs. The command adapter and optional application worker live here.

The separate [OpenFOAM backend](OPENFOAM.md) provides bounded Foundation-13
execution, a native/external cavity comparison and a frozen experimental
backstep screen. It does not change the native optimizer profiles below.

## Command execution

The runner prepares output parent directories before launch. launch_command.py runs the CFD CLI in a fresh simulation/ directory, then copies its summary to a declared flat output. On SIGTERM or SIGINT (a runner deadline or cancellation) it forwards the signal to the solver and waits, so the cancelled summary is still collected. Its handlers are installed before the solver starts; a signal that arrives while the solver is starting is delivered once it exists. The launcher, CFD executable and case are staged as separately hashed inputs. An empty prepared parent directory does not disable the CFD CLI's overwrite protection.

The command result describes process execution and collected outputs. Its completed state does not create an optimization claim or an empirical CFD validation claim.

## Native scalar application worker

~~~sh
cargo build --release --locked --manifest-path integrations/fcmaes-cfd-worker/Cargo.toml
integrations/fcmaes-cfd-worker/target/release/fcmaes-cfd-worker describe
python integrations/run_jobs.py --runner /absolute/path/optimization-run --output runs/jobs
~~~

The optional crate has its own lockfile and exact source pins:

- fcmaes-rust 583f33a9a815ede0e1115c8ddd69029a874593f9.
- optimization-jobs job API 602d31afacf8bd2ecb0b0e941d18bd8e2821c1e3, matching that worker's dependency identity.

run_jobs.py is tested against optimization-run built from optimization-jobs cc6b03d (0.4.0 plus later documentation and tutorials); CI builds that revision. The adapter does not change either repository or the job/result protocols.

The model app.cfd.source-allocation consumes a hashed case, requires prescribed flow, three sources, one constituent and receptors, and exposes two box-bounded source multipliers. It uses Scalar::simulation for evaluate, retry and surrogate. Each call propagates the SimContext deadline/cancellation into CFD Control. Prescribed transport is serial per evaluation; the SDK controls concurrent evaluations.

Any incomplete CFD calculation returns an error to the optimizer. The selected objective must pass native numerical checks. The worker's normal best-found/feasible optimization evidence refers to the objective and parameter bounds; it is not an atmospheric validation certificate.

The example runs a baseline evaluation, BiteOpt hard-cap retry and the experimental GP surrogate. It inspects terminal execution state, task counts, failed and cancelled evaluation counts (both must be present and zero) and checked result manifests. It does not assume that a zero CLI exit means a job completed successfully.

## Campaigns

The command and optimizer JSON files produced by run_jobs.py are ordinary execution.command/0.1 and optimization.job/0.1 envelopes. They can become experiment-craft steps without a new CFD protocol or server. command.json names the Python interpreter that ran run_jobs.py as argv[0]; replace it with the interpreter of the target node when reusing the file. A full multi-node CFD campaign, remote machine commissioning and large-field transport were not tested in this release.
