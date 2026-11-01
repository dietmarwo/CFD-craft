# Anisotropic pressure multigrid results

## Scope and frozen protocol

Measured 2026-10-31 on one AMD EPYC 9V74 solver thread; host exposes 9 CPUs,
8-CPU quota and 8 GiB memory limit. Both cores use Rust stable 1.99.1 and locked
dependencies. Baseline core is merged PR #13, main `2ddf17d`. The old point core
has only two measurement overlays: the identical shared `pressure_probe.rs`
and an unused empty `multigrid/line.rs` source-fingerprint marker; its algorithm
is unchanged. The candidate adds symmetric line/small-plane relaxation and
semicoarsening; IC(0) remains default. See the
[plan](../docs/iterations/19-anisotropic-pressure-plan.md) and
[algorithm and API](../docs/PRESSURE_MULTIGRID.md).

Rough exact pressure is `sin(0.73*i) + 0.3*cos(0.17*i)`, centered in closed
domains; the fine operator generates its RHS. NumPy independently checks the
returned vector, with separate dense operator/Galerkin/block references in the
Rust tests. Each of 18 shapes has one warmup plus three balanced timed triplets
(IC(0), merged point MG, candidate MG). Each child makes one cold and one cached
solve. All use tolerance **1e-14**, maximum **1200** iterations, independent RMS
recovery **<=1e-8** and true relative residual **<=1.1e-12**. Repeated work and
result/source signatures must agree. These are pressure fixtures, not accepted
flow or experimental validation.

All **216 child records (432 successful pressure solves)** passed. Maximum
independent recovery error across all methods was **1.844e-10**; maximum true
relative residual was **1.036e-14**. No gate was relaxed. An initial pilot at
1e-12 failed the recovery bound on the most stretched grid for IC(0) and the
candidate; its rows are retained separately and excluded from this campaign.
Tightening the common solver tolerance preceded the formal measurements.

## Cached pressure solves

Times are medians in milliseconds, excluding output and hashing. A speedup
greater than one favors the candidate. Iterations are IC(0)/point/candidate.
The first three rows keep point arithmetic and have bit-identical point and
candidate pressure vectors. Short timing samples can vary substantially.

| Shape | Iterations | IC(0) ms | Point ms | Candidate ms | Point/candidate | IC(0)/candidate |
|---|---:|---:|---:|---:|---:|---:|
| isotropic | 60 / 8 / 8 | 1.557 | 1.029 | 1.084 | 0.95× | 1.44× |
| near-isotropic | 122 / 13 / 13 | 14.849 | 7.294 | 13.619 | 0.54× | 1.09× |
| threshold25 | 108 / 24 / 24 | 23.692 | 27.689 | 25.278 | 1.10× | 0.94× |
| thin100 | 92 / 45 / 5 | 21.113 | 48.411 | 5.694 | 8.50× | 3.71× |
| thin400 | 86 / 83 / 5 | 18.598 | 87.434 | 6.230 | 14.03× | 2.99× |
| cube100 | 147 / 46 / 5 | 504.977 | 881.392 | 141.581 | 6.23× | 3.57× |
| slab100 | 118 / 51 / 6 | 48.116 | 106.360 | 15.520 | 6.85× | 3.10× |
| plate64 | 126 / 49 / 11 | 109.486 | 211.561 | 52.795 | 4.01× | 2.07× |
| plate256 | 199 / 94 / 12 | 378.140 | 997.147 | 144.499 | 6.90× | 2.62× |
| thin1600 | 152 / 150 / 19 | 143.281 | 664.697 | 149.841 | 4.44× | 0.96× |
| thin6400 | 162 / 278 / 18 | 147.785 | 1313.360 | 136.872 | 9.60× | 1.08× |
| review-stretched | 161 / 1169 / 17 | 146.109 | 5245.237 | 137.499 | 38.15× | 1.06× |
| odd | 87 / 108 / 14 | 5.828 | 36.645 | 5.373 | 6.82× | 1.08× |
| periodic | 145 / 257 / 7 | 8.773 | 81.955 | 2.807 | 29.19× | 3.13× |
| outlet | 92 / 102 / 13 | 6.349 | 34.082 | 4.420 | 7.71× | 1.44× |
| stiff-two-cell | 95 / 50 / 9 | 4.481 | 11.923 | 1.714 | 6.96× | 2.61× |
| long-domain | 220 / 54 / 23 | 26.079 | 27.406 | 12.005 | 2.28× | 2.17× |
| short-stiff-axis | 204 / 57 / 6 | 174.028 | 244.178 | 32.047 | 7.62× | 5.43× |

On the 15 block-selected shapes, cached solves are **2.28–38.15×** faster than
merged point MG. Against IC(0), the range is **0.96–5.43×**: at thin1600 IC(0)
is about 4.6% faster; on review-stretched, the large point-MG improvement buys
only about 6% over IC(0). Fewer iterations alone do not establish a useful
speedup. Near-isotropic's initial short samples have large spread (candidate
7.25–16.53 ms), despite unchanged arithmetic and field hashes; do not interpret
that row as an algorithmic isotropic gain.

A follow-up investigated this spread without replacing any original row:
one warmup plus five timed triplets on the three point controls, unchanged
binaries/fields/gates (54 more child records, all accepted). Point/candidate
cached medians were 1.081/1.086 ms isotropic, 7.763/7.692 ms near-isotropic,
and 24.985/25.871 ms at threshold25. The point/candidate ratios were
1.00/1.01/0.97 respectively. This supports treating the large initial
near-isotropic difference as timing variation; no isotropic speedup is claimed.

## Cold cost and memory

Cold time includes setup and solve. Hierarchy MiB counts retained numeric/index
vector capacities and level records, excluding the exact face signature,
reporting handles, grid, outer PCG vectors, allocator and construction temporary
storage. Peak RSS is the complete candidate child, including JSON output;
it is not a hierarchy-only memory number. Preflight adds a further 512 bytes
per cell to the existing 1024-byte MG allowance, before its 25% margin, when
the block policy is selected.

| Shape | Cold IC(0) ms | Cold point ms | Cold candidate ms | Point hierarchy MiB | Candidate hierarchy MiB | Candidate peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|
| isotropic | 1.683 | 4.598 | 4.349 | 0.48 | 0.48 | 3.39 |
| near-isotropic | 14.994 | 28.204 | 27.580 | 2.04 | 2.04 | 6.96 |
| threshold25 | 25.702 | 62.804 | 65.651 | 3.26 | 3.26 | 10.69 |
| thin100 | 21.194 | 90.097 | 29.507 | 3.26 | 6.26 | 13.68 |
| thin400 | 19.831 | 142.240 | 37.677 | 3.26 | 6.26 | 13.71 |
| cube100 | 575.653 | 2659.865 | 651.832 | 52.68 | 95.23 | 169.95 |
| slab100 | 50.982 | 296.262 | 65.790 | 7.10 | 12.50 | 25.37 |
| plate64 | 111.984 | 551.616 | 288.298 | 14.09 | 24.65 | 48.56 |
| plate256 | 396.839 | 1997.226 | 651.084 | 29.88 | 49.31 | 94.73 |
| thin1600 | 135.050 | 1046.937 | 273.989 | 14.09 | 28.31 | 51.71 |
| thin6400 | 165.341 | 1622.962 | 256.804 | 14.09 | 28.31 | 51.67 |
| review-stretched | 141.563 | 5725.831 | 274.649 | 14.09 | 28.31 | 51.75 |
| odd | 6.246 | 56.797 | 15.103 | 1.40 | 2.57 | 6.49 |
| periodic | 9.083 | 99.551 | 11.822 | 1.37 | 2.42 | 6.15 |
| outlet | 6.620 | 56.990 | 13.750 | 1.40 | 2.57 | 6.52 |
| stiff-two-cell | 4.772 | 18.481 | 9.736 | 0.78 | 1.25 | 4.77 |
| long-domain | 25.226 | 43.394 | 23.562 | 1.54 | 2.89 | 7.62 |
| short-stiff-axis | 182.163 | 517.239 | 146.811 | 13.52 | 23.20 | 46.79 |

Cold candidate solves are often slower than IC(0). Retaining weak-axis modes
also retains larger coarse grids and operators. Setup and operator complexity
remain explicit P2c work; this implementation does not claim universal cold
or low-memory superiority.

## Shape definitions

All meshes are uniform within each axis. Grid counts and domain lengths are
separate; this is not support for graded/nonuniform meshes. Wall fixtures use
wall x/z, periodic y and no moving wall; periodic uses periodic x/y and wall z;
outlet uses open x, periodic y, wall z and imposed initial x velocity.
Every exact input JSON is retained. Labels are mnemonics, not acceptance gates.

| Shape | Cells x,y,z | Domain m x,y,z | x boundary |
|---|---|---|---|
| isotropic | 24, 2, 24 | 1.0, 1.0, 1.0 | wall |
| near-isotropic | 96, 2, 24 | 4.0, 0.1, 1.0 | wall |
| threshold25 | 64, 2, 64 | 1.0, 0.1, 0.2 | wall |
| thin100 | 64, 2, 64 | 1.0, 0.1, 0.1 | wall |
| thin400 | 64, 2, 64 | 1.0, 0.1, 0.05 | wall |
| cube100 | 48, 48, 48 | 1.0, 1.0, 0.1 | wall |
| slab100 | 32, 32, 16 | 1.0, 1.0, 0.05 | wall |
| plate64 | 64, 8, 64 | 1.0, 1.0, 1.0 | wall |
| plate256 | 64, 16, 64 | 1.0, 4.0, 1.0 | wall |
| thin1600 | 64, 8, 64 | 1.0, 1.0, 0.2 | wall |
| thin6400 | 64, 8, 64 | 1.0, 1.0, 0.1 | wall |
| review-stretched | 64, 8, 64 | 1.0, 1.0, 0.02 | wall |
| odd | 33, 5, 17 | 1.0, 1.0, 0.1 | wall |
| periodic | 31, 5, 17 | 0.05, 1.0, 1.0 | periodic |
| outlet | 33, 5, 17 | 1.0, 1.0, 0.1 | open |
| stiff-two-cell | 32, 2, 32 | 1.0, 0.001, 1.0 | wall |
| long-domain | 128, 2, 16 | 100.0, 1.0, 1.0 | wall |
| short-stiff-axis | 64, 64, 8 | 1.0, 1.0, 0.01 | wall |

## Accepted coupled anisotropic flow

Square-domain Re=100 cavity, 64x2x12, canonical flow numerics; one warmup and
three alternating timed IC(0)/MG pairs per mode. Limits are 600 s/20000 steps.
Archive integrity and independent field audits must pass. The steady row also
retains the existing 0.06 Ghia screen. The transient row means completion to
1 s, not convergence to steady flow. Both methods repeat their work and fields.
All **16 child records** pass. Total solver time includes setup; workflow time
also includes launch, archive and checking work.

| Mode | Steps both | IC(0)/MG PCG work | Solver IC(0)/MG s | Solver speedup | Workflow IC(0)/MG s | Workflow speedup | Ghia error |
|---|---:|---:|---:|---:|---:|---:|---:|
| steady | 4950 | 477,555 / 59,315 | 23.632 / 16.751 | 1.41× | 23.722 / 16.843 | 1.41× | 0.04298755 |
| transient | 297 | 28,846 / 3,479 | 1.546 / 0.942 | 1.64× | 1.642 / 1.048 | 1.57× | not steady |

Maximum pairwise velocity difference is 2.22e-16 m/s and pressure difference
5.01e-15 m²/s²; predeclared bounds are 1e-8 and 1e-7 with the same gauge. Steady
stopping steps are unchanged. This throughput fixture's 0.04299 Ghia error
does not reach the 0.01 accuracy objective; it is not a matched-accuracy
OpenFOAM comparison. It compares the candidate with IC(0), while the isolated
pressure suite additionally compares the merged point algorithm.

## Hosted reproduction

The manual `external=anisotropy` job ran both campaigns on a GitHub runner
(AMD EPYC 7763, 4 CPUs, ubuntu-24.04;
[run 41268224744](https://github.com/dietmarwo/CFD-craft/actions/runs/41268224744))
at commit `8ebee01`, whose solver code is the code measured above. The job
builds the merged point core from main `2ddf17d` with the same two
measurement overlays. All kernel and flow records passed, and all 16 flow
archives verified after a zip round trip.

Every shape repeated the recorded iteration counts for all three methods, and
the coupled runs repeated the recorded steps, PCG work and Ghia error. Reused
kernel times (medians, ms) and speedups of the candidate:

| Shape | IC(0) | Point | Candidate | Point/candidate | IC(0)/candidate |
|---|---:|---:|---:|---:|---:|
| isotropic | 1.914 | 1.221 | 1.203 | 1.01× | 1.59× |
| near-isotropic | 16.301 | 8.239 | 8.271 | 1.00× | 1.97× |
| threshold25 | 25.200 | 26.998 | 27.166 | 0.99× | 0.93× |
| thin100 | 21.606 | 49.934 | 6.397 | 7.81× | 3.38× |
| thin400 | 20.313 | 91.608 | 6.425 | 14.26× | 3.16× |
| cube100 | 494.481 | 847.348 | 117.416 | 7.22× | 4.21× |
| slab100 | 53.578 | 113.898 | 15.276 | 7.46× | 3.51× |
| plate64 | 119.990 | 222.678 | 47.255 | 4.71× | 2.54× |
| plate256 | 392.266 | 935.114 | 113.898 | 8.21× | 3.44× |
| thin1600 | 144.321 | 682.025 | 113.470 | 6.01× | 1.27× |
| thin6400 | 153.792 | 1332.020 | 112.213 | 11.87× | 1.37× |
| review-stretched | 153.559 | 5373.320 | 108.438 | 49.55× | 1.42× |
| odd | 6.777 | 40.360 | 5.921 | 6.82× | 1.14× |
| periodic | 10.568 | 91.285 | 2.898 | 31.50× | 3.65× |
| outlet | 6.764 | 35.949 | 5.121 | 7.02× | 1.32× |
| stiff-two-cell | 5.414 | 13.113 | 1.980 | 6.62× | 2.73× |
| long-domain | 26.192 | 28.792 | 12.549 | 2.29× | 2.09× |
| short-stiff-axis | 199.073 | 251.838 | 30.483 | 8.26× | 6.53× |

On this runner the candidate's cached solves beat IC(0) on all 15
block-selected shapes (1.14–6.53×), including thin1600, where IC(0) was faster
on the recording host. Against merged point MG the range is 2.29–49.55×.

| Mode | Steps both | IC(0)/MG PCG work | Solver IC(0)/MG s | Solver speedup | Workflow IC(0)/MG s | Workflow speedup | Ghia error |
|---|---:|---:|---:|---:|---:|---:|---:|
| steady | 4950 | 477,555 / 59,315 | 26.861 / 19.107 | 1.41× | 26.941 / 19.218 | 1.40× | 0.04298755 |
| transient | 297 | 28,846 / 3,479 | 1.600 / 1.128 | 1.42× | 1.706 / 1.206 | 1.42× | not steady |

The opt-in multigrid cavity accuracy sweep (`external=accuracy` with
`native_pressure=multigrid`, AMD EPYC 9V74, 4 CPUs;
[run 41267955525](https://github.com/dietmarwo/CFD-craft/actions/runs/41267955525))
accepted all 20 records with unchanged Ghia errors. Native/OpenFOAM solver
time was 6.85× at 24² and 10.99× at 48² (workflow 3.60× and 9.79×), close to
the [same-host comparison](PERFORMANCE_GAP_STATUS.md#how-close-native-is-now).
Native still misses the 0.01 target through 48², so no equal-accuracy ratio
exists.

## Identity, reproduction and limits

Shared-probe source fingerprints (different scope from the CLI build SHA):

- point_mg: `694a65b070e537d1026368517e9d0ffdea6621bef04a293e562ffe0f4571677e`.
- candidate_mg: `a00c21b56c2ba635d9888da064309c8dc65c47966dc816c0337ba1b71451cfd1`.

The raw evidence records executable/input/producer SHA-256 values, compiler,
host limits, every child, returned pressure vectors, hierarchy dimensions,
block bandwidth/storage, work, RSS, repeated profiles and complete native flow
archives. The [guide](../docs/PRESSURE_MULTIGRID.md#reproduce-comparisons) gives
local and opt-in CI commands. The tables above come from the recording host;
the [hosted reproduction](#hosted-reproduction) above ran on a GitHub runner.

Verification passes 75 Rust release tests on minimum 1.88.0 and stable 1.99.1,
with all-target Clippy warnings denied, plus 396 distinct Python tests per
normal/optimized mode across 16 suites. The 23 runtime-dependent tests were
rerun with the pinned real backend, with no skips. The existing scalar/flow
verification, Poiseuille, empty-ABL, manual examples and masked SciPy reference
pass. A block-selected 12x4x12 checkpoint replay produces bit-identical fields
to the uninterrupted run; a forced one-iteration pressure failure retains the
whole initial state, with attempted work visible in the validated profile.

Mask support, component-preserving transfers, narrow passages and the 27k/93k
canyon gate are still open. Anisotropy selection is a fixed spacing heuristic,
not a guarantee for every aspect ratio or arbitrary modified face matrix.
No OpenFOAM code is copied. No flow/transport/turbulence model or scientific
tolerance changes. The [fresh overall gap and remaining stages](PERFORMANCE_GAP_STATUS.md)
keep pressure throughput, accuracy and physical qualification distinct.
