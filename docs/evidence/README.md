# About the evidence

Version 0.1.1 is a research prototype. A numerically accepted run is not an
experimentally validated prediction.

These pages are the committed records of measurements: what was run, on which
code and machine, what came out, and what failed. Pages elsewhere quote their
numbers with a link to the record.

## What counts as evidence here

- A record names the commands, the code revision or source fingerprint, the
  machine and, where it has one, the CI run. Numbers come from the returned
  reports, never from a hand estimate.
- Failed, incomplete and rejected rows stay in the record. A later record adds
  rows; it does not rewrite earlier ones.
- Termination (did a run complete), numerical assessment (is a result
  accepted) and experimental validation (does a model match measurements) are
  separate. No record here validates a model against measurements of the use
  case: the street-canyon data could not be obtained.

What does not count: a wall time read as a target on another machine, a
same-grid speed ratio read as cost at matched accuracy, an iterate of a solve
that did not pass its numerical gate, and a comparison with a numerical
reference (the Ghia et al. cavity) read as a comparison with an experiment.
The Driver and Seegmiller backstep measurements are the one experimental data
set, and only the OpenFOAM backend is compared with them.

## The records

Each line gives the date the record states. "Current" means no later record
replaces its rows; a later record that adds to it is named.

**Native verification**

- [Native verification](native-verification.md): analytic orders, transport, cavity, empty ABL, coarse canyons, memory; the record gives no date. Current; its canyon timings use default numerics (opt-in timings in [implicit RANS](implicit-rans.md)).
- [Momentum verification](momentum-verification.md): donor-cell order and the paired cavity baseline; 1 November 2026. Current as the default-numerics baseline; its stage table is the plan as recorded.

**Native numerics campaigns**

- [Native CPU performance](native-cpu-performance.md): eight kernel increments against the previous build, bit-identical results; the record gives no date. Current.
- [Pressure multigrid](pressure-multigrid.md): opt-in point multigrid on the cavity and shapes; 31 October 2026. The record calls itself historical; the line and semicoarsening version is in [anisotropic pressure](anisotropic-pressure.md).
- [Anisotropic pressure multigrid](anisotropic-pressure.md): line and small-plane blocks on stretched grids; 31 October 2026. Current.
- [Second-order momentum](second-order-momentum.md): opt-in momentum schemes and the cavity sweep; 1 November 2026. Current.
- [Implicit steady iteration](implicit-steady.md): `implicit_viscous` (fixed-point gate failed) and `implicit_projection`; 1 November 2026. Current; later recipe timings in [performance iterations](performance-iterations.md).
- [Implicit steady iteration with RANS](implicit-rans.md): RANS and constituents with `implicit_projection`, canyons at 27k and 93k cells; 1 November 2026. Current; the canyon is not grid-converged.
- [Performance iterations](performance-iterations.md): ten iterations and the final implicit recipe; 1 November 2026. Current.

**Native against OpenFOAM** (Re = 100 cavity only)

- [Backend comparison](backend-comparison.md): default numerics, OpenFOAM faster and closer to the reference; the record gives no date. Current for default numerics; opt-in numerics in [matched accuracy](matched-accuracy.md).
- [Gap baseline](gap-baseline.md): same-host accuracy, cost and phase attribution; 31 October 2026. A baseline; the later state is in [performance gap status](performance-gap-status.md).
- [Matched accuracy](matched-accuracy.md): both backends at the 0.01 target with opt-in numerics; 1 November 2026. Current, with a later run added in the record itself.
- [Performance gap status](performance-gap-status.md): dated sections, newest first; latest 1 November 2026. Current summary.

**OpenFOAM backend campaigns**

- [External backend](external-backend.md): cavity against the reference, legacy backstep (stalled, not accepted); the record gives no date. Current for the cavity; the wall-resolved recipe is in [backstep resolution](backstep-resolution.md).
- [Backstep resolution](backstep-resolution.md): wall-resolved level-1 backstep accepted on one mesh; the record gives no date. Current.
- [Steady continuation](steady-continuation.md): a staged solve equals one uninterrupted run; the record gives no date. Current.
- [Mesh initialization](mesh-initialization.md): mapped against cold starts, no accepted level 2; the record gives no date. Current.
- [Refinement campaign](refinement-campaign.md): three stages, `stage_limit`, no accepted fine grid; 31 October 2026. Current.

**Optimization lessons**

- [Optimization lessons](optimization-lessons.md): F1 to F3, including the failed fidelity gate of F3; the record gives no date. Current.

## Open gates

- **Measured canyon data.** The raw wind-tunnel files and their terms were not
  obtained ([data inventory](https://github.com/dietmarwo/CFD-craft/blob/main/validation/data-inventory.json));
  no canyon result is experimentally validated.
- **Grid study.** The native canyon is not grid-converged, and the OpenFOAM
  backstep has no accepted pair of meshes, so there is no grid-convergence
  index for either.
- **Same-case comparison.** There is no OpenFOAM canyon recipe, so no canyon
  comparison between the two solvers exists.
