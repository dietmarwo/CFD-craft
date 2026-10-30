# Iteration 04: verified bounded steady continuation

Date: 30 October 2026. Base: merged PR #4,
`dee9c5afb9ef5ab8455f3d2b5da4651e2cb39035`.

## Evidence and decision

The merged wall-resolved/simplec level-1 backstep converges after 18412
iterations in one run of about 3000 s and passes the independent audit and the
measurement screen. A passing coarse screen is not physical qualification. A
level-2 case has four times the cells, so a single 3600-second run cannot
converge it. The first prerequisite is verified same-mesh field continuation in
bounded stages. The mesh, SST package, inlet, pressure scheme and acceptance
thresholds stay unchanged.

## Implementation and invariants

1. `prepare-restart --source RUN --iterations N --output NEW_INPUT` accepts a
   sealed, completed archive from the current generator with finite final
   fields. Timeout, cancellation and failure snapshots are ineligible. An
   unconverged completed stage is eligible if its stored face flux is a solver
   state (see below).
2. Keep the exact consumed physics/mesh dictionaries and boundary definitions.
   Copy final U/p/phi and, for SST, k/omega/nut into a new local iteration-0
   directory, and change only endTime/writeInterval. This is a steady field
   restart: local pseudo-iteration numbering and solver history reset.
   Cumulative iteration counts report work, not physical time or bitwise
   equivalence.
3. Record the source manifest/case hashes, metadata, controls, acceptance and
   work, the copied field identities, the fixed-input and actual mesh
   identities and the runtime identity. Check the copied bytes, the field
   snapshot times, the rebuilt mesh and the exact runtime before solving, and
   again when reading an archive. Unkeyed hashes are consistency, not
   authenticity.
4. Add `--max-stages` (default 1, at most 8) to the resolution tutorial.
   Continue only a completed, unconverged stage; stop at numerical acceptance,
   a converged but unaccepted stage, failure, timeout, cancellation, an
   ineligible source or the stage limit, and record which. Keep every stage and
   distinguish final-stage convergence from cumulative work. Finer meshes still
   require accepted coarser levels.
5. A run that stops at its iteration limit writes a final field only if the
   limit is a multiple of the write cadence; endTime 400 with cadence 250
   leaves none. Use the largest divisor of the limit up to 250, and reject
   limits without a divisor between 50 and 250, which would force nearly
   per-iteration writes of 8 MB snapshots.
6. Test source eligibility, corruption and races, receipt and archive
   consistency, mesh/runtime/input mismatches, cumulative counts, occupied
   paths, the stage loop and optimized Python. Provide tools that repeat the
   field comparisons from the repository.

## Source eligibility

A completed source is eligible only if its stored face flux passes the
auditor's independent local gate, max abs(div(phi))*H/U <=1e-4. This gate was
preregistered and stays in force. Two properties limit it: it follows the last
pressure solve's relative tolerance rather than the state (a PCG profile with
relative tolerance 0 passes by orders of magnitude, a GAMG SIMPLEC iterate at
iteration 500 fails), and it tightens like H/dx with refinement, the use case of
continuation. Whether a scale-free integrity check should replace it is an open
decision, recorded with its evidence in the results; it is not changed after
the gate rejected a source.

## Acceptance and experiments

The software target is an auditable field restart with all relevant tests
passing. Fixed-work comparisons continue FIRST iterations for SECOND and compare
the final fields with an uninterrupted FIRST + SECOND run of the same recipe:
maximum component-wise U and p differences of 1e-6 for the cavity (400 + 200)
and 1e-5 for the wall-resolved backstep; for k/omega/nut, the maximum difference
over the control's largest magnitude is at most 1e-5. The planned `simplec`
500 + 500 backstep comparison cannot start, because its source fails the flux
gate; the `simple` profile (250 + 250) supplies the backstep comparison. The final local-flux audits must pass. These
equivalence checks do not require nonlinear convergence and imply no
measurement screen.

The reference-recipe check runs the wall-resolved/simplec level-1 case in
stages of 6000 iterations (up to four) and in one 20000-iteration run on the
same runner. Preregistered before the result: both are numerically accepted
and pass the audit and screen; the chain's cumulative work is within 5% of the
single run's; reattachment agrees within 0.01 H, Cf RMSE within 1e-5, each
profile RMSE within 1e-4 and each wall's maximum y+ within 0.01; the final U
and p differ by at most 1e-3 (U_ref, U_ref^2, without removing an offset) and
k/omega/nut by at most 1e-3 of the control's largest magnitude.

The scientific mesh-pair, inlet-sensitivity and model-form gates remain open.
Cross-mesh mapping, changes to the turbulence treatment, native-kernel changes,
GPU and MPI are outside this plan.

## Primary reference

[Foundation 13 time/I-O controls](https://doc.cfd.direct/openfoam/user-guide-v13/controldict)
describe startTime, endTime, writeInterval and ASCII precision. This work uses
a fresh local pseudo-time zero for steady field initialization, with explicit
source and work provenance, rather than a transient-history restart.
