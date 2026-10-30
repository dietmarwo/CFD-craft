# Iteration 04: verified bounded steady continuation

Date: 30 October 2026. Base: merged PR #4,
`dee9c5afb9ef5ab8455f3d2b5da4651e2cb39035`.

## Merged evidence and decision

PR #4 removes the 140:1 streamwise cell-width jump at the step plane and
checks the actual grading. It also makes the breakdown log scan incremental,
checks face orientation and relative local imbalance, strengthens wall/audit
screening and preserves workflow errors. Its wall-resolved/simplec level-1
reference now converges after 18412 iterations and passes the independent and
measurement screens. A passing coarse screen is not physical qualification.

A level-2 case has four times the cells; a single 3600-second solve is not a
practical route to its convergence. First provide verified same-mesh field
continuation in bounded stages. Do not change the mesh, SST package, inlet,
pressure scheme or acceptance thresholds in this iteration.

## Implementation and invariants

1. Add `prepare-restart --source RUN --iterations N --output NEW_INPUT`.
   Accept only a sealed, completed generated archive with a finite final
   snapshot and a passing independent local-continuity check. An unconverged
   completed stage is eligible; timeout/cancellation/failure snapshots are not.
2. Keep the exact consumed physics/mesh dictionaries and boundary definitions.
   Copy final U/p/phi and, for SST, k/omega/nut into a new local iteration-0
   directory. Change only endTime/writeInterval for the new bounded stage.
   This is a steady field restart: local pseudo-iteration numbering and solver
   history reset. Cumulative iteration counts report work, not physical time or
   bitwise equivalence to a monolithic solve.
3. Record the source manifest/case hashes, source acceptance, copied field
   identities, fixed-input identities, actual mesh identities and runtime
   identity. Check copied bytes, rebuilt mesh and exact runtime before solving.
   Verify the initial-state contract again when reading an archive. Preserve
   source archives separately; unkeyed hashes are consistency, not authenticity.
4. Add a bounded `--max-stages` option (default 1, at most 8) to the existing
   resolution tutorial. Continue only a completed unaccepted stage; stop at
   numerical convergence, failure, timeout, cancellation or the stage budget.
   Keep every stage and distinguish final-stage convergence from cumulative work.
   Finer meshes still require accepted coarser levels.
5. Test source eligibility, corruption/races, mesh/runtime/input mismatches,
   provenance and cumulative counts, occupied output paths, workflow stopping
   and optimized Python. Test actual cavity restart/continuous agreement and
   short same-recipe SST backstep stages against an uninterrupted control.
6. Run required Rust/Ruff, existing Python and native analytic/empty-ABL checks.
   Apply the final patch on a pristine base, test it and package the patch,
   plan, log and selected evidence without external program binaries/raw data.

## Acceptance and bounded experiments

The software target is an auditable field restart with all relevant tests
passing. Predeclare maximum component-wise U and pressure-offset-adjusted p
differences of 1e-6 in the cavity fixed-work comparison and 1e-5 for the short
SST fixed-work comparison; report actual errors. Require the final local-flux
audits. For k/omega/nut also require maximum component difference divided by
the uninterrupted field's maximum magnitude <=1e-5. Use 500+500 versus 1000
iterations for the bounded SST comparison. Keep numerical acceptance and
experimental screening separate from these equivalence checks.
Require the unchanged numerical checks independently. A short SST fixture can
verify continuation without reaching nonlinear convergence; retain that failure
of acceptance and do not screen its measurements as a qualified solution.

The scientific mesh-pair, inlet-sensitivity and model-form gates remain open.
Cross-mesh mapping, changing turbulence treatment, native-kernel changes,
owner-machine benchmarks, GPU and MPI are outside this iteration. All tests
and bounded experiments use cloud CPU; workstation tasks remain lower priority
until January.

## Review amendment: final snapshot availability

The initial tests found that `endTime=400`, `writeInterval=250` finishes the
solve without a field at iteration 400. Select the largest divisor of each
stage's iteration limit that is <=250 for its write cadence. Default limits
6000 and 20000 retain their existing cadence of 250; prime limits can require
writing every iteration. This changes I/O, not equations or acceptance. Add a
real non-multiple-of-250 regression and keep incomplete runs ineligible.

## Review amendment: source eligibility in short SST stages

The 500-iteration reference SIMPLEC prefix completed but has maximum local
normalized flux divergence 0.00483124, above the unchanged 1e-4 source gate.
It cannot supply the planned 500+500 comparison. Preserve that rejected
experiment and the corresponding automatic-workflow gate stop. Do not weaken
the source gate or call the prefix corrupt merely because it is unconverged.

Use the already merged `wall-resolved`/`simple` profile for a bounded positive
SST equivalence fixture: 250+250 versus 500 iterations with the same profile
on both sides. Its tighter pressure solve makes it a suitable early flux
fixture; it is not substituted for the accepted SIMPLEC accuracy reference.
The same preregistered U/p and turbulence difference targets apply. Longer
SIMPLEC stages are needed for the reference continuation workflow.

In the automatic tutorial, an otherwise valid completed stage that fails the
source local-flux gate is unaccepted row evidence: assess that stage and skip
refinement, with exit 2. Other preparation, archive and I/O errors still stop
the workflow with exit 1. The standalone prepare-restart command rejects an
ineligible source as an invalid request.

## Primary reference

[Foundation 13 time/I-O controls](https://doc.cfd.direct/openfoam/user-guide-v13/controldict)
describe startTime, endTime, writeInterval and ASCII precision. This work uses
fresh local pseudo-time zero for steady field initialization, with explicit
source/work provenance, rather than claiming a transient-history restart.
