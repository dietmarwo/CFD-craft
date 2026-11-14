# Mobile-measurement source extension: numerical evidence
<!-- check: none: record of bounded synthetic experiments on 14 November 2026 -->

R1–R3 are implemented and synthetic gate GR passes on both committed-case
derivatives below. This verifies observation weights, frozen-flow responses,
inference and bounded route selection under the declared assumptions. It does
not close urban experimental validation, grid/rotation qualification or the
earlier district performance gates. Defaults remain unchanged. See
[the guide](../guide/24-mobile-source-inference.md).

## Identity and frozen gates

Base commit: `7d8d70a864383e92f431d8afdacd15864e6c1c54` (0.1.1).
Native mobile producer source SHA-256:
`bb0a97221837bafb1fc82e6c4f29c7f0a8bcf60e5fc5e21b4bfebebcfd75c845`.
Each report records the native example-driver, request and immutable-flow
hashes. The matrix additionally records its frozen study-plan and Python
driver hashes, complete sensor parameters and per-wind producer identities.
No raw map or measured ride dataset is needed for these synthetic fixtures.

Before execution, `tutorials/mobile_measurements.py` writes the plan and gates:
relative rate and held-out errors at most 1e-3, relative superposition defect
at most 1e-4, full training rank, disclosed alias ambiguity, and a certified
integer solution within 2e-6 normalized defect of exhaustive enumeration.
Thresholds were not relaxed after observing results.

Both studies use three source groups, multipliers [0.7,1.3,0.4], two winds,
two training and two held-out routes. Each wind executes one native flow
preparation, three scalar columns and one separate combined-truth scalar
solve, with zero flow updates during responses. All 20 final archives across
the two studies pass the independent stored-field audit, including every
path sample/mean, mass, represented geometry and frozen-flow fingerprint.
The independent combined truth is not formed by multiplying A by the truth.

## Path and supplied-street verification

The native Gaussian path interpolation fixture's relative RMS errors at
16/32/64/128 cells are 0.01173618/0.00291733/0.000728648/0.000199703.
A shrinking straight path versus its thin volume average gives differences
0.00492794/0.00123327/0.000308397, consistent with second-order convergence.
Other fixtures cover reversed samples, exact linearity, corner geometry,
continuous solid crossing between samples, solid interpolation support and
bounded sample allocation. Actual returned field samples and path means agree
with independent reconstruction. The first-order sensor reproduces analytic
step and ramp responses, preserves the exact final timestamp without duplicates,
and handles a zero response time.

The supplied-street converter fixture preserves multisegment lengths and
adds exactly 3.7e-6 kg/s from the supplied synthetic CSV. Tests include native
emitted-mass normalization, 90° map rotation, crop/domain clipping, an
intermediate thin-building intersection, positive-rate omissions, unknown IDs,
wrong units, malformed geometry and native coarse-mask rejection. The tool
consumes and hashes actual street/rate bytes; it invents no emission rate.
Malformed input produces a coded diagnostic under normal and optimized Python.

## GR results from actual native fields

| Study | Relative superposition defect | Relative rate error | Held-out relative error | Training rank | GR |
|---|---:|---:|---:|---:|---|
| Uniform laminar source-response, winds 270/250 | 3.153e-16 | 3.629e-16 | 2.212e-16 |3/3| Pass |
| WH1 canyon, winds 270/225 | 3.230e-8 | 2.859e-9 | 4.363e-7 |3/3| Pass |

The canyon uses the opt-in implicit flow recipe, fixed linear scalar transport
and coarse existing geometry. Its residual-level superposition error is
consistent with independently terminated scalar solves; it is below the frozen
gate. Whole held-out rides are excluded from fitting, weighting and selection.
The reference station is excluded from the fit. Appending a deliberately
collocated identical street-b response gives rank 3 of 4, nullity 1, with the
street-b/alias ambiguity named rather than individually interpreted.

The virtual sensor travels at 1.5 m/s, records every 0.25 s and has a 1 s response
time, starting at zero. Declared sensor sigma is 2e-10 kg/m3 and coherent
between-pass sigma 1e-9 kg/m3. Neither is sampled or estimated from data.

| Study | Selected route/wind opportunities | Riding + setup seconds | Budget seconds | Worst-direction information | Master solves |
|---|---|---:|---:|---:|---:|
| Source-response | Near at270 and250 |26.6667|36|236.1870|4|
| Canyon | Canyon path at270 and225 |32|36|79160.1633|4|

LP-IP-craft 0.29.0's native mixed integer solves and eigenvector cuts converge
within the 1e-7 normalized floating-point gap. All 16 candidate subsets are
independently enumerated for each four-candidate campaign; normalized objective
defects are below 2e-16. The selected matrices have rank 3. A separate five-route
fixture checks 32 patterns and a nontrivial optimum. Cut/time/native-solver
limits preserve the incumbent and actual failure/bounds without claiming a
certificate. No exact rational optimality proof is claimed.

## Conditional pass planning and station ratios

With a 10% relative mean half-width, Gaussian z=1.96, five effective independent
samples/pass and zero systematic floor, the assumed pass counts are:

| Study / wind | First training path | Second training path |
|---|---:|---:|
| Source-response270 |31|69|
| Source-response250 |45|102|
| Canyon270 |1|32|
| Canyon225 |1|15108|

The high downwind count at225° follows its tiny modeled increment and the
assumed pass scatter; it is retained. Counts are planning calculations, not
measured precision. A systematic uncertainty floor can make the target
unachievable; correlated drift and CFD error are not removed by repetition.

The canyon's modeled adjacent steady-path/station ratio is 1.0 at both winds
on this coarse field. The lagged, zero-initial sensor-mean/station ratios are
0.2693913 and 0.2499111. Short-ride warm-up is part of this observation operator.
These numbers neither validate sensors nor compare total ambient PM.

## Independent review and limits

Separate reviewers tested R1, R2 and R3. Fixed issues included exact endpoint
handling, bounded-memory tall-matrix SVD/whitening, complete named nullspace
coefficients for disparate source scales, malformed street input diagnostics,
frozen-flow adoption eligibility, timeout-row retention, original bent-route
geometry and exact consumed-byte fit provenance. Resealed changes to each flow
array, declared fingerprint or flow-update count are rejected by the independent
checker in both normal Python and `python -O`.

No measured concentrations, traffic counts or calibrated sensor response were
provided. V2 remains unopened under the
[mobile protocol](../../validation/protocols/mobile-rides.md). The existing
OpenFOAM backend still does not translate an urban dispersion case. All previous
[urban failures and open gates](urban-extension.md) remain part of the evidence;
synthetic GR is not a substitute for those qualifications.
