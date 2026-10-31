# Iteration 06: bounded mapped refinement campaign

Date: 30 October 2026. Base: merged PR #6,
`06bf8b5d894e5252a5b04d14ff04cda06e010bb8`.

## Review and decision

PR #6 adds independent replay of mapped fields, stronger source/target receipt
checks, 58 mapping tests and failure annotations. Keep those fixes, including
the recorded Foundation-13 behavior on the graded backstep: all fields take
their values from one of the 27 nearby source cells, not necessarily the
Euclidean nearest. It also records real mapped and cold level-2 starts after
3000 iterations; neither is converged. Do not repeat that report-only driver
and call it accepted fine-grid evidence.

The next increment connects mapping, same-mesh continuation and final acceptance
in one bounded campaign. The initial and final numerical, local-flux, wall-y+
and measurement gates remain unchanged. Native equations, solver recipes,
experimental protocols and mapping/restart schemas are not changed.

## Implementation

1. Snapshot a verified accepted cold coarse archive into a fresh campaign;
   copy checked bytes and verify the source and copy inventories. Retain the
   complete parent rather than relying on a summary or an external path.
2. Freeze a plan with source identity, producer identities, next level, work,
   stage count and per-stage preparation/solve limits before execution.
3. Map once, then continue completed eligible fine stages using the existing
   restart API. Verify every stage and bind its parent, runtime, mesh and
   cumulative fine work to the previous stage. Keep coarse work separate.
4. Retain per-stage numerical, independent-audit and measurement verdicts.
   Stop at accepted convergence, converged-but-rejected evidence, an execution
   stop, an ineligible source or the declared stage limit. Never restart a
   timeout/cancellation or promote a pre-failure snapshot.
5. Reverify every complete archive after each stage and at final collection;
   retain checkpoint identities. An archive/progress mismatch stops the
   workflow and is not repaired or resealed. This investigates/contains the
   extra-time-directory anomaly without claiming an unproven root cause.
6. Compare coarse and fine observables only when both numerical assessments
   and independent audits pass. Pair velocity sample identities exactly and
   compare Cf at common measured positions without extrapolation. Report
   differences, original measurement screens and remaining qualification
   blockers. Two grids are not a GCI or a mesh-independence certificate.
7. Add normal/optimized Python tests, including real mapped cavity stages,
   rejected sources/archives, parent/work mismatches, stopping and gate
   semantics. Run required Rust/Ruff and existing external suites. Extend the
   optional CI workflow and retain complete campaign archives.

## Preregistered local campaign

Reuse the cold wall-resolved SIMPLEC level-1 backstep from GitHub run
41106074755 only after its complete archive passes the current verifier,
independent audit, frozen measurement screen and exact runtime comparison.
Its downloaded artifact must match GitHub's published digest. Otherwise
regenerate the source and record that work separately.

Target level 2 has 195584 cells. Attempt at most three stages of 4000
iterations, at most 3500 seconds per solve, 1024 MiB output and 4096 MiB child
address space. Preparation has a separate 900-second limit. The source's
18412 recorded coarse iterations are additional provenance, not fine work or
new local CPU time. No cold level-2 rerun or new speed claim is included.

A successful scientific outcome requires final numerical acceptance, the
independent local gate <=1e-4, maximum y+ <=1 on each wall and the original
backstep measurement screen. If the bounded trial does not achieve that,
deliver its actual stop reason and unaccepted evidence. No thresholds will be
adjusted after results are read. Inlet/model sensitivity, another refinement,
native canyon qualification, owner hardware, MPI and GPU remain later work.

## Local execution amendment

Two longer host executions disappeared without a returned solver record or
archive seal, including a repetition with heartbeat monitoring. Their exact
producers, plans, partial reports/logs and unknown-exit receipts are retained;
neither incomplete field is a continuation source. This is an observed host
execution limitation, not a diagnosed solver failure or a reason to change a
scientific gate.

Before starting a new local proof, reduce its declared work to at most **two
400-iteration stages**, **450 seconds per execution**, preparation **180
seconds**, and the same 1024 MiB output / 4096 MiB child address-space limits.
Start again from the verified cold coarse source. The objective of this shorter
proof is actual turbulent mapping, eligible fine continuation and complete
returned-field/audit/report handling within a sustained host session. It is not
expected to establish fine-grid convergence. Any source-gate rejection remains
an explicit bounded result.

The implemented driver still supports the original larger limits. Manual CI's
explicit `refinement` selection retains the three 4000-iteration stages and
3500-second per-execution limits on a longer-lived runner. It is not dispatched
by this task. An accepted fine backstep therefore remains a scientific gate
unless actual returned evidence passes it; a short local proof cannot replace
the larger convergence experiment.

## Delivery

Deliver the source patch, plan, implementation log, actual campaign report,
selected complete run archives and test evidence. Check the patch on a pristine
base checkout and verify the extracted ZIP. Do not dispatch remote CI, publish,
push or change remote branches.
