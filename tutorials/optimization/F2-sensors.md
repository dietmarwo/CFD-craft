# F2 — Select sensors and test what remains identifiable

Sensor coverage answers whether an event can be detected. Source inversion asks
which rates generated the observations. This lesson solves the first problem
exactly for a small scenario set and tests the second independently. See
[sensors.py](sensors.py).

## Freeze the decision problem

There are six candidate receptors and a budget of **at most three sensors**.
Construct response matrices at training winds 0.85 and 1.15 m/s. Six source
vectors at each wind make twelve scenarios: three single-source releases and
three two-source releases. Single-source scenarios have weight three and pairs
weight one.

A sensor detects a scenario when its normalized concentration reaches 0.24:
a physical threshold `0.22 * 1e-8 kg/m³` plus a declared noise allowance
`0.02 * 1e-8 kg/m³`. These values are fixed before the search. Let binary `z_i`
select a sensor and binary `y_j` claim scenario coverage. The native MIP is:

```text
maximize sum_j weight_j * y_j
sum_i z_i <= 3
y_j <= sum_i detection_ij * z_i
z_i,y_j in {0,1}
```

All variable bounds are finite, as required by the native MIP backend.
`support.py` builds CSR rows and independently checks bounds, activities and
integrality of the returned candidate.

## Run the checks

After [setup](README.md), run from CFD-craft:

```bash
python tutorials/optimization/run.py F2 --output /tmp/f2-smoke
```

This exact small lesson uses the same finite scenario design for both presets;
`study` is intentionally not a larger combinatorial problem. Its natural
extensions are described below. Each wind's response matrix comes from three
accepted unit-source CFD solves with independent field checks; the scenario
columns are linear combinations of those responses, exact for the linear
transport.

Enumerate all twenty three-sensor subsets and compare the best covered weight
with the MIP result. This also certifies the optimum for *at most* three sensors:
weights are nonnegative, so padding a smaller subset cannot decrease coverage.
A greedy procedure adds the largest marginal-coverage sensor three times and
provides a separate baseline. Ties can yield different subsets or an optimal
MIP solution that uses fewer than three sensors. Never reinterpret such a
solution as a three-sensor identifiability certificate.

The chapter also lists every subset of at most three sensors that reaches the
coverage optimum (`optimal-subsets.json`, summarized in
`coverage_optimal_subsets`), with the rank and condition number of its
calibration matrix. In this fixture two single receptors already detect all
twelve scenarios, so every three-sensor subset is optimal: the instance cannot
separate MIP from greedy, and which optimal subset each returns is decided by
solver and index order, not by the objective.

## Challenge the selected sensors

Use held-out source multipliers `[0.7,1.3,0.4]`. Build a calibration response
matrix at wind 1.0, then generate fresh observations at winds 1.0 and 1.3. The
second wind deliberately mismatches the inverse model. Add bounded uniform
noise with a fixed seed and the declared allowance.

For the MIP and greedy subsets, report singular values, matrix rank, condition
number, nonnegative least-squares residual and relative source-rate error for
both noiseless and noisy observations. Wind 1.0 is the calibration wind, so its
noiseless inversion is in-model and exact up to rounding; wind 1.3 is the
mismatch case. The held-out `detection` flag compares the noiseless field with
the physical threshold 0.22. A deficient inverse has a nonzero nullity
and a null `condition_number`; the finite condition of its observed subspace is
reported separately. NNLS is a separate inverse-problem
validation tool; it does not solve or replace the sensor MIP.

In this deliberately permissive detection fixture, coverage can saturate with
one central sensor. That is a useful counterexample: the MIP can be optimal for
coverage while its inverse matrix has rank one, and a three-sensor optimum can
be well or poorly conditioned (condition numbers 2.0 to 259 here). Even a tiny residual may leave
many source combinations indistinguishable. Inspect `scenario-matrix.json`,
`exhaustive.json`, `optimal-subsets.json` and the `inversion` rows in
`summary.json` before interpreting an optimal solver status.

## Prompt and follow-up

> Choose sensors under a count budget and verify the finite coverage optimum
> exhaustively. Then reconstruct held-out source strengths with noise and wind
> mismatch. Explain why an optimal detection decision can remain unidentifiable,
> using rank and conditioning rather than optimizer status alone.

Predeclare a stricter detection threshold, scenario costs, or a larger candidate
set and repeat the experiment; a threshold at which no single receptor covers
every scenario is needed before this instance can separate methods. If identifiability is the actual objective,
formulate and validate it explicitly: Fisher-information or continuous-location
criteria generally produce a different nonlinear design problem. Do not call
that extension the same LP/MIP. See the existing
[source-inference lesson](../source-inference-prompt.md) for further inverse
controls.
