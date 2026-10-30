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
SHA-256 before extraction. OpenFOAM remains separately licensed GPL software;
the generated case dictionaries and Python adapter are original CFD-craft code.

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

The mesh has 22656, 90624 or 203904 cells at levels 1,2,3. It is graded toward
walls and the step. Momentum advection uses bounded linear upwind; k/omega use
upwind. Pressure uses GAMG and SIMPLEC; the linear systems use absolute 1e-11
and relative 0.001 stopping targets in the backstep. A separate nonlinear gate
requires each final initial residual <=1e-7, explicit solver convergence, local
reported continuity <=1e-6, and stored boundary-flux imbalance <=1e-6. Final
cell fields are checked for finiteness and positive turbulence quantities.
Reported turbulence bounding messages are counted; they are not independently
instrumented floor events like the native solver's counter.

The protocol was frozen before comparing predictions with downstream data:
each station's U/Uref RMSE <=0.10, lower-wall Cf RMSE <=0.001, and reattachment
error <=0.75 H. These are development screening targets. The measured Cf file's
error column is retained without asserting an undocumented 95% confidence level.
The U profile file supplies no uncertainty interval. Cf uses the signed
kinematic wall traction, Cf=-2*tau_x/Uref^2, at the lower wall. All downstream
velocity sample identities are paired exactly; Cf interpolation cannot extrapolate.

## Interpretation and open gates

Execution, numerical convergence, measurement screening and physical
qualification have separate fields. A zero exit or a passed measurement screen
cannot make a nonconverged solve acceptable. The physical-qualification status
remains preliminary even if all development metrics pass: inlet uncertainty,
near-wall resolution, mesh sensitivity and model-form sensitivity require work.
Failed meshes remain in the report and are excluded from converged mesh pairs.
No GCI is manufactured from an incomplete or non-asymptotic series.

There are no passive-scalar measurements in this benchmark. This iteration
therefore does not validate gas dispersion, particles, the native RANS package
or a street canyon. CODASC and the native building-wall/throughput gates remain
open. See the recorded [external results](../../validation/EXTERNAL_RESULTS.md).

## Execution limits

The backend executes only trusted generated dictionaries in a copied fresh
directory. Input hashes detect changes; they are not a signature authorizing
untrusted OpenFOAM code. OpenFOAM itself can load user code, so do not substitute
unreviewed case directories. The adapter never shells out to construct commands.

The runtime is serial. Each child has a hard address-space limit and per-file
size limit; the overall output budget and wall time are polled every 50 ms.
There can be a small polling overshoot and manifests add metadata overhead.
SIGTERM/SIGINT and deadline expiry terminate the process group, with a forced
kill after one second if necessary. The log and failure archive are retained.
Hashing/manifest creation and the bounded runtime preflight add overhead outside
the child solve. These are CPU cases and require no desktop, GPU or home cluster.
