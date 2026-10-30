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

## Experimental wall-resolved reference (iteration 03)

The legacy dictionaries remain the default. Explicit backstep-only options
select `mesh_family=wall-resolved` and `solver_profile=legacy|simplec|simple`.
The `simplec` profile changes pressure relaxation to 1 and transport relaxation
to 0.7; on the legacy mesh this is a pressure-coupling control, which still
fails the nonlinear gate. It is not a convergence fix.

The experimental mesh has 47616, 190464 and 428544 cells at levels 1,2,3.
It grades all four solid walls, including the step face. First-cell heights
come from a geometric series and are checked against the actual generated
Cartesian mesh. SST keeps its default coefficients and omegaWallFunction;
k is fixed to zero and nutLowReWallFunction imposes zero wall eddy viscosity.
This is a low-Re near-wall package, not a change to the bulk Reynolds number.
The inlet and its uncertainty assumptions are unchanged.

The wall-resolved `simple` reference uses classic SIMPLE, pressure/transport
relaxation 0.1, zero initial interior U, first-order bounded upwind momentum
and cell-limited U/k/omega gradients. Pressure uses PCG/DIC, absolute tolerance
1e-12, relative tolerance zero and a 5000-iteration linear cap. The nonlinear
1e-7 gate and experimental screening protocol are unchanged. This heavily
damped reference still develops nonfinite residuals on the tested runtime.
Do not describe it as numerically qualified, more accurate or faster.

The separate Cartesian auditor reconstructs volumes and local divergence from
the stored owner/neighbour face fluxes, with target max(abs(div(phi)))*H/U
<=1e-4. For this package it checks the first-cell distance and max(y+) <=1 on
every solid wall, using tangential stored wall traction. Its report separates
its own checks from the execution adapter's numerical verdict. It does not
reconstruct full momentum/turbulence residuals or validate SST against nature.

Measurement screening of the wall-resolved package additionally requires this
independent audit. A failed numerical/independent gate leaves the screen not
assessed. Refinement skips finer cases after a coarse case is not accepted.
The [tutorial](../../tutorials/backstep-resolution-prompt.md) and
[results](../../validation/RESOLUTION_RESULTS.md) retain those failures.

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

Logged NaN/Inf initial/final residuals or continuity values stop the process
group with CFD-X010, including a nonfinite log from a child that exits zero.
The guard polls a bounded log tail; the actual log, return code and progress
are retained. Earlier saved snapshots are not promoted to final solutions.

`report` verifies an archive's consistency: file hashes, the consumed inputs and
that the case holds nothing else besides solver outputs, the numerical summary
recomputed from the returned log and fields, status and error codes, command
return codes, the Foundation-13 runtime and log identity, progress and samples.
Unkeyed hashes are not tamper-evidence: a consistent rewrite of log, fields and
summary cannot be detected this way.
