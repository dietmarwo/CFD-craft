# Command line reference

One section per command of the `cfd-craft` binary. The usage list and the exit
codes are generated from the binary by `scripts/generate_reference.py`; the rest
is written by hand and checked against the source of the command line.

## Setup

Commands run from the root of a checkout with `target/release` on `PATH`.
Fields of a case are in the [case schema](case-schema.md), files of a run in the
[result contract](../result-contract.md), codes in [diagnostics](../diagnostics.md).

## Usage

<!-- begin generated: usage -->
- `cfd-craft describe`
- `cfd-craft check CASE`
- `cfd-craft run CASE --output NEW_DIR [--restart CHECKPOINT]`
- `cfd-craft profile CASE --output NEW_DIR [--restart CHECKPOINT]`
- `cfd-craft preview CASE --output NEW_DIR [--factor N]`
- `cfd-craft report DIR`
- `cfd-craft verify CASE`
<!-- end generated: usage -->

`help` and `--help` print this text as `{"usage": ...}`. `--output`, `--restart`
and `--factor` take one value each and may appear once; anything else is an
unknown or duplicate option. The thread count, budgets and wall-time limit are
case fields (`run.*`), not options.

## Exit codes

<!-- begin generated: exit-codes -->
| Exit | Meaning |
|---|---|
| 0 | success: valid case, passed numerical assessment or verified archive |
| 1 | invalid input or an execution/I/O error; check reports are printed on stdout |
| 2 | completed execution with incomplete or failed numerical evidence |
<!-- end generated: exit-codes -->

Errors that are not check reports go to stderr as `{"error": "..."}` with exit
1, as does a missing case or directory argument. Exit 0 from `report` does not
mean the run converged: read `termination` and `assessment`.

## describe

Prints the build and schema description as JSON. No options. Fields include
`case_schema`, `result_schema`, `phase_profile_schema`, `exit_codes`, the names
and defaults of the physics and numerics, `coordinates`, `pressure_units`,
`experimental_validation` and `limitations`.

## check

`check CASE` parses and checks a case without solving. Stdout is
`{"check": REPORT, "geometry": EVIDENCE}`: `valid`, `diagnostics` (code,
severity, path, message), the estimated memory and the cell count. `geometry`
is present when the grid could be built. Exit 0 when valid, 1 when not;
warnings do not invalidate.

```bash
python -c "import json; c=json.load(open('cases/verification/periodic-tracer.json')); c['name']=''; json.dump(c, open('bad.json', 'w'))"
cfd-craft check bad.json > bad.out || echo "exit $?"
python -c "import json; d=json.load(open('bad.out'))['check']['diagnostics'][0]; print(d['code'], d['path'])"
```

```text
exit 1
CFD-E002 name
```

## run

`run CASE --output NEW_DIR [--restart CHECKPOINT]` checks the case, solves it
and writes a native archive. `NEW_DIR` must not exist and its parent must
(CFD-E062, CFD-E063). An invalid case, or an estimated peak above 80 percent of
the available memory (CFD-E070), prints the check report and exits 1 before
anything is created. Stdout is the `summary.json` content. Exit 0 when
`assessment` is `steady_discrete_solution` or `transient_interval_completed`
and nothing was omitted; exit 2 otherwise, including artifacts omitted over the
output budget (CFD-E061 on stderr). SIGINT and SIGTERM stop the run: it ends
`cancelled` and `incomplete`, writes its archive and exits 2. `--restart`
continues from a `checkpoint.json` with the same physics (CFD-E050, E060, E065,
E066); the case sets the new endpoint.

```bash
cfd-craft run cases/verification/periodic-tracer.json --output runs/a > runs/a.json; echo "exit $?"
cfd-craft run cases/verification/periodic-tracer.json --output runs/a > /dev/null 2>&1 || echo "exit $?"
python -c "import json; s=json.load(open('runs/a.json')); print(s['termination'], s['assessment'])"
```

```text
exit 0
exit 1
completed transient_interval_completed
```

## profile

`profile CASE --output NEW_DIR [--restart CHECKPOINT]` runs like `run` and times
the solver phases. `NEW_DIR` holds `profile.json` and the ordinary archive in
`run/`. Stdout is the profile envelope `cfd-craft.native-profile/0.1`: `passed`,
`error`, the identities, `summary` and `timing` (the Profile table of the
[result schema](result-schema.md)). `physical_qualification` is always false.
Exit codes are those of `run`; if the solve fails, `profile.json` is still
written with `passed` false and the exit is 1.

## preview

`preview CASE --output NEW_DIR [--factor N]` runs the case on a coarser grid.
Each axis keeps `cells / N` cells, at least 2; an axis of one cell stays at one.
`N` is an integer of at least 2 (default 2). The name gets the suffix
`-preview` and `model_scope` starts with `preview:`. With geometry, a preview is
rejected when coarsening changes the solid volume by more than 20 percent or the
fluid components (CFD-E072), or when the original mask cannot be counted
(CFD-E073). Output and exit codes are those of `run`.

## report

`report DIR` verifies a native archive (manifest, file hashes, completion marker,
no unlisted entries) and prints its `summary.json`. Exit 0 for an intact archive
whatever its assessment; 1 with CFD-E064 when verification fails. Omitted
artifacts exit 0 and repeat CFD-E061 as a warning on stderr. It reads native
archives only, not OpenFOAM ones.

```bash
cfd-craft run cases/verification/periodic-tracer.json --output runs/a > /dev/null
cfd-craft report runs/a | python -c "import json,sys; print(json.load(sys.stdin)['assessment'])"
```

```text
transient_interval_completed
```

## verify

`verify CASE` runs the pressure fixture on the grid of the case and prints
`fixture`, `passed`, `iterations`, residual and error. Exit 0 when `passed`, 2
when not, 1 for an invalid case. It tests the pressure solver, not an archive.
