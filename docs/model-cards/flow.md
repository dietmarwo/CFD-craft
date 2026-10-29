# Flow model 0.1

## Scope

Constant-density incompressible flow, flat ground, uniform Cartesian cells, box masks, CPU f64. Face velocities and cell pressure share the same divergence/gradient definition. Local coordinates are east/north/up. Pressure is kinematic pressure in m2/s2; the isotropic 2k/3 contribution is absorbed in RANS pressure.

The momentum predictor uses first-order donor-cell advection of each staggered velocity component and an explicit variable-viscosity stencil. The extra variable-viscosity symmetric-stress contribution is reconstructed from cell gradients under the incompressibility assumption. It is not a claim of globally second-order momentum accuracy.

An incremental projection is applied to each SSPRK2 velocity stage. Tests recover second-order decay for periodic viscous shear. General unsteady open-boundary pressure order is not established by that fixture. The intended urban use is a checked steady solution.

## Pressure

The matrix-free operator is minus divergence times gradient. Internal faces have one shared flux. Pressure-outlet correction is zero; fixed normal-velocity faces use a homogeneous correction derivative. A closed fluid component has a mean-zero gauge and a compatibility check.

PCG uses a cached incomplete Cholesky factor with zero fill. A tiny shift regularizes only the preconditioner, not the solved operator. Recomputed residuals use the compatible mean-zero right-hand side in closed components. The nominal recurrent tolerance is checked against an independently formed operator residual, allowing a documented round-off margin of ten times the target plus 1e-12.

Projection residuals, actual face-flux continuity and boundary balance are separate checks. There is no multigrid, sparse direct factorization or MPI implementation in 0.1.

## Neutral turbulence package

The closure is nu_t = C_mu k² / epsilon. Constants are:

| Constant | Value |
|---|---:|
| C_mu | 0.09 |
| C_epsilon1 | 1.44 |
| C_epsilon2 | 1.92 |
| sigma_k | 1 |
| kappa | 0.4 |
| sigma_epsilon | kappa² / ((C_epsilon2-C_epsilon1) sqrt(C_mu)) = 1.111111... |

This coefficient choice supports the high-Re neutral log-layer equilibrium, rather than mixing an inlet profile with unrelated standard coefficients.

The inlet profiles are U = u_star/kappa log((z+z0)/z0), k = u_star²/sqrt(C_mu), and epsilon = u_star³/(kappa(z+z0)). Wind direction is meteorological direction from, so horizontal components are [-U sin(theta), -U cos(theta)].

Ground momentum uses a log-law stress based on adjacent tangential velocity. Wall dissipation follows C_mu^(3/4) k^(3/2)/(kappa distance), which remains meaningful at stagnation cells. Wall production uses the stress and k-derived friction scale. A cell with several wall faces, such as a canyon floor cell between two buildings, uses the mean of the wall production and of the wall dissipation over those faces, with equal weights. Building faces use a documented small effective roughness min(inlet z0, 0.001 cell width); this adaptation has no independent urban-wall validation yet.

That building-wall adaptation depends on cell width. A future qualification study must replace it with an explicit physical wall parameterization before treating refinement as a pure discretization study. The current canyon grid experiments combine numerical and wall-model sensitivity.

The upper boundary has zero normal velocity, the equilibrium tangential stress and reference k/epsilon diffusion treatment. That stress closure is what makes `ground_open_top` an open top, so laminar cases may not use it (CFD-E023): without the closure the top would act as a no-slip lid. This is a particular neutral-domain closure, not a reproduction of an arbitrary tunnel ceiling. Side faces are classified from the prescribed wind as inlet, pressure outlet or impermeable slip.

Turbulence destruction terms use positive implicit denominators. Wall epsilon is an explicit algebraic constraint; tiny k/epsilon floors are counted. Any floor event prevents numerical acceptance. Excessive eddy viscosity causes a reported divergence instead of silent clipping.

The counter covers state-update floors. The wall algebraic relation itself has a minimum epsilon of 1e-14 and is not separately counted by that field; its activity must be treated as an additional regime check before physical qualification.

## Evidence and limitations

Verification covers Poisson/projection identities, gauges, analytic channels, Couette flow, periodic viscous shear and the Re=100 lid cavity. The empty-ABL test compares near-outlet U/k/epsilon to the inlet at heights H..5H under frozen tolerances. It is a consistency check for this setup. The suite also reports, without a gate, the drift below H. There the cell-centered velocity gradient of the second cell overestimates the logarithmic gradient, so production and epsilon run high: on the canonical empty-ABL grid epsilon is up to 16 % above the inlet profile below H (U 4 %, k 4 %), and more on coarser vertical grids. A log-consistent near-wall gradient is an open improvement.

The illustrative canyon examples are not exact CODASC geometry/inflow reproductions. Their coarse-grid numerical convergence does not validate urban dispersion. Fine-grid pressure/explicit-time throughput is an open performance gate. No buoyancy, stratification, traffic turbulence, particles, vegetation, chemistry or unsteady turbulent statistics are represented.

Method references: Richards and Hoxey (1993), Richards and Norris (2011), and the [OpenFOAM atmospheric-boundary implementation documentation](https://cpp.openfoam.org/v13/atmBoundaryLayer_8H_source.html). No OpenFOAM source code is included.
