# Optimization lessons F1 to F3

<!-- check: rel=1e-4 -->

This chapter runs three complete optimization exercises on the real solver: a linear program hidden in a transport problem (F1), a sensor-placement problem where the optimum does not identify the sources (F2), and a coupled-flow design that must survive a finer grid (F3). Each lesson ends with checks that are allowed to say "no design is supported". You need a checkout with the release build, the validation requirements and two Python packages; F1 also needs the job runner of [chapter 14](14-optimization-jobs.md).

The lessons read `cases/verification/source-response.json` (F1, F2) and `cases/verification/lid-cavity.json` (F3) and write every native case, summary and field they produce.

## Setup

Run all commands from the root of a checkout. Build the command line, install the validation requirements and the two optimization packages:

```sh
cargo build --release --locked
python -m pip install -r requirements-validation.txt
python -m pip install fcmaes-rust==0.2.1 lp-ip-craft==0.29.0
```

`fcmaes-rust` provides BiteOpt; `lp-ip-craft` provides the native LP and MIP solvers. The outputs below were made with these two versions. The lesson scripts find `target/release/cfd-craft` in the checkout by default (`--binary` changes it).

```bash
mkdir -p runs
```

Each lesson is one command, `python tutorials/optimization/run.py LESSON --output NEW_DIRECTORY`, with `--preset smoke` (default) or `--preset study`. The lessons are implemented in [`allocation.py`](https://github.com/dietmarwo/CFD-craft/blob/main/tutorials/optimization/allocation.py) (F1), [`sensors.py`](https://github.com/dietmarwo/CFD-craft/blob/main/tutorials/optimization/sensors.py) (F2) and [`coupled.py`](https://github.com/dietmarwo/CFD-craft/blob/main/tutorials/optimization/coupled.py) (F3); [`support.py`](https://github.com/dietmarwo/CFD-craft/blob/main/tutorials/optimization/support.py) holds the bounded CFD runs, the native LP and MIP models and the independent checks of their answers. The output directory must be new. Its `summary.json` keeps every solve, including rejected ones, and two fields that mean different things:

- `passed` is true when the lesson ran to the end and all its checks held. It is a workflow verdict.
- `supported_at_requested_fidelity` (F3 only, one per design) is the scientific gate: does the design survive a finer grid? A lesson can pass with zero supported designs.

Neither field is experimental validation of a real site. The checks stay active under `python -O`. F1 and F2 use prescribed flow and serial transport, so they run with one thread; only F3 solves momentum and pressure.

Outputs on this page are real. The documentation check compares floating-point numbers with a relative tolerance of 1e-4; everything else must match exactly.

## F1: a linear problem hides in the simulator

<!-- check: jobs -->

With fixed flow, diffusivity, geometry and boundaries, the `linear_upwind` transport of the source-response case is linear in its source strengths. Three equal sources (same base rate, same volume) feed six receptors. One unit-source run per source gives one column of a response matrix `A` (concentrations divided by 1e-8 kg/m3). With source multipliers `q`, the receptor responses are `A q`. Minimizing the largest receptor concentration at a fixed total emission is then a linear program with an epigraph variable `t`:

<!-- check: none: problem statement, not output -->
```text
minimize t
A q <= t
q0 + q1 + q2 = 3
0.1 <= q0,q1 <= 1.4
0.2 <= q2 <= 2.8
```

These are the bounds and the fixed total of the worker model `app.cfd.source-allocation` (chapter 14), whose two search coordinates are `q0, q1` with `q2 = 3 - q0 - q1`. Equal source volumes matter: equal rate densities alone would not give equal base emissions for arbitrary source shapes.

The lesson solves the same problem three ways:

1. **LP.** The native LP of `lp-ip-craft`. An independent reference eliminates `q2`, enumerates the intersections of three active inequalities and checks every candidate against all inequalities. The two optima must agree within 1e-7.
2. **BiteOpt.** Every evaluation is a full CFD run with its native and independent field checks. An unacceptable solve returns an unusable objective and stays in the report.
3. **GP.** A deterministic Gaussian-process surrogate (`fcmaes.surrogate/1`: seed 601 as for BiteOpt, four initial points, 64 candidates, ten fit iterations, one fit restart) runs through the fcmaes worker on a local foreground node of `optimization-run`. Its search evaluations are accepted on the worker's native steady assessment; the independent field check applies to its answer at the final replay. The lesson fails if this arm has failed or canceled evaluations.

The smoke preset requests 16 BiteOpt and 16 GP evaluations; the study requests 128 each.

```bash
python tutorials/optimization/run.py F1 \
  --runner ../optimization-jobs/target/release/optimization-run \
  --output runs/f1 > /dev/null
```

```python
import json

s = json.load(open("runs/f1/summary.json"))
print("passed:", s["passed"])
for arm in s["arms"]:
    print(arm["method"], arm.get("replay_objective"), arm.get("heldout_wind_objective"))
```

`--worker` and `--binary` take other locations of the worker and the solver. The study preset is a separate command:

```sh
python tutorials/optimization/run.py F1 --preset study \
  --runner ../optimization-jobs/target/release/optimization-run --output runs/f1-study
```

**Charge the setup.** The LP pays for three unit-response solves before it solves a small model; BiteOpt and GP pay for each objective solve. Compare total cost with response construction, search, the GP's native recheck and the final replays included. The GP's work counters are additional to `work.full_field_solves`, because its worker does not export full fields at each objective; its job handle, inputs, snapshots and result stay under `gp/` in the output.

**Replay the answers.** Each chosen multiplier vector is replayed with a fresh full CFD run. The replay must be a steady discrete solution, pass the independent field checks, and match `A q` for every receptor within `1e-4 * max(1, r)`, where `r` is the replay's largest normalized receptor value. No replay may beat the LP optimum beyond that tolerance.

**Change the wind.** Finally every answer is replayed with the wind raised from 1.0 to 1.15 m/s. This is a separate model-mismatch exercise: the training matrix is not exact for the new wind, and the best training allocation need not be best there. Switching the transport to MUSCL would also break the premise, because the limiter is nonlinear and superposition no longer holds exactly.

To go further, try more receptors or another fixed total. For uncertain winds, build one response matrix per frozen wind scenario, put all their receptor inequalities into one robust LP, and replay every selected allocation under its matching conditions.

## F2: coverage is not identifiability

Sensor coverage asks whether a release is detected. Source inversion asks which rates produced the observations. F2 solves the first problem exactly and tests the second separately.

There are six candidate receptors and a budget of at most three sensors. Response matrices at training winds 0.85 and 1.15 m/s and six source vectors per wind give twelve scenarios: three single-source releases (weight 3) and three two-source releases (weight 1). A sensor detects a scenario when its normalized concentration reaches 0.24: a physical threshold of 0.22 x 1e-8 kg/m3 plus a noise allowance of 0.02 x 1e-8 kg/m3, both fixed before the search. With binary `z_i` (sensor chosen) and `y_j` (scenario covered), the native MIP is:

<!-- check: none: problem statement, not output -->
```text
maximize sum_j weight_j * y_j
sum_i z_i <= 3
y_j <= sum_i detection_ij * z_i
z_i,y_j in {0,1}
```

All variable bounds are finite, as the native MIP backend requires. The lesson checks the returned candidate's bounds, row activities and integrality itself, enumerates all twenty three-sensor subsets to confirm the optimum, and runs a greedy baseline that adds the sensor with the largest marginal coverage three times. Each wind's matrix comes from three accepted unit-source solves with independent field checks; scenario columns are linear combinations of them, exact for linear transport. The study preset uses the same small scenario design.

Then it tests the chosen sensors on held-out source multipliers `[0.7, 1.3, 0.4]`: a calibration matrix at wind 1.0 and fresh observations at winds 1.0 (in-model) and 1.3 (a deliberate mismatch), with bounded uniform noise from a fixed seed. For each subset it reports singular values, rank, nullity, condition number, the nonnegative least-squares residual and the relative source-rate error.

```bash
python tutorials/optimization/run.py F2 --output runs/f2 > /dev/null
```

```python
import json

s = json.load(open("runs/f2/summary.json"))
print("passed:", s["passed"])
for arm in s["arms"]:
    print(arm["method"], "sensors", arm["sensors"], "covered weight", arm["coverage"])
c = s["coverage_optimal_subsets"]
print("coverage-optimal subsets:", c["count"], c["by_size"])
print("rank deficient:", c["rank_deficient"])
low, high = c["full_rank_condition_range"]
print(f"condition numbers of the full-rank ones: {low:.6g} to {high:.6g}")
for arm in s["arms"]:
    noisy = arm["inversion"][0]["noisy"]
    print(
        f"{arm['method']}: rank {noisy['rank']}, nullity {noisy['nullity']}, "
        f"rate error at wind 1.0 with noise {noisy['relative_rate_error']:.6g}"
    )
```
```text
passed: True
MIP sensors [4] covered weight 24.0
greedy sensors [1, 0, 2] covered weight 24.0
coverage-optimal subsets: 35 {'1': 2, '2': 13, '3': 20}
rank deficient: 15
condition numbers of the full-rank ones: 2.00322 to 259.403
MIP: rank 1, nullity 2, rate error at wind 1.0 with noise 0.627158
greedy: rank 3, nullity 0, rate error at wind 1.0 with noise 0.00699284
```

Both methods reach the coverage optimum of 24. In this deliberately permissive fixture two single receptors already detect all twelve scenarios, so every three-sensor subset is optimal too: the instance cannot separate MIP from greedy, and which optimal subset each returns is decided by solver and index order, not by the objective. The MIP's one sensor gives a rank-1 inverse that cannot recover three rates (a deficient inverse reports its nullity and a null `condition_number`); greedy's three sensors give rank 3. An optimal solver status says nothing about identifiability. Inspect `scenario-matrix.json`, `exhaustive.json`, `optimal-subsets.json` and the `inversion` rows of `summary.json` before reading anything into it. NNLS here is a separate inverse-problem check; it does not solve or replace the MIP.

To separate the methods, predeclare a stricter detection threshold (one at which no single receptor covers every scenario), scenario costs or more candidates, and repeat. If identifiability is the real objective, state it directly: Fisher-information or continuous-location criteria give a different, nonlinear design problem, not the same MIP.

## F3: a design must survive a finer grid

The optimizer searches a coarse grid; a separate fixed gate decides whether its design holds on a finer one. The problem is the laminar lid-driven cavity with the lid speed in [0.6, 1.4] m/s as the only design variable, training kinematic viscosities 0.01 and 0.015 m2/s, and 0.0125 m2/s withheld. The solves use supported box geometry, `implicit_projection`, `limited_upwind` momentum advection with the van Leer limiter and multigrid pressure; there are no masks and no new physics.

The objective targets a mean squared fluid speed of 0.04 m2/s2: `((mean_square_speed - 0.04) / 0.04)^2 + 0.02 * lid_speed^2`, worst case over the two training viscosities. `mean_square_speed` is the trapezoid volume mean of the squared face-normal velocities of the staggered grid. The target is a teaching criterion, not a measured requirement.

Frozen before any search: at most 5,000 steps and 30 s of wall time per native solve, the case's residual tolerance 1e-5 and monitor tolerance 0.001, and at most a 10 % relative change of the mean squared speed between grids. The 30 s limit makes acceptance depend on host load. A solve counts only if the native summary reports `steady_discrete_solution` and the independent field checks pass; rejected or timed-out solves stay in the evidence with an unusable objective.

The smoke preset trains on 8 x 2 x 8 cells and replays on 16 x 2 x 16 with twelve BiteOpt calls; the study uses 16 x 2 x 16 and 32 x 2 x 32 with 64 calls. Both compare a fixed lid speed of 1.0, five evenly spaced samples and the BiteOpt incumbent, then replay every nominee on the fine grid at both training viscosities and at the withheld one (a convergence check only: it must be accepted, its objective is not gated).

```bash
python tutorials/optimization/run.py F3 --output runs/f3 > /dev/null
```

```python
import json

s = json.load(open("runs/f3/summary.json"))
print("passed:", s["passed"])
print("solves:", s["work"]["full_field_solves"], "accepted:", s["work"]["accepted"])
for arm in s["arms"]:
    print(
        f"{arm['method']}: lid speed {arm['training']['speed']:.6g} m/s, "
        f"grid change {arm['relative_energy_grid_change']:.6g}, "
        f"supported {arm['supported_at_requested_fidelity']}"
    )
print(
    "distinct designs:",
    s["distinct_designs"],
    "supported designs:",
    s["supported_designs"],
)
```
```text
passed: True
solves: 45 accepted: 45
fixed: lid speed 1 m/s, grid change 0.321019, supported False
sampling: lid speed 1 m/s, grid change 0.321019, supported False
BiteOpt: lid speed 1 m/s, grid change 0.321019, supported False
distinct designs: 1 supported designs: 0
```

Every native solve was accepted, and the lesson passed, yet no design is supported: the mean squared speed changes by about 32 % between the grids, against the 10 % gate. `passed: True` must not be read as `supported_designs > 0`. All three arms return the same lid speed here, so they are one design, and their order in `coarse_ranking` and `fine_ranking` is a tie, not a reversal. The study preset is a separate command:

```sh
python tutorials/optimization/run.py F3 --preset study --threads 2 --output runs/f3-study
```

Two-grid agreement is a screening criterion, not a grid-convergence proof. A supported design would still need a systematic refinement study and a physical validation case. The source-allocation worker of chapter 14 never runs this pressure and momentum problem; F3 uses a fallible Python callback, which can be wrapped in a command job. To go further, run the study preset, add a third grid level and report cost to accepted quality.

## Unit checks of the lessons

Eight unit and negative checks cover the steady gate (it refuses partial and transient work), a small minimax LP, a rank-deficient coverage optimum, the list of coverage ties, the mean squared speed measure and the record writer (it refuses incomplete runs). They run in about a second and must pass with and without `-O`:

```bash
python -m unittest discover -s tutorials/optimization -p 'test_*.py'
python -O -m unittest discover -s tutorials/optimization -p 'test_*.py'
```

## Recorded results

The [lesson record](../evidence/optimization-lessons.md) (the record gives no date) holds one complete smoke and one complete study run of all three lessons. In it the F1 LP and the vertex enumeration agree on the normalized optimum 1.6662105873, and the fresh replays match `A q` to within 1.8e-15 for all three arms; F2 matches the run above; F3 supports zero designs in both presets, with grid changes of 32 % in smoke and 10.4 % to 12.1 % in the study. Every F3 solve in that record was accepted numerically; none of it is experimental validation.

## Next

- [Chapter 14](14-optimization-jobs.md): run the solver as a job of `optimization-run`, which lesson F1 needs.
- [Chapter 12](12-studies.md): response matrices and source inference without an optimizer.
