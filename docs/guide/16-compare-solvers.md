# Compare solvers and measurements

<!-- check: openfoam -->

This chapter makes three comparisons with the OpenFOAM backend: the native solver and OpenFOAM on the same cavity against a numerical reference, OpenFOAM on the backward-facing step against public measurements under a frozen protocol, and the cost of both backends on one host. You need the runtime of [chapter 15](15-openfoam-first-run.md), a checkout with the release build and the validation requirements.

The three comparisons answer different questions. The cavity is a numerical cross-check. The backstep is a first screen against measurements, which a calculation may enter only after it passes the numerical gate. The timing compares configured workflows, not equal work.

## Setup

Run all commands from the root of a checkout, with the runtime installed as in [chapter 15](15-openfoam-first-run.md) at `runs/openfoam13/runtime/opt/openfoam13`:

```bash
mkdir -p runs
```

## Two solvers against a numerical reference

```bash
python tutorials/external_cfd.py --preset cavity \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --output runs/two-cavities
```

The cavity preset runs the Re = 100 lid-driven cavity with the native solver (`--binary`, default the checkout's release build) and with OpenFOAM, samples both along the centerlines with shared helpers, and compares each with the Ghia, Ghia and Shin (1982) stations and with the other solver. The native case uses x and z, OpenFOAM x and y; the mapping between the vertical axes is explicit. Ghia et al. is a numerical benchmark, not an experiment, so this is a numerical cross-check. Its report is `runs/two-cavities/cavity-comparison.json`.

In the [external-backend record](../evidence/external-backend.md) (committed state of 8 November 2026, a GitHub-hosted run of the study preset), the maximum centerline velocity error over the lid speed was 0.0275488 for native against Ghia, 0.00896632 for OpenFOAM against Ghia and 0.0311705 between the two solvers, each against a target of 0.06. Both runs completed and were numerically accepted; the native case ran transient to 30 s, OpenFOAM converged in 696 steady iterations.

## One solver against measurements

<!-- check: long -->

The backstep uses the raw Driver and Seegmiller measurements published by the [Turbulence Modeling Resource](https://tmbwg.github.io/turbmodels/backstep_val.html). Fetch them once; the script checks frozen SHA-256 identities and never substitutes synthetic data:

```bash
python validation/backstep_data.py --output runs/backstep-measurements
python tutorials/external_cfd.py --preset smoke \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 \
  --data runs/backstep-measurements --timeout-s 300 \
  --output runs/external-smoke || echo "exit $?"
```

Without `--data`, the smoke and study presets download the same pinned files into their output. The smoke preset runs the cavity and the level-1 backstep (legacy recipe, 6,000 iterations) with a 300 s budget per case. It exits 0 when everything passes, 2 when it recorded failed, unaccepted or cancelled evidence, and 1 on a workflow error.

The same backstep with the single commands, so that each verdict can be read on its own:

```bash
python integrations/openfoam_backend.py prepare --case backstep --level 1 \
  --iterations 6000 --data runs/backstep-measurements --output runs/backstep-input
python integrations/openfoam_backend.py run --case runs/backstep-input \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --timeout-s 300 \
  --memory-mib 2048 --output-mib 512 --output runs/backstep-run || echo "exit $?"
python integrations/openfoam_backend.py report runs/backstep-run || echo "exit $?"
python validation/compare_backstep.py --run runs/backstep-run \
  --data runs/backstep-measurements --output runs/backstep-comparison || echo "exit $?"
```

The profile at x/H = -4 defines the inlet. The stations x/H = 1, 4, 6 and 10 (112 velocity samples) and 17 lower-wall skin-friction values are evaluation data; no case parameter is fitted to them. Pressure coefficients are fetched for provenance and are not scored. The comparison is assessed only when the run passed its numerical gate; otherwise it reports the screen as `not_assessed` and its metrics describe the final iterate only.

In the [external-backend record](../evidence/external-backend.md) (committed state of 8 November 2026) the level-1 legacy backstep (22,656 cells) ran all 6,000 iterations and did **not** pass the numerical gate: its final pressure residual was 1.19e-3 against 1e-7, and the solve was stalled, so the measurement screen was not assessed. A plausible velocity plot does not change that. The wall-resolved recipe of [chapter 18](18-backstep-resolution.md) is the one that passes.

## The frozen protocol

The screen's stations, pairing rules and targets are in `validation/protocols/backstep-v1.json`, and the evaluator checks its hash, so a local edit cannot relax a threshold. A justified change needs a new reviewed protocol version with its own identity and reason, and a fresh evaluation; keep the previous report. Measurement error, mesh sensitivity and uncertain inlet or model assumptions are separate quantities.

## Mesh levels and the study preset

```sh
python tutorials/external_cfd.py --preset study --timeout-s 300 \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --output runs/external-study
```

The study preset runs backstep levels 1, 2 and 3 (22,656, 90,624 and 203,904 cells) under the same per-case budget and keeps timeouts and incomplete rows. Levels 2 and 3 need far more than 300 s of serial time for their 6,000 iterations; in the [external-backend record](../evidence/external-backend.md) they timed out. An incomplete mesh series gives no GCI and no mesh-independent physical claim.

## Time both backends on one host

<!-- check: long -->

```bash
python validation/compare_backends.py \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 \
  --repeats 1 --timeout-s 180 --output runs/backend-timing
```

`--binary` defaults to the checkout's release build. The script runs the cavity three ways (OpenFOAM steady, native steady and native transient to 30 s), one solver thread each. After warmups, each repeat runs all six orders of the three methods. It requires accepted runs, identical repeated work, profiles and producer identities, and stable input hashes; any failed run fails it. The CI selection `external=comparison` runs it with `--repeats 2`.

Workflow time and solver time are different measurements. OpenFOAM's workflow includes meshing, sampling, runtime hashing and process polling; its solver time is the `foamRun` child. The native solver time is its own `elapsed_s`, not the Python helper's total time.

## Cost at a declared accuracy

The grid sweep asks a different question: how much does each backend cost to reach a stated centerline accuracy?

```sh
python validation/compare_backends.py --grid-sweep \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 \
  --levels 1 2 --sweep-rounds 3 --accuracy-target 0.01 \
  --native-wall-s 180 --timeout-s 180 --native-max-steps 20000 \
  --foam-iterations 3000 --output runs/accuracy-sweep
```

Levels 1 and 2 are 24 x 24 and 48 x 48 cells in the flow plane; `--grids 16 24 32 48` gives an explicit list instead. The sweep alternates the backends within each grid, keeps one warmup per configuration and adds a native 12 x 12 diagnostic. Native uses two periodic span cells (`--native-span 1` for one); OpenFOAM one empty span cell. Opt-in native numerics are given as JSON with `--native-numerics` and the pressure preconditioner with `--native-pressure-preconditioner`.

Every row keeps numerical acceptance, the independent checks, the frozen 0.06 Ghia screen and the measured error apart. The best cost at the target uses only configurations whose timed repeats are all accepted and repeat their work, producer and samples. If a backend misses the target on every grid, its best cost and the ratio are `null`; no crossing is extrapolated. The sweep exits 0 when all rows pass the existing checks, 2 when it holds unaccepted evidence, and 1 for an invalid workflow, changed input or inconsistent repeat; missing the 0.01 development target alone is a recorded outcome. The CI selection `external=accuracy` runs this sweep with a 600 s native budget. The [profiling page](../developer/profiling.md#measure-cost-at-a-declared-accuracy) describes the timers and memory observations.

## What the committed measurements say

All of them come from one laminar two-dimensional case, the Re = 100 cavity. With the default native numerics, the [backend comparison](../evidence/backend-comparison.md) (committed state of 8 November 2026) found OpenFOAM's workflow 4.7 to 5.5 times faster than native steady mode on two hosts, its solver process about 9 times faster, and OpenFOAM closer to Ghia. With the opt-in `limited_upwind`, `implicit_projection` and multigrid settings, the [matched-accuracy record](../evidence/matched-accuracy.md) of 1 November 2026 found native at 24 x 24 cells with solver time 0.549 s and Ghia error 0.00543 against 0.743 s and 0.00897 for OpenFOAM, all 32 rows accepted. The [comparison page](../comparison.md) puts these in context; none of it says anything about urban flows.

## A task for an agent

> Use CFD-craft's external backend and the [OpenFOAM backend model card](../model-cards/openfoam-backend.md).
>
> 1. Check out a named revision and build the native CLI with `--locked`. Install the pinned Foundation 13 package with the provided installer on Ubuntu 24.04.
> 2. Run `tutorials/external_cfd.py --preset cavity` first. Check each solver against Ghia and against the other solver, including the different vertical coordinates.
> 3. Run the smoke backstep experiment with the frozen protocol and the raw-data hashes. Use a fresh output directory and a declared per-case wall budget.
> 4. Inspect every execution and numerical status before discussing measurement errors. Preserve failed rows. Do not increase tolerances to obtain a pass.
> 5. Use the study preset for mesh sensitivity only when the smoke calculation and the resources justify it. Incomplete meshes cannot support grid convergence.
> 6. Report what is measured, which data define the inlet, which are held out, the turbulence assumptions, and what remains unqualified. A velocity comparison does not validate concentrations or the native canyon solver.
>
> Deliver the report, paired samples, runtime and input identities, and figures. Do not contact data owners or publish results.

## Next

- [Chapter 17](17-continuation-and-mapping.md): continue a solve on the same mesh, or start a finer mesh from an accepted one.
- [Chapter 18](18-backstep-resolution.md): the wall-resolved backstep that passes the numerical gate.
