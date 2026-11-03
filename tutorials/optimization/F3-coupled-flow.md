# F3 — Optimize coupled flow without exploiting a coarse grid

This lesson can legitimately conclude that **no design is supported at the
requested fidelity**. The optimizer searches a coarse discretization, but a
separate fixed gate decides whether its selected design survives refinement.
The implementation is [coupled.py](coupled.py).

## Define a supported coupled problem

Use the laminar lid-driven cavity, varying only lid speed in `[0.6,1.4] m/s`.
The two training viscosities are 0.01 and 0.015 m²/s; 0.0125 is withheld. This
bounded flow-setting problem uses supported box geometry, implicit projection,
limited-upwind momentum advection with the van Leer limiter, and multigrid
pressure preconditioning. There are no masks or new physics models.

The teaching objective targets mean squared fluid speed `0.04 m²/s²`:
`((mean_square_speed-0.04)/0.04)^2 + 0.02*lid_speed^2`. The solver returns one
normal velocity per cell face (a staggered grid). `mean_square_speed` sums the
squared face velocities of each component and divides by the number of cells,
the trapezoid rule along every grid line with zero normal velocity at the
walls. Minimize its worst value
across the two training viscosities. This target is an illustrative design
criterion, not a measured physical requirement or validation of a ventilation
system.

## Run fixed, sampled and optimized designs

After [setup](README.md), run from CFD-craft:

```bash
python tutorials/optimization/run.py F3 --output /tmp/f3-smoke
python tutorials/optimization/run.py F3 --preset study --threads 2 --output /tmp/f3-study
```

Smoke uses `8×2×8` training and `16×2×16` validation grids, with twelve requested
BiteOpt calls. Study uses `16×2×16` and `32×2×32`, with 64 calls. Both compare a
fixed speed of 1.0, five evenly spaced samples, and the optimized incumbent.
The fixed and sampled baselines are additional evaluations, explicitly retained
rather than hidden inside the optimizer budget.

Before any search, freeze a maximum 5,000 steps and 30 seconds per native solve,
the case's residual tolerance `1e-5` and monitor tolerance `0.001` (read from
`lid-cavity.json` and recorded), and a maximum 10% relative change in mean
squared speed between grids. The 30-second wall limit makes acceptance depend
on host load; record the host when comparing runs. The parent subprocess timeout adds
a fixed allowance for output. These thresholds are not relaxed to obtain a
successful design.

A callback is usable only when the native summary reports a steady discrete
solution **and** independent returned-field checks pass. Rejected or timed-out
solves remain in the evidence and receive an unusable objective. A transient
completion is not accepted as a steady design evaluation. All actual solves,
steps, pressure iterations and failure counts are reported.

## Replay before choosing a design

Re-evaluate each nominated baseline/search design on the fine grid at both
training viscosities, then at the withheld viscosity. Require accepted native
and independent checks and the predeclared grid-change threshold. The withheld
viscosity is a convergence check only: its solve must be accepted, and its
objective is reported but not gated. The summary compares coarse and fine
rankings, retains every failed case, and reports
`supported_at_requested_fidelity` per design. `distinct_designs` counts the
different lid speeds; designs with equal speeds are one design, and their order
in a ranking is a tie, not a reversal.

The smoke preset is a useful negative example: its native solves are
accepted, but the coarse/fine energy changes exceed 10% (about 32%), so zero
designs are supported. `passed: true` means the experiment and its checks completed; it
must not be read as `supported_designs > 0`. A numerical acceptance assessment
also does not establish physical validation.

Two-grid agreement is a screening criterion, not a grid-convergence proof.
A supported candidate still needs a systematic refinement study and an
appropriate physical validation case before an engineering claim. The existing
prescribed-flow source-allocation worker never runs this pressure/momentum
problem. This lesson uses a fallible Python callback and can be wrapped in the
existing command-job interface; no coupled-flow stock worker is claimed.

## Prompt and follow-up

> Optimize the supported cavity setting under frozen numerical and work limits.
> Compare a fixed design and simple sampling, replay the nominees on finer grids
> and withheld conditions, and retain failures and ranking reversals. State
> clearly when no design meets the requested fidelity.

Run the larger preset, add a third refinement level, and report cost to accepted
quality. For masked geometries use supported IC(0); do not assume masked
multigrid is available. Canyon/RANS qualification and the older room-ventilation
LBM model remain separate questions. See the
[refinement campaign](../refinement-campaign-prompt.md) and
[implicit RANS evidence](../../validation/IMPLICIT_RANS_RESULTS.md).
