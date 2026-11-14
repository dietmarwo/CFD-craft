# The command line and the run archive
<!-- check: rel=1e-4 -->

At the end of this chapter you have the fields of a run on disk, know every
file of a run directory, and have checked and viewed the fields. You need the
`cfd-craft` command and, for the last two sections, a checkout of the
repository with its Python requirements.

## Setup

The command is built from source with Rust 1.88 or newer. There is no prebuilt
binary. Either install the released command:

```sh
cargo install cfd-craft-cli --locked
```

or build it in a checkout and put it on `PATH`:

```sh
git clone https://github.com/dietmarwo/CFD-craft.git
cd CFD-craft
cargo build --release --workspace --locked
export PATH="$PWD/target/release:$PATH"
```

From here on, the guide runs every command from the root of a checkout,
because the cases and the Python tools live there. The tools of the last two
sections need NumPy and a few other packages:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-validation.txt
```

Run outputs go to `runs/`, which Git ignores. `describe` prints the schemas,
the exit codes and the build identity of the command as JSON:

```bash
mkdir -p runs
cfd-craft describe > runs/describe.json
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## Check, run, report

The case is the point source of [chapter 1](01-first-run.md), which is
committed as `examples/manual/point-source.json`.

```bash
cfd-craft check examples/manual/point-source.json
cfd-craft run examples/manual/point-source.json --output runs/point
cfd-craft report runs/point
```

Each command prints JSON. `check` prints the check report and the geometry
counts. `run` solves the case, writes the directory `runs/point` and prints
the summary. `report` verifies that directory against its checksums and prints
the summary again. The summary is also the file `summary.json`:

```python
import json

s = json.load(open("runs/point/summary.json"))
print(s["termination"], s["assessment"])
tracer = next(c for c in s["constituents"] if c["id"] == "tracer")
print(f'R_down = {tracer["receptors_kg_m3"]["R_down"] * 1e9:.6g} micrograms/m3')
```

```text
completed steady_discrete_solution
R_down = 17.8118 micrograms/m3
```

This is the value the Python binding returned in chapter 1. Both call the same
solver.

The output directory must be new, and its parent must exist. A run never
writes into an existing directory, not even after a failed run. To repeat a
run, choose a new name or delete the old directory yourself.

## Exit codes

| Outcome | Exit |
|---|---:|
| A valid case (`check`), a numerically accepted run with all its files (`run`), an intact archive (`report`), a passed fixture (`verify`) | 0 |
| Invalid input, or an execution or I/O error. A check report is on stdout; other errors are on stderr as `{"error": "..."}` | 1 |
| A run that ended without numerical acceptance, or an accepted run that had to omit files over its output budget; a failed `verify` fixture | 2 |

Two errors every user meets once are an existing output directory and a
missing parent directory:

```bash
cfd-craft run examples/manual/point-source.json --output runs/point > /dev/null
echo "first run: exit $?"
cfd-craft run examples/manual/point-source.json --output runs/point \
  2> runs/second.err || echo "second run: exit $?"
grep -o "CFD-E[0-9]*" runs/second.err
cfd-craft run examples/manual/point-source.json --output missing/point \
  2> runs/third.err || echo "missing parent: exit $?"
grep -o "CFD-E[0-9]*" runs/third.err
```

```text
first run: exit 0
second run: exit 1
CFD-E062
missing parent: exit 1
CFD-E063
```

Both are found before the solve starts. Exit 2 is shown in
[chapter 4](04-reading-a-result.md).

`report` exits 0 for every intact archive, also for one whose run was stopped
early. Never use the exit code of `report` as a convergence test. Read
`termination` and `assessment`.

## The files of a run

```bash
cfd-craft run examples/manual/point-source.json --output runs/point > /dev/null
ls runs/point
```

```text
case.json
checkpoint.json
complete.json
fields.json
geometry.json
manifest.json
probes.csv
summary.json
```

| File | What to read in it |
|---|---|
| `case.json` | The case as the solver used it, with omitted lists written out |
| `summary.json` | Why the run stopped, the checks, the work done, receptor values, model scope |
| `geometry.json` | Fluid and solid cell counts, solid volume, cells per box, connected fluid regions, a hash of the cell mask |
| `probes.csv` | The final receptor values in kg/m3, one line per constituent and receptor |
| `fields.json` | The final state: concentrations, pressure, face velocities, mass budgets. Written when `output.fields` is true |
| `checkpoint.json` | A checksummed state for restart ([chapter 8](08-checkpoint-restart.md)). Written when `output.checkpoint` is true |
| `manifest.json` | A hash of every file above, omitted files with the reason, and the identity of the input file, the source code, the executable and the initial state |
| `complete.json` | The hash of the manifest. It is written last |

`complete.json` marks an archive whose files are all written. It says nothing
about convergence: an incomplete run also has one. The hashes detect damage and
mix-ups. They are not signatures, so they do not prove who made an archive.

Keep notes, plots and logs beside a run directory, not inside it. `report`
rejects an archive that contains a file the manifest does not list. The
[result contract](../result-contract.md) has the details.

## Check the fields independently

`check_fields.py` is a second implementation, in Python with NumPy, that reads
the archived fields and recomputes what the solver claimed.

```bash
cfd-craft run examples/manual/point-source.json --output runs/point > /dev/null
python validation/check_fields.py runs/point > runs/point-audit.json
```

```python
import json

audit = json.load(open("runs/point-audit.json"))
print(audit["passed"], [scalar["id"] for scalar in audit["scalars"]])
```

```text
True ['tracer']
```

It recomputes the velocity divergence of every cell, the mass of each
constituent, the emitted mass from source rate and time, the recorded mass
budget, the receptor values and the cell mask, and it requires finite fields.
It does not rebuild the history of fluxes over all time steps, and it does not
test the turbulence model. It is a numerical cross-check of one archive, not a
validation against measurements.

## Look at the fields in ParaView

```bash
cfd-craft run examples/manual/point-source.json --output runs/point > /dev/null
python validation/export_vtk.py --run runs/point --output runs/point.vtr
```

Open `runs/point.vtr` in ParaView. It is a rectilinear grid with cell data.
Threshold by `fluid_mask` before you look at a case with buildings, so solid
cells do not enter color scales or averages. The exported velocity is a cell
value reconstructed from the faces. The solver's own face velocities, which
satisfy continuity, are in `fields.json`. The exporter needs a run with fields
and refuses to overwrite an existing file.

## Next

- [Chapter 4](04-reading-a-result.md): what `termination`, `assessment` and the
  validation label mean, on an accepted, an incomplete and a transient run.
- [Command line reference](../reference/cli.md): every command and option.
