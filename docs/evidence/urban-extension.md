# Urban source extension: verification and open gates
<!-- check: none: record of bounded experiments on 14 November 2026 -->

The source extension implements U0–U7's numerical features and campaign
infrastructure from the urban plan. It does **not** pass the plan's practical
urban qualification gates. Masked multigrid is numerically verified but has no
consistent coupled gain; the rotated-canyon and district runs retain failures.
Defaults are unchanged. No release is tagged and no experimental validation
claim is made. See [guide chapter 22](../guide/22-urban-geometry-particles-vegetation.md).

## Source and measurement scope

Base: `7d8d70a864383e92f431d8afdacd15864e6c1c54` (0.1.1, latest main when
checked out). An isolated clean build independently confirmed the original
IC0 producer source fingerprint
`ce85729bc3564d2658ce6894e232e69da981a07ac36fde4512c5468ba05866fc`.
The U0–U7 evidence producer's source-extension CLI fingerprint is
`786eb87c9f81b86fd1f8aa8aa947d090524abeedd5d6de3ef0eb2daceba30a72`.
The later R1–R3 producer and its separate synthetic gate are recorded in
[mobile evidence](mobile-measurements.md); these earlier experiments were not
silently relabeled as runs of that implementation.
Compiler: rustc 1.100.0, x86_64 Linux. Each numerical run requests one thread;
the district campaign uses two concurrent workers. Timings are one cold run
per recipe on a shared cloud host, with complete setup/phase profiles. They
are exploratory measurements, not a repeated statistical speed ranking.

The provisional G0 target is an accepted one-million-cell steady district run
within two hours on one CPU thread, with a 6144 MiB preflight budget and independent
field audit. This target is declared for future qualification, not achieved
by the present short-budget experiment. The synthetic block has 20 buildings,
a 200 m × 200 m × 60 m domain and 5H/15H/5H clearances for its declared prevailing wind.
The 4 m grid has37,500 cells; the 2 m grid has300,000.

## Coupled performance: G1 remains open

Solver elapsed time below includes native setup/solve scope; launcher and archive
overheads are retained separately in the detailed records.

| Case | IC0 seconds | Multigrid seconds | Outer steps each | Independent fields | IC0/MG time |
|---|---:|---:|---:|---|---:|
| Synthetic block,37,500 cells | 30.4519 | 33.5757 | 400 | Both pass | 0.907 |
| Canyon, 27,648 cells | 66.4748 | 63.4473 | 1100 | Both pass | 1.048 |
| Canyon, 93,312 cells | 816.9110 | 869.2023 | 3000 | Both pass | 0.940 |
| Synthetic block, 300,000 cells | 60.2711 | 60.5119 | 50/54 | Both incomplete; continuity audit fails | No ratio |

The accepted field comparisons use bounds declared before comparison:
maximum velocity difference 1e-4 m/s, pressure difference 1e-3 m2/s2, and receptor
relative difference 1%. Actual velocity/pressure differences are about 1e-15
on both canyon grids; receptor differences are 4.43e-10 and 3.27e-11 relative.
Both methods solve the unchanged fine equation to the existing native and
independent archived-field checks. There is no accuracy-for-speed trade.

The 27k gain is small and absent on 93k and the block. Therefore G1's coupled
gain requirement is not met, and U2 keeps donor-cell/explicit/IC0 defaults.
The opt-in implicit recipe remains available as an explicit case copy.

## U1/P2c: setup and pressure work

| Case | MG setup seconds | IC0 pressure iterations | MG pressure iterations |
|---|---:|---:|---:|
| 37,500-cell block | 0.03923 | 2794 | 510 |
| 27k canyon | 0.006855 | 5890 | 2019 |
| 93k canyon | 0.07484 | 12827 | 4231 |

Each hierarchy builds once and is reused. Fewer PCG iterations do not imply
lower coupled cost. Masked connected-aggregate verification covers exact
Galerkin products, full-cycle symmetry/positive energy, independent pivoted
dense reference solutions, sealed/anchored/singleton components, barriers,
passages, cache rebuilding, projection and transactional cancellation.

The original sequential campaign recorded `RUSAGE_CHILDREN.ru_maxrss`, a
cumulative maximum over all preceding children. Its later rows must not be
read as per-case RSS. The durable 93k replays independently sampled 245,300 KiB
(IC0) and 273,484 KiB (MG). Profiles/fields identify every producer. An initial
IC0 session interruption is retained separately; the bounded replay supplies
the completed 93k result.

## Geometry and G3

Boxes, simple concave prisms, equivalent 0°/90° masks, exact shape volumes,
represented volume errors, adjacent passage resolution, diagnostic paths and
empty-ABL roughness controls pass. The independent checker rebuilds polygon
masks, shape counts/volumes/passages and rejects forged geometry evidence.
A positive optional non-ground wall roughness is independent of cell width;
omission preserves the legacy wall recipe.

The frozen 45° study uses 32×32×12 and 64×64×24 grids, 90 s per run, receptor
relative bounds 35%/25%, and requires shrinking error. It **does not pass**:

| Grid | Aligned | 45° |
|---|---|---|
| 12,288 cells | Accepted in 10.153 s, 400 steps | Rejected: receptor stencil crosses a stair-stepped solid(`CFD-E042`) |
| 98,304 cells | 90.092 s timeout, 285 steps | 90.111 s timeout, 260 steps |

No rotation accuracy ratio is reported for rejected/incomplete pairs. The
strict interpolation rule is preserved. Wider passages, sufficiently resolved
sampling and a complete frozen refinement study are needed before claiming
orientation independence; improved wall treatment remains a possible follow-up.

## Particle and vegetation verification

| Fixture | Result |
|---|---|
| Falling layer cumulative mass budget | Relative defect 3.47e-16 |
| Periodic settling L1, 32/64/128 cells |0.0053689/0.0027203/0.0013672 |
| Wind-plume centroid |(0.390000000000005,0.539999999999995), analytic(0.39,0.54) |
| Complete steady settling–diffusion/source column, 16/32/64 | Relative RMS 1.760%/0.894%/0.451%; first-order boundary/spatial refinement |
| Column steady source/deposition rates | Agree within frozen 1.1e-6; maximum cumulative mass defect 1.08e-13 |
| Uniform-force canopy speed | Matches sqrt(0.08) with zero measured error |
| Porous-block pressure drop |0.799999999965 versus integrated drag0.800000000000 |
| Uniform leaf decay | Relative error 1.07e-6, mass defect 1.47e-15 |
| Leaf-block refinement | Relative errors 3.26e-4/8.10e-5/2.05e-5 |
| Active-canopy transient momentum | Verified first-order time convergence |
| Zero leaf area density | Entire numerical State bytes and empty-ABL terms unchanged |

The complete column supplements the earlier interior manufactured exponential
residual test. It starts cold, includes its top-layer source and boundary
balance, and permits steady particle sources only when a represented removal
path exists in their fluid component. Gas outlet rules are preserved. Other
regressions cover one-cell periodic drift, periodic roof deposition,
near-buoyant aerodynamic diameter, positivity, units, superposition and exact
checkpoint continuation. Instantaneous discrete canopy work is recomputed
from staggered face fields; cumulative deposited mass is checkpointed.

Case/physics identities record declared zero-LAD input, so identity fields and
full archives differ; byte identity applies to the complete numerical State.
No gas, particle or canopy field is experimentally validated by these tests.

## Delft district: G7 infrastructure works, steady study not ready

Data: 3DBAG v2025.09.03, tile 9-284-556, EPSG 7415, CC BY4.0;
credit **© 3DBAG by tudelft3d and 3DGI**. Source:
[download](https://data.3dbag.nl/v20250903/tiles/9/284/556/9-284-556.city.json.gz),
[license](https://docs.3dbag.nl/en/copyright/).
No user site was supplied; this is a public demonstration crop in Delft.
The converter records 21 input objects, retains 5 prisms at 3 m, and records 16
below-two-cell omissions. Ground elevation range 0.413 m is within the declared
0.5 m screen. Buildings are cropped/rotated/simplified and terrain flattened;
15H clearances are used on all horizontal sides. Source emission 1e-7 kg/s and
one porous canopy are synthetic additions, not measured traffic or vegetation.
The raw map is not committed.

The 183,260-cell ensemble has twelve cold local directions 0, 30, …, 330°, 45 s per
run, one thread each, two concurrent workers and 720 s total budget. All twelve
rows are retained; all twelve are incomplete timeouts. Workflow elapsed 296.18 s
is inside the budget. These are failed study rows, not concentration predictions.
Their incomplete local continuity audits also fail where recorded; mass
closure alone does not make them accepted.

The same physical footprints, source, canopy and domain were refined to
1,466,080 cells on local 270° (geographic 247° after 23° map rotation). With a 45 s
solver budget and 6,144 MiB preflight budget it reached 5 steps in 46.83 s and remained
incomplete. Observed peak RSS was 3,844,560 KiB. The raw fine job omitted its map
rotation metadata and initially labeled geographic 270°; a declared derived
metadata correction sets 247° without changing native input or fields.
No grid-convergence conclusion is available from these incomplete runs.

The fine profile gives pressure solve 5.34 s (11.4%) and scalar transport 11.89 s
(25.4%) of 46.83 s; setup is separate. Coarse district profiles put pressure near
5–6% and scalar transport near40%. These are partial-run profiles.

A separate one-second orchestration smoke repeated all twelve directions
through the pinned optimization-jobs trusted-command runner. All twelve
failed rows, native archive ZIPs and verified runner manifests were retained
in 39.26 s. This verifies orchestration/failure preservation, not convergence.
An initial command-output cap error was fixed to the runner's 64 MiB limit and
its twelve rejected rows were kept. `app.cfd.wind-direction` also completed
one actual SDK evaluation with zero failed/cancelled evaluations.

## Validation and GPU decisions

U8 is not triggered: pressure is not the dominant measured cost, including the
million-cell sensitivity run. No GPU backend or speed/parity claim is added.
V1's urban OpenFOAM translator/comparison remains pending; this host has no
OpenFOAM installation, and the existing backend still supports its earlier two
cases. V2 remains blocked on measured urban data/terms; no contact or agreement
was made. Existing data inventory and CODASC protocol remain authoritative.
The published backstep evidence does not validate urban PM or vegetation.

The next useful performance work follows the measured coupled profile:
scalar substeps/canopy coefficient reuse, momentum residual and turbulence
work. Re-run the same accepted 27k/93k fields and the frozen district/rotation
gates before changing defaults or recommending district optimization campaigns.
