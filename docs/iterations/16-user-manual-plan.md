# Detailed user manual and project banner

Base: merged PR #9 (`4f156e5`).

## Scope

Provide one human entry point that explains the architecture, numerical and
evidence concepts, and the actual supported APIs. Cover the merged native
solver, OpenFOAM adapter and existing optimization-jobs/fcmaes integration;
describe only implemented features (particles, for example, are not part of
the native model). Preserve the reviewed backend timing definitions,
shared cavity helpers and numerical/physical acceptance distinctions.

## Deliverables

1. `docs/USER_MANUAL.md`: navigation, quickstart, architecture diagrams and a
   complete case walkthrough; CLI, Rust and Python examples; outputs, budgets,
   cancellation, restart, external workflows, optimizer jobs, troubleshooting,
   validation and performance interpretation. Link to detailed model cards.
2. Small runnable examples under `examples/manual/` and the Rust crate's
   examples directory. Test real API calls with a fast source-response case,
   receptor lookup by ID, checkpoint continuation, archive verification,
   cancellation and coded invalid input. Include an optional actual OpenFOAM
   cavity example and the existing runner integration without inventing APIs.
3. A generated engineering banner under `docs/images/`, displayed at the top
   of README with meaningful alternative text and a prominent manual link.
   Treat the artwork as illustration, not a CFD result or validation badge.
4. Documentation-example checks in CI: the small native examples on every
   push, and the manual's OpenFOAM recipes in the manual external backend job.

## Implementation and acceptance

- Read CLI describe, public Rust definitions and existing Python workflow
  entry points before documenting them. Case/result schemas remain 0.1.
- Explain the two independent backends and the outer job/campaign layers;
  Rust is the native library API, Python orchestrates the CLI and adapters.
- Use small bounded, serial examples and fresh output roots that run on a
  modest CPU host without remote commissioning.
- Keep required fields, units, coordinate conventions, source normalization,
  receptor ordering and unknown-field rejection explicit.
- Demonstrate that `Result::Ok`, exit 0, numerical assessment, archive integrity
  and experimental validation answer different questions. Preserve failures.
- Explain native transient restart separately from steady OpenFOAM continuation
  and cross-mesh field initialization. Neither replaces final acceptance.
- Compile and execute every new Rust example; run Python examples normally
  and under -O; verify source budgets, mass/receptor checks and real returned
  fields. Run the optional OpenFOAM example against the pinned runtime.
- Run locked workspace release tests, fmt/clippy, Python Ruff and the relevant
  CLI/backend/benchmark/integration contracts. Do not rerun expensive unrelated
  campaigns for a documentation change or weaken scientific thresholds.
- Check Markdown links/anchors and example-to-manual references. Inspect the
  banner's text and appearance and the README reference.

## Boundaries

No solver method, physical model, numerical tolerance, package pin or job
protocol change is needed. Documentation examples are executable API usage,
not additions to numerical scope. The manual must preserve the measured
OpenFOAM advantage on the cavity and avoid extrapolating it to canyon or
particle workloads. Source-gate decisions and experimental qualification
remain separate work.
