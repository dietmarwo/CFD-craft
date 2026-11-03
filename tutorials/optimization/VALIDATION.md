# Validation and implementation record

Implemented F1–F3 using existing numerical solvers, the native LP/MIP API, native
BiteOpt and the advertised CFD GP worker. No transport, pressure or physical
model was changed. [results/verified.json](results/verified.json) records versions,
source identities and chapter gates; the combined bundle retains raw command
artifacts, larger-preset summaries, figures and validation logs.

| Check | Result |
|---|---|
| F1 native LP versus independent vertex enumeration | Passed; normalized optimum about 1.6662105873 |
| F1 fresh full-field superposition replay | Passed; maximum normalized receptor difference below 2e-15 in recorded runs |
| F1 BiteOpt and native GP, smoke and study | Completed with fresh/changed-wind validation; not a solver-superiority claim |
| F2 native MIP versus all 20 three-sensor subsets | Passed; both MIP and greedy covered weight 24 |
| F2 identifiability control | MIP chose one sensor, rank 1; greedy chose three, rank 3 |
| F3 smoke and study numerical/workflow checks | Passed; every native solve was retained and independently checked |
| F3 separate fidelity gate | Zero supported designs in both presets; smoke grid changes about 35%, study about 12–14%, above the frozen 10% limit |
| Four independent/negative Python unit checks | Passed normally and under `python -O` |
| Core fmt, clippy with warnings denied, release workspace tests | Passed with locked dependencies |
| Command-job execution and optimized-Python smoke route | Passed for all three chapters |

A rank-deficient inverse now reports nullity and a null full-inverse condition
number separately from its observed-subspace condition. This prevents a
one-row matrix's finite singular-value ratio from appearing to certify a
three-source inverse. The final F2 check was repeated under optimized Python.

F1 uses serial prescribed transport; only F3 exercises coupled pressure/momentum.
F1's GP work counters are separate from full-field replay counts. All study
presets were executed, but timings overlapped repository checks and establish
no performance ranking. The figures report numerical quantities instead.
F2 deliberately keeps the same small exact scenario design in both presets.

The F3 negative result is part of the lesson. Accepted discrete solutions,
two-grid agreement and physical validation are distinct. These fixtures do
not qualify canyon/RANS predictions, masked multigrid, a new coupled-flow worker
or real-world sensor placement. A future refinement study must retain the
current failures and predeclare its next resolution and criteria.
