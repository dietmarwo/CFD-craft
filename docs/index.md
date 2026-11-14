# CFD-craft

A Rust CFD research solver for incompressible flow and passive-gas dispersion
on uniform Cartesian grids, used from Python, a JSON command line or Rust, with
a bounded OpenFOAM Foundation 13 backend for cross-checks.

Version 0.1.1 is a research prototype. A numerically accepted run is not an
experimentally validated prediction.

## Start here

- [First run](guide/01-first-run.md): install the Python package and compute
  one accepted concentration in a few minutes.
- [How do I …?](how-to.md): tasks in plain words, each linked to the section
  of the guide that does it.
- [CFD-craft, OpenFOAM and Ansys Fluent](comparison.md): what each tool is
  for, the committed measurements, and where the others are ahead.

## What 0.1.1 contains

- Uniform Cartesian grids with box-shaped solids.
- Laminar flow and one neutral k-epsilon package.
- Passive gas with point, line and volume sources, and point and volume receptors.
- Bounded runs (steps, wall time, memory, output) with checksummed restart.
- Strict case and result schemas, listed by `cfd-craft describe`.
- Opt-in second-order momentum, implicit steady iteration and pressure multigrid; the defaults are unchanged.
- An optional, bounded OpenFOAM Foundation 13 backend for two generated cases: a laminar cavity and a turbulent backward-facing step.
- Optimization examples: a linear program, sensor placement and a coupled-flow design.

It does not contain particles, vegetation, LES, chemistry, stretched grids or
GPU execution.

## The guide

21 chapters, ordered by difficulty; each starts with its own setup. The
[guide index](guide/README.md) lists them and says which interface to use.

- **Part I, First steps:** run a case from Python, the case file, the command
  line and the run archive, how to read a result, sources and receptors.
- **Part II, Flow:** a lid-driven cavity, budgets and previews, checkpoint and
  restart, opt-in numerics, buildings and a street canyon.
- **Part III, Automation:** the Python binding in depth, many runs and source
  inference, optimization lessons, optimization jobs.
- **Part IV, OpenFOAM backend:** install and run, compare two solvers and
  measurements, continuation and mesh initialization, a wall-resolved
  backstep, a bounded refinement campaign.
- **Part V, Embedding and help:** the Rust library, troubleshooting.

## Reference

Case and result schemas, the command line, the Python API, units and
conventions, diagnostic codes and model cards: [reference](reference/README.md).

## Evidence

The verification records, the comparisons with OpenFOAM and with measurements,
and the optimization lessons' records, failed rows included:
[evidence](evidence/README.md).

## Developer

Architecture, the checks before a change, profiling, pressure multigrid,
numerics decisions, the roadmap and releasing: [developer](developer/README.md).

## History

Iteration plans as they were written, kept unchanged: [history](history/README.md).

## For AI agents

The run loop, the rules and the machine-readable entry points:
[agent entry point](ai-context.md).

## Related repositories

CFD-craft is one of 18 related repositories; the
[repository overview](https://github.com/dietmarwo/fcmaes-rust/blob/main/docs/repositories.md)
shows what each one does.
