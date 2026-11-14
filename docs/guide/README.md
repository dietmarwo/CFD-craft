# About the guide

The guide teaches CFD-craft in 21 chapters, ordered by difficulty. Each chapter
is self-contained: it starts with a setup, uses one small case and ends with
links to the next steps. It covers the native solver (constant-density
incompressible flow and passive gas on uniform Cartesian grids), its Python
binding, and the separate OpenFOAM backend.

Version 0.1.0 is a research prototype. A numerically accepted run is not an
experimentally validated prediction.

## Chapters

| Part | Chapters |
|---|---|
| I First steps | 1 [First run](01-first-run.md) · 2 [The case file](02-case-file.md) · 3 [The command line and the run archive](03-cli-and-archive.md) · 4 [Can I trust this result?](04-reading-a-result.md) · 5 [Sources, receptors and transport](05-sources-receptors-transport.md) |
| II Flow | 6 [Compute a flow](06-flow-cavity.md) · 7 [Before you spend compute](07-budgets-preview-cancel.md) · 8 [Checkpoint and restart](08-checkpoint-restart.md) · 9 [Opt-in numerics](09-opt-in-numerics.md) · 10 [Buildings and a street canyon](10-street-canyon.md) |
| III Automation | 11 [Python](11-python.md) · 12 [Many runs](12-studies.md) · 13 [Optimization lessons F1 to F3](13-optimization-lessons.md) · 14 [Optimization jobs](14-optimization-jobs.md) |
| IV OpenFOAM backend | 15 [Install and run a cavity](15-openfoam-first-run.md) · 16 [Compare solvers and measurements](16-compare-solvers.md) · 17 [Continue a solve, start a finer mesh](17-continuation-and-mapping.md) · 18 [Audit a wall-resolved backstep](18-backstep-resolution.md) · 19 [A bounded refinement campaign](19-refinement-campaign.md) |
| V Embedding and help | 20 [The Rust library](20-rust-library.md) · 21 [Troubleshooting](21-troubleshooting.md) |

Chapters 1 and 2 need only `pip install cfd-craft`. From chapter 3 on, commands
run from the root of a checkout. Part IV needs Linux and an OpenFOAM
Foundation 13 runtime, which chapter 15 installs.

## Which interface

| Goal | Use | Start at |
|---|---|---|
| Get receptor values and checks in Python | `cfd_craft.check`, `cfd_craft.simulate` | chapter 1 |
| Keep fields, a verified archive, restart, preview, profile | the `cfd-craft` command | chapter 3 |
| Script many archived runs | the command through `subprocess` | chapters 11 and 12 |
| Embed the solver in a Rust program | `cfd_craft::solver::run` | chapter 20 |
| Run optimization jobs or campaigns | the fcmaes worker and `optimization-run` | chapters 13 and 14 |
| Run or compare with OpenFOAM | `integrations/openfoam_backend.py` | chapter 15 |

The Python package installs from PyPI without a toolchain. The command and the
library are built with Rust 1.88 or newer. The analysis scripts and the
OpenFOAM tools are run from a checkout. The native solver does not need
OpenFOAM, and the adapter starts OpenFOAM as separate programs.

## How to read the code blocks

- A `python` or `bash` block is meant to be run as it stands, in the order of
  its section, after the `Setup` section of its chapter. A `sh` block shows
  commands that install, build or take long; adapt them before you run them.
- Every section starts from what `Setup` left, not from the section before
  it. When you run a whole chapter in order, first remove an output directory
  that an earlier section made (`rm -r runs/point`): a run never writes into
  an existing directory (`CFD-E062`, chapter 3).
- A `text` block is the real output of the block before it. Outputs show a few
  chosen fields, never wall times or hashes.
- A `json` block is a complete case, or a fragment that the text names.
- `scripts/check_docs.py` runs the blocks of the chapters and compares the
  outputs: floating-point numbers within the tolerance a chapter states,
  everything else exactly. Part IV runs only where the runtime is installed.

Three words are kept apart on every page. A run **completed** or stopped
(termination). A result is numerically **accepted** or not (assessment). A
model is **validated** against measurements or not; in 0.1.0 none is.
