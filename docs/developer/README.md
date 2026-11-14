# Working on CFD-craft

This section is for contributors, human or agent, who change the solver, the
adapters, the checks or the documentation. To run cases, start with the
[guide](../guide/README.md). The rules for every change are in
[AGENTS.md](https://github.com/dietmarwo/CFD-craft/blob/main/AGENTS.md).

## Pages in this section

- [Architecture](architecture.md): the components, a map of the repository and the steps of a native run.
- [Profiling and accuracy sweeps](profiling.md): phase timers, `profile` and cost at a declared accuracy.
- [Pressure multigrid](pressure-multigrid.md): the opt-in multigrid preconditioner and its API.
- [Numerical decisions](decisions.md): the choices behind version 0.1 and what each costs.
- [Roadmap](roadmap.md): the milestones of the plan, their state and the next steps.
- [Releasing](releasing.md): versions, registries, qualification and tagging.

The measurements behind these pages are listed in the [evidence index](../evidence/README.md);
the plans as they were written are in the [history](../history/README.md).

## Checks before a change

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --release --workspace --locked
ruff format --check . && ruff check .
python validation/test_cli.py -v
python -O validation/test_cli.py -v
python validation/test_manual_examples.py -v
python scripts/generate_reference.py --check
python validation/run_suite.py --preset smoke --output runs/verification
python validation/flow_accuracy.py --output runs/flow-accuracy
python validation/cavity.py --output runs/cavity
python validation/scipy_reference.py --output runs/scipy-reference
```

Every `validation/test_*.py` runs normally and under `python -O`; the jobs
`rust`, `python-lint`, `numerical` and `external-contracts` of
`.github/workflows/ci.yml` list them all. The OpenFOAM tests without a runtime
check contracts, not physical accuracy. A failed row stays in its report; a
failed refinement run never becomes an accepted grid-convergence result.

## Opt-in CI work

A manual dispatch of `ci.yml` installs the pinned OpenFOAM runtime. Its input
`external` selects `backend`, `resolution`, `mapping`, `refinement`,
`comparison` or `all`, and, not part of `all`, `accuracy` (the cavity grid
sweep, with the inputs `native_pressure`, `native_numerics` and `native_span`),
`momentum` (adds `momentum_scheme`), `pressure` and `anisotropy`. A recorded
backstep failure keeps a job green; a workflow error fails it; `comparison`
fails on any failed run. Chapters [16](../guide/16-compare-solvers.md) and
[19](../guide/19-refinement-campaign.md) of the guide show what these jobs run.

## Accuracy and steady-solver work

The defaults are donor-cell momentum advection, explicit pseudo-time and the
IC(0) pressure preconditioner. Opt-in selections are second-order momentum
advection, the `implicit_projection` steady algorithm and multigrid
([chapter 9](../guide/09-opt-in-numerics.md)). Start from the
[accuracy and steady-solver plan](../history/accuracy-steady-plan.md), the
[donor-cell baseline](../evidence/momentum-verification.md) and the
[matched-accuracy record](../evidence/matched-accuracy.md).
`validation/compare_backends.py --grid-sweep --grids 16 24 32 48` runs both
backends on the same grids; `--native-numerics JSON` selects opt-in native
numerics. Keep the default path, the acceptance thresholds and failed rows.

## Performance work

Compare two builds at fixed work with the `performance_probe` example,
`validation/benchmark_native.py` and the cases in `cases/performance/`: inputs,
producers, work counts and fields are compared, and timing is a separate
observation from acceptance. Record slower controls and memory costs. For phase
attribution use [`profile`](profiling.md); add exclusive times only. A
same-grid ratio is not cost at matched accuracy, and an unreached target has no
finite ratio. For pressure work, IC(0) stays the default and multigrid is
rejected on masked grids, without fallback; `validation/benchmark_pressure.py`,
`benchmark_anisotropy.py` and `benchmark_anisotropic_flow.py` keep cold setup,
reused solves and accepted coupled cost apart ([pressure multigrid](pressure-multigrid.md)).
The current state is in the [performance gap status](../evidence/performance-gap-status.md).
