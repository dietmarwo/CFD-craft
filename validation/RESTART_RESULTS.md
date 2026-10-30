# Iteration 04: steady continuation results

Date: 30 October 2026. Base: merged PR #4,
`dee9c5afb9ef5ab8455f3d2b5da4651e2cb39035`.
The [plan](../docs/iterations/04-steady-continuation-plan.md) records targets and
review amendments. [Iteration 03 results](RESOLUTION_RESULTS.md) remain the
record of the merged, accepted coarse SIMPLEC backstep. Its 18412-iteration
convergence supersedes the earlier divergent mesh. This iteration preserves
that geometry, solver package and all acceptance targets.

## Result and scope

Verified same-mesh steady field continuation is implemented. Cavity and short
SST split/control field comparisons meet their preregistered equivalence
bounds. The new source-flux gate correctly rejects an early SIMPLEC prefix.
The iteration adds no accepted finer-grid backstep or physical qualification.

All experiments use the pinned Foundation-13 `20260407` package,
`13-441953dfbb42`, serial/f64/32-bit labels, on Ubuntu 24.04.3 x86_64 with
Python 3.12.14, AMD EPYC 9V74, an eight-core CPU quota and 8 GiB memory limit.
No owner workstation, GPU or MPI was used. Timings below are observations on
this machine, not performance rankings.

## Cavity: actual fields and numerical gate

A 400-iteration stage followed by a 200-iteration restart is compared with an
uninterrupted 600-iteration Re=100 cavity. All fixed dictionaries, cold initial
fields and runtimes match, the source phi is copied byte-for-byte, and the
final independent local-flux audits pass. Maximum differences are
1.0269563e-15 m/s in U and
6.6064205e-16 m2/s2 in p after
removing a constant pressure offset, against the 1e-6 bounds. Work is 600
iterations on each path. These 600-iteration fields have not reached the
nonlinear gate and are not reported as converged.

A separate public-CLI restart from iteration 400 converges after 296 new
iterations (696 cumulative), passing the unchanged numerical gate and
independent audit. A run ending at 400 now retains its actual final field:
previously cadence 250 left only iteration 250, and assessment failed. The
write-cadence fix changes I/O only; defaults 6000 and 20000 retain cadence 250.

## SST SIMPLE: bounded field-equivalence fixture

Use the existing wall-resolved/simple stability profile on all three runs,
48896 cells: 250 iterations, a further 250 from stored fields/phi, and a
separate uninterrupted 500-iteration control. This is not a replacement for
the accepted SIMPLEC accuracy reference. Neither short path converges, and
both measurement screens remain not assessed (null).

| Field | Maximum absolute difference | Difference / max control magnitude | Equivalence |
|---|---:|---:|---|
| U | 1.5451949e-06 | 1.4256997e-06 | pass |
| p | 2.6316143e-07 | 2.1649687e-06 | pass |
| k | 2.5953899e-08 | 1.0993704e-06 | pass |
| omega | 0.00015490321 | 1.4582152e-08 | pass |
| nut | 7.9951197e-09 | 1.8176178e-06 | pass |

For p a constant offset of
2.5515059e-08 m2/s2 is removed. U/p
bounds are 1e-5; k/omega/nut use a 1e-5 normalized bound. The maximum normalized
turbulence difference is 1.82e-6. These tolerances were declared before this
comparison. Small measured differences are retained; no bitwise-equivalence
claim is made because solver history/caches reset.

Maximum local normalized divergence is 1.47021e-11 at the source,
1.28047e-11 in the split result and 1.24424e-11 in the continuous result,
against 1e-4. The full wall/flux audit is **not passed**: final step-wall y+
is 1.41049, and upstream/upper maxima are 1.05078/1.11779, above 1.
Thus passing continuation equivalence and local flux is not passing the
wall-resolution or nonlinear/measurement gates. The source step-wall maximum
is 3.25172. These early fields are initialization/equivalence fixtures only.

Source, second stage and control took 111.77, 113.97 and 219.48 seconds,
respectively, under 600-second per-run limits. Cumulative work is 500 on each
path. Fixed physics/cold inputs, actual mesh and runtime identities match;
initial phi and all transferred fields retain their source hashes.

## Early SIMPLEC prefix: rejected, retained

The initially planned 500+500 versus 1000 reference-profile comparison cannot
start its second stage: at iteration 500 the source's maximum local normalized
divergence is 0.00483124, above 1e-4. Its reported mean continuity is only
3.56323e-8 and boundary imbalance 8.61752e-9; these do not establish the
worst-cell flux gate. The standalone restart request fails with CFD-X012 and
no destination input is created. The original negative experiment is retained.

The actual automatic study with `--iterations 500 --max-stages 2` records one
completed but unaccepted stage and its continuation-stop reason. It exits 2,
`workflow_completed=true`, `passed=false`, with levels 2 and 3 explicitly not
started. It does not spend on a second stage or finer mesh. Numerical,
independent wall/flux and measurement verdicts describe the returned final
iterate; the measurement screen remains null. Other preparation/archive/I/O
errors still make the workflow fail with exit 1.

This establishes an eligibility limit, not a reason to weaken the source gate.
Longer completed SIMPLEC stages may be needed. Same-mesh continuation does not
guarantee that a fine-grid cold start can supply an eligible prefix within a
single run budget; cross-mesh initialization remains separate work.

## Software checks and reproduction

- Rust formatting, Clippy with warnings denied, and 32 locked release tests
  pass on current Rust; the same 32 tests pass with Rust 1.88.0.
- Ruff passes; native CLI 35, external 38, resolution 41 and new continuation
  22 tests pass normally and with optimized Python, actual runtime enabled.
- Native analytic/empty-ABL verification passes unchanged thresholds.
- The applied patch passes the 22 actual-runtime continuation tests in both
  Python modes and Ruff on a pristine base checkout.

The ZIP includes complete selected run archives, exact experiment scripts,
source identities, test logs and the revised plan. No external program binary
or raw measurement download is redistributed. The scripts reproduce the
positive cavity/SST and negative early-prefix comparisons; use fresh outputs
and the verified measurement download where required. The public workflow is:

```sh
python tutorials/backstep_resolution.py --preset study --iterations 500 \
  --max-stages 2 --timeout-s 180 --foam-root ROOT --data VERIFIED_DATA \
  --output NEW_OUTPUT
```

That deliberately short command demonstrates a retained flux-gate stop, not
expected convergence. For practical continuation see the
[guide](../integrations/STEADY_RESTART.md). CI now retains complete resolution
archives, including fields and seals, for later continuation. No remote CI job
was dispatched by this delivery. Fine/coarse sensitivity, inlet uncertainty,
model-form sensitivity and native canyon/scalar validation remain open.
