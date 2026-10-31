# Iteration 06: bounded mapped refinement campaign

Date: 30 October 2026. Base: merged PR #6,
`06bf8b5d894e5252a5b04d14ff04cda06e010bb8`.

## Evidence and decision

The mapping results record mapped and cold level-2 backstep starts after 3000
iterations; neither converged, and neither is a source for anything else. The
next step connects mapping, same-mesh continuation and final acceptance in one
bounded campaign that keeps every archive it uses. The numerical, local-flux,
wall-y+ and measurement gates, the native equations, the solver recipes, the
experimental protocols and the mapping and restart schemas stay unchanged.

## Implementation

1. Snapshot a verified, accepted, cold coarse archive into a fresh campaign
   directory: check the copied bytes and both inventories, and keep the complete
   parent rather than a summary or an external path. The source must pass its
   numerical gate, the independent audit and its measurement screen.
2. Freeze a plan with the source identity, the producer identities, the next
   level, the work, the stage count and the per-stage preparation and solve
   limits before anything is executed.
3. Map once, then continue completed eligible fine stages with the existing
   restart API. Verify every stage and bind its parent, runtime, mesh and
   cumulative fine work to the previous stage. Keep coarse work separate.
4. Keep the numerical, independent-audit and measurement verdicts of every
   stage. Stop at accepted convergence, converged-but-rejected evidence, an
   execution stop, an ineligible source or the declared stage limit. Never
   restart a timeout or cancellation or promote an earlier snapshot.
5. Reverify every complete archive after each stage and at final collection,
   and require each archive to keep its first checkpoint's manifest. An archive
   or progress mismatch stops the workflow; nothing is repaired or resealed.
6. Compare coarse and fine observables only when both numerical assessments
   and independent audits pass. Pair velocity samples by exact identity and
   compare Cf at common measured positions without extrapolation. Two grids are
   not a GCI or a mesh-independence certificate.
7. Test the rules in normal and optimized Python, including real mapped cavity
   stages, rejected sources and archives, parent and work mismatches, stopping
   and gate semantics; run the campaign in the optional CI workflow and keep
   its complete archives.

## Declared campaign

Source: the accepted cold wall-resolved `simplec` level-1 backstep (48896
cells, 18412 iterations), verified and checked against its measurement screen.
Target: level 2 (195584 cells). At most three stages of 4000 iterations, at
most 3500 s per solve, 1024 MiB output and 4096 MiB child address space per
stage, 900 s for the preparation. The source's coarse iterations are
provenance, not fine work. No cold level-2 control and no speed claim.

A successful outcome requires final numerical acceptance, the independent local
gate (<=1e-4), maximum y+ <=1 on each wall and the original backstep
measurement screen. Otherwise the actual stop reason and the unaccepted
evidence are the result. No threshold is adjusted after results are read.
Inlet and model sensitivity, another refinement and native canyon
qualification remain later work.

## Executions before the declared run

The campaign was first exercised on a cloud machine (eight-core quota). A
prototype was cancelled at started iteration 238 to correct the cancellation
rule; two runs of the declared campaign then ended without a returned solver
record or seal, at started iterations 1457 and 1193, for reasons that are
unknown. None of these fields was used as a source. A reduced campaign (two
400-iteration stages, 450 s per solve, 180 s preparation) then ran to the end;
its limits were frozen in its report before it started, but an earlier version
of this document was changed to declare it only afterwards. It is a workflow
check, not the declared campaign, and is recorded as such in the
[results](../../validation/REFINEMENT_RESULTS.md). The declared campaign above
then ran on a GitHub runner through the manual `external=refinement` selection.

## Outcome

The declared campaign ran on a GitHub runner (workflow run 41151497327) with
the limits above. All three stages completed; none was numerically accepted,
and the stop reason is `stage_limit` after 12000 fine iterations. Every stage
passed the independent audit. At the end the Ux, p and omega residuals met the
1e-7 gate, while Uy (1.8e-7) and k (1.05e-7) did not; the residuals fell in
every stage. The two-grid comparison was not assessed, and there is no accepted
fine backstep. The thresholds were not changed. See the
[results](../../validation/REFINEMENT_RESULTS.md).
