# Validation record

F1–F3 use the existing numerical solvers, the native LP/MIP API, native
BiteOpt and the CFD GP worker; no transport, pressure or physical model is
changed by them. [results/verified.json](https://github.com/dietmarwo/CFD-craft/blob/main/tutorials/optimization/results/verified.json) holds the
numbers below for one complete smoke and one complete study run of the
committed lessons. [record.py](https://github.com/dietmarwo/CFD-craft/blob/main/tutorials/optimization/record.py) writes it from the runs' summaries
and refuses incomplete or failed runs:

```bash
python tutorials/optimization/record.py --smoke SMOKE_DIR --study STUDY_DIR \
  --output tutorials/optimization/results/verified.json
```

| Check | Result (smoke and study) |
|---|---|
| F1 native LP versus independent vertex enumeration | Agree; normalized optimum 1.6662105873 |
| F1 fresh full-field superposition replay | Largest normalized receptor difference 1.1e-15 to 1.8e-15 for all three arms |
| F1 BiteOpt and native GP (seed 601 each) | Completed with fresh and changed-wind replays; not a solver-superiority claim |
| F2 native MIP versus all 20 three-sensor subsets | Both MIP and greedy cover weight 24, the optimum |
| F2 coverage-optimal subsets | 35 subsets of at most three sensors reach 24 (2 single sensors, 13 pairs, all 20 triples); 15 are rank deficient, the full-rank ones have condition numbers 2.0 to 259 |
| F2 held-out inversion | MIP: one sensor, rank 1; greedy: three sensors, rank 3, condition 2.0 |
| F3 numerical and workflow checks | Every native solve accepted (45 smoke, 149 study) and independently checked |
| F3 fidelity gate (10% change in mean squared speed) | Zero supported designs; smoke 32% (all three arms at lid speed 1.0), study 12.1% (fixed), 10.4% (sampling), 10.6% (BiteOpt) |
| Eight Python unit and negative checks | Pass normally and under `python -O` |

F2 cannot separate the MIP from greedy: two single receptors already detect
all twelve scenarios, so every three-sensor subset is coverage-optimal, and the
rank contrast between the two answers comes from the solver's and greedy's tie
order, not from the objective. That is the lesson's point: coverage optimality
says nothing about identifiability. A rank-deficient inverse reports its nullity
and a null full-inverse condition number, separately from the condition number
of its observed subspace.

F3 measures mean squared speed as the trapezoid volume mean of the staggered
face velocities. Its study designs miss the 10% screen by 0.4 to 2.1 points;
the gate is not relaxed. The withheld viscosity is a convergence check only.
In smoke, sampling and BiteOpt return the fixed lid speed, so the three arms
are one design.

F1 uses serial prescribed transport; only F3 exercises coupled pressure and
momentum. F1's GP work counters are separate from its full-field solve counts.
Timings depend on host load and establish no performance ranking. F2 keeps the
same small exact scenario design in both presets.

The F3 negative result is part of the lesson. Accepted discrete solutions,
two-grid agreement and physical validation are distinct. These fixtures do
not qualify canyon/RANS predictions, masked multigrid, a coupled-flow worker or
real-world sensor placement. A refinement study must retain the current
failures and predeclare its next resolution and criteria.
