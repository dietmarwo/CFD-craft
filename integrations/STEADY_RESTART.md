# Continue a costly steady solve in verified bounded stages

The merged coarse backstep reference converges, but a finer mesh can need more
than the adapter's 3600-second single-run limit. Same-mesh field continuation
lets a solve make progress in separately bounded, auditable stages. It does not
interpolate between meshes or restore a transient simulation's time history.

## Prepare a new stage

Install the validation dependencies and pinned Foundation-13 runtime as in
[OPENFOAM.md](OPENFOAM.md). Use a trusted, complete generated source archive,
including its case, mesh, final fields, logs, summary, manifest and completion
marker. Summary/log-only evidence cannot supply a restart.

```sh
python integrations/openfoam_backend.py report SOURCE_RUN
python integrations/openfoam_backend.py prepare-restart --source SOURCE_RUN \
  --iterations 5000 --output NEW_INPUT
python integrations/openfoam_backend.py run --case NEW_INPUT \
  --foam-root ROOT --timeout-s 900 --output-mib 512 --output NEW_RUN
python validation/audit_openfoam_mesh.py --run NEW_RUN --output NEW_AUDIT.json
```

A verified but numerically unaccepted source can make `report` exit 2. That is
eligible only when execution completed with finite final fields and the
independent local flux gate passes. Failed, timed-out and cancelled runs are
rejected, including any older saved snapshots they contain. A missing/invalid
source or initialization mismatch is an error with a field path. Fresh output
paths are required; occupied paths are preserved.

The source must use the current case generator. The exact runtime and rebuilt
mesh must match its recorded identities. No user-selected physics/mesh/profile
change is accepted by `prepare-restart`. To start another numerical model,
prepare an ordinary cold case; cross-mesh mapping is separate future work.

## What is carried forward

U/p/phi and, for SST, k/omega/nut are copied byte-for-byte from the source's
actual final field directory to the new `0` directory, including the stored
boundary definitions/values. The initial phi is checked independently; it is
not silently reconstructed from interpolated cell velocity. Fixed physics,
mesh and sampling dictionaries retain their source identities. Only endTime
and writeInterval are changed for the new stage.

Local steady pseudo-time and the solver's residual history/caches start afresh.
An original field header's location still identifies the source snapshot;
OpenFOAM reads the file from the new local zero directory. This is field
initialization, not a claim that every solver-internal state was restored.
`numerical.iterations` counts the new stage. The receipt's
`source_completed_iterations` plus this value counts solver work along the
chain, not physical time or a guarantee of bitwise monolithic equivalence.

The receipt in `case.json` and `summary.json` records the parent case/manifest,
source acceptance, copied field hashes, actual mesh, fixed inputs and runtime
identity. These are checked before solving and when verifying an archive.
Keep parent archives for chain inspection; the parent hash alone does not
provide their contents. Checksums establish consistency, not authenticity of
an untrusted case. Existing trusted-input restrictions still apply.

## Automate bounded stages

```sh
python tutorials/backstep_resolution.py --preset smoke --iterations 5000 \
  --max-stages 4 --timeout-s 900 --foam-root ROOT --data VERIFIED_DATA \
  --output NEW_STUDY
```

The default is one stage, preserving the existing workflow. At most eight
stages are permitted per requested case. A numerically converged stage stops
the loop; its independent wall/flux audit and measurement screen still decide
acceptance. An unconverged completed stage can continue if eligible. A stopped
execution or exhausted stage count stays unaccepted. The next mesh is skipped
after an unaccepted coarse case.

Each stage retains a complete archive and a prepared input. The 512 MiB run
output limit and 2048 MiB child address-space limit apply per stage; total disk
and time grow with the number of stages, plus preparation/hash overhead.
The manual CI job keeps full resolution archives for later use. Automatic
download/resume across separate CI jobs is not implemented.

Preparation selects the largest write cadence <=250 that divides the requested
iteration limit, ensuring a normal iteration-limit exit has a final snapshot.
Limits 6000/20000 keep cadence 250; prime limits can write every iteration.
Composite stage lengths such as 500 or 5000 avoid that extra I/O.

## Verification and limits

Run `validation/test_restart.py` normally and under `python -O`; set
`CFD_OPENFOAM_ROOT` to include actual field-equivalence and rejection tests.
The [plan](../docs/iterations/04-steady-continuation-plan.md) and
[results](../validation/RESTART_RESULTS.md) distinguish software equivalence,
nonlinear convergence, measurement screening and physical qualification.
No tolerance, mesh or turbulence package is weakened for continuation. The
native Rust solver and its physical-validation gates are unchanged.
