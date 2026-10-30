# Initialize a finer generated case from accepted coarse volume fields

This is a new-mesh start, distinct from [same-mesh continuation](STEADY_RESTART.md).
The source must be numerically accepted and independently audited. The new fine
case starts at local pseudo-time zero and must establish its own numerical and
measurement results. The source-flux and final acceptance thresholds are
unchanged.

## Prepare and solve

Use the [pinned runtime](OPENFOAM.md) and validation dependencies; the runtime
provides the Foundation-13 `mapFields` utility. The source is a complete archive
(case, final fields, mesh, summary, logs and seals) of a cold-generated case:
a restarted or mapped source is not accepted. The single-run wall-resolved
`simplec` level-1 backstep of the [resolution results](../validation/RESOLUTION_RESULTS.md)
is such a source; a summary alone is not.

```sh
python integrations/openfoam_backend.py prepare-mapped --source COARSE_RUN \
  --level 2 --iterations 3000 --foam-root ROOT --data VERIFIED_DATA \
  --timeout-s 600 --output-mib 1024 --output NEW_FINE_INPUT
python integrations/openfoam_backend.py run --case NEW_FINE_INPUT \
  --foam-root ROOT --timeout-s 3500 --output-mib 1024 --output NEW_FINE_RUN
python validation/audit_openfoam_mesh.py --run NEW_FINE_RUN --output NEW_AUDIT.json
python validation/compare_backstep.py --run NEW_FINE_RUN --data VERIFIED_DATA \
  --output NEW_COMPARISON
```

For the cavity omit `--data`. Level 1 maps to level 2 and level 2 to level 3;
the case, mesh family, turbulence model and solver profile cannot change. The
source inputs must equal what the current generator writes for that recipe,
with the verified measurement files for the backstep.

`prepare-mapped` exits 0 when the case is prepared and 1 otherwise; exit 0 says
nothing about the fine flow, which `run`, the audit and the comparison judge
with their usual exit codes and gates. Outputs must be new. Checks of the source
and the runtime run before the output is created; a later failure leaves a
directory without `case.json`, which cannot run, with `mapping-failure.json`
(the error that was raised) and the logs of the utilities that ran.

## What is mapped and how it is checked

`mapFields -consistent -mapMethod mapNearest` runs on checked copies of the
source and of the generated target case. Only the mapped internal U and p and,
for SST, k, omega and nut enter the fine case. The target's generated boundary
conditions, dimensions and controls are written by the generator and kept
byte for byte; the mapper's own boundary values are discarded. Field counts,
finite values and turbulence signs are checked. Nearest-cell initialization is
not conservative interpolation and makes no accuracy claim.

There is no fine `0/phi`: a coarse face flux has no meaning on another mesh.
The solver builds phi from the new U and corrects it as usual. No initial local
continuity is claimed; the source passed the full audit, and every final check
of the fine run is unchanged.

`case.json` carries a `mesh_initialization` receipt
(`cfd-craft.mesh-initialization/0.2`). The consumed inputs include
`mapping_evidence/`: the checked source copy (inputs, mesh, final fields,
case record, manifest, summary and audit), the generated target templates, the
mapper's output and mesh, and the utility logs and arguments. Validation, before
every solve and when an archive is verified:

- checks the source chain: the manifest, summary, case record, audit, field
  identities and snapshot times, acceptance, work and runtime;
- checks that the utilities ran in order on this case's own copies, with the
  recorded source time, `-consistent` and `mapNearest`, and that the mapper's log
  names Foundation 13, the method and every field;
- replays the mapping with the independent mesh reader: each consumed internal
  value must equal the value of a source cell whose centre is nearest to the
  target cell's centre;
- rebuilds each consumed field from its stored template and the mapper output,
  and compares the controls with the generator.

A solve also requires the recorded runtime and the identical rebuilt mesh. The
receipt records the `mapFields` hash at preparation, where it must not change;
the solve's runtime identity covers the solver and its libraries, not
`mapFields`. The stored templates are compared with the generator only at
preparation, as for a cold case. Unkeyed hashes establish consistency, not
authenticity of an untrusted case; keep the complete source archive.

After a mapped run completes, ordinary `prepare-restart` can continue it on the
same mesh under the unchanged source-flux gate. Its parent identity binds the
mapping history; only the new continuation receipt is active. The coarse work is
recorded as `source_iterations` and is not counted as fine-grid work.

## Budgets and verification

Preparation defaults to 300 s, 512 MiB of output and a 2048 MiB child address
space; the limits are 3600 s, 2048 MiB and 8192 MiB. The evidence counts towards
the output and is copied into the run, so a mapped run needs more output room
than a cold one; `mapped_start.py` gives both level-2 runs 1024 MiB.

```sh
CFD_OPENFOAM_ROOT=ROOT python validation/test_mapping.py -v
CFD_OPENFOAM_ROOT=ROOT python -O validation/test_mapping.py -v
python validation/mapping_equivalence.py --foam-root ROOT --timeout-s 120 \
  --output NEW_CAVITY_EXPERIMENT
python validation/mapped_start.py --source COARSE_RUN --iterations 3000 \
  --timeout-s 3500 --data VERIFIED_DATA --foam-root ROOT --output NEW_REPORT
```

The cavity experiment compares a converged mapped level-2 cavity with a cold
one, with bounds declared before the runs; it exits 0 when they hold, 2 for
unaccepted returned runs and 1 for an input, workflow or archive error.
`mapped_start.py` runs a mapped and a cold start of the next level with equal
limits and reports both; it applies no gate. The actual-runtime tests also map
nonuniform synthetic SST fields between the real level-1 and level-2 backstep
meshes and check them with the replay; that is a utility check, not a turbulent
solve. See the [results](../validation/MAPPING_RESULTS.md).
