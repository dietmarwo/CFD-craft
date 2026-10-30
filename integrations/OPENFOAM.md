# Established-solver comparisons

This adapter supports two generated cases on **OpenFOAM Foundation 13**:
a laminar Re=100 cavity and a turbulent Driver--Seegmiller backstep. It is a
bounded starting point for an external-backend workbench. It does not yet
translate arbitrary native canyon JSON, run scalar dispersion in OpenFOAM,
or provide a new fcmaes worker profile. The existing native worker is unchanged.

Read the [external model card](../docs/model-cards/openfoam-backend.md),
[plan](../docs/iterations/02-external-validation-plan.md) and
[results](../validation/EXTERNAL_RESULTS.md). A measured velocity comparison
cannot qualify the native canyon's concentration predictions.

## Reproduce

Use Ubuntu 24.04 x86_64, Python 3.10 or newer, Rust 1.88 or newer, and dpkg-deb.
The installer downloads the exact tested 118.6 MB package and extracts it to a
new directory without installing system packages or requiring root. OpenFOAM's
serial Pstream library is used, so MPI is not required for these cases. The
Foundation package is licensed under the GNU GPL, version 3 or later, with its
own source and license notices. CFD-craft runs its programs and neither links
nor imports them; no OpenFOAM executable, library or source is part of this
repository.

~~~sh
cargo build --release --locked
python -m pip install -r requirements-validation.txt
mkdir -p runs
python integrations/install_openfoam13.py --output runs/openfoam13
python tutorials/external_cfd.py --preset cavity \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 \
  --output runs/external-cavity
~~~

`--package-file` may reuse a local copy of the exact pinned .deb. Its size and
SHA-256 are still checked before extraction. A different Foundation major
version or OpenCFD fork is rejected by the execution adapter. Another build
of Foundation 13 is identified by its actual hashes and needs its own review.

Run a preliminary comparison with real measurements:

~~~sh
python validation/backstep_data.py --output runs/backstep-measurements
python tutorials/external_cfd.py --preset smoke \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 \
  --data runs/backstep-measurements --timeout-s 300 \
  --output runs/external-smoke
~~~

Without `--data`, smoke/study explicitly downloads the same hash-pinned public
files into its output. The upstream x/H=-4 mean velocity is an input; x/H=1,4,6,10
are evaluation stations. Raw downloads are not replaced by synthetic fixtures.
Cp is acquired for provenance and a future pressure evaluation; it is not
scored. No private-data credentials, owner contact or agreement is used.

`--preset study` runs levels 1,2,3 (22656/90624/203904 backstep cells) under
the same per-case budget; the recorded results use `--timeout-s 300`. It
preserves timeouts and incomplete rows. An uncompleted mesh series supplies no
GCI or mesh-independent physical claim. Levels 2 and 3 need far more than 300 s
of serial time to finish their 6000 iterations.

## Use the individual commands

For refinement, [prepare-mapped](MESH_INITIALIZATION.md) is a separate operation
from same-mesh continuation: use accepted cold coarse fields, preserve generated
fine boundaries and construct new phi in the target solver. It carries no
fine-grid acceptance verdict; run the normal numerical/audit/screen checks.

For a steady solve longer than one run's limits, see the
[continuation guide](STEADY_RESTART.md). `prepare-restart` turns a completed
archive into a fresh same-mesh input from its final fields and phi. The
resolution tutorial's `--max-stages` chains such stages; the default is one.

The [resolution tutorial](../tutorials/backstep-resolution-prompt.md) runs
wall-resolved backstep recipes and an independent Cartesian
mesh/local-flux/wall-distance audit. Select a recipe explicitly, for example
`prepare --mesh-family wall-resolved --solver-profile simplec`; the legacy
recipe remains the default. The `backstep_resolution.py` study preset skips
finer meshes when a coarse case is not accepted. Read the
[resolution results](../validation/RESOLUTION_RESULTS.md) before allocating a
larger run.

~~~sh
python integrations/openfoam_backend.py prepare --case backstep --level 1 \
  --iterations 6000 --data runs/backstep-measurements --output runs/backstep-input
python integrations/openfoam_backend.py run --case runs/backstep-input \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --timeout-s 300 \
  --memory-mib 2048 --output-mib 512 --output runs/backstep-run
python integrations/openfoam_backend.py report runs/backstep-run
python validation/compare_backstep.py --run runs/backstep-run \
  --data runs/backstep-measurements --output runs/backstep-comparison
~~~

Each output directory must be new; its parent must exist. Inputs are copied
into the run archive, and the copy is checked against their sealed identities. If the generator
changes, prepare a new case. Execution is shell-free, single-process and serial.
Trusted OpenFOAM binaries still execute their ordinary libraries and dictionary
features; the checksum is an integrity check, not authorization for untrusted
user code.

The external artifact is `cfd-craft.external-run/0.1`, not a native CFD or
optimization result. Native `cfd-craft report` does not read it. The archive has
a checksummed manifest and completion marker, including on failure; a symlink
left by a child marks the run failed. `report` checks consistency, not
tampering: see the [model card](../docs/model-cards/openfoam-backend.md). Completion
means the evidence has been written. `passed` additionally requires numerical
acceptance and valid final samples. Child failure, cancellation and timeout
remain distinct. The command record preserves the actual return code and log;
progress lists started iterations and saved snapshots, which may precede a
partial final iteration.

`prepare` exits 0 on success; invalid requests exit 1. `run` exits 0 for
accepted numerical evidence, 2 for a completed, timed-out or cancelled run
without it, and 1 when the execution itself failed (runtime, input, I/O).
`report` exits 0 or 2 by the archived result, and 1 for an archive that fails
verification. `compare_backstep` exits 0 when the numerical gate and the
development screen pass, otherwise 2, and 1 when its output cannot be written.
Both tutorials exit 0 when everything passes, 2 when they recorded failed,
unaccepted or cancelled evidence, and 1 on a workflow error.
`audit_openfoam_mesh.py` exits 0 when its checks pass, 2 when they fail or the
archive has no final field, and 1 for an invalid archive or output path.
`prepare-restart` exits 0 for a prepared stage and 1 for an ineligible source or
invalid request. `compare_restart.py` and `restart_equivalence.py` exit 0 when
their bounds hold, 2 when they do not and 1 for invalid input. In the resolution
tutorial an ineligible completed stage is recorded evidence (exit 2), not a
workflow error. **None of these exit codes sets physical
qualification to true.** Read all four levels: execution, numerics, measurement
screen and physical qualification.

## Tests and CI

~~~sh
python validation/test_openfoam.py -v
python -O validation/test_openfoam.py -v
python validation/test_resolution.py -v
python validation/test_restart.py -v
CFD_OPENFOAM_ROOT="$PWD/runs/openfoam13/runtime/opt/openfoam13" \
  python validation/test_openfoam.py -v
CFD_OPENFOAM_ROOT="$PWD/runs/openfoam13/runtime/opt/openfoam13" \
  python validation/test_resolution.py -v
CFD_OPENFOAM_ROOT="$PWD/runs/openfoam13/runtime/opt/openfoam13" \
  python validation/test_restart.py -v
~~~

Unit tests have explicit synthetic fixtures, including a synthetic stand-in for
the four Foundation-13 programs that drives `run` and `report` end to end. They
test contracts, not physical accuracy. With the environment variable set, the additional tests run actual
OpenFOAM cavity solves, check an iteration-limit failure, corrupt returned
fields and face fluxes to verify rejection, and compare the actual wall-resolved
`blockMesh` output with the generated first-cell heights and spacing, and
continue actual cavity runs against uninterrupted controls. CI runs the
boundary tests on each push/PR. A manual workflow dispatch installs the pinned
runtime in two parallel jobs; its `external` input (`all`, `backend` or
`resolution`) selects which of them run. `external-backend` runs the real backend tests,
the external study preset with `--timeout-s 300` and a fixed-work
continuation check of the wall-resolved backstep (`simple` profile, 250+250
iterations). `external-resolution` runs the resolution smoke
preset in one run (`--iterations 20000 --timeout-s 3500`) and in stages
(`--iterations 6000 --max-stages 4 --timeout-s 3500`) on the same runner, then
compares the two converged results. Both publish the key numbers as notices and
upload the reports. A recorded backstep failure keeps a job green; a workflow
error fails it.

## Frozen protocol

`validation/protocols/backstep-v1.json` is hashed in the evaluator. A local edit
cannot relax a threshold. A scientifically justified protocol change requires
a new reviewed version, updated identity, a reason and a fresh evaluation;
retain the previous report. Measurement error, mesh sensitivity and uncertain
inlet/model assumptions are separate quantities. No parameter of the generated
case is fitted to the downstream evaluation measurements.
