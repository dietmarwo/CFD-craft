# Matched-accuracy measurement against OpenFOAM (stage M)

Date: 1 November 2026. Protocol: stage M of the
[accuracy and steady-solver plan](../docs/ACCURACY_STEADY_PLAN.md), run through the
`external=momentum` CI selection, which was declared for Stage V and extended
with the `native_numerics` and `momentum_scheme` inputs.

## Hosted run

[Run 41345659321](https://github.com/dietmarwo/CFD-craft/actions/runs/41345659321)
on branch head `4973d3c`: GitHub runner, Intel Xeon Platinum 8370C, 4 CPUs, one
solver thread for both backends. Inputs: `momentum_scheme=van_leer`,
`native_numerics={"momentum_advection": "limited_upwind", "momentum_limiter": "van_leer", "steady_algorithm": "implicit_projection"}`.
Unchanged from Stage V: the shared grids 16, 24, 32 and 48 for both backends, one
warmup plus three timed rounds alternating the backends, native budgets 600 s and
20,000 steps, native multigrid pressure, the OpenFOAM recipe (3,000 iterations,
180 s), the archive and field audits, the 0.06 Ghia screen and the 0.01 target.

All 32 rows were accepted, and the evidence archive verified all 51 sealed
archives after the zip round trip.

| Grid | Native solver s | OpenFOAM solver s | Native/OpenFOAM | Native Ghia error | OpenFOAM Ghia error |
|---|---:|---:|---:|---:|---:|
| 16² | 0.236 | 0.320 | 0.74× | 0.0243 | 0.0188 |
| 24² | 0.549 | 0.743 | 0.74× | **0.00543** | **0.00897** |
| 32² | 0.967 | 1.612 | 0.60× | 0.00365 | 0.00870 |
| 48² | 3.041 | 6.002 | 0.51× | 0.00502 | 0.00708 |

Medians of three rounds. Workflow medians (including meshing, sampling and
audits) are 0.348/0.994 s, 0.654/1.453 s, 1.060/2.316 s and 3.180/6.808 s.

**Both backends first reach the 0.01 target at 24². There the native solver
takes 0.74× OpenFOAM's solver time and 0.45× its workflow time
(`native_over_openfoam_at_target`), and is more accurate (0.0054 against
0.0090).** On every grid from 24² up, native is both faster and more accurate.
At 16² native is faster but less accurate than OpenFOAM, and neither reaches
the target.

## How the gap closed

The same protocol with the earlier default numerics (Stage V, hosted run
41302658721, another runner) gave a native/OpenFOAM solver ratio of 6.98× at 24²
with native missing the target on every shared grid; native needed 96² and
about 826 s to reach 0.01. The changes, each opt-in:

| Change | Effect on the 24² cavity (local host) |
|---|---|
| P3a: `limited_upwind`/`van_leer` momentum advection | Ghia error 0.0276 → 0.0054; the target is reached at 24² instead of 96² |
| P5a: `implicit_projection` steady algorithm | 2,460 explicit steps → 210 outer iterations; solver time 9.4 → 0.51 s |

The explicit mode with the same scheme isolates the two levers. In the
accuracy sweep of [run 41346827479](https://github.com/dietmarwo/CFD-craft/actions/runs/41346827479)
(`external=accuracy`, `native_numerics={"momentum_advection": "limited_upwind", "momentum_limiter": "van_leer"}`,
branch head `4973d3c`, AMD EPYC 7763, 4 CPUs, three rounds), van Leer with the
explicit steady mode also first reaches the target at 24² (Ghia error 0.00544,
OpenFOAM 0.00897), but its solver time there is 11.19 s against OpenFOAM's
0.844 s, **13.25×** (workflow 7.47×). At 48² it takes 136.5 s against 6.48 s.
So P3a moves the target to the coarse grid, and P5a removes the cost of the
explicit pseudo-time on it.

## After the performance iterations

[Run 41361132558](https://github.com/dietmarwo/CFD-craft/actions/runs/41361132558)
repeats the protocol with the final implicit recipe (pressure tolerance 0.1,
non-binding `max_time_step_s`, one span cell; see the
[performance iterations](PERFORMANCE_ITERATIONS_RESULTS.md)) on an AMD EPYC
9V74 runner. All rows were accepted. At 24² native takes **0.0698 s against
OpenFOAM's 0.628 s (0.111×)**, workflow 0.119×, with Ghia error 0.00543
against 0.00897; 0.092×, 0.101× and 0.081× at 16², 32² and 48². The 96²
reference took 570 outer iterations and 3.39 s. Default controls stayed
byte-identical to `main`.

## Other results of the run

- **Momentum fixtures (van Leer):** translating-vortex orders 2.159 / 2.062 /
  1.761 (L1 / L2 / max), momentum drift at most 5.7e-17 per run, time difference
  2.0e-4 of the spatial error, transverse step range 0.0009–0.9991 with no new
  extrema. These equal the local values.
- **96² reference with the same numerics:** accepted after 990 outer iterations
  and 48.5 s (the explicit van Leer reference needed 22,830 steps and 1,742 s
  locally), Ghia error 0.00505. Self-convergence orders against it: 2.45 (L1),
  2.42 (L2), 2.21 (max).
- **Default controls:** the cavity, a transient Poiseuille run and a masked
  canyon are byte-identical to `main` (`6d33850`) with identical work.

## Scope

The cavity is laminar and two-dimensional. The ratio describes this case, these
recipes and this runner: in run 41345659321 native computed two span cells
and OpenFOAM one (in run 41361132558 both compute one), and the two stopping
rules differ (native: the unchanged `assess` gates with three stable monitor
windows; OpenFOAM: `residualControl` 1e-7). It does not transfer to the RANS
canyon: `implicit_projection` now runs it
([results](IMPLICIT_RANS_RESULTS.md)), but there is no OpenFOAM canyon recipe
to compare with. Defaults are unchanged: donor-cell and the explicit mode remain the
default numerics until a separate, announced decision.
