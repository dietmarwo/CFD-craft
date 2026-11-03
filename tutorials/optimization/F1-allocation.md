# F1 — Expose a response matrix and choose LP or black-box search

A simulation objective need not require repeated black-box optimization. With
fixed flow, diffusivity, geometry and boundaries, the `linear_upwind` transport
fixture is linear in its source strengths. [allocation.py](allocation.py)
constructs that linear map and solves the same problem with three native solvers.

## Derive one common feasible problem

There are three equal-base, equal-volume sources and six receptors. A unit
source simulation supplies one column of `A`, whose concentrations are divided
by `1e-8 kg/m³`. If `q` contains source multipliers, receptor responses are `Aq`.
Minimize the maximum receptor concentration using an epigraph variable `t`:

```text
minimize t
A q <= t
q0 + q1 + q2 = 3
0.1 <= q0,q1 <= 1.4
0.2 <= q2 <= 2.8
```

These are exactly the bounds and fixed-total constraint of
`app.cfd.source-allocation`. The two black-box coordinates are `q0,q1` with
`q2=3-q0-q1`. Equal support volumes matter: equal rate densities alone would not
imply equal base emissions for arbitrary source geometries.

The LP has four variables and receptor inequalities plus one equality. It is
solved with LP-IP-craft's native backend. A separate reference eliminates q2,
enumerates intersections of three active inequalities and checks every
candidate against all inequalities. The native objective must agree with this
independent vertex optimum within `1e-7`.

## Run all three methods

Follow [setup](README.md), then from CFD-craft:

```bash
python tutorials/optimization/run.py F1 --output /tmp/f1-smoke
python tutorials/optimization/run.py F1 --preset study --output /tmp/f1-study
```

For nondefault locations, supply `--binary`, `--worker` and `--runner` with
absolute paths. The GP arm obtains the real worker's advertised
`fcmaes.surrogate/1` example, uses the same input case and runs it through an
isolated foreground node. It has one run, one concurrent proposal, one evaluation
thread and a final native recheck. This is the current deterministic GP
interface, not a noise-aware simulator extension.

The smoke preset requests 16 BiteOpt and 16 GP objective evaluations; the study
requests 128 each. Every BiteOpt evaluation runs full CFD and records its native
and independent assessment. An unacceptable solve returns an unusable objective
and remains in the report. The GP's native work manifest retains failed,
cancelled and validation evaluations; the chapter fails if that arm is incomplete
or has failed/cancelled evaluations.

## Charge setup and validate the answers

The LP pays for three unit-response solves before solving its small model.
BiteOpt and GP pay for each full objective solve. Compare total cost using
response construction, search, native GP recheck and final validation. The
GP's work counters are **additional** to `work.full_field_solves`; its native
worker does not export full fields at each objective. The native job handle,
input, snapshots and result remain under `gp/`.

Replay each chosen multiplier vector with a fresh full CFD run. Require steady
discrete acceptance and the independent field checks. Compare all receptor
values with `Aq` within the frozen normalized tolerance `1e-4 * max(1,max(Aq))`.
No replay may beat the independent LP optimum beyond the declared tolerance.
The final replay fields make this more than a comparison of optimizer return
values.

Finally, replay each answer with wind increased from 1.0 to 1.15 m/s. This is a
separate model-mismatch exercise. The training matrix is not exact for the
changed wind, and good training allocation need not be best there. MUSCL would
also change the premise: limiter nonlinearity prevents an exact-superposition
claim. Do not replace the transport scheme while retaining the LP guarantee.

## Prompt and follow-up

> Determine whether source allocation is linear, construct and verify its
> response matrix, and compare native LP, BiteOpt and deterministic GP on the
> identical domain. Charge setup and rechecks, then use fresh full CFD and
> changed-wind validation to explain what the optimum actually guarantees.

Try more receptors or a different fixed total. For uncertain winds, build one
response matrix per frozen scenario and add all receptor inequalities to a
robust finite-scenario LP. Recheck every selected solution with its matching
simulator conditions. Start from [source inference](../source-inference-prompt.md)
and the [application worker](../../integrations/README.md).
