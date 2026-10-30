# External backend: OpenFOAM Foundation 13

## Purpose and supported scope

An external execution backend for reproducible numerical comparisons and
experimental assessment. It complements the native Rust solver. Their result
schemas, turbulence packages and scientific claims remain separate.

The tested build is Foundation 13 package `20260407`, `13-441953dfbb42`, Ubuntu
24.04 x86_64, double precision, 32-bit labels, serial Pstream. Other forks,
versions, MPI decompositions and architectures are not qualified by these tests.
The adapter checks the executable's own version and records executable and
solver-library hashes. The package installer verifies a frozen 118586852-byte
SHA-256 before extraction. OpenFOAM is licensed under the GNU GPL, version 3 or
later. CFD-craft runs it as separate programs and neither links nor imports it;
no OpenFOAM source or executable is part of this repository. The generated case
dictionaries and the Python adapter are original CFD-craft code.

## Numerical comparison: cavity

The cavity is a unit square, lid speed 1 m/s, nu=0.01 m2/s, Re=100. OpenFOAM
uses x/y coordinates with an empty span; the native case uses x/z with an
invariant periodic span. There is no open-boundary mass flux. Both profiles
are compared at the existing Ghia stations with a maximum error target of
0.06 lid-speed units, and against each other with the same target.

OpenFOAM solves the steady equations; the native case advances to 30 s. The
report retains this distinction. Ghia is a numerical reference, not a physical
experiment. Code agreement is not experimental validation.

## Experimental comparison: Driver--Seegmiller backstep

The reference is the zero-angle configuration in Driver and Seegmiller (1985),
DOI 10.2514/3.8890, distributed by the [TMR dataset owner](https://tmbwg.github.io/turbmodels/backstep_val.html).
The corrected reference Reynolds number is approximately 36000 based on step
height. The reported reattachment is 6.26 +/-0.10 H.

The generated domain is x/H=-4..50, y/H=0..9; the upstream floor is y/H=1 and
the downstream floor is y/H=0. H=1 m and Uref=1 m/s are incompressible similarity
scales; nu=1/36000 m2/s. A 0.1H empty span makes a two-dimensional calculation.
This is a short-inlet reconstruction using measured upstream data, rather than
TMR's long developing-plate inflow construction. It assumes that compressibility
at the experiment's approximately Mach 0.128 is negligible.

The closure is Foundation 13 `kOmegaSST`, with `kqRWallFunction`,
`omegaWallFunction` and `nutkWallFunction`, using its default coefficients.
The inlet U is linearly interpolated from the x/H=-4 profile. That profile is
an input and is excluded from downstream scoring. Mean transverse velocity is
set to zero. The unmeasured spanwise variance is assumed equal to vv, giving
k=(uu+2vv)/2000 in the table's units. Omega follows a mixing length of 0.07*1.5H.
No-slip endpoint values at y/H=1,9 and tiny positive turbulence endpoint values
are assumptions. None of these parameters is calibrated to downstream data.

The mesh has 22656, 90624 or 203904 cells at levels 1,2,3. The channel above
y/H=1 is graded toward its walls. The block below the step is uniform in y, with
24 cells per H at level 1, so the first cell centre sits at H/48. With wall
functions this places the first lower-wall cell in the buffer layer in the
scored region, where the k-based wall function switches near y+ 11; refinement
moves it lower, so a mesh series also changes the wall treatment. Each
comparison report estimates the first-cell y+ from the sampled wall stress. Momentum advection uses bounded linear upwind; k/omega use
upwind. Pressure uses GAMG and SIMPLEC; the linear systems use absolute 1e-11
and relative 0.001 stopping targets in the backstep. A separate nonlinear gate
requires each final initial residual <=1e-7, explicit solver convergence, local
reported continuity <=1e-6, and stored boundary-flux imbalance <=1e-6. Final
cell fields are checked for finiteness, nonnegative k and nut, and positive omega.
The summary also records a residual trend: the median first-solve residual of
each field over the last tenth of the iterations and over the tenth before it.
A ratio near one at a high level is a stall, which more iterations do not cure.
Reported turbulence bounding messages are counted; they are not independently
instrumented floor events like the native solver's counter.

The protocol (`validation/protocols/backstep-v1.json`, whose hash the comparison
checks) sets the targets: each station's U/Uref RMSE <=0.10, lower-wall Cf RMSE
<=0.001, and reattachment error <=0.75 H. These are project screening choices,
not derived from measurement uncertainty. To show how much they discriminate,
each station also reports its RMSE below and above y/H=2 and the RMSE of a
predictor that ignores the step (the inlet profile above y/H=1, zero below), and
the friction comparison reports the RMSE of Cf=0. The measured Cf file's
error column is retained without asserting an undocumented 95% confidence level.
The U profile file supplies no uncertainty interval. Cf uses the signed
kinematic wall traction, Cf=-2*tau_x/Uref^2, at the lower wall. All downstream
velocity sample identities are paired exactly; Cf interpolation cannot extrapolate.

## Wall-resolved recipes

The legacy dictionaries remain the default. Explicit backstep-only options
select `mesh_family=legacy|wall-resolved` and `solver_profile=legacy|simplec|simple`:

| Profile | Pressure coupling | Relaxation p / U, k, omega | Other settings |
|---|---|---|---|
| legacy | SIMPLEC | 0.2 / 0.5 | as described above |
| simplec | SIMPLEC | 1 / 0.7 | as described above |
| simple | SIMPLE | 0.3 / 0.5; on the wall-resolved mesh 0.1 / 0.1 | on the wall-resolved mesh: PCG/DIC pressure (absolute 1e-12, relative 0, at most 5000 iterations), bounded first-order upwind momentum, cell-limited gradients, zero initial interior U |

On the wall-resolved mesh, GAMG uses a DICGaussSeidel smoother with two pre-
and post-sweeps and a direct solve on its coarsest level. The tutorial's
wall-resolved reference recipe is `wall-resolved`/`simplec`, with second-order
bounded linear-upwind momentum. The first-order `simple` profile is a stability
reference, not an accuracy reference.

The wall-resolved mesh has 48896, 195584 and 440064 cells at levels 1, 2, 3.
In y, the channel above y/H=1 is graded toward both walls (first cell 1.18e-3 H
at level 1) and the block below the step is graded toward both the floor and
the shear-layer line y/H=1 (first cell 9.15e-4 H). In x, both sides of the step
plane start from the step wall's 0.002 H first cell (at level 1). Widths grow
by 10% per cell downstream, with an 11% step into a uniform 0.1 H over the
scored region 1 < x/H < 12, then to 0.31 H at the outlet, and by 15% per cell
upstream to 0.18 H at the inlet. At level 1, neighbouring cell widths differ by
at most a factor 1.15 in x and 1.32 in y, also across block interfaces; finer
levels keep these bounds. Tests check these widths
against blockMesh's grading rules and against the actual Foundation-13
`blockMesh` output. An earlier streamwise spacing with a 140:1 width jump at the
step plane diverged in every run ([results](../../validation/RESOLUTION_RESULTS.md)).

SST keeps its default coefficients. k is fixed to zero at walls,
nutLowReWallFunction imposes zero wall eddy viscosity, and omegaWallFunction
takes its viscous-sublayer value while the k-based y+ is below its switch point
(about 11.5 in Foundation 13). This is a low-Re near-wall package, not a change
to the bulk Reynolds number. The inlet and its assumptions are unchanged; its
near-wall velocity is a linear ramp to the first measured point, which is not
an inner-layer profile.

The separate Cartesian auditor has its own readers for the polyMesh files, the
stored face flux phi and the wall traction; it uses the adapter only to verify
the archive's seal. It checks the point, face, owner and neighbour lists, the
owner-below-neighbour order, face orientation (area vectors point from owner
to neighbour and out of the domain), patch ranges and the represented volume.
From the stored phi it reconstructs each cell's divergence, with the target
max(abs(div(phi)))*H/U <=1e-4. That measure grows like H/dx for a given relative
flux error, so it tightens as cells shrink; the per-cell relative imbalance
abs(sum phi)/(sum abs(phi)/2) is reported beside it, ungated. A stored phi is
conservative to the pressure-solver tolerance by construction, so this gate
tests the linear solve and the file's integrity, not nonlinear convergence.

For the wall-resolved package the auditor also checks the first-cell distance
on all four walls against the generated heights, and max(y+) <=1 on each wall
from the tangential part of the stored wall traction, reporting where the
maximum lies. A wall whose traction is zero everywhere was not sampled and is
rejected. Its report separates its own checks from the adapter's numerical
verdict. It does not reconstruct momentum/turbulence residuals or validate SST
against nature.

Measurement screening of the wall-resolved package additionally requires this
independent audit. A failed numerical/independent gate leaves the screen not
assessed. Refinement skips finer cases after a coarse case is not accepted.
The [tutorial](../../tutorials/backstep-resolution-prompt.md) and
[results](../../validation/RESOLUTION_RESULTS.md) retain those failures.

## Bounded steady field continuation

`prepare-restart` copies the verified final U/p/phi and (for SST) k/omega/nut
of a completed same-mesh run into a fresh local pseudo-time zero. A completed
but unconverged stage is eligible only with finite final fields and independent
local flux <=1e-4; failed, timed-out or cancelled snapshots are ineligible.
This resets steady solver history/caches and does not restore transient time
history. Cumulative iteration counts report work. The native Rust models,
SST/mesh/inlet choices and acceptance thresholds are unchanged.

The sealed initial-state receipt records parent manifest/case hashes, source
acceptance and work, exact fields including phi, fixed physics inputs, actual
mesh files and runtime identity. The rebuilt mesh and exact runtime must match
before solving; the archive verifier checks the receipt against consumed
inputs and records rejected initializations as failed archives. Retain parent
archives to inspect the chain: a receipt's parent hash alone is not a substitute
for those bytes, and unkeyed checksums do not establish authenticity.

The resolution tutorial can continue up to `--max-stages 8` (default 1) with
unchanged per-stage limits. It stops at numerical convergence or a stopped
execution; wall-y+/measurement gates still decide final acceptance. Each stage
is retained. The final report distinguishes local iterations from cumulative
work and never substitutes a source's acceptance for the new stage's result.

For normally completed iteration-limited runs, preparation chooses the largest
writeInterval <=250 that divides the iteration limit. The defaults 6000 and
20000 retain cadence 250. Prime limits can require writes every iteration;
choose composite stage lengths for lower I/O overhead. This fixes missing final
snapshots when an endTime falls between scheduled writes. It does not promote
stopped snapshots or change numerical thresholds. See the
[guide](../../integrations/STEADY_RESTART.md) and
[continuation results](../../validation/RESTART_RESULTS.md).

## Interpretation and open gates (all packages)

Execution, numerical convergence, measurement screening and physical
qualification have separate fields. A zero exit cannot make a nonconverged solve
acceptable. When the numerical gate fails, the comparison still reports the
metrics of the final iterate, each marked within or outside its target, but the
measurement screen is not assessed (`measurement_screen_passed` is null). The physical-qualification status
remains preliminary even if all development metrics pass: inlet uncertainty,
near-wall resolution, mesh sensitivity and model-form sensitivity require work.
Failed meshes remain in the report and are excluded from converged mesh pairs.
No GCI is manufactured from an incomplete or non-asymptotic series.

There are no passive-scalar measurements in this benchmark. These comparisons
therefore do not validate gas dispersion, particles, the native RANS package
or a street canyon. CODASC and the native building-wall/throughput gates remain
open. See the recorded [external results](../../validation/EXTERNAL_RESULTS.md).

## Execution limits

The backend executes only trusted generated dictionaries in a copied fresh
directory. Input hashes detect changes; they are not a signature authorizing
untrusted OpenFOAM code. OpenFOAM itself can load user code, so do not substitute
unreviewed case directories. The adapter never shells out to construct commands.

The runtime is serial. Each child gets a fixed environment (the runtime paths,
single-threaded BLAS/OpenMP and `HOME=/nonexistent`, nothing inherited from
OpenFOAM settings of the caller), a hard address-space limit and a per-file size
limit; the host's hard limits are checked first. The overall output budget and
wall time are polled every 50 ms.
There can be a small polling overshoot and manifests add metadata overhead.
SIGTERM/SIGINT and deadline expiry terminate the process group, with a forced
kill after one second if necessary. The log and failure archive are retained.
Hashing/manifest creation and the bounded runtime preflight add overhead outside
the child solve.

The solver log is read incrementally, each line once. A NaN/Inf residual or
continuity value, or a reported mean continuity error ("sum local", in units of
U_ref/H because the cases are scaled to U_ref = H = 1 with deltaT 1) of at least
1, stops the process group with CFD-X010, also when the child exits zero.
Converged and stalled runs stay below 3e-4, including their first iterations;
the recorded diverging runs crossed 1 at iterations 7 to 154, well before their
last logged iteration (38 to 700). The actual log, return code and progress are
retained. Earlier saved snapshots are not promoted to final solutions.

`report` verifies an archive's consistency: file hashes, the consumed inputs and
that the case holds nothing else besides solver outputs, the numerical summary
recomputed from the returned log and fields, status and error codes, command
return codes, the Foundation-13 runtime and log identity, progress and samples.
Unkeyed hashes are not tamper-evidence: a consistent rewrite of log, fields and
summary cannot be detected this way.
