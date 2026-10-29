# Agent entry point

CFD-craft is a numerical research tool. Use the actual CLI schemas and model cards rather than inventing case fields from an older proposal.

1. Build with cargo build --release --locked. Inspect cfd-craft describe.
2. Choose a canonical case. Run check before allocating a larger simulation.
3. Set an available thread/memory allowance, an iteration limit and a wall-time limit. Use a new output directory.
4. Read summary.json and its checks. Inspect the termination, assessment, scope, numerical interventions and experimental-validation label.
5. Verify the manifest with report. If full fields were retained, use validation/check_fields.py for independent mass/continuity checks.
6. Compare settings only under the same source, geometry, sampling and numerical-fidelity definitions. Keep failed rows and actual work counts.

Successful assessments are steady_discrete_solution or transient_interval_completed. They describe the discrete calculation. An iteration/time limit is incomplete even when some diagnostics pass. Model validation is a separate dataset-specific report.

Local coordinates are east/north/up, in meters. Meteorological wind is direction **from**, clockwise from north. A wind from 270 degrees travels in positive x. Stored pressure is kinematic pressure; RANS isotropic turbulent pressure is absorbed into it.

Sources declare mass per second, per line length, or per source volume. The code integrates represented support and rejects masked-solid intersections. Point receptors interpolate from cell centers and reject stencils through a wall; near the external boundary they use the nearest available cell center. Volume receptors integrate exact Cartesian overlap.

Use linear_upwind for an exact source-response matrix. The MUSCL limiter makes the discrete transport map nonlinear. Keep model mismatch experiments separate from exact same-model recovery. An inverse optimizer's solutions or archive are not a calibrated posterior.

The steady transport operator needs a removal path for sourced regions. Fully periodic or closed domains with persistent positive sources have no steady concentration solution in this release.

The optional native optimization worker supports prescribed-flow, three-source scalar allocation. Its positive box parameterization preserves total emissions and supplies a dimensionless concentration objective. MODE/QD, noisy GP, PM and vegetation are outside this adapter.

Until data access and the frozen experimental protocol exist, use the canyon examples as illustrative research cases. Their dimensions are not an exact reproduction of the CODASC wind tunnel. Do not infer experimental compliance from a zero process exit or a visually plausible concentration field.

Canonical workflows:

~~~sh
python tutorials/source_inference.py --preset smoke --output runs/new-inference
python tutorials/canyon_study.py --preset smoke --output runs/new-canyons
python tutorials/canyon_study.py --preset sensitivity --output runs/new-sensitivity
~~~

The study preset is deliberately more expensive; it may hit its per-case budgets. Record this outcome. Change numerical methods or available resources with evidence before increasing scope.
