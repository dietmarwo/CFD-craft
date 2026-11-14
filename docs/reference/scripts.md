# Scripts

The Python tools a user calls. Each runs from the root of a checkout as
`python PATH`. This list comes from their argument parsers and exit statements.
Several write files: give each a new `--output`, and read the source of a script
before running it with other arguments.

## Setup

Native scripts need the release binary (`cargo build --release -p cfd-craft-cli`).
The scripts find it at `target/release/cfd-craft`; `--binary` overrides that.
OpenFOAM scripts need `--foam-root`, the Foundation 13 runtime that
[`integrations/install_openfoam13.py`](https://github.com/dietmarwo/CFD-craft/blob/main/integrations/install_openfoam13.py)
stages.

## Exit codes

A script exits 0 when its checks passed and 1 when they did not or its input was
invalid, unless the table says otherwise. Exit 2 means the work completed without
accepted evidence (the convention of the native CLI). Failures carry a code from
[diagnostics](../diagnostics.md). No exit code sets physical qualification.

## Inspect and export a run

| Script | Arguments | Result |
|---|---|---|
| `validation/export_vtk.py` | `--run DIR --output FILE.vtr [--max-mib 64]` | ParaView rectilinear file from a verified archive with fields. Exits 1 if `FILE` exists or the archive fails the field checks |
| `validation/check_profile.py` | `DIR` | Checks a `cfd-craft profile` directory against its archive; prints the findings |
| `validation/profile_case.py` | `--binary PATH --case CASE --output DIR` | Child-process resource use (KiB, Linux) of one command |

```bash
cfd-craft run cases/verification/periodic-tracer.json --output runs/a > /dev/null
python validation/export_vtk.py --run runs/a --output runs/a.vtr | python -c "import json,sys; print(json.load(sys.stdin)['cells'])"
```

```text
3456
```

## Verification and acceptance

| Script | Arguments | Result |
|---|---|---|
| `validation/run_suite.py` | `--output DIR [--binary PATH] [--preset smoke\|study] [--pressure-preconditioner ic0\|multigrid] [--abl-numerics JSON] [--abl-steady]` | Analytic cases against frozen targets, with a report under `--output` |
| `validation/cavity.py` | `--output DIR [--binary PATH]` | Lid-driven cavity against the Ghia reference; a numerical benchmark, not urban validation |
| `validation/manual_examples.py` | `--output DIR [--binary PATH] [--example-dir DIR] [--foam-root ROOT]` | Runs the native examples; with `--foam-root` also the OpenFOAM ones |
| `validation/check_installed.py` | `--output FILE [--binary PATH]` | Installed-wheel acceptance; run it with `python -I` outside the checkout |

## Measurement

| Script | Arguments | Result |
|---|---|---|
| `validation/benchmark_native.py` | `--baseline PATH --candidate PATH --case CASE --mode setup\|pressure\|momentum\|production\|transport\|steps --output DIR [--rounds 5] [--inner 4] [--steps 8] [--threads 1] [--timeout-s 180]` | Alternating paired probes of two binaries at fixed work |
| `validation/compare_backends.py` | `--foam-root ROOT --output DIR [--binary PATH] [--repeats 1] [--timeout-s 180] [--grid-sweep ...]` | Same-host cavity timing, native against OpenFOAM. Exit 2 in sweep mode when the workflow is valid but a gate failed |

`--grid-sweep` adds `--levels`, `--grids`, `--sweep-rounds`, `--accuracy-target`,
`--native-wall-s`, `--native-max-steps`, `--native-pressure-preconditioner`,
`--native-numerics`, `--native-span` and `--foam-iterations`; read
`validation/compare_backends.py` for their defaults.

## Tutorials

| Script | Arguments | Result |
|---|---|---|
| `tutorials/canyon_study.py` | `--output DIR [--binary PATH] [--preset smoke\|sensitivity\|study]` | Canyon wind, grid, domain and Schmidt sensitivity; failed rows are kept |
| `tutorials/source_inference.py` | `--output DIR [--binary PATH] [--preset smoke\|study]` | Three-source inverse problem with held-out sensors |
| `tutorials/external_cfd.py` | `--foam-root ROOT --output DIR [--binary PATH] [--data PATH] [--preset cavity\|smoke\|study] [--timeout-s 600]` | Both backends and a measurement comparison. Exit 2 for recorded unaccepted evidence, 1 for a workflow error |
| `tutorials/backstep_resolution.py` | `--foam-root ROOT --output DIR [--data PATH] [--preset smoke\|controls\|study] [--timeout-s 900] [--iterations 6000] [--max-stages 1]` | Convergence and mesh-resolution study. Exit codes as above |

## OpenFOAM backend

`python integrations/openfoam_backend.py COMMAND`:

| Command | Arguments | Exit |
|---|---|---|
| `prepare` | `--case cavity\|backstep --output DIR [--level 1] [--cavity-grid N] [--iterations 3000] [--data PATH] [--mesh-family legacy\|wall-resolved] [--solver-profile legacy\|simplec\|simple]` | 0, or 1 for an invalid request |
| `prepare-restart` | `--source DIR --output DIR [--iterations 6000]` | 0, or 1 for an ineligible source |
| `prepare-mapped` | `--source DIR --level N --output DIR --foam-root ROOT [--iterations 6000] [--data PATH] [--timeout-s 300] [--output-mib 512] [--memory-mib 2048]` | as `prepare-restart` |
| `run` | `--case CASE --output DIR --foam-root ROOT [--timeout-s 600] [--output-mib 256] [--memory-mib 2048]` | 0 accepted; 2 completed, timed out or cancelled without accepted evidence; 1 execution failed |
| `report` | `DIR` | as `run` for the archived result; 1 if verification fails |

| Script | Arguments | Result |
|---|---|---|
| `integrations/install_openfoam13.py` | `--output DIR [--package-file DEB]` | Stages the pinned package without root; 1 on failure |
| `integrations/run_jobs.py` | `--runner PATH --output DIR [--binary PATH] [--worker PATH]` | Runs a CFD command and scalar application profiles on a foreground node |

## Release tools

| Script | Arguments | Result |
|---|---|---|
| `scripts/package_version.py` | none | Prints the release version; fails when the three version sources disagree |
| `scripts/check_release.py` | none | Checks crate metadata, licenses and lockfiles before packaging |
| `scripts/generate_reference.py` | `[--binary PATH] [--check]` | Writes the generated pages of this section; `--check` writes nothing and fails when one differs |
| `scripts/generate_cases.py` | none | Rewrites the committed cases under `cases/`; do not run it casually |
