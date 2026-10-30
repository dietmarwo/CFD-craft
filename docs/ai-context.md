# Agent entry point

CFD-craft is a numerical research tool. Use the actual CLI schemas and model cards rather than inventing case fields from an older proposal.

For established-solver execution, start with [OPENFOAM.md](../integrations/OPENFOAM.md)
and the [external model card](model-cards/openfoam-backend.md). The generated
Foundation-13 cavity and backstep cases have their own external result schema.
Do not feed those archives to the native `cfd-craft report` command. Numerical
code agreement, comparison with measurements and physical qualification remain
distinct. The native canyon validation gate is unchanged.

For the backstep resolution workflow, read the
[prompt](../tutorials/backstep-resolution-prompt.md) and the
[resolution results](../validation/RESOLUTION_RESULTS.md). Legacy remains the
default recipe; the wall-resolved reference is `wall-resolved`/`simplec`, accepted
at level 1 only. Its measurement screen additionally requires the independent
local-flux and all-wall y+ audit. Never turn a saved pre-failure snapshot into
a final result.

For long steady solves use [verified continuation](../integrations/STEADY_RESTART.md)
and its [results](../validation/RESTART_RESULTS.md). `prepare-restart` accepts a
completed run with finite final fields whose stored face flux passes the
independent local gate; unconverged completed stages are eligible,
failed/timeout/cancelled ones are not. It preserves physics and mesh, resets local pseudo-time and records source
fields, runtime and mesh. `--max-stages` defaults to 1. These are steady field
initializations, not transient-history restarts or cross-mesh mappings.

For one-level refinement use [mesh initialization](../integrations/MESH_INITIALIZATION.md)
and [iteration 05](iterations/05-mesh-initialization-plan.md). It is a different
operation: accepted, independently audited cold-generated source only; preserve
target BCs, map internal volume fields, never copy coarse phi. Fine-grid work
starts at zero and needs the unchanged final gates. Same-mesh source-flux
eligibility is unchanged. A mapped run can later supply an ordinary continuation.

1. Build with cargo build --release --locked. Inspect cfd-craft describe.
2. Choose a canonical case. Run check before allocating a larger simulation. Each diagnostic names its element and field (for example `geometry[1]` or `sources[0].rate_kg_s_m`); [diagnostics](diagnostics.md) lists the codes. Invalid input exits 1 from check, run and preview, with the report on stdout. A check on a host too small for the case warns with CFD-W070 and skips the grid checks; run the case on a larger host, or preview it here.
3. Set an available thread/memory allowance, an iteration limit and a wall-time limit. Use a new output directory.
4. Read summary.json and its checks. Inspect the termination, assessment, scope, numerical interventions and experimental-validation label.
5. Verify the manifest with report. If full fields were retained, use validation/check_fields.py for independent mass/continuity checks.
6. Compare settings only under the same source, geometry, sampling and numerical-fidelity definitions. Keep failed rows and actual work counts.

Successful assessments are steady_discrete_solution or transient_interval_completed. They describe the discrete calculation. An iteration/time limit is incomplete even when some diagnostics pass. Model validation is a separate dataset-specific report.

Local coordinates are east/north/up, in meters. Meteorological wind is direction **from**, clockwise from north. A wind from 270 degrees travels in positive x. Stored pressure is kinematic pressure; RANS isotropic turbulent pressure is absorbed into it.

Give a trace gas its molecular diffusivity (of order 1e-5 m2/s). In RANS cases the turbulent diffusivity nu_t/Sc_t then does the mixing; a large constant would hide the effect of the turbulent Schmidt number.

Sources declare mass per second, per line length, or per source volume. The code integrates represented support and rejects masked-solid intersections. Point receptors interpolate from cell centers and reject stencils through a wall; near the external boundary they use the nearest available cell center. Volume receptors integrate exact Cartesian overlap.

summary.json stores receptor values by ID, in sorted order (R10 before R2). Look them up by ID; do not rely on their position.

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
