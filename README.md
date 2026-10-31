# CFD-craft

CFD experiment and validation workbench, with a Rust CPU research solver for incompressible flow and conservative passive-gas dispersion and a bounded OpenFOAM Foundation 13 backend. Cases are data; runs report numerical checks, stopping reason, model scope and reproducible input/build identity.

Version 0.1.0 is a **research prototype**. The coarse finite-canyon examples converge under independent continuity and mass checks. Experimental canyon validation is blocked by access to raw benchmark data, and the first finer-grid study exceeded its compute budgets. These are recorded release gates, rather than a claim of general urban-model validation. See [results](validation/RESULTS.md) and [model cards](docs/model-cards/README.md).

## Start

Rust 1.88 or newer is required. The normal workspace has two crates and no native scientific-library dependency.

~~~sh
cargo build --release --locked
target/release/cfd-craft describe
target/release/cfd-craft check cases/verification/periodic-tracer.json
mkdir -p runs
target/release/cfd-craft run cases/verification/periodic-tracer.json --output runs/tracer
target/release/cfd-craft report runs/tracer
~~~

The output directory must be new, and its parent must exist; both are checked before the solve starts. Exit 0 means the request succeeded (a valid case, a passed numerical assessment or a verified archive); exit 2 means a completed execution with incomplete/failed numerical evidence; exit 1 means invalid input or an execution/I/O error. For invalid input, check, run and preview print the check report on stdout: every diagnostic carries a code and the path of the offending field ([diagnostics](docs/diagnostics.md)). `preview CASE --output NEW_DIR [--factor N]` runs the case on a grid coarsened by N (default 2) and refuses a coarsening that changes the solid volume by more than 20 % or the fluid topology. A timeout or cancelled solve retains a report.

Python is optional for the solver. Install the analysis dependencies to reproduce tutorials, independent checks and figures:

~~~sh
python -m pip install -r requirements-validation.txt
python validation/check_fields.py runs/tracer
python tutorials/source_inference.py --output runs/inference
python tutorials/canyon_study.py --preset smoke --output runs/canyons
python validation/export_vtk.py --run runs/tracer --output runs/tracer.vtr
~~~

Open the VTR file in ParaView. Filter by the fluid mask before analyzing solid cells. The default field archive also contains native face velocities, allowing continuity to be recomputed without relying on reconstructed cell velocities.

## What is implemented

- Uniform Cartesian finite volumes; staggered face velocities; deterministic box masks and fluid-component discovery.
- Matrix-free pressure projection, one gauge per unanchored fluid component, cached IC(0) preconditioning and an independent residual check.
- Laminar flow, moving tangential walls, donor-cell momentum advection and SSPRK2 stepping.
- One neutral equilibrium k–epsilon package with rough-wall stress, k-based wall dissipation and a matching upper-boundary treatment.
- Passive gas with linear upwind or bounded MUSCL/MC transport, diffusion, point/line/volume sources, and point or volume-average receptors.
- Explicit work/time/memory/output budgets, cooperative cancellation, checksummed restart and immutable output-directory behavior.
- Strict case/result schemas through describe; JSON/CSV evidence; VTK conversion.
- Synthetic source inversion, finite-canyon wind/Schmidt/domain studies, and a scalar fcmaes application worker.

The RANS coefficients, wall treatment and supported assumptions are documented in [the flow card](docs/model-cards/flow.md). The [roadmap](docs/roadmap.md) maps the development plan's milestones, numeric targets and tutorials to this release and lists the next steps. Particle deposition, vegetation, LES, city import, annual statistics, stretched grids, multigrid and GPU execution are later work.

The [native CPU performance results](docs/iterations/07-14-performance-results.md)
give paired pressure, stencil, step and CLI timings at fixed work, with the
fields compared against the previous implementation and the memory cost. The
paired runner is `validation/benchmark_native.py`; the frozen cases are in
`cases/performance/`.

## Verification

~~~sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --release --workspace --locked
ruff format --check . && ruff check .
python validation/test_cli.py -v
python -O validation/test_cli.py -v
python validation/test_openfoam.py -v
python -O validation/test_openfoam.py -v
python validation/test_resolution.py -v
python -O validation/test_resolution.py -v
python validation/test_restart.py -v
python -O validation/test_restart.py -v
python validation/test_mapping.py -v
python -O validation/test_mapping.py -v
python validation/test_refinement.py -v
python -O validation/test_refinement.py -v
python validation/run_suite.py --preset smoke --output runs/verification
python validation/flow_accuracy.py --output runs/flow-accuracy
python validation/cavity.py --output runs/cavity
python validation/scipy_reference.py --output runs/scipy-reference
~~~

The independent Python checker tests archived mass, emission-rate/time accounting, positivity, current face-flux continuity and open-boundary scalar rates. It also recomputes every receptor value from the concentration field, the geometry mask from the case boxes, and the finiteness and signs of the stored fields. It does not independently reconstruct the full time history or establish turbulence-model validity.

The study preset adds a larger transport grid series or a canyon resolution series. Study reports include failed rows. A failed refinement run does not become an accepted grid-convergence result.

## Established-solver and experimental comparisons

The [external backend](integrations/OPENFOAM.md) runs generated Foundation-13
cases with resource limits and input/runtime hashes. Its cavity tutorial
compares both solvers with the Ghia numerical reference. A separate backstep
tutorial compares actual predictions with public Driver--Seegmiller measurements
under a frozen protocol. Execution, numerical convergence, measurement screening
and physical qualification are separate results. See the
[model card](docs/model-cards/openfoam-backend.md),
[iteration plan](docs/iterations/02-external-validation-plan.md) and
[recorded results](validation/EXTERNAL_RESULTS.md). These comparisons do not
qualify the native street-canyon model.

The [backstep resolution tutorial](tutorials/backstep-resolution-prompt.md)
runs wall-resolved recipes with independent Cartesian mesh, local face-flux and
wall-y+ audits; refinement stops after a coarse case that is not accepted. On
its coarse mesh the reference recipe converges, passes the audit and is screened
against the measurements; no mesh pair or physical qualification is claimed.
See the [plan](docs/iterations/03-wall-resolution-plan.md) and the
[resolution results](validation/RESOLUTION_RESULTS.md).

The [continuation workflow](integrations/STEADY_RESTART.md) starts a fresh
bounded stage from the verified final fields and face flux of a completed
same-mesh run. Initial-state provenance, runtime and rebuilt mesh are checked;
staged work counts and final convergence remain distinct, and the numerical
gates are unchanged. See the [plan](docs/iterations/04-steady-continuation-plan.md)
and the [continuation results](validation/RESTART_RESULTS.md).

The separate [coarse-to-fine initializer](integrations/MESH_INITIALIZATION.md)
uses Foundation-13 mapNearest volume fields from an accepted cold-generated
source, preserves generated fine-grid boundaries and lets the solver construct
new face flux. Its receipt, an independent replay of the mapping and the rebuilt
mesh and runtime are checked. A mapped and a cold level-2 cavity converge to the
same fields ([mapping results](validation/MAPPING_RESULTS.md)); an accepted fine
turbulent backstep and physical qualification remain open.

The [bounded refinement campaign](integrations/REFINEMENT_CAMPAIGN.md) retains
an accepted cold coarse source, maps once and chains eligible fine stages under
declared limits. Every stage keeps its own numerical, independent and reference
verdicts; parent/archive checks run again at collection. A two-grid observable
comparison requires accepted fields on both meshes and does not establish a
GCI. The declared level-2 backstep campaign (three stages of 4000 iterations)
ended at its stage limit without an accepted fine grid: every stage passed the
audit, but the Uy and k residuals stayed above the gate. See the
[plan](docs/iterations/06-refinement-campaign-plan.md),
[tutorial](tutorials/refinement-campaign-prompt.md) and
[results](validation/REFINEMENT_RESULTS.md).

## Ecosystem

[optimization-jobs](https://github.com/dietmarwo/optimization-jobs) runs the CLI through a trusted command; CFD evidence stays in a separate CFD result artifact. The optional [fcmaes adapter](integrations/README.md) uses fallible, cancellable scalar simulations with hashed case inputs and existing evaluate/retry/surrogate profiles. [experiment-craft](https://github.com/dietmarwo/experiment-craft) can schedule those same command or optimizer envelopes.

Agents should start with [ai-context](docs/ai-context.md). The [tutorial guide](tutorials/README.md) supplies concrete tasks, budgets and interpretation rules. No release tag or package publication is implied by this source version.
