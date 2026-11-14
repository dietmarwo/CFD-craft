# Install OpenFOAM and run a cavity

<!-- check: openfoam -->
<!-- check: timeout=900 -->

This chapter installs the pinned OpenFOAM Foundation 13 runtime without root, then generates, runs and checks one laminar cavity through CFD-craft's bounded OpenFOAM adapter, from the command line and from Python. You need Ubuntu 24.04 on x86_64, a checkout, Python 3.10 or newer, Rust 1.88 or newer and `dpkg-deb`.

No output is shown on the OpenFOAM pages: the documentation check runs them only in the opt-in CI job that installs the runtime, and the outputs of this host would be invented. Recorded numbers are quoted from the evidence pages, with their date.

## Setup

Run all commands from the root of a checkout:

```sh
cargo build --release --locked
python -m pip install -r requirements-validation.txt
```

```bash
mkdir -p runs
```

The pages of this part write the runtime root as `runs/openfoam13/runtime/opt/openfoam13`, the directory the installer below produces.

## What the backend is and is not

The adapter supports two generated cases on OpenFOAM Foundation 13: a laminar Re = 100 lid-driven cavity and a turbulent backward-facing step (the Driver and Seegmiller experiment) with the k-omega SST model. It is a bounded workbench for numerical cross-checks and for comparison with measurements.

It is not a translator: a native CFD-craft case (for example a street canyon) cannot be run in OpenFOAM, OpenFOAM runs no scalar dispersion here, and there is no fcmaes worker for it. The native solver and its worker are unchanged by it.

OpenFOAM is licensed under the GNU GPL, version 3 or later. CFD-craft runs its programs (`blockMesh`, `checkMesh`, `foamRun`, field post-processing) as separate, bounded processes and neither links nor imports them; no OpenFOAM source, library or executable is part of the repository. The generated dictionaries and the Python adapter are CFD-craft code. A velocity comparison on these cases cannot qualify the native canyon's concentrations. The [OpenFOAM backend model card](../model-cards/openfoam-backend.md) states the supported scope.

## Install the pinned runtime

```sh
python integrations/install_openfoam13.py --output runs/openfoam13
```

The installer downloads one pinned Ubuntu package (118,586,852 bytes), checks its size and SHA-256 and extracts it with `dpkg-deb` into a new directory. It installs no system packages and needs no root. OpenFOAM's serial Pstream library is used, so MPI is not needed. `--package-file PATH` reuses a local copy of the same package; its size and hash are still checked.

The tested build is package `20260407` (build `13-441953dfbb42`, double precision, 32-bit labels). The adapter checks the executable's own version and records the hashes of the executables and solver libraries: another Foundation major version or an OpenCFD fork is rejected, and another build of Foundation 13 is identified by its hashes and needs its own review. An existing Foundation 13 installation can be given as the runtime root instead. The CI jobs that run these pages install the runtime in a step of their own.

## Generate, run and inspect

<!-- check: timeout=2700 -->

```bash
python integrations/openfoam_backend.py prepare --case cavity --level 1 \
  --iterations 3000 --output runs/foam-cavity-input
python integrations/openfoam_backend.py run --case runs/foam-cavity-input \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 \
  --timeout-s 180 --output runs/foam-cavity
python integrations/openfoam_backend.py report runs/foam-cavity
```

`prepare` writes the generated case: dictionaries, mesh description and its own `case.json` record. Level 1 is a 24 x 24 cavity, levels 2 and 3 are 48 x 48 and 72 x 72. `run` copies the input into the new archive, checks the copy against the sealed identities and runs mesh generation, the mesh check, the solver and post-processing as separate processes, each under a shared deadline (`--timeout-s`), an output budget (`--output-mib`, default 256) and an address-space limit (`--memory-mib`, default 2048). `report` reads the archive back and checks it.

A convergence message in the log is not enough. The adapter also requires final residuals, continuity and stored-field checks, and it records the runtime, dictionary, mesh, log and output identities. Each output directory must be new and its parent must exist. If the generator changes, prepare a new case. Execution is shell-free, single-process and serial.

## Exit codes of the adapter

| Command | 0 | 2 | 1 |
|---|---|---|---|
| `prepare`, `prepare-mapped`, `prepare-restart` | prepared | – | invalid request or ineligible source |
| `run` | accepted numerical evidence | completed, timed out or canceled without it | the execution itself failed (runtime, input, I/O) |
| `report` | as `run` for the archived result | as `run` | failed execution, or an archive that fails verification |
| `validation/compare_backstep.py` | numerical gate and development screen pass | either fails | output cannot be written |
| `tutorials/external_cfd.py`, `tutorials/backstep_resolution.py` | everything passes | failed, unaccepted or canceled evidence recorded | workflow error |
| `validation/audit_openfoam_mesh.py` | checks pass | checks fail, or no final field | invalid archive or output path |
| `validation/compare_restart.py`, `validation/restart_equivalence.py` | bounds hold | bounds do not hold | invalid input |

In the resolution tutorial of [chapter 18](18-backstep-resolution.md) a completed stage that cannot seed the next stage is recorded evidence (exit 2), not a workflow error. **No exit code sets physical qualification to true.** Read all four levels separately: execution, numerics, measurement screen and physical qualification.

## The external archive

The result of `run` is an archive of schema `cfd-craft.external-run/0.1`. It is not a native run archive and not an optimization result: the native `cfd-craft report` does not read it; use the adapter's `report`.

The archive has a checksummed manifest and a completion marker, written also when the run fails. Completion means the evidence has been written. `passed` additionally requires numerical acceptance and valid final samples. Child failure, cancellation and timeout stay distinct. The command record keeps the real return code and log; the progress record lists the iterations started and the snapshots saved, which may precede a partial last iteration. A symbolic link left by a child marks the run failed.

`report` checks consistency: file hashes, the consumed inputs, that the case holds nothing but solver outputs, the numerical summary recomputed from the returned log and fields, status and error codes, return codes, the runtime and log identity, progress and samples. Unkeyed hashes are not tamper evidence: a consistent rewrite of log, fields and summary cannot be detected this way.

## Use the adapter from Python

```bash
python examples/manual/openfoam_api.py \
  --foam-root runs/openfoam13/runtime/opt/openfoam13 --output runs/manual-foam
```

[`examples/manual/openfoam_api.py`](https://github.com/dietmarwo/CFD-craft/blob/main/examples/manual/openfoam_api.py) imports `openfoam_backend` from the checkout's `integrations/` directory and calls `prepare`, `run` and `verify` on a level-1 cavity with 3,000 iterations, a 180 s deadline and 64 MiB of output. It writes `runs/manual-foam/report.json` with `passed`, `archive_consistent` and `physical_qualification` (always false). An intact archive can still hold an unaccepted solve, so the script checks `numerical.passed` of the verified archive explicitly. The adapter is a source-checkout module: it is not part of the installed `cfd_craft` Python package, and its results are not native result schemas.

## Trusted inputs only

The backend executes only dictionaries it generated, in a copied fresh directory. Input hashes detect changes; they are not a signature that authorizes untrusted OpenFOAM code, and OpenFOAM itself can load user code, so do not substitute unreviewed case directories.

Each child process gets a fixed environment (the runtime paths, single-threaded BLAS and OpenMP, `HOME=/nonexistent`, nothing inherited from the caller's OpenFOAM settings), a hard address-space limit and a per-file size limit. The output budget and the wall time are polled every 50 ms, so a small overshoot is possible. SIGTERM, SIGINT and the deadline terminate the process group, with a forced kill after one second if needed; the log and the failure archive are kept. A NaN or infinite residual, or a mean continuity error of at least 1 (in units of the reference velocity over the step height), stops the process group with `CFD-X010`, also when the child exits 0. Earlier saved snapshots are never promoted to final solutions. The [model card's execution limits](../model-cards/openfoam-backend.md#execution-limits) give the details.

## Tests without a runtime

The contract tests use synthetic fixtures, including a stand-in for the four Foundation 13 programs that drives `run` and `report` end to end. They test contracts, not physical accuracy, and need no runtime:

```sh
python validation/test_openfoam.py -v
python -O validation/test_openfoam.py -v
python validation/test_resolution.py -v
python validation/test_restart.py -v
python validation/test_mapping.py -v
```

With `CFD_OPENFOAM_ROOT` set, the same files add tests with real solves: cavity runs, an iteration-limit failure, corrupted fields and face fluxes that must be rejected, the wall-resolved `blockMesh` output against the generated first-cell heights, continued runs against uninterrupted controls, and mapped fields at the next level:

```sh
CFD_OPENFOAM_ROOT="$PWD/runs/openfoam13/runtime/opt/openfoam13" \
  python validation/test_openfoam.py -v
CFD_OPENFOAM_ROOT="$PWD/runs/openfoam13/runtime/opt/openfoam13" \
  python validation/test_resolution.py -v
CFD_OPENFOAM_ROOT="$PWD/runs/openfoam13/runtime/opt/openfoam13" \
  python validation/test_restart.py -v
CFD_OPENFOAM_ROOT="$PWD/runs/openfoam13/runtime/opt/openfoam13" \
  python validation/test_mapping.py -v
```

The CI job `external-contracts` runs the contract tests normally and under `-O`, together with `validation/test_refinement.py` ([chapter 19](19-refinement-campaign.md)); the runtime tests run in the opt-in `external-backend` job.

## Next

- [Chapter 16](16-compare-solvers.md): compare the cavity with the native solver and the backstep with measurements.
- [Chapter 17](17-continuation-and-mapping.md): continue this cavity on the same mesh or start a finer one from it.
