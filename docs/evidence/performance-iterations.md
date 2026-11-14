# Ten performance iterations after P5d: results

<!-- check: none: record of past runs -->

Date: 1 November 2026. Goal: close the remaining cost gap to OpenFOAM at
matched accuracy (stage M measures it on the cavity) and make the steady RANS
canyon with its tracer, the case of the dust study, cheaper. No OpenFOAM source
was read or copied; the levers are standard steady-solver practice (inexact
inner pressure solves, a bounded pseudo-time ramp, one cell on the homogeneous
axis of a two-dimensional problem) and plain kernel work.

## How the iterations were checked

- **Bit identity.** Iterations 1–3, 5 and 8–10 do not change any result. A new
  regression (`kernels_keep_their_recorded_bits`, recorded at `2ffedec` before
  the first iteration) pins the bits of the momentum right-hand side for all
  five momentum schemes, the laminar and RANS implicit matrices and their
  product, an implicit k–ε step and both scalar transport schemes, on a
  cavity, a masked cavity, an open channel and an open and a periodic RANS
  canyon. It passed unchanged after each of these iterations, as did
  `rans_stencils_keep_their_recorded_bits`, and the archived fields of the
  benchmark runs kept their SHA-256.
- **Changed paths.** Iterations 4, 6 and 7 change the path to the steady state
  (or, for 6, the grid), not the steady state; their evidence is acceptance
  under the unchanged gates and unchanged accuracy.
- **Timing.** The 2-vCPU VM is noisy (±10–50% between identical runs), so
  timings are medians of 3–5 alternating rounds, and kernel iterations are
  also compared by instruction counts of fixed-work runs (valgrind
  cachegrind; about a third of each count is the SHA-256 of the executable,
  which valgrind runs in software, and is constant).

## The iterations

| # | Commit | Change | Identity | Evidence |
|---|---|---|---|---|
| 1 | `8334d31` | Flux-form momentum advection: each control-volume face flux evaluated once (center fluxes per cell, edge fluxes per face) instead of from both momentum cells | bit-identical | 48² cavity¹: 2.92 → 2.41 s |
| 2 | `ac5e33e` | Cached same-axis neighbor faces of every face (`Grid::neighbor_faces`) | bit-identical | 2.41 → 2.30 s |
| 3 | `874bd8c` | Allocation-free k and ε transport operator in the implicit turbulence solves | bit-identical | no measurable change; the turbulence step's cost is in its residual terms |
| 4 | `090676b` | Inexact inner projections for `implicit_projection` (recipe: `pressure_relative_tolerance` 0.1; the sweep accepts 0.1 or 0.01) | same fixed point | 48² cavity: 1,536 → 270 multigrid PCG iterations, Ghia error 0.0050161 unchanged to 1e-9; development canyon: 26,947 → 3,690 IC(0) iterations in the same 500 outer iterations |
| 5 | `222a3c8` | Edge-flux faces from cached tables (`Grid::edge_faces`); laminar momentum skips the eddy-viscosity face means | bit-identical | 48² cavity, tolerance 0.1: 1.67 → 1.35 s |
| 6 | `906fdd4` | One cell on a periodic axis: two-dimensional runs; fixes the IC(0) factor for faces that join a cell to itself | span 1 = span 2 to 1e-10 | 24² cavity: 0.272 → 0.191 s, same 210 iterations and Ghia error |
| 7 | `5d08fc5` | CFL ramp capped at 5 (was 1e6, so only `max_time_step_s` bounded it); recipe: non-binding `max_time_step_s` 100 | same fixed point | development canyon with tracer: 1,300 → 400 outer iterations |
| 8 | `875819d` | Ghost probes evaluate a boundary branch once for both values; eddy-viscosity face means computed once per call | bit-identical | canyon, 40 iterations: 3.175e9 → 3.065e9 instructions |
| 9 | `7f148b1` | Scalar transport sub-steps reuse their buffers; one division per face | bit-identical | tracer recipe, 60 iterations: 5.718e9 → 5.452e9 |
| 10 | `d7a9a31` | Fixed scalar transport faces gathered once per outer iteration (`transport::FixedRhs`) | bit-identical | 5.452e9 → 4.994e9 |

¹ van Leer, `implicit_projection`, multigrid, 3 alternating rounds on a loaded
host. Rejected on the way: a compact face-kind array (slightly more
instructions); scalar sub-step caps other than 16 and CFL caps other than 5
(see the [P5c/P5d results](implicit-rans.md) and the commit messages).

Iteration 6 found a real defect: for a face that joins a cell to itself, the
IC(0) factor added a diagonal term and a self off-diagonal entry, so the
preconditioner was wrong on such grids. The dense IC(0) reference test with
[3, 1, 4] and [1, 3, 1] grids failed before the fix. Grids with at least two
cells per axis have no such faces, so nothing else changed.

## Before and after

Solver seconds on this host, medians of 3–5 alternating rounds. "Before" is
`2ffedec` (P5d, before iteration 1) with the stage M recipe for the cavity
(van Leer, `implicit_projection`, multigrid, two span cells) and the case
settings for the canyon (`implicit_projection`, pressure tolerance 1e-10,
`max_time_step_s` 0.1). "Final" is `d7a9a31` with the final recipe: pressure
tolerance 0.1, `max_time_step_s` 100 and, for the cavity, one span cell.

| Case | Before | Final, same settings | Final recipe | Speed-up | Accuracy |
|---|---:|---:|---:|---:|---|
| 24² cavity | 0.47 s (210 it.) | 0.33 s | **0.069 s** (180 it.) | 6.8× | Ghia 0.005433 → 0.005427 |
| 48² cavity | 2.84 s (270 it.) | 2.29 s (300 it.)² | **0.49 s** (300 it.) | 5.8× | Ghia 0.005016 → 0.005012 |
| Development canyon, flow | 3.69 s (500 it.) | 3.55 s | **1.55 s** (400 it.) | 2.4× | — |
| Development canyon, tracer | 10.7 s (1,300 it.) | 9.8 s | **1.99 s** (400 it.) | 5.4× | receptors to 2e-7 |
| 27k canyon, tracer | 180 s³ (1,400 it.) | — | **57.6 s** (1,000 it.) | 3.1× | receptors to 1.2e-6 of explicit |
| 93k canyon, tracer | 1772 s³ (2,500 it.) | — | **615 s** (2,500 it.) | 2.9× | receptors to 1.6e-7 of the case-settings run |

² The CFL cap changes the 48² path (300 instead of 270 iterations).
³ Two runs shared the two cores.

Against the explicit steady mode, which the dust study used before P5c: the
development canyon with its tracer takes 42 s explicit and 2.0 s with the final
recipe (21×); the 27k canyon 2,974 s and 57.6 s (52×), and the explicit mode
needs twice the case's step budget.

On this host the final recipe makes the 24² cavity 6.8× cheaper than the
stage M recipe, which had a hosted native/OpenFOAM solver ratio of 0.74×; the
hosted reproduction below measures 0.111×.

## Hosted reproduction

[Run 41361132558](https://github.com/dietmarwo/CFD-craft/actions/runs/41361132558)
(`external=momentum`) on branch head `639b331`: GitHub runner, AMD EPYC 9V74,
4 CPUs, one solver thread per backend, the unchanged stage M protocol (shared
grids 16, 24, 32, 48; one warmup and three alternating timed rounds; the
OpenFOAM recipe, the audits and the screens unchanged). Native inputs:
`momentum_scheme=van_leer`, `native_span=1`,
`native_numerics={"momentum_advection": "limited_upwind", "momentum_limiter": "van_leer", "steady_algorithm": "implicit_projection", "pressure_relative_tolerance": 0.1, "max_time_step_s": 100.0}`,
multigrid pressure. All rows were accepted, and the evidence archive verified
all 51 sealed archives after the zip round trip.

| Grid | Native solver s | OpenFOAM solver s | Native/OpenFOAM | Native Ghia error | OpenFOAM Ghia error |
|---|---:|---:|---:|---:|---:|
| 16² | 0.0244 | 0.264 | 0.092× | 0.0243 | 0.0188 |
| 24² | 0.0698 | 0.628 | **0.111×** | **0.00543** | **0.00897** |
| 32² | 0.142 | 1.399 | 0.101× | 0.00366 | 0.00870 |
| 48² | 0.439 | 5.415 | 0.081× | 0.00501 | 0.00708 |

Workflow medians (with meshing, sampling and audits): 0.091/0.842,
0.142/1.200, 0.345/2.013 and 0.551/6.095 s. **At the 0.01 target (24² for
both) native takes 0.111× OpenFOAM's solver time and 0.119× its workflow
time**, against 0.74× and 0.45× in the stage M run with the earlier recipe and
code (another runner model; each ratio is a same-runner pairing). The native
96² reference with the same numerics was accepted after 570 outer iterations
and 3.39 s (48.5 s before), Ghia error 0.00505, self-convergence orders 2.46
(L1), 2.42 (L2) and 2.21 (max). The default controls (cavity, transient
Poiseuille, masked canyon) are byte-identical to `main` (`6d33850`) with
identical work, and the van Leer momentum fixtures repeat the stage V values.

Scope as in stage M: a laminar two-dimensional cavity; both backends now
compute one span cell; the stopping rules differ (native: the unchanged
`assess` gates; OpenFOAM: `residualControl` 1e-7). The canyon has no OpenFOAM
counterpart in this repository.
