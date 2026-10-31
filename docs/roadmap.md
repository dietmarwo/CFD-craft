# Roadmap

This page maps the development plan (version 2, which replaces the initial plan) to what 0.1.0 contains, and lists the next steps. The plan's proposed case file is a draft; the schemas from `cfd-craft describe` are authoritative. [RESULTS](../validation/RESULTS.md) holds the numbers.

An [external-backend workstream](iterations/02-external-validation-plan.md) runs
OpenFOAM Foundation 13 next to the native solver: a same-Re cavity cross-check
and a preliminary comparison against public backstep measurements.
[EXTERNAL_RESULTS](../validation/EXTERNAL_RESULTS.md) records the runs and the
remaining gates. This gives the optimization ecosystem a path to an established
solver while native numerical development continues. It does not close M3b: an
external backstep is not a measured native street-canyon comparison. The native
wall and throughput tasks below remain.

## Milestones

| Milestone | Exit gate in the plan | State in 0.1.0 |
|---|---|---|
| M0 Contracts and evidence skeleton | Case/result schemas, diagnostics, resource estimator, data inventory, proposed protocols | Done. Diagnostics carry codes and field paths ([catalog](diagnostics.md)). The memory and output estimates bound the measured peak and the written artifacts. `validation/data-inventory.json` lists each dataset's access status. The CODASC protocol is `blocked_data` |
| M1a Grid and elliptic operators | Uniform staggered grid, mask topology, pressure reference, projection identities, manufactured Poisson | Done. The matrix-free operator matches an independently assembled reference on a masked grid with an outlet, a sealed pocket and a periodic axis (products to 1e-12, solutions to 1e-10). One gauge per closed component; projection and adjoint identities; second-order Poisson convergence |
| M1b Verified laminar flow | Documented time scheme, channel/cavity/manufactured flow, bounded execution, CPU profile | Mostly. Periodic shear has spatial and temporal order 2.00 and 2.01, with Poiseuille, Couette and the Re=100 cavity ([decisions](decisions/numerics.md)). Diffusion is explicit, not the plan's semi-implicit candidate, and limits the time step. Measured CPU time and memory are in RESULTS |
| M2 Passive transport and response matrices | Sources/receptors, analytic transport, superposition, synthetic inverse tutorial, small command job | Done, without area sources. Point, line and volume sources; the Gaussian order is 2.32; superposition holds to 2.2e-16; there is a SciPy reference, the source-inference tutorial and the command launcher. The discrete adjoint is a later extension |
| M3a Neutral ABL package | k-ε with consistent wall, inlet and top; empty-domain profiles pass | Partly. The empty ABL drifts 0.23 % (U), 0.94 % (k) and 2.68 % (ε) in H..5H, under gates of 2 % and 5 %. Below H, ε drifts up to 16 %. There is one top configuration, the open atmosphere. The building-wall roughness is tied to the cell width, which the plan rules out (§5.3) |
| M3b Finite canyon evaluation | Grid and domain studies, development and held-out cases, external comparison, experimental verdict | Not passed. The development case (W/H = 1, 270°) and the held-out analogs (W/H = 2; 225°) are steady on 18x16x12. The resolution series does not finish, there is no external comparison, and the experimental verdict is `blocked_data` |
| M4 Application integration | Scalar adapter, budgets and cancellation, campaign reporting, replay | Partly, ahead of order. An fcmaes worker runs evaluate, BiteOpt retry and the GP surrogate, within the evaluation's thread allowance and with cancellation. There is also the command launcher. There is no experiment-craft campaign or fine-grid replay yet |
| M5a Particle settling | Bin schema, settling and capture tests, mass budgets | Not started. Depends only on M2, so it can proceed in parallel |
| M5b Vegetation and deposition | Drag and deposition checks, factorial scenarios | Not started; needs M3b |
| M6 Mitigation optimization | Budget-matched baseline, held-out scenarios, fine-grid replay | Not started; needs M4 and validated physics |
| M7 Neighborhood and climatology | City geometry, conditional scenario maps, separate annual gate | Not started |
| M8 Time-resolved turbulence | LES with spin-up and averaging studies | Not started |
| M9 Acceleration | One targeted experiment on a measured bottleneck | First native CPU implementation experiment complete: [iterations 07–14](iterations/07-14-performance-results.md) measure pressure/storage/stencil improvements at fixed work with unchanged fields and gates. Multigrid and semi-implicit diffusion remain later algorithms |

The [native performance results](iterations/07-14-performance-results.md) update
CPU and memory observations after eight implementation increments. Use their
matched baseline/candidate tables for version comparisons; hardware differs
from the original resource measurements in RESULTS. Accepted fine-grid and
experimental-validation gates remain open.

## First-release definition

| Requirement | State |
|---|---|
| One documented neutral RANS, wall and inflow combination | Yes ([flow card](model-cards/flow.md)), with the below-H drift and the wall-roughness caveat |
| Conservative passive transport with explicit source units | Yes, for point, line and volume sources |
| A finite 3D canyon with end effects | Yes: 10 m buildings in a 16 m wide domain |
| A development case and held-out geometry and wind cases | Yes, on a coarse grid |
| Grid, domain and parameter sensitivity | Domain (extended outlet) and parameter (Sc_t 0.5 and 0.9) yes; grid no |
| Measured-data comparison with a frozen protocol | Blocked: no data |
| Prompt-driven tutorial with smoke and study presets | Yes ([tutorials](../tutorials/README.md)) |
| Runner integration that keeps CFD evidence | Yes (`integrations/`) |
| Measured CPU time, peak memory and output size on named hardware | Yes (RESULTS) |

0.1.0 is therefore a verified research prototype. The first release waits on the grid study and the measured data.

## Numeric targets of the plan

| Target | Plan | 0.1.0 |
|---|---|---|
| Assembled versus matrix-free pressure | ≤ 1e-10 | Products ≤ 1e-12 relative, solutions ≤ 1e-10 |
| Spatial order of the second-order modes | ≥ 1.8 | 2.00 (flow), 2.32 (MUSCL transport, gated at 1.8) |
| Temporal order | ≥ 1.8 | 2.01 |
| Closed periodic scalar budget | ≤ 1e-10 | Below 1e-12 on the periodic fixture; the acceptance bound of a run is 1e-9 |
| Positivity | No negative mass beyond round-off; report the minimum and the negative mass | `CFD-E053` stops the run; each constituent reports its minimum and negative mass |
| RANS continuity | 1e-5 net, 1e-4 local | The same gates |
| RANS equation residuals | 1e-5, recomputed | The same gate, recomputed from the fields |
| Steady scalar balance | 1e-6 | The same gate |
| Receptor stability | 0.1 % over three successive 100-iteration windows | 0.1 % over three 100-step windows in every committed steady case, relative to each monitor's window mean |
| Empty ABL | 2 % for U, 5 % for k and ε | Met in H..5H; below H reported, not gated |
| Superposition / transpose reciprocity | 1e-8 | 2.2e-16 / no adjoint yet |
| Study resolution | < 5 % change between the two finest grids | Not reached; the study does not finish |

## Tutorials of the plan

| Tutorial | State |
|---|---|
| 1. Wind direction and a canyon sensor | Partly: `canyon_study.py` with smoke, sensitivity and study presets and a prompt. Wind-convention regressions cover the cardinal and oblique directions and the inlet/outlet classification. There are no measured data, and the grid series does not finish |
| 2. What sensors tell about emissions | Done on prescribed flow: superposition, held-out receptors, an unidentifiable pair (rank 2), bounded noise, and model mismatch from changed inflow and grid. The LP, SQP and adjoint extensions are not started |
| 3. Trees, ventilation and particle removal | Not started (M5) |
| 4. Improving a design without exploiting the simulator | Partly: `integrations/run_jobs.py` compares evaluate, BiteOpt retry and the GP surrogate at 24 evaluations each, with no failed evaluations. Held-out and fine-grid replay are not started |
| 5. A neighborhood map and the limits of annual claims | Not started (M7) |

## Remaining differences from the plan

- **Building-wall roughness (§5.3):** it is the smaller of the ground roughness and 0.001 cell widths. The plan asks for a wall property specified independently of the ground.
- **Top boundary (§5.3):** only the open-atmosphere configuration exists; a wind-tunnel reproduction needs its own.
- **Diffusion (§5.2):** explicit rather than semi-implicit.
- **Sources (§5.4):** there are no area sources. A source that intersects a solid is rejected outright, so no redistribution policy is needed yet.
- **Preview (§6.2):** it publishes the derived case and its geometry, and it rejects vanished boxes, topology changes and solid-volume changes above 20 %. It does not list per-box changes against the original.
- **Geometry evidence (§5.1):** it has no facade/ground classification and no resolved street widths.
- **`verify` (§6.2):** it runs the pressure fixture of one case. The suites run through the validation scripts.
- **Flow cache (§4.4):** a converged flow is not yet reused for several passive releases.
- **Guideline document:** the COST 732 numbers behind W002 and W003 come from secondary summaries. The primary document was not retrieved.

## The gate that decides what comes next

Throughput is the limit; memory is not. One million cells peak at 851 MiB, against an estimate of 1064 MiB, which meets the plan's M1/M2 memory gate. A three-step run at that size, including the grid construction, takes two minutes.

The steady canyon cost grows roughly with the sixth power of the refinement ratio. Explicit diffusion and advection bound the pseudo-time step, and every step solves the pressure equation twice with about 50 CG iterations each. The 36x32x24 and 54x48x36 canyon grids do not converge within 300 seconds, so the resolution study, and with it any physical canyon claim, waits on a faster solver.

## Next steps, in order

The [mesh-initialization plan](iterations/05-mesh-initialization-plan.md)
provides an explicit accepted-coarse-to-new-fine start, verified against a cold
fine cavity ([results](../validation/MAPPING_RESULTS.md)). A bounded
[refinement campaign](../integrations/REFINEMENT_CAMPAIGN.md) maps once and
chains eligible fine stages, with complete retained parents and work and
archive checks; its [results](../validation/REFINEMENT_RESULTS.md) record
the declared level-2 backstep campaign: three 4000-iteration stages, each
passing the audit. It ended at the stage limit with the Uy and k residuals still
above the gate. An accepted fine backstep is still missing; another declared
trial would need more fine work. Mesh independence, inlet and model uncertainty
and physical qualification remain separate open gates.

The external-backend track has a separate
[wall-resolution plan](iterations/03-wall-resolution-plan.md). Its wall-resolved
SST reference converges and passes the independent audit at level 1; a mesh
pair needs a larger per-case budget or a coarse-to-fine start, and inlet and
model sensitivity remain open ([results](../validation/RESOLUTION_RESULTS.md)).
This does not advance the native canyon's physical-validation gate.

The [continuation plan](iterations/04-steady-continuation-plan.md) provides
verified same-mesh field continuation in bounded stages, which lets a solve
exceed one run's 3600 s limit; staged, the coarse reference reaches the same
converged solution as one run. A level-2 mesh still needs several stages of
roughly an hour each, whose sources must pass the source flux gate as
preregistered; whether that gate suits continuation is an open decision in the
[continuation results](../validation/RESTART_RESULTS.md). Nearest-cell
coarse-to-fine initialization exists for accepted cold sources; conservative
interpolation, chained sources and an accepted fine/coarse turbulent pair
remain work.

1. **Throughput (M1b, M3b):** multigrid for the pressure equation now that the masked operator is pinned against its reference; semi-implicit diffusion for momentum, k-ε and scalars; and solving the passive scalar after the flow has converged, with the flow cached for several releases. Each change is accepted only if the verification suite and the empty-ABL check pass with unchanged tolerances.
2. **Near-wall consistency (M3a):** a log-consistent velocity gradient in wall-adjacent cells, so the empty ABL also stays homogeneous below H, and a building-wall roughness specified independently of the ground and the grid.
3. **Resolution study (M3b):** the canyon at 10 or more cells per building height, a domain that meets the COST 732 clearances, and a GCI where the sequence supports one.
4. **Measured data (M3b):**
   - CODASC or the Hamburg datasets; access requests are prepared for the owner to send.
   - A protocol frozen before evaluation.
   - A pinned OpenFOAM run of the same case.
5. **Replay and particles, in parallel:**
   - Fine-grid, held-out replay of the optimizer tutorial (M4).
   - Particle settling (M5a), which depends only on M2.

Domain questions that would sharpen M3 onward:
- Which practical question matters most: mean sensor interpretation, source attribution, mitigation comparison or short-term peaks?
- Which instruments and measured quantities are available?
- Which existing geometry, inflow or reference cases may be used?
