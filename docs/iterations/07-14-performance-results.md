# Native CPU performance: iterations 07–14

Eight implementation increments from merged PR #7, `402a15036636d8f48591a2d9b5f4ed203cb5ab91`. The declared
plan is [07-14-performance-plan.md](07-14-performance-plan.md). Measurements
compare fixed work under unchanged equations, tolerances, initial fields,
physical parameters and stopping rules. They support implementation-cost claims
for the listed workloads, not physical validation or accepted fine-grid studies.

## What merged and what remains fixed

The fresh GitHub fetch still resolves `main` to PR #7. It contains the delivered
iteration 06 plus `e7b0952` (source/checkpoint/producer binding, measurement
screening and workflow integrity), `4ee538a` (stronger tests), `d7eacc3` (bounded
GitHub notices) and `fee6f21` (actual declared campaign results). This series
preserves those fixes. The source-flux decision from PR #5 is still open.

The actual GitHub backstep campaign ran three fine stages of 4000 iterations,
continued residual decay and passed archive audits, but remained numerically
unaccepted at 12000 fine iterations. This series does not relabel that result,
rerun the large campaign, or accelerate the external OpenFOAM engine. The
previous cloud-only empty-time-directory observation still has no proved cause
or fix; it was not observed on GitHub.

## Eight changes

| Iteration | Implementation | Verification and measured interpretation |
|---|---|---|
| 07 | Reuse one preconditioned residual buffer per PCG solve | Removes an allocation per application; isolated 2.3% median difference has overlapping ranges, so no clear CPU claim |
| 08 | Flat row offsets, columns and IC(0) values; local triangular accumulators | Independent dense IC(0) oracle on duplicate periodic faces, odd cycles, masked/closed/outlet grids; clear pressure-probe gain |
| 09 | Direct coalesced flat assembly and sorted-prefix intersection | Preserves original diagonal/duplicate summation order, shift and zero-fill pattern; probe peak RSS 61.64→58.82 MiB, no demonstrated complete-solve CPU gain (median was slower) |
| 10 | Per-solve compact ordered active-face operator with precomputed weights | Current public coefficients observed on every solve; original uncompressed operator recomputes true residual; exact products and mutation regression; clear pressure gain |
| 11 | Form projection RHS/scales directly; apply gradients to faces without temporary arrays | Exact comparison with composed divergence/gradient on periodic, closed, masked and outlet cases; removes temporary arrays; isolated coupled-step median was slower, no CPU gain claimed |
| 12 | Reuse six local cell-neighbor indices in RANS production and cross stress | Same gradient arithmetic, walls and floors; empty ABL passes; production and momentum kernel gains |
| 13 | Share staggered neighbors across advective samples and viscous coefficients | Wall ghosts, outlet and periodic semantics unchanged; empty ABL and laminar tests pass; RANS and laminar momentum gains |
| 14 | Construct only required candidate-state fields; transfer history after every fallible gate | Full-state atomicity tests for pressure cancellation, invalid history and late positivity failure; preserves unchanged trailing constituents; isolated canyon median slower, prescribed-step difference small |

These are eight performance-directed implementation increments, not eight
independent demonstrated speedups. Retained neutral/slower observations are
part of the result. The two largest improvements are flat triangular sweeps
and precomputed pressure products. No solver iteration or scientific check was
removed to obtain them.

## Measurement protocol

Release profile: Cargo.lock fixed, thin LTO, debug=1, same rustc 1.99.1
for baseline and candidates. Host: AMD EPYC 9V74 80-Core Processor, Linux x86_64,
9 visible/allowed logical CPUs, cgroup quota 8 CPU equivalents,
8 GiB memory limit. Python 3.12.14, NumPy 2.5.4,
SciPy 1.18.1. No concurrent builds or tests during
timed comparisons. These are measurements on one shared cloud host, not a
cross-machine ranking.

One unscored warmup pair, then five alternating A/B and B/A pairs, fresh
processes and frozen cases/binaries. Reports retain all five ranges and hashes.
Native kernel timing excludes JSON/hashing; the first inner pressure/step sample
is cold and is excluded from the warm median when there is another inner sample.
Full CLI timing below includes setup, cold factorization, solving and output.
The merged core baseline is built with the common probe example added solely
for measurement. The CLI fingerprint includes that example because build.rs
hashes all Rust sources; its solver implementation remains the exact merged base.

Work counts, stopping state, pressure iterations and floor counts must match.
Fields/budgets must be finite and satisfy 1e-13 absolute plus 1e-11 relative per
value. Exact result hashes are also reported. Every listed paired comparison
passed; all listed retained results are exact, including full State/history.
This is equivalence under the stated fixtures, not universal bitwise portability.
The native paired benchmark checks hashes before/after children, retains failures,
kills bounded child process groups and records fresh-child wait4 resource usage.
CI checks benchmark contracts and a functional pressure probe, without a noisy
wall-clock pass/fail threshold.

## Adjacent-iteration observations

Each row compares that increment with its immediate predecessor, rather than
with the original merged baseline. Time is the median of paired warm-median
samples (seconds per pressure solve, kernel call or stated step batch).

| Measurement | Threads | Baseline seconds (range) | Candidate seconds (range) | Throughput factor | Exact result |
|---|---:|---|---|---:|---|
| `07-pressure-final` | 1 | 0.859198 (0.790571–0.957565) | 0.839912 (0.801808–0.885957) | 1.023× | yes |
| `08-pressure` | 1 | 0.845340 (0.824954–0.899944) | 0.679899 (0.647539–0.711295) | 1.243× | yes |
| `09-pressure` | 1 | 0.648867 (0.608595–0.680112) | 0.687647 (0.641616–0.703004) | 0.944× | yes |
| `10-pressure` | 1 | 0.674222 (0.618206–0.699698) | 0.411149 (0.384090–0.463806) | 1.640× | yes |
| `11-steps` | 1 | 1.383702 (1.340611–1.438044) | 1.448005 (1.391337–1.479168) | 0.956× | yes |
| `12-production` | 1 | 0.004696 (0.004558–0.005121) | 0.003979 (0.003742–0.004374) | 1.180× | yes |
| `12-momentum` | 1 | 0.042822 (0.042073–0.043752) | 0.039211 (0.037462–0.041891) | 1.092× | yes |
| `13-momentum` | 1 | 0.039169 (0.038083–0.040817) | 0.032198 (0.031195–0.036091) | 1.216× | yes |
| `13-cavity-momentum` | 1 | 0.001673 (0.001644–0.001720) | 0.001289 (0.001249–0.001325) | 1.298× | yes |
| `14-steps` | 1 | 1.320212 (1.289107–1.358964) | 1.373159 (1.298782–1.392525) | 0.961× | yes |
| `14-periodic-steps` | 1 | 0.067284 (0.066101–0.071740) | 0.065320 (0.064263–0.066455) | 1.030× | yes |

## Final version versus merged main

Frozen grids: canyon 27,648 total cells `[36,32,24]`; canyon 93,312
`[54,48,36]`; periodic 27,648 `[48,24,24]`; cavity 4,608 `[48,2,48]`.
The 27k coupled probe uses 8 steps, 93k uses 4 and cavity uses 20. Transport
uses the probe's positive nonuniform scalar field with MUSCL. Full source and
case identities and inner work counts are retained in JSON reports.

| Measurement | Threads | Baseline seconds (range) | Candidate seconds (range) | Throughput factor | Exact result |
|---|---:|---|---|---:|---|
| `final-pressure-93k` | 1 | 0.827566 (0.795666–0.889123) | 0.393146 (0.383360–0.407823) | 2.105× | yes |
| `final-steps-27k` | 1 | 1.923034 (1.831214–2.074935) | 1.418245 (1.360255–1.527298) | 1.356× | yes |
| `final-steps-93k` | 1 | 6.895446 (6.613648–7.243533) | 3.697075 (3.500438–3.950186) | 1.865× | yes |
| `final-momentum-1` | 1 | 0.039268 (0.037651–0.040835) | 0.031472 (0.030745–0.033244) | 1.248× | yes |
| `final-production-1` | 1 | 0.004408 (0.004363–0.005795) | 0.003767 (0.003603–0.003835) | 1.170× | yes |
| `final-momentum-4` | 4 | 0.016792 (0.016663–0.017377) | 0.013269 (0.012132–0.013671) | 1.265× | yes |
| `final-steps-27k-4` | 4 | 1.860154 (1.824871–1.897006) | 1.219921 (1.190750–1.244716) | 1.525× | yes |
| `final-transport-1` | 1 | 0.001179 (0.001104–0.001218) | 0.001145 (0.001093–0.001329) | 1.030× | yes |
| `final-transport-4` | 4 | 0.001191 (0.001136–0.001779) | 0.001258 (0.001138–0.001853) | 0.947× | yes |
| `final-setup-93k` | 1 | 0.024547 (0.022512–0.026668) | 0.022653 (0.022164–0.030408) | 1.084× | yes |
| `final-cavity-steps` | 1 | 0.711224 (0.680099–0.798692) | 0.520557 (0.498224–0.562699) | 1.366× | yes |

The unchanged scalar kernel and setup are controls, not newly optimized
algorithms. Four-thread behavior is reported rather than presumed beneficial;
pressure and several stencil stages remain serial. The current optimizer
worker uses prescribed flow, so it does not receive the pressure-solve gain.
Its potential benefit is limited to the state/transport path measured here;
no optimization-campaign speedup was measured.

### Full CLI, fixed work and independent archived-field checks

Warmup plus five alternating pairs. Canyon 27k: 30 steps; canyon 93k: 10;
periodic 27k: 30. Each archive passed independent mass, positivity, receptor and
continuity checks, and all fields/budgets/history matched exactly. Exit 2,
termination `iteration_limit`, assessment `incomplete` are expected and retained.
The original profiling helper therefore reports `passed=false` for these
intentional incomplete steady/transient runs; the separate fixed-work comparison
requires that exact exit/work/stopping state and independently audits fields.
These timings are not time-to-steady-acceptance measurements.

The first CLI warmup exposed a harness bug: the archive explicitly serializes
an empty moving_walls default omitted by the frozen input. The corrected check
requires exact case equality after inserting only that documented empty default.
The original failed report and actual-archive regression proof are retained;
no case, work count or numerical tolerance changed. Producer revisions and the
original/final measurement plans are included.

| Measurement | Threads | Baseline seconds (range) | Candidate seconds (range) | Throughput factor | Exact result |
|---|---:|---|---|---:|---|
| `cli-canyon-27k` | 1 | 7.037264 (6.934881–7.336335) | 4.929432 (4.878793–5.180386) | 1.428× | yes |
| `cli-canyon-93k` | 1 | 16.516343 (16.115981–17.369829) | 9.295386 (9.040095–9.497321) | 1.777× | yes |
| `cli-periodic-27k` | 1 | 0.164736 (0.164686–0.215004) | 0.165001 (0.164537–0.214932) | 0.998× | yes |

| CLI case | Baseline RSS MiB | Final RSS MiB | Baseline estimate MiB | Final estimate MiB |
|---|---:|---:|---:|---:|
| `cli-canyon-27k` | 47.836 | 47.359 | 53.691 | 57.382 |
| `cli-canyon-93k` | 79.902 | 77.543 | 121.822 | 134.280 |
| `cli-periodic-27k` | 35.695 | 35.352 | 53.481 | 57.172 |

### Memory tradeoff and one million cells

Compact per-solve pressure entries consume memory. The preflight estimate was
raised by 112 bytes/cell before its existing 25% margin. Flat factor construction
and fewer discarded state copies offset some of that cost. The million-cell
sample increases RSS by 44.078 MiB
(5.66%).
Cases close to their declared memory allowance can now be rejected earlier by
preflight because it accounts for the added workspace. Fresh-child RSS is
reported without cumulative maxima across earlier children. Probe RSS includes
fixtures and JSON and must not be treated as production memory.

One bounded three-step, one-million-cell CLI pair was declared before execution,
with one thread, 170-second solver budgets and full fields/checkpoint disabled.
It is a resource sample, not a steady or physical validation and not a five-pair
CPU speed claim. Its raw stopping state and checks remain in the evidence.

| Three-step million-cell resource sample | Baseline | Final |
|---|---:|---:|
| Wall seconds (single sample) | 130.777 | 78.060 |
| Peak resident MiB | 778.836 | 822.914 |
| Case estimated peak MiB | 1062.598 | 1196.113 |
| Completed steps | 3 | 3 |
| Pressure iterations | 2309 | 2309 |

## Validation

| Check | Actual result |
|---|---|
| Rust release workspace | 41 passed: 5 pressure units, 18 numerical tests, 18 regressions |
| Required static checks | cargo fmt, clippy all targets with -D warnings, Ruff format/check, git diff --check pass |
| `test_benchmark_native.py`, ordinary / `-O` | 11 / 11 passed |
| `test_cli.py`, ordinary / `-O` | 35 / 35 passed |
| `test_openfoam.py`, ordinary / `-O` | 38 / 38 passed |
| `test_resolution.py`, ordinary / `-O` | 41 / 41 passed |
| `test_restart.py`, ordinary / `-O` | 54 / 54 passed |
| `test_mapping.py`, ordinary / `-O` | 58 / 58 passed |
| `test_refinement.py`, ordinary / `-O` | 68 / 68 passed |
| Periodic shear spatial / temporal order | 1.997159 / 2.010160; gates 1.8 / 1.8 |
| MUSCL Gaussian spatial order | 2.323308; gate 1.8 |
| Poiseuille maximum speed error | 0.00488276293 m/s |
| Empty ABL U / k / epsilon drift H..5H | 0.2341% / 0.9405% / 2.6754%; gates 2% / 5% / 5% |
| Lid cavity maximum centerline error | 0.02754881; gate 0.06 |
| Independent SciPy field / assembled residual | 6.08427e-13 / 8.22817e-13 |
| Exact source superposition / held-out defect | 3.86113e-16 / 3.9386e-16 |
| Coarse canyons | all three accepted, independent mass/continuity checks pass, zero floor events |

| Case | Steps | Pressure iterations | Assessment |
|---|---:|---:|---|
| canyon-wh1-wind270 | 3800 | 398027 | steady_discrete_solution; independent checks pass |
| canyon-wh2-wind270 | 3800 | 394667 | steady_discrete_solution; independent checks pass |
| canyon-wh1-wind225 | 1800 | 171079 | steady_discrete_solution; independent checks pass |

The 93k manufactured pressure fixture takes the same 166 iterations in both
versions, with a recomputed relative residual of 6.9540e-12 and RMS pressure
error of 3.1094e-12. The full-vector comparison is exact.

Tolerances are unchanged. The below-H empty-ABL epsilon drift remains about
16.16% and is reported, not gated. Local checks used stable Rust 1.99.1;
the existing CI matrix still includes Rust 1.88.0, but that toolchain was not
rerun locally in this series. The large declared fine OpenFOAM backstep was
not repeated; the bounded real Foundation-13 contract tests were repeated.

## Reproduce and inspect

After applying all eight patches, install requirements-validation.txt and build
with `cargo build --release --locked --example performance_probe --bin cfd-craft`.
For a comparable old probe, create a worktree at the exact base and copy only
`crates/cfd-craft/examples/performance_probe.rs` from the final tree there before
building the same targets. Do not copy optimized core files to the baseline.
Use the exact cases in the evidence bundle and the same compiler/build flags.

~~~sh
python validation/benchmark_native.py --baseline BASE_PROBE --candidate FINAL_PROBE \
  --case canyon-93k.json --mode pressure --rounds 5 --inner 4 --steps 8 \
  --threads 1 --output fresh-pressure-comparison
~~~

The bundle contains the frozen case files and final-measurement-plan.json with
all variants; tools/benchmark_cli.py accepts --repo, --baseline, --candidate,
--case, --rounds and --output for CLI reproduction. The measurement reports
retain original invocation paths as provenance; replace paths when rerunning.
Large fields and binaries are intentionally absent from the compact download;
source/binary/result hashes, comparisons, resource samples and test logs are
included. Raw field/probe archives used here remain in the execution workspace.

Native probe source identity: `85d03b0d6cf169e3e6afc6ba6cdcf0ab453f379991d703d854086a4b1187ded5`.
Native CLI source identity: `ab5ba1170207df69eef0dfd97a07f299c63ae0fba1e0782e4aa22823ec1e8025`.
The probe identity also frames the common example and manifests, so it is
expected to differ from the CLI fingerprint. Both refer to the actual compiled
producer rather than the later documentation commit.

## Open performance and scientific gates

Pressure still needs serial PCG work at every projection; a verified multigrid
preconditioner remains a larger algorithmic opportunity. Explicit diffusion and
advection still restrict the time step. This work does not establish accepted
fine canyon throughput, asymptotic grid convergence, a mesh-independent building
wall roughness law, experimental urban validation or calibrated uncertainty.
Raw matched experimental data/protocol access and the external fine-backstep
acceptance gate remain open. No source-flux decision, physical model or
validation threshold changed in this series.
