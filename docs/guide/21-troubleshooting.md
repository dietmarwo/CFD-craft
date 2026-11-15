# Troubleshooting

This chapter leads from a symptom to a diagnostic code and an action, and
reproduces the five most common failures. You need the `cfd-craft` command and
a checkout ([chapter 3](03-cli-and-archive.md)).

## Setup

Commands run from the root of a checkout with `cfd-craft` on `PATH`. The setup
writes three broken copies of `examples/manual/point-source.json`: one with an
unknown field, one whose steady source has no outlet, and one with a budget of
five steps.

```bash
mkdir -p runs
```

```python
import json


def variant(name, change):
    case = json.load(open("examples/manual/point-source.json"))
    change(case)
    json.dump(case, open(f"runs/{name}.json", "w"), indent=2)


variant(
    "unknown-field",
    lambda c: c["sources"][0].update(position_m=c["sources"][0].pop("point_m")),
)
variant("no-outlet", lambda c: c["boundaries"].update(x="periodic"))
variant("five-steps", lambda c: c["run"].update(max_steps=5))
```

Outputs on this page are real. They contain no floating-point numbers, so the
documentation check requires an exact match.

## Where the message is

- **Exit 1 with JSON on stdout.** `check`, `run`, `profile` and `preview`
  print the check report for an invalid case. Read `check.diagnostics`: each
  entry has a `code`, a `severity`, the `path` of the field and a `message`.
- **Exit 1 with `{"error": "CFD-..."}` on stderr.** An I/O problem, a rejected
  archive or a rejected restart. Nothing was solved.
- **Exit 2.** The run ended and wrote its archive, without numerical
  acceptance or without all files. Read `termination`, `assessment` and `error`
  in `summary.json`, and `omitted` in `manifest.json`.
- **Exit 0** means a valid case, an accepted run with all files, or an intact
  archive. For `report` it does not mean the run converged.

## By symptom

| Symptom | Look at | Action |
|---|---|---|
| Unknown field or variant | `CFD-E000` and its path | Correct the name; nothing is ignored. [Chapter 2](02-case-file.md#a-wrong-field-is-an-error) |
| Memory or output estimate too large | `CFD-E006`, `CFD-E007`, `CFD-E070` | Reduce the case or use a larger budget or host. [Chapter 7](07-budgets-preview-cancel.md#what-check-estimates) |
| `check` skipped the grid checks | `CFD-W070` | Check again on a host that can hold the case. [Chapter 7](07-budgets-preview-cancel.md#what-check-estimates) |
| Source or receptor in a solid cell | `CFD-E040`, `CFD-E042` | Move it into the fluid or resolve the gap; nothing is moved for you. [Chapter 5](05-sources-receptors-transport.md#point-and-volume-receptors) |
| Steady source without a way out | `CFD-E020`, `CFD-E043` | Give the region an open boundary, or run transient. [Chapter 5](05-sources-receptors-transport.md#a-steady-source-needs-a-way-out) |
| Output exists or parent is missing | `CFD-E062`, `CFD-E063` | Use a new directory inside an existing one. [Chapter 3](03-cli-and-archive.md#exit-codes) |
| A run exits 2 | `termination`, `assessment`, `omitted` | Keep the archive; tell a budget from a failed check from omitted files. [Chapter 4](04-reading-a-result.md#an-incomplete-run-is-still-a-result) |
| `report` rejects an archive | `CFD-E064` | Keep the archive as it is; do not rewrite its hashes. [Chapter 3](03-cli-and-archive.md#the-files-of-a-run) |
| Restart rejected | `CFD-E060`, `CFD-E065`, `CFD-E066` | Compare physics, checksum, memory budget and the new horizon. [Chapter 8](08-checkpoint-restart.md#what-a-checkpoint-fits) |
| Preview refused | `CFD-E072`, `CFD-E073`, `CFD-E040`, `CFD-E042` | The coarse geometry differs; use a smaller factor or the full grid. [Chapter 7](07-budgets-preview-cancel.md#when-a-preview-is-refused) |
| Pressure iteration limit | `CFD-E033` in `error` | Look at resolution and conditioning; the saved earlier state is not a converged result. [Chapter 6](06-flow-cavity.md#what-the-pressure-step-does) |
| Turbulence floors or very large eddy viscosity | `turbulent_floor_events`, `CFD-E054` | A numerical failure of this regime, not something to clip away. [Chapter 10](10-street-canyon.md#the-result) |
| OpenFOAM timeout or invalid mesh | `CFD-X004`, `CFD-X006` and the logs | An earlier snapshot is not a final solution. [Chapter 15](15-openfoam-first-run.md#trusted-inputs-only) |
| An example script fails | `CFD-U001 manual.<field>` and the saved logs | Build the examples and check the paths. [Chapter 11](11-python.md#the-whole-native-workflow-in-one-script) |
| A building footprint is rejected | `CFD-E084` at `geometry[i].footprint_m` | Remove crossing edges, holes and a repeated last vertex; make `min_m` and `max_m` the bounds of the polygon. [Chapter 22](22-urban-geometry-particles-vegetation.md#a-building-with-a-polygon-footprint) |
| A building or a street is too small for the grid | `CFD-E028`, `CFD-W011` | Refine the grid or drop the shape yourself; read `shapes` in `geometry.json`. [Chapter 22](22-urban-geometry-particles-vegetation.md#a-building-with-a-polygon-footprint) |
| Building roughness is rejected | `CFD-E085` | Use a positive value with `neutral_rans` flow. [Chapter 22](22-urban-geometry-particles-vegetation.md#a-building-with-a-polygon-footprint) |
| Multigrid is slower than the default | `CFD-W004` | With buildings and strongly unequal cell widths keep `ic0`. [Chapter 22](22-urban-geometry-particles-vegetation.md#multigrid-with-buildings) |
| The map converter stops | `CFD-M001 map` and `check.json` in the output | Reproject to meters, check heights and holes, or give a `--template` with larger budgets. [Chapter 22](22-urban-geometry-particles-vegetation.md#import-buildings-from-a-map) |
| A particle bin is rejected | `CFD-E080`, `CFD-E081` | Keep diameter, density and speeds in range; above a particle Reynolds number of 0.1 give `settling_velocity_m_s`. [Chapter 22](22-urban-geometry-particles-vegetation.md#particle-size-classes) |
| A vegetation volume is rejected or has no effect | `CFD-E082`, `CFD-E083`; `volume_fluid_cells` of 0 | Fix the box or the range; use drag 0 with prescribed flow; make the volume contain a fluid cell center. [Chapter 22](22-urban-geometry-particles-vegetation.md#hedges-and-trees) |
| A wind-direction campaign exits 2 | `accepted` and `error` of each row in `report.json` | A timeout is an incomplete run; raise the budgets or coarsen the case. [Chapter 22](22-urban-geometry-particles-vegetation.md#one-case-twelve-wind-directions) |
| A path receptor is rejected | `CFD-E086`, `CFD-E087`, `CFD-E088` | Keep the route inside the domain and out of buildings; use fewer samples. [Chapter 23](23-mobile-paths-and-virtual-rides.md#declare-a-path-receptor) |
| The ride tool refuses a run | `CFD-M004 virtual_ride` | Give it an accepted steady run, an existing path and a new output file. [Chapter 23](23-mobile-paths-and-virtual-rides.md#simulate-a-ride) |
| The street converter stops | `CFD-M002` and `diagnostic.json` in the output | Supply rates in `kg/s/m`; a street that touches a building is rejected, not moved. [Chapter 24](24-mobile-source-inference.md#street-emissions-from-map-data) |
| A frozen-flow response or the study is rejected | `CFD-E089`, `CFD-M003 mobile_inference` | Use steady `linear_upwind` transport without initial concentration on an accepted flow. [Chapter 24](24-mobile-source-inference.md#one-flow-one-transport-run-per-street) |

## Reproduce the common ones

```bash
codes() { grep -o "CFD-[A-Z][0-9]*" "$1" | sort -u | tr "\n" " "; echo; }
cfd-craft check runs/unknown-field.json > runs/1.out || echo "unknown field: exit $?"
codes runs/1.out
cfd-craft check runs/no-outlet.json > runs/2.out || echo "no outlet: exit $?"
codes runs/2.out
cfd-craft run examples/manual/point-source.json --output runs/point > /dev/null
cfd-craft run examples/manual/point-source.json --output runs/point 2> runs/3.err || echo "occupied output: exit $?"
codes runs/3.err
cfd-craft run examples/manual/point-source.json --output absent/point 2> runs/4.err || echo "missing parent: exit $?"
codes runs/4.err
cfd-craft run runs/five-steps.json --output runs/five-steps > runs/5.out || echo "five steps: exit $?"
python -c "import json; s = json.load(open('runs/5.out')); print(s['termination'], s['assessment'])"
```

```text
unknown field: exit 1
CFD-E000
no outlet: exit 1
CFD-E020
occupied output: exit 1
CFD-E062
missing parent: exit 1
CFD-E063
five steps: exit 2
iteration_limit incomplete
```

The first four fail before any work is done and write nothing. The fifth is
not an error of the program: the run stopped at its budget, exits 2 and leaves
a complete archive in `runs/five-steps`.

## What to attach to a report

Report problems at
[github.com/dietmarwo/CFD-craft/issues](https://github.com/dietmarwo/CFD-craft/issues)
with:

- the exact command and its exit code;
- stdout and stderr of the command;
- for an invalid case, the case file;
- for a run, `case.json`, `summary.json` and `manifest.json` from the run
  directory. They hold the consumed case, the stopping reason and the checks,
  and the version, compiler and hashes of the build. Do not attach
  `fields.json` unless asked; it is large.

## All codes

Every code with its meaning is in the [diagnostics catalog](../diagnostics.md).
The native solver, the Python package, the OpenFOAM adapter and the scripts use
separate code families, so a code also tells you which part reported it.

## Next

- [Diagnostics](../diagnostics.md) and the [result contract](../result-contract.md).
- [Chapter 22](22-urban-geometry-particles-vegetation.md): Part VI, city blocks and mobile measurements.
- [Guide index](README.md): all chapters.
