# The Rust library
<!-- check: rel=1e-4 -->

At the end of this chapter you have called the solver in process from Rust,
canceled it, round-tripped a checkpoint and read a run archive. It is for
readers who embed the solver in a service or a worker. You need Rust 1.88 or
newer and a checkout.

## Setup

Commands run from the root of a checkout. Build the command and the example
programs once:

```sh
cargo build --release --workspace --examples --locked
export PATH="$PWD/target/release:$PATH"
```

The sections run the built examples from `target/release/examples/`.
`cargo run --release --locked -p cfd-craft --example NAME` builds and runs one
in a single step. The archive reader needs an accepted and an incomplete run:

```bash
mkdir -p runs
cfd-craft run examples/manual/point-source.json --output runs/point > /dev/null
python -c "import json; c = json.load(open('examples/manual/point-source.json')); c['run']['max_steps'] = 5; json.dump(c, open('runs/point-5.json', 'w'))"
cfd-craft run runs/point-5.json --output runs/partial > /dev/null || true
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## Depend on the crate

The package is `cfd-craft`; the import name is `cfd_craft`.

```toml
[dependencies]
cfd-craft = "0.1"
serde_json = "1"
rayon = "1"
```

To build against a reviewed checkout instead, write
`cfd-craft = { path = "/path/to/CFD-craft/crates/cfd-craft" }`. Commit your
application's own `Cargo.lock`.

## The API in one table

| API | Use |
|---|---|
| `serde_json::from_slice::<Case>` | Parse the typed case; unknown fields are rejected |
| `Case::check()` | `CheckReport`: validity, estimates, diagnostics |
| `Case::validate()` | `Result` with the check report, or the report as the error |
| `Grid::build(&case)` | The grid, masks and fluid regions |
| `Source::rate()` | Integrated rate in kg/s of any source kind |
| `Control::new(seconds)` | A wall-time allowance; holds the cancellation flag |
| `Control::with_poll(seconds, closure)` | Adds an external deadline or cancellation check |
| `solver::run(&case, &control, restart)` | `Result<RunResult>`: summary, state, geometry |
| `output::checkpoint_bytes`, `read_checkpoint` | Write and read a checksummed state |
| `output::create_run_dir`, `write_run` | Publish a run archive; the caller supplies its build identity |
| `output::read_verified` | Read and verify a run archive |

`cfd_craft::Result<T>` has a `String` error. Read the diagnostic code or the
check report in it; do not parse its English text. `Control::new` expects
finite positive seconds. The modules for grid, faces and state vectors are
public for research use; prefer the calls above. The full API is on
[docs.rs](https://docs.rs/cfd-craft).

## Solve in process

[`manual_library.rs`](https://github.com/dietmarwo/CFD-craft/blob/main/crates/cfd-craft/examples/manual_library.rs) loads
`source-response.json`, validates it, builds a one-thread pool, runs the
solver, requires steady acceptance and reads receptor `R1`.

```bash
target/release/examples/manual_library \
  | python -c "import json, sys; r = json.load(sys.stdin); print(r['passed'], r['assessment'], abs(r['source_total_kg_s'] - 1.92e-7) < 1e-19, f\"R1 = {r['R1_ug_m3']:.6g} micrograms/m3\")"
```

```text
True steady_discrete_solution True R1 = 18.6825 micrograms/m3
```

The third value tests that the three volume sources integrate to 1.92e-7 kg/s
within 1e-19. The central calls of the example are:

<!-- check: fragment of crates/cfd-craft/examples/manual_library.rs -->
```rust
let control = Control::new(case.run.wall_time_limit_s);
let run = pool.install(|| solver::run(&case, &control, None))?;
// Ok(RunResult) can also contain cancellation or an incomplete solve.
if run.summary.assessment != "steady_discrete_solution" {
    return Err(format!(
        "CFD-U001 manual.library.assessment: {} / {}",
        run.summary.termination, run.summary.assessment
    ));
}
```

`Ok(RunResult)` means the solver returned a result you can inspect. That
result can be canceled, incomplete or numerically failed. Always test
`summary.assessment`.

## Cancellation and deadlines

[`manual_control.rs`](https://github.com/dietmarwo/CFD-craft/blob/main/crates/cfd-craft/examples/manual_control.rs) cancels in two ways: a
flag that is set before the run starts, and a poll closure that returns an
error during the run.

```bash
target/release/examples/manual_control \
  | python -c "import json, sys; r = json.load(sys.stdin); print(r['passed'], r['termination'], r['assessment'], r['queued_steps'], r['external_steps'] > 0)"
```

```text
True cancelled incomplete 0 True
```

Both runs come back as `Ok` with `cancelled / incomplete` and the steps they
really took: none for the flag set in advance, a few for the poll. Any poll
error ends the run as `cancelled`, or as `wall_time_limit` when the poll
returns exactly that text. The poll's own message is not kept, so record it in
the caller. A job worker passes its own deadline check as the poll.
Cancellation is cooperative: the solver polls between pieces of work.

## Checkpoint round trip

[`manual_checkpoint.rs`](https://github.com/dietmarwo/CFD-craft/blob/main/crates/cfd-craft/examples/manual_checkpoint.rs) stops the periodic
tracer case after five steps, writes a checkpoint file, reads it back, resumes
the full case and compares the final state with an uninterrupted run.

```bash
target/release/examples/manual_checkpoint runs/lib-checkpoint.json \
  | python -c "import json, sys; r = json.load(sys.stdin); print(r['passed'], r['partial_steps'], r['final_steps'], r['same_state_as_cold'], r['initial_state_id_differs'])"
```

```text
True 5 20 True True
```

The resumed state equals the cold one, and the two runs report different
initial-state identities, as in [chapter 8](08-checkpoint-restart.md). The
file must be new. It is a checkpoint only, not a run archive.

## Read a CLI archive

[`manual_archive.rs`](https://github.com/dietmarwo/CFD-craft/blob/main/crates/cfd-craft/examples/manual_archive.rs) reads a run directory
with `output::read_verified`. A Rust service that collects the output of
`cfd-craft run` jobs does this.

```bash
for run in runs/point runs/partial; do
  target/release/examples/manual_archive "$run" \
    | python -c "import json, sys; r = json.load(sys.stdin); print(r['archive_consistent'], r['numerically_accepted'], r['termination'], r['assessment'])"
done
```

```text
True True completed steady_discrete_solution
True False iteration_limit incomplete
```

Both archives are consistent. Only the first is numerically accepted.
Integrity and acceptance are separate answers, and the example prints the
validation label as a third.

## Threads, pools and build identity

The library does not create a thread pool from `case.run.threads`. The caller
installs a Rayon pool, as the examples do with `pool.install`; without one the
solver runs on Rayon's global pool. The command and the Python binding do
this for you.

A bare library result identifies the core package: its source fingerprint,
version and compiler. The command and the binding add the identity of their
own wrapper sources. Before you call `write_run` in your application, put
your application's build identity into those fields. Do not copy the
command's identity into another producer.

## Profile from Rust

Phase timing ([chapter 9](09-opt-in-numerics.md)) is a property of the
control. These lines are from a test of the library:

<!-- check: fragment of crates/cfd-craft/tests/profiling.rs -->
```rust
let control = Control::new(60.0).with_profiling();
let r = pool.install(|| solver::run(&c, &control, None)).unwrap();
let p = control.profile().unwrap().unwrap();
```

`Control::profile` returns `None` without `with_profiling`. See
[profiling](../developer/profiling.md).

## Select multigrid from Rust

Set the preconditioner on the case before the grid is built or the solver is
called. `pressure::multigrid_stats` reports the hierarchy after the first
pressure solve. From a test of the library:

<!-- check: fragment of crates/cfd-craft/tests/multigrid.rs -->
```rust
c.numerics.pressure_preconditioner = PressurePreconditioner::Multigrid;
let stats = pressure::multigrid_stats(&g).unwrap();
```

See [pressure multigrid](../developer/pressure-multigrid.md).

## Next

- [docs.rs/cfd-craft](https://docs.rs/cfd-craft): the API reference.
- [Chapter 21](21-troubleshooting.md): symptoms, codes and actions.
