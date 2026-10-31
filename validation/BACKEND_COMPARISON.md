# Native solver and OpenFOAM on the lid-driven cavity: measured cost

Both backends solve the supported Re=100 lid-driven cavity on the same machine,
one solver thread each, on two hosts. The first host ran an earlier script of
the same procedure; the second, a GitHub runner, ran
`validation/compare_backends.py` with the current repository. This compares
configured, accepted workflows; it is not a fixed operation count or a ranking
of Rust against C++.

## Result

On this case OpenFOAM is faster and closer to the Ghia reference. Native
steady mode costs about half as much as the native transient run to 30 s, but
OpenFOAM's whole workflow is still 4.7–5.5 times faster than native steady mode
on the two hosts, and its solver process about 9 times faster than the native
steady solver.

First host: AMD EPYC 9V74 virtual machine, Linux x86_64, Python 3.12. One
warmup per method, then the six orders of the three methods once each.

| Configuration | Workflow median (range), s | Solver median, s | Steps or iterations | Cells | Maximum centerline u error / lid speed |
|---|---:|---:|---:|---:|---:|
| OpenFOAM steady SIMPLE/GAMG | 1.2622 (1.2091–1.5991) | 0.7764 | 696 | 576 | 0.00896632 |
| Native steady | 6.9443 (6.8714–7.0333) | 6.9060 | 2010 | 1152 | 0.02756134 |
| Native transient to 30 s | 13.9984 (13.7937–14.0767) | 13.9303 | 4093 | 1152 | 0.02754881 |

| Native / OpenFOAM | Workflow, ratio of medians | Workflow, median within rounds | Solver, ratio of medians |
|---|---:|---:|---:|
| Native steady | 5.502 | 5.455 | 8.895 |
| Native transient | 11.090 | 10.989 | 17.942 |

GitHub runner: AMD EPYC 9V45, 4 CPUs, ubuntu-24.04, Python 3.12, workflow run
[41195406078](https://github.com/dietmarwo/CFD-craft/actions/runs/41195406078).
One warmup per method, then the six orders twice (12 rounds).

| Configuration | Workflow median (range), s | Solver median, s | Steps or iterations | Cells | Maximum centerline u error / lid speed |
|---|---:|---:|---:|---:|---:|
| OpenFOAM steady SIMPLE/GAMG | 0.89909 (0.89281–1.0084) | 0.47209 | 696 | 576 | 0.00896632 |
| Native steady | 4.2183 (4.1309–4.3696) | 4.1921 | 2010 | 1152 | 0.0275613 |
| Native transient to 30 s | 8.7101 (8.4174–8.8005) | 8.6833 | 4093 | 1152 | 0.0275488 |

| Native / OpenFOAM | Workflow, ratio of medians | Workflow, median within rounds | Solver, ratio of medians |
|---|---:|---:|---:|
| Native steady | 4.692 | 4.675 | 8.88 |
| Native transient | 9.688 | 9.549 | 18.39 |

The solver ratios agree closely between the hosts (8.9 and 8.9 for steady,
17.9 and 18.4 for transient). The workflow ratios differ more (5.5 and 4.7),
because OpenFOAM's fixed workflow overhead, about 0.4–0.5 s, is a larger share
of its shorter workflow.

All runs on both hosts passed their numerical checks, their independent
audits and the frozen 0.06 Ghia screen, and each method repeated its work count
and sampled profile exactly in every round. The first host's native build has
a different source identity from the current repository, but its native fields
are byte-identical to those of the current build (checked separately on a third
machine), so both hosts measure the same native numerics.

## What is held fixed and what differs

Both solve a unit square cavity with lid speed 1 m/s, viscosity 0.01 m²/s
(Re=100), zero initial velocity and 24×24 cells in the flow plane. The native
case is x/z with two periodic span cells (24×2×24, 1152 cells), because native
validation rejects a one-cell axis; OpenFOAM uses one empty span cell
(24×24×1, 576 cells, 0.1 m deep). Both are nominally two-dimensional, but the
native solver computes both span layers.

| | OpenFOAM | Native steady | Native transient |
|---|---|---|---|
| Case | generated cavity recipe, unchanged | `cases/verification/lid-cavity.json`, one thread, `run.mode = steady` | the same case, one thread |
| Algorithm | steady SIMPLE (consistent), GAMG pressure, bounded linear-upwind momentum | explicit SSPRK2 pseudo-time steps with two pressure projections per step (PCG with IC(0)), donor-cell momentum | the same steps, in physical time |
| Stopping | 1e-7 initial residuals plus independent stored-flux checks | the existing momentum and monitor gates (momentum residual 8.85e-6 at 2010 steps, pseudo-time 14.81 s) | the end time of 30 s (momentum residual 3.88e-10) |
| Ghia error | 0.0090 | 0.0276 | 0.0275 |

The residual definitions of the two backends are not interchangeable. The Ghia
profile is a numerical reference, not an experiment, and the error is one
sampled velocity component, not a full-field assessment.

## Where the time goes

Per cell and step, native costs about 1.5 times as much as OpenFOAM per cell
and SIMPLE iteration on both hosts. Most of the factor of about 9 comes from how
many steps the native method needs and from its second span layer:

| Solver time | First host | GitHub runner |
|---|---:|---:|
| OpenFOAM, per SIMPLE iteration | 1.12 ms | 0.68 ms |
| Native steady, per step | 3.44 ms | 2.09 ms |
| OpenFOAM, per cell and iteration | 1.94 µs | 1.18 µs |
| Native steady, per cell and step | 2.98 µs | 1.81 µs |

Native steady takes 2.9 times as many steps as OpenFOAM takes SIMPLE
iterations, on twice the cells, and each native step runs about 102 PCG
iterations in its two projections (204,850 over 2010 steps). The OpenFOAM time
includes process start-up and file input and output, so its per-iteration cost
is overstated here. This decomposition explains the measured numbers on this
case; it is not a measured attribution of what a different algorithm would
save.

## Timing definitions

- **Workflow** time encloses case preparation, the solve, the independent
  audit and the centerline evaluation. For OpenFOAM that includes copying the
  case, the runtime check (which hashes the runtime's binaries and libraries),
  blockMesh, checkMesh, foamRun, sampling and archive verification, each child
  polled every 50 ms. For native it includes writing the case, the CLI run and
  its output, `check_fields.py` and reading the fields. Installation and
  compilation are excluded.
- **Solver** time is the foamRun process for OpenFOAM and the native solver's
  own timer (`elapsed_s`, without process start) for native. The two are
  similar in scope but not identical.
- One unscored warmup per method precedes the timed rounds; every order of the
  three methods is used, so each method runs first, second and last equally
  often. The runs are serial with one solver thread and BLAS and OpenMP limited
  to one thread. No CPU frequency pinning or host isolation was established.

## Consequences

1. There is no measured native speed advantage over OpenFOAM on this shared
   case. The [native performance results](../docs/iterations/07-14-performance-results.md)
   compare the native solver with its own previous version, not with OpenFOAM.
2. The native cost is dominated by the number of explicit pseudo-time steps and
   by the pressure solve in each. A steady algorithm and a multigrid pressure
   solver or preconditioner are the natural next native experiments; this
   comparison does not measure what they would save.
3. Ranking the backends for the urban canyon needs the same 3D canyon with
   compatible physical assumptions, accepted fields, cost at comparable
   observable error and complete campaigns. The backstep and native canyon
   results solve different problems and cannot supply that ranking.
4. Large-case scaling and memory are not measured head to head. OpenFOAM
   supports MPI domain decomposition, but the CFD-craft adapter runs it
   serially; the native solver uses shared-memory threads on uniform grids.
   Nothing about multi-core speedups follows from these single-thread runs.

## Reproduce

With the pinned runtime installed as in [OPENFOAM.md](../integrations/OPENFOAM.md)
and a release build:

```sh
cargo build --release --locked
python validation/compare_backends.py --foam-root ROOT --output runs/backend-comparison
```

`--repeats N` runs the six orders N times (default 1). A manual CI dispatch
with `external=comparison` runs two passes on a GitHub runner, publishes the
medians and ratios as notices and uploads the report. Exit 0 means every run
passed and the comparison completed; any failed run, changed input or
unrepeated result exits 1 with a coded `CFD-B002 comparison.<field>` error.
