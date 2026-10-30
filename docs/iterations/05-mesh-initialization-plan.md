# Iteration 05: explicit coarse-to-fine field initialization

Date: 30 October 2026. Base: PR #5,
`e6134cd2e74d675819b8acd696af7d813c06809b`.

## Evidence and decision

Same-mesh continuation reaches the single-run solution of the wall-resolved
level-1 backstep in stages ([continuation results](../../validation/RESTART_RESULTS.md)).
Its source-flux gate stays as preregistered. A fine-grid campaign needs a
different operation first: initialize a newly generated finer case from
accepted coarse volume fields. The new mesh has no transferable face flux; the
solver initializes phi from its new U and corrects it. Preparation makes no
claim of initial conservation or of an accepted fine solution.

## Implementation

1. `prepare-mapped` accepts a cold-generated, numerically accepted source with a
   passing independent audit, built by the current generator, and maps it to
   exactly one finer level of the same case, mesh family and solver profile.
   Restarted or mapped sources are not accepted.
2. Foundation 13's separately licensed `mapFields` runs with
   `-consistent -mapMethod mapNearest` on checked copies. This is nearest-cell
   initialization, not conservative interpolation or an accuracy method. No
   OpenFOAM code is copied into the repository.
3. Only the mapped internal U and p and, for SST, k, omega and nut are imported.
   The target's generated boundary definitions, dimensions, geometry, inlet and
   controls stay byte-identical; phi and wall stress are not mapped. Field
   counts, finite values and turbulence signs are checked. The raw mapper
   output, templates and logs are kept as inputs.
4. A distinct receipt binds the source case, manifest, summary, audit, fields
   and work, the target metadata and templates, the mapper output and mesh, and
   the runtime and mapper identities. Validation before solving and during
   archive verification rechecks this chain and replays the nearest-cell
   mapping independently from the stored source copy. A solved case requires
   the recorded runtime and a passed, identical rebuilt mesh. A failed
   preparation stays non-runnable and keeps its diagnostic and logs.
5. Same-mesh restart is unchanged. A completed mapped run can be continued on
   its mesh; the new stage's receipt names the mapped parent, and the mapping
   receipt is removed from the stage. Coarse work is not counted as fine-grid
   iterations.
6. Tests cover boundary preservation, exact nearest mapping on known fields,
   source eligibility, source-copy races, provenance, missing or altered
   evidence, runtime and mesh mismatch, limits, occupied outputs and optimized
   Python. Real Foundation-13 tests cover cavity 1->2 and nonuniform SST fields
   on the real backstep meshes, distinguished from an accepted turbulent flow.

## Acceptance and experiments

Declared before the runs: a mapped and a cold level-2 cavity, with identical
final settings, both pass the nonlinear and local-continuity gates; their
final U and p differ by at most 1e-4 (U_ref, U_ref^2, no pressure offset
removed); both Ghia centerline errors are at most 0.06. All work, including
the source and the mapping, is reported; one run supports no speed claim.

A mapped and a cold start of the wall-resolved level-2 backstep, from the
accepted single level-1 run, run with equal iteration limits and budgets. This
is a report, with no gate: it shows whether the path works on the backstep and
what each start reaches, not an accepted fine solution.

No source-flux, final residual, wall-y+ or measurement threshold changes. A
GCI, mesh independence and physical validation remain open, as do native
physics, GPU and MPI.

## Primary source

[Foundation 13 mapFields](https://cpp.openfoam.org/v13/mapFields_8C_source.html)
supports mapNearest, interpolate and cellPointInterpolate. Only mapNearest is
used, with the generated target boundary dictionaries.
