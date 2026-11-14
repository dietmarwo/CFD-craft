# The documentation check

`scripts/check_docs.py` runs the code blocks of the documentation and compares
their outputs. Without arguments it checks the default set: the root README,
the package READMEs, `examples/manual/README.md` and every page under `docs/`
except stubs, `SUMMARY.md`, the generated reference pages and the records in
`docs/history/`. Each page is one session in a new temporary directory, never
inside the checkout.

## Run the documentation check

From the root of a checkout, with the Python binding of the checkout installed
(`maturin build --release --locked --out dist`, then `pip install dist/*.whl`):

```sh
cargo build --release --workspace --locked
cargo build --release --workspace --examples --locked
python -m pip install -r requirements-validation.txt
python -m pip install fcmaes-rust==0.2.1 lp-ip-craft==0.29.0
python scripts/check_docs.py --smoke > runs/docs-check.json
python scripts/check_docs.py docs/guide/03-cli-and-archive.md
```

`--smoke` does not execute pages and sections marked `long`; their blocks are
still parsed, their script paths must exist and their JSON cases still pass
`cfd-craft check`. Without `--smoke` (full mode) everything runs except the
OpenFOAM and jobs sections. On a 2-core host the default set takes about
2.5 minutes in smoke mode and 3.5 minutes in full mode. The report on standard
output lists, per page, the blocks run, the `text` blocks compared, the `json`
blocks validated, the blocks not run and every unchecked block with its
reason. A failure is printed as `CFD-R003 docs.<field>: PAGE:LINE: message`
([diagnostics](../diagnostics.md)), and the exit code is 1.

## Fences

| Fence | What the check does |
|---|---|
| `python` | Runs it; the blocks of one level-2 section share one interpreter. |
| `bash` | Runs it with `bash -euo pipefail`; each block is its own shell. |
| `text` | The exact output of the runnable block directly before it. |
| `json` | Strict JSON; a case (`cfd-craft.case/…`) must pass `cfd-craft check`. |
| `sh` | `bash -n` only; a `python PATH.py` it names must exist. For installs, builds, placeholders and long or external commands. |
| `toml` | Parsed. |
| `rust` | Every non-comment line must occur, in order, in the file named by `fragment of PATH`. |
| `mermaid` | Not run. |

A block without an info string fails. Both backtick and tilde fences work, also
indented inside a list item.

## Markers

Markers are one-line HTML comments `check: …` or `file: …`: under the title
for the page, under a level-2 heading for the section, directly before a fence
for the block. `rel=1e-4` (page) declares the tolerance of floats; the setup
section must then state it in the fixed sentence that the check compares with
the marker (see the end of the setup of [chapter 1](../guide/01-first-run.md)).
A tolerance looser than 1e-4 is refused. `long`, `openfoam` and `jobs` (page or
section) select when blocks run. `timeout=SECONDS` (page or section) replaces
the default limit of 180 s per block; the OpenFOAM chapters use the recorded
run times. `fragment`, `fragment of PATH`, `file: NAME` and
`file: NAME = REPO_PATH` belong to one block. `none: REASON` leaves a block or
a page unchecked; the reason is listed in the report. A marker given twice or a
comment that looks like a marker and does not parse fails.

## Sessions and outputs

A first section `## Setup` runs once; every other section starts from its own
copy of what the setup made, so a link can land in the middle of a chapter.
Python variables and shell state do not carry between sections. An expected
non-zero exit is written in the block, `COMMAND || echo "exit $?"`, and shown
in the `text` block. Floats agree when
`|actual - shown| <= rel * max(|actual|, |shown|) + abs`; integers, words,
version strings and schema names must be identical, and so must the number of
lines.

## The ledger

`docs/check-counts.json` holds, per page, the minimum number of runnable
blocks, compared `text` blocks and `json` blocks, separately for blocks that
always run and for each of `long`, `openfoam` and `jobs`. Every run compares
the pages with it in every mode: fewer blocks of a class, a page without an
entry, or an entry whose page left the default set fails with `docs.counts`.
After adding blocks, run `python scripts/check_docs.py --write-counts` and
commit the file; it is written only when every page passes. Lower counts are a
change that a reviewer sees in the diff.

## Add a chapter

1. Start with `## Setup`: how the reader gets the command and the case.
2. Show selected fields with a short `python` block and its `text` output, made
   by running it; add the tolerance marker and sentence if a float is shown.
3. Mark sections over about a minute `long`, OpenFOAM sections `openfoam`,
   sections that need `optimization-run` `jobs`.
4. Run the check on the page, then `--write-counts`, and add the page to
   `docs/SUMMARY.md`.

## What CI runs

The job `docs` of `.github/workflows/ci.yml` runs the default set in smoke mode
on every push, normally and under `python -O` with identical reports, with
`scripts/generate_reference.py --check` and the tests of both scripts. Two
more jobs run what needs a runtime. `runner-integration` runs chapter 14 with
`--runner` on every push. `external-backend`, a manual dispatch, runs chapters
15 to 19 with `--smoke --foam-root`; this path has not been exercised yet,
because the OpenFOAM runtime does not exist on the host where the
documentation was written. The F1 section of chapter 13 (`jobs`) is executed
by no job: `runner-integration` does not install the two optimization
packages, so its blocks are checked for syntax and script paths only. Full
mode for chapters 18 and 19 takes hours and is not part of any job. `validation/manual_examples.py` still runs its fixed suite
of 11 native steps in the job `numerical` and its 8 OpenFOAM steps in
`external-backend`; `validation/test_manual_examples.py` requires those steps
to equal the blocks of chapters 15 and 17.
