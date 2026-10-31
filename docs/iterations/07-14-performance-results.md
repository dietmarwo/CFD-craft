# Native CPU performance: results

Measured against merged main `402a15036636d8f48591a2d9b5f4ed203cb5ab91`, as
declared in the [plan](07-14-performance-plan.md). The changes reduce the cost
of the native pressure solve, the RANS and momentum stencils and the step's
state handling. Equations, tolerances, initial fields, stopping rules and
acceptance gates are unchanged, and the results are bit-identical to the
previous implementation on every workload compared. The measurements support
cost claims for the listed workloads; they are not physical validation or an
accepted fine-grid study.

## Changes and their measured effect

Each row was measured against the preceding row on the first host below
(single thread, fixed work). The eight increments are not eight independent
speedups: three are neutral or slower on their own workload, and only the
pressure-solve and stencil changes give a clear gain.

| Increment | Implementation | Measured against the preceding increment |
|---|---|---|
| 07 | One preconditioned-residual buffer per PCG solve | pressure solve 1.023×, ranges overlap: no clear gain |
| 08 | IC(0) factor in contiguous row arrays; flat triangular sweeps | pressure solve 1.243× |
| 09 | Factor assembled directly into the flat arrays | pressure solve 0.944× and first (cold) solve 0.982×, both slower; probe peak RSS 61.6 → 58.8 MiB |
| 10 | Per-solve compact list of face weights for the PCG products | pressure solve 1.640×; probe peak RSS 58.8 → 67.9 MiB |
| 11 | Projection right-hand side and correction without temporary arrays | 27k coupled steps 0.956×, slower |
| 12 | Cell neighbors looked up once in RANS production and cross stress | production 1.180×, momentum 1.092× |
| 13 | Staggered neighbor faces shared by advection and viscosity | RANS momentum 1.216×, cavity momentum 1.298× |
| 14 | Candidate state built from only the fields a step changes | 27k coupled steps 0.961×, slower; periodic steps 1.030× |

The unchanged control kernels (scalar transport and grid setup) ranged from
0.947× to 1.084× in the same measurements, so differences of a few percent,
including the 1.092× of increment 12's momentum kernel, are within the noise of
that host. In time saved per pressure solve, increments 08 and 10 contribute
most.

## Equivalence

- **Paired runs.** Every timed comparison compares the complete result of both
  builds: work counts exactly, floating-point values within 1e-13 absolute plus
  1e-11 relative, and the result hash. All comparisons on both hosts were exact.
- **Verification suites.** The flow-accuracy, analytic, cavity, SciPy-reference,
  source-inference and coarse-canyon suites were run with both builds on the
  second host. Their fields and reports are identical (about 630,000 compared
  values); the only differences are the memory estimate and the hashes of the
  summary files that contain it.
- **Tests.** A dense IC(0) reference checks the flat factor on duplicate
  periodic edges, odd cycles and masked, closed and outlet grids. The compact
  face list must equal the face-by-face operator bit for bit, also on unequal
  spacing. The projection's right-hand side and round-off scale are checked
  against their definitions. The bit patterns of the momentum, production and
  turbulence-step results on an open and a periodic canyon grid were recorded
  from `402a150` and are pinned. Step tests cover cancellation inside the
  pressure solve, invalid history, a late positivity failure, unsupplied
  constituents and the step counters.

## Measurement protocol

`crates/cfd-craft/examples/performance_probe.rs` runs one kernel or a batch of
coupled steps a fixed number of times on a frozen case and reports the timings,
the work counts and the full result. Every repetition repeats the same work from
the same input and must return the same result. In pressure and step modes the
first repetition is cold (it builds the cached factor) and is excluded from the
warm median. Timings exclude JSON output and hashing.

`validation/benchmark_native.py` runs a baseline and a candidate probe as fresh
child processes: one unscored warmup pair, then five pairs in alternating order
(three baseline-first, two candidate-first). It checks the binaries, the case and
itself before and after every child, requires each child to report the requested
work, rejects failed, timed-out or cancelled children and records per-child CPU
time and peak RSS. `speedup` is the ratio of the medians of the per-round warm
medians; `paired_speedup_median` is the median of the per-round ratios. The
baseline probe is the same example file built against the base sources. The
frozen cases are in `cases/performance/`.

## First host

AMD EPYC 9V74 (8 CPU quota, 8 GiB), Linux x86_64, rustc 1.99.1, thin LTO,
`debug = 1`. Grids: canyon 27,648 cells `[36,32,24]`, canyon 93,312
`[54,48,36]`, periodic 27,648 `[48,24,24]`, cavity 4,608 `[48,2,48]`. Step
batches: 8 steps (27k), 4 (93k), 20 (cavity). Seconds are the median of the
per-round warm medians, with the range.

| Measurement | Threads | Base seconds (range) | Current seconds (range) | Ratio of medians | Paired median |
|---|---:|---|---|---:|---:|
| Pressure solve, 93k | 1 | 0.827566 (0.795666–0.889123) | 0.393146 (0.383360–0.407823) | 2.105× | 2.105× |
| Coupled steps, 27k | 1 | 1.923034 (1.831214–2.074935) | 1.418245 (1.360255–1.527298) | 1.356× | 1.356× |
| Coupled steps, 93k | 1 | 6.895446 (6.613648–7.243533) | 3.697075 (3.500438–3.950186) | 1.865× | 1.827× |
| Coupled steps, 27k | 4 | 1.860154 (1.824871–1.897006) | 1.219921 (1.190750–1.244716) | 1.525× | 1.520× |
| Cavity steps | 1 | 0.711224 (0.680099–0.798692) | 0.520557 (0.498224–0.562699) | 1.366× | 1.347× |
| RANS momentum, 93k | 1 | 0.039268 (0.037651–0.040835) | 0.031472 (0.030745–0.033244) | 1.248× | 1.196× |
| RANS momentum, 93k | 4 | 0.016792 (0.016663–0.017377) | 0.013269 (0.012132–0.013671) | 1.265× | 1.260× |
| Production, 93k | 1 | 0.004408 (0.004363–0.005795) | 0.003767 (0.003603–0.003835) | 1.170× | 1.197× |
| Transport (control), 27k | 1 | 0.001179 (0.001104–0.001218) | 0.001145 (0.001093–0.001329) | 1.030× | 0.985× |
| Transport (control), 27k | 4 | 0.001191 (0.001136–0.001779) | 0.001258 (0.001138–0.001853) | 0.947× | 0.987× |
| Grid setup (control), 93k | 1 | 0.024547 (0.022512–0.026668) | 0.022653 (0.022164–0.030408) | 1.084× | 1.016× |

Setup mode compares only the cell and face counts. Four threads are reported,
not presumed beneficial: the pressure solve and several stencil stages are
serial. The optimizer worker uses prescribed flow, so it does not receive the
pressure-solve gain; no optimization-campaign speedup was measured.

Full command-line runs at fixed work (warmup plus five pairs, one thread,
setup, cold factorization, solve and output included): canyon 27k with 30
steps, canyon 93k with 10, periodic 27k with 30. All end at their step limit
(exit 2, `iteration_limit`, assessment `incomplete`) as intended; their fields,
budgets and histories are identical and pass the independent mass, positivity,
receptor and continuity checks. These are not times to an accepted steady
state. They were measured with a separate harness that is not part of the
repository; the second host repeats them with plain `cfd-craft run` commands.

| Run | Base seconds (range) | Current seconds (range) | Ratio | Base / current RSS MiB |
|---|---|---|---:|---|
| Canyon 27k, 30 steps | 7.037264 (6.934881–7.336335) | 4.929432 (4.878793–5.180386) | 1.428× | 47.8 / 47.4 |
| Canyon 93k, 10 steps | 16.516343 (16.115981–17.369829) | 9.295386 (9.040095–9.497321) | 1.777× | 79.9 / 77.5 |
| Periodic 27k, 30 steps | 0.164736 (0.164686–0.215004) | 0.165001 (0.164537–0.214932) | 0.998× | 35.7 / 35.4 |

## Second host

A 2-vCPU Intel Xeon virtual machine, Linux x86_64, rustc 1.97.0, Python 3.13,
same build profile and frozen cases, one thread, nothing else running. Both
probes were built from the same example source.

| Measurement | Base seconds (range) | Current seconds (range) | Ratio of medians | Paired median |
|---|---|---|---:|---:|
| Pressure solve, 93k | 0.476113 (0.473162–0.479557) | 0.326266 (0.322278–0.330026) | 1.459× | 1.468× |
| Coupled steps, 27k | 1.577008 (1.556403–1.583522) | 1.077420 (1.072821–1.098611) | 1.464× | 1.448× |
| Coupled steps, 93k | 4.040266 (3.996620–4.069136) | 2.857895 (2.838412–2.907191) | 1.414× | 1.414× |
| Cavity steps | 0.543029 (0.523197–0.590023) | 0.376625 (0.376356–0.397618) | 1.442× | 1.443× |
| RANS momentum, 93k | 0.026979 (0.026858–0.027269) | 0.021527 (0.021392–0.021570) | 1.253× | 1.258× |
| Production, 93k | 0.002734 (0.002713–0.002902) | 0.002274 (0.002242–0.002338) | 1.202× | 1.205× |
| Transport (control), 27k | 0.001058 (0.001042–0.001615) | 0.001061 (0.001043–0.001665) | 0.998× | 1.005× |
| Grid setup (control), 93k | 0.012031 (0.011492–0.012770) | 0.012132 (0.011653–0.013764) | 0.992× | 0.992× |

Full command-line runs on the same cases, timed as alternating
`cfd-craft run` processes (warmup plus five pairs). In every round the two
builds wrote byte-identical fields, checkpoint, geometry, case and probe files
and the same summary apart from the memory estimate, elapsed time and source
identity; `validation/check_fields.py` passes on the archives of both builds.

| Run | Base seconds (range) | Current seconds (range) | Ratio of medians | Base / current RSS MiB |
|---|---|---|---:|---|
| Canyon 27k, 30 steps | 5.747947 (5.729801–6.025189) | 4.000546 (3.937259–4.041992) | 1.437× | 52.3 / 51.7 |
| Canyon 93k, 10 steps | 10.171532 (10.021527–10.196703) | 7.235306 (7.166604–7.266669) | 1.406× | 87.3 / 85.0 |
| Periodic 27k, 30 steps | 0.156923 (0.151550–0.164198) | 0.156661 (0.149262–0.173452) | 1.002× | 35.0 / 34.5 |

The gains carry over, but their size depends on the machine: the pressure
solve is 1.46× faster here against 2.1× on the first host, the 93k step batch
1.41× against 1.87× and the 93k command-line run 1.41× against 1.78×. The
periodic run uses prescribed flow and has no pressure solve, so it does not
change.

## Memory

Measured with an allocator count on a 48³ grid, in bytes per cell:

| | Base | Current |
|---|---:|---:|
| Factor kept after construction | 96 | 64 |
| Peak while building the factor (first solve) | 120 | 88 |
| Working set of a pressure solve | 56 | 144 |
| Working set of a projection | 72 | 160 |

The face list (32 bytes per entry, about three faces per cell) outweighs the
smaller factor, so peak memory rises by about 56 bytes per cell. The preflight
estimate adds 112 bytes per cell before its 25% margin, which is conservative.
Cases close to their declared memory allowance can therefore be rejected where
they were accepted before: a one-million-cell periodic tracer is now estimated
at 1190 MiB instead of 1056 MiB. Nothing is allocated per PCG iteration.

One three-step, one-million-cell CLI pair (one thread, 170 s solver budgets,
fields and checkpoint disabled) was declared before execution on the first host
as a resource sample. It is a single sample, not a speed claim and not a steady
or physical validation.

| Three-step million-cell sample | Base | Current |
|---|---:|---:|
| Wall seconds | 130.777 | 78.060 |
| Peak resident MiB | 778.836 | 822.914 (+5.7%) |
| Estimated peak MiB | 1062.598 | 1196.113 |
| Completed steps | 3 | 3 |
| Pressure iterations | 2309 | 2309 |

## Validation

Current build. Both hosts give these values, and on the second host the base
build gives them too.

| Check | Result |
|---|---|
| Rust release workspace | 7 pressure unit tests, 18 numerical tests, 21 regression tests pass |
| Static checks | cargo fmt, clippy on all targets with `-D warnings`, Ruff format and lint |
| Python suites, normal and `-O` | benchmark runner 28, CLI 35, OpenFOAM backend 38, resolution 41, continuation 54, mapping 58, refinement 68 |
| Periodic shear spatial / temporal order | 1.997159 / 2.010160 (gates 1.8 / 1.8) |
| MUSCL Gaussian spatial order | 2.323308 (gate 1.8) |
| Poiseuille maximum speed error | 0.00488276293 m/s |
| Empty ABL U / k / epsilon drift, H to 5H | 0.2341% / 0.9405% / 2.6754% (gates 2% / 5% / 5%) |
| Lid cavity maximum centerline error | 0.02754881 (gate 0.06) |
| Independent SciPy field / assembled residual | 6.08427e-13 / 8.22817e-13 |
| Exact source superposition / held-out defect | 3.86113e-16 / 3.9386e-16 |
| Coarse canyons | all three accepted; independent mass and continuity checks pass; no floor events |

| Coarse canyon | Steps | Pressure iterations | Assessment |
|---|---:|---:|---|
| canyon-wh1-wind270 | 3800 | 398027 | steady_discrete_solution |
| canyon-wh2-wind270 | 3800 | 394667 | steady_discrete_solution |
| canyon-wh1-wind225 | 1800 | 171079 | steady_discrete_solution |

The 93k manufactured pressure problem takes 166 iterations in both builds, with
a recomputed relative residual of 6.9540e-12 and an RMS error of 3.1094e-12.
The below-H empty-ABL epsilon drift is still about 16.16% and is reported, not
gated. The external OpenFOAM backend does not use the native solver and is
unchanged.

## Reproduce

```sh
cargo build --release --locked --example performance_probe --bin cfd-craft
git worktree add ../cfd-craft-base 402a15036636d8f48591a2d9b5f4ed203cb5ab91
mkdir -p ../cfd-craft-base/crates/cfd-craft/examples
cp crates/cfd-craft/examples/performance_probe.rs ../cfd-craft-base/crates/cfd-craft/examples/
(cd ../cfd-craft-base && cargo build --release --locked --example performance_probe --bin cfd-craft)
python validation/benchmark_native.py \
  --baseline ../cfd-craft-base/target/release/examples/performance_probe \
  --candidate target/release/examples/performance_probe \
  --case cases/performance/canyon-93k.json --mode pressure --rounds 5 \
  --inner 4 --steps 8 --threads 1 --output runs/pressure-comparison
```

The other rows use modes `steps`, `momentum`, `production`, `transport` and
`setup` with the inner repetitions and step counts given above (20 inner
repetitions for the kernels, 2 for step batches). Copy only the probe example
into the base checkout, never optimized core files, and keep builds and other
work off the machine while measuring.

## Open performance and scientific gates

The pressure solve still runs serial PCG at every projection; a verified
multigrid preconditioner remains the larger algorithmic opportunity. Explicit
diffusion and advection still limit the time step. These results do not
establish accepted fine canyon throughput, asymptotic grid convergence, a
mesh-independent building-wall law, experimental urban validation or calibrated
uncertainty. The external fine-backstep acceptance gate and the source-flux
decision from PR #5 remain open.
