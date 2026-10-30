# Iteration 05: coarse-to-fine initialization results

Date: 30 October 2026. Base: merged PR #5,
`e6134cd2e74d675819b8acd696af7d813c06809b`.
See the [plan](../docs/iterations/05-mesh-initialization-plan.md) and
[guide](../integrations/MESH_INITIALIZATION.md). The merged
[continuation results](RESTART_RESULTS.md) remain the record of the accepted
staged coarse backstep; they are not replaced by this cavity experiment.

## Result and decision

Explicit one-level nearest-cell volume initialization is implemented and
verified on actual Foundation-13 meshes. It preserves generated fine-grid
boundaries and does not transfer coarse phi. The accepted source and final
fine fields have separate checks. The existing same-mesh source-flux gate
stays unchanged; the early SIMPLEC restart failure in the review does not
justify weakening it.

Only current cold-generated sources with numerical acceptance and a passing
independent audit are supported in this first release. The recorded cold
coarse control qualifies; restarted/mapped sources are excluded for new-mesh
mapping. A completed mapped run can supply a subsequent same-mesh continuation.
All original source, final nonlinear, wall-y+ and measurement targets remain.

## Actual cavity comparison

Foundation 13 package 20260407, build 13-441953dfbb42, serial/f64/32-bit labels,
cloud CPU. The 24x24 Re=100 source is mapped to a fresh 48x48 case using the
separate mapFields utility. Compare the converged fine result with a cold
48x48 control under identical final physics/numerical settings.

| Check | Mapped fine / control | Frozen target |
|---|---|---|
| Final numerical gates | pass / pass | both pass |
| Fine iterations | 1356 / 2132 | reported, no performance gate |
| Maximum U difference | 5.111148e-09 m/s | <=1e-4 |
| Maximum anchored p difference | 2.45290251e-09 m2/s2 | <=1e-4; no offset removed |
| Maximum local div(phi)*H/U | 1.67052e-9 / 1.67193e-9 | <=1e-4 each |
| Ghia centerline error | 0.0070799887 / 0.0070799840 | <=0.06 each |

The source took 696 iterations and 1.268 s;
preparation (verification, copying, meshing, mapping and sealing) took
0.761 s. Mapped and cold fine solves took
4.593 / 6.862 s;
the complete comparison took 13.854 s on this run. Source-grid
work is additional, not fine-grid iterations. These observations from one run
are not a performance ranking. All bounds above were declared before the runs.
The report records implementation and Ghia CSV identities.

An independent test on the uniform cavity checks every mapped value against
the expected coarse cell and checks exact target boundary preservation.
Other real tests continue a mapped result on the same fine mesh, reject
runtime/rebuilt-mesh mismatch before solving, preserve failed initialization
evidence and reject source-copy races and nonaccepted sources.

## SST format coverage and limits

Real Foundation-13 blockMesh and mapFields run on the existing 48896/195584-cell
backstep meshes with synthetic, uniform U/p/k/omega/nut fields. This tests field
formats, empty/solid/inlet patches and exact target boundary preservation.
It is **not an accepted turbulent-flow source or fine backstep result**. The
factory's source acceptance/audit requirements are not bypassed in production.
No GCI, turbulent mesh independence, scalar/canyon validation or new physical
qualification is claimed. A cold accepted coarse archive is needed for the next
real fine-backstep campaign.

## Software and evidence

- 22 new mapping tests pass normally and under optimized Python: 14 receipt/
  workflow tests and 8 actual-runtime tests. The SST utility fixture is labeled
  synthetic; actual accepted-flow claims are limited to the cavity.
- Existing 54 continuation, 41 resolution, 38 external and 35 native CLI tests
  pass in both Python modes with the runtime enabled where applicable.
- Rust formatting, Clippy with warnings denied and 32 locked release tests pass;
  the same 32 tests pass on Rust 1.88.0. Ruff passes.
- Native analytic/empty-ABL verification passes unchanged targets.

The final experiment was executed in a private temporary directory and all
three complete run archives were verified before and after copying. An earlier
workspace experiment acquired an old time directory after sealing and was
rejected by the existing progress/archive checks. Its failure is retained as
prototype evidence. The cause remains unproven; no verification rule was
weakened to ignore extra snapshots.

```sh
python validation/mapping_equivalence.py --foam-root ROOT --timeout-s 120 \
  --output NEW_CAVITY_EXPERIMENT
```

The experiment exits 0 on the bounds above, 2 for unaccepted returned evidence,
and 1 for an input/workflow error. The optional external CI backend job now
runs this cavity verification and retains its archives; no remote job was
triggered during this delivery. The [guide](../integrations/MESH_INITIALIZATION.md)
provides source/target commands for a future bounded backstep campaign.
