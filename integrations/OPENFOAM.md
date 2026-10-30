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

## Reproduce on a cloud CPU

Use Ubuntu 24.04 x86_64, Python 3.10 or newer, Rust 1.88 or newer, and dpkg-deb.
The installer downloads the exact tested 118.6 MB package and extracts it to a
new directory without installing system packages or requiring root. OpenFOAM's
serial Pstream library is used, so MPI is not required for these cases. The
Foundation package remains GPL software with its own source/license notices;
no OpenFOAM executable or library is distributed in the CFD-craft patch.

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
  --data runs/backstep-measurements --timeout-s 600 \
  --output runs/external-smoke
~~~

Without `--data`, smoke/study explicitly downloads the same hash-pinned public
files into its output. The upstream x/H=-4 mean velocity is an input; x/H=1,4,6,10
are evaluation stations. Raw downloads are not replaced by synthetic fixtures.
Cp is acquired for provenance/future pressure evaluation; it is not scored by
this iteration. No private-data credentials, owner contact or agreement is used.

`--preset study` attempts levels 1,2,3 (22656/90624/203904 backstep cells) under
the same per-case budget. Choose this after reviewing smoke. It preserves
timeouts and incomplete rows. An uncompleted mesh series supplies no GCI or
mesh-independent physical claim. The complete study can be much slower than
the cavity and should run on available cloud CPUs while home machines are
unavailable.

## Use the individual commands

~~~sh
python integrations/openfoam_backend.py prepare --case backstep --level 1 \
  --iterations 6000 --data runs/backstep-measurements --output runs/backstep-input
python integrations/openfoam_backend.py run --case runs/backstep-input \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --timeout-s 600 \
  --memory-mib 2048 --output-mib 256 --output runs/backstep-run
python integrations/openfoam_backend.py report runs/backstep-run
python validation/compare_backstep.py --run runs/backstep-run \
  --data runs/backstep-measurements --output runs/backstep-comparison
~~~

Each output directory must be new; its parent must exist. Inputs are copied
into the run archive and their sealed identities are checked. If the generator
changes, prepare a new case. Execution is shell-free, single-process and serial.
Trusted OpenFOAM binaries still execute their ordinary libraries and dictionary
features; the checksum is an integrity check, not authorization for untrusted
user code.

The external artifact is `cfd-craft.external-run/0.1`, not a native CFD or
optimization result. Native `cfd-craft report` does not read it. The archive has
a checksummed manifest and completion marker, including on failure. Completion
means the evidence has been written. `passed` additionally requires numerical
acceptance and valid final samples. Child failure, cancellation and timeout
remain distinct. The command record preserves the actual return code and log;
progress lists started iterations and saved snapshots, which may precede a
partial final iteration.

`prepare` exits 0 on success; invalid requests exit 1. `run`/`report` exit 0 for
accepted numerical evidence, 2 for a valid but unsuccessful result, and 1 for
invalid input/archive handling. `compare_backstep` exits 0 when the frozen
development screen and numerical gate pass, otherwise 2. The tutorial follows
the same screen convention. **None of these exit codes sets physical
qualification to true.** Read all four levels: execution, numerics, measurement
screen and physical qualification.

## Tests and CI

~~~sh
python validation/test_openfoam.py -v
python -O validation/test_openfoam.py -v
CFD_OPENFOAM_ROOT="$PWD/runs/openfoam13/runtime/opt/openfoam13" \
  python validation/test_openfoam.py -v
~~~

Unit tests have explicit synthetic fixtures. They test contracts, not physical
accuracy. With the environment variable set, the additional test runs actual
OpenFOAM cavity solves, checks an iteration-limit failure and corrupts returned
fields to verify rejection. CI runs boundary tests on each push/PR; manual
workflow dispatch additionally installs the pinned runtime, runs the real
backend tests and compares the two cavity solvers. The experimental backstep
screen is a separate scientific run and can remain incomplete or fail.

## Frozen protocol

`validation/protocols/backstep-v1.json` is hashed in the evaluator. A local edit
cannot relax a threshold. A scientifically justified protocol change requires
a new reviewed version, updated identity, a reason and a fresh evaluation;
retain the previous report. Measurement error, mesh sensitivity and uncertain
inlet/model assumptions are separate quantities. No parameter was optimized
against the downstream evaluation measurements in this iteration.
