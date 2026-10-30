# Initialize a finer generated case from accepted coarse volume fields

This is a new-mesh start, distinct from [same-mesh continuation](STEADY_RESTART.md).
The source must be accepted and independently audited. The new fine case starts
at local pseudo-time zero and must establish its own numerical/measurement
results. The source-flux and final acceptance thresholds are unchanged.

## Prepare and solve

Use the [pinned runtime](OPENFOAM.md) and validation dependencies, including its
Foundation-13 mapFields executable. Start with a complete current cold-generated
source archive (case, final fields, mesh, summary, logs and seals). This first
release excludes sources whose initial fields were restarted or mapped. The
recorded cold SIMPLEC coarse control is a suitable source; a summary-only
archive is insufficient.

```sh
python integrations/openfoam_backend.py prepare-mapped --source COARSE_RUN \
  --level 2 --iterations 2000 --foam-root ROOT --data VERIFIED_DATA \
  --timeout-s 300 --output-mib 512 --output NEW_FINE_INPUT
python integrations/openfoam_backend.py run --case NEW_FINE_INPUT \
  --foam-root ROOT --timeout-s 3500 --output-mib 512 --output NEW_FINE_RUN
python validation/audit_openfoam_mesh.py --run NEW_FINE_RUN --output NEW_AUDIT.json
python validation/compare_backstep.py --run NEW_FINE_RUN --data VERIFIED_DATA \
  --output NEW_COMPARISON
```

For the cavity omit `--data`. Source level 1 maps to level 2, and 2 to 3; no
geometry, mesh family, turbulence or solver-profile change is accepted. Source
inputs must match the current cold generator and verified measurement files.
Source numerical acceptance and the complete independent audit must pass.

`prepare-mapped` exits 0 for successful preparation and 1 for invalid or failed
preparation. This does not mean the fine flow passed. The ordinary `run`/audit/
comparison exit conventions and acceptance gates still apply. Fresh outputs are
required. Failed preparation has no case.json and cannot run; its diagnostic
mapping-failure.json and available work/logs are preserved. Use another fresh
path after inspecting it.

## What is mapped and retained

The separate utility executes `mapFields -consistent -mapMethod mapNearest`
on checked copies with matching geometry/patch names. Only the mapped internal
U/p and, for SST, k/omega/nut enter the fine case. Target generated boundaries,
dimensions and numerical controls remain exact; raw mapped boundary values
are not imported. Field counts/finiteness and turbulence signs are checked.
Nearest-cell initialization is not conservative interpolation and provides no
accuracy improvement by itself.

There is no fine-grid `0/phi`: copying a coarse face field to a different mesh
would be invalid. The target solver constructs new phi from its own U and uses
normal pressure correction. No initial local-continuity pass is asserted for
this new mesh. This does not bypass same-mesh eligibility: the coarse source
already passes the full audit, and every final fine check is unchanged.

`case.json` stores a distinct `mesh_initialization` receipt. Consumed inputs
include mapping_evidence: exact source fields/inputs and manifests, generated
target templates, raw mapper outputs/mesh, source audit and command logs. The
receipt binds the parent/target, runtime and mapper binary identity. Verification
replays the internal-field insertion and checks runtime/rebuilt mesh before a
solve. Retain the complete original source archive for parent-chain inspection;
hashes establish consistency, not authenticity of untrusted dictionaries.

After a mapped run completes, ordinary `prepare-restart` may continue on that
fine mesh under the unchanged source-flux gate. Its parent identity binds the
mapping history; only its new continuation receipt remains active. Coarse
iterations are recorded as initialization provenance and are not fine work.

## Budgets and verification

Preparation defaults: 300 seconds, 512 MiB output, 2048 MiB child address space;
public limits are 3600 seconds, 2048 MiB output and 8192 MiB child address space.
Input/evidence copies count toward output and add I/O. The later solve needs
its own limits and room for that evidence; 512 MiB is the documented example.
Source verification, hashing and metadata add overhead. No owner workstation,
GPU or MPI is required.

```sh
CFD_OPENFOAM_ROOT=ROOT python validation/test_mapping.py -v
CFD_OPENFOAM_ROOT=ROOT python -O validation/test_mapping.py -v
python validation/mapping_equivalence.py --foam-root ROOT --timeout-s 120 \
  --output NEW_CAVITY_EXPERIMENT
```

The cavity experiment compares converged mapped and cold level-2 fields, their
independent audits and the Ghia numerical reference. Its 1e-4 field and 0.06
Ghia bounds were declared before the runs. The SST utility fixture checks file
formats and boundary preservation with synthetic fields; it is not an accepted
turbulent solve. See [results](../validation/MAPPING_RESULTS.md). No fine
backstep, mesh-independent turbulent flow, scalar or urban validation is claimed.
