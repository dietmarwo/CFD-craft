// Explicit tensor indices keep the stencil equations readable.
#![allow(clippy::needless_range_loop)]
use crate::{
    case::*,
    grid::{FaceKind, Grid},
    transport,
};
use rayon::prelude::*;

pub const C_MU: f64 = 0.09;
pub const C1: f64 = 1.44;
pub const C2: f64 = 1.92;
pub const SIGMA_EPSILON: f64 = 0.4 * 0.4 / ((C2 - C1) * 0.3);
pub fn eddy_viscosity(g: &Grid, k: &[f64], eps: &[f64]) -> Vec<f64> {
    (0..g.count())
        .map(|i| {
            if g.fluid[i] && eps[i] > 0.0 {
                C_MU * k[i] * k[i] / eps[i]
            } else {
                0.0
            }
        })
        .collect()
}
pub(crate) fn adjacent_mean(f: &crate::grid::Face, v: &[f64]) -> f64 {
    match (f.lo, f.hi) {
        (Some(i), Some(j)) => 0.5 * (v[i] + v[j]),
        (Some(i), None) | (None, Some(i)) => v[i],
        _ => 0.0,
    }
}
#[allow(clippy::too_many_arguments)]
pub(crate) fn wall_ghost(
    c: &Case,
    g: &Grid,
    fi: usize,
    d: usize,
    side: isize,
    u: &[f64],
    nut: &[f64],
    cell_u: &[[f64; 3]],
) -> f64 {
    ghost_value(c, g, fi, d, side, u[fi], nut, cell_u)
}
/// The ghost value of face `fi` beyond direction `d` and `side`, for the face
/// value `value`. It is affine in `value` with `nut` and `cell_u` held fixed,
/// which is how the implicit steady iterations read its coefficient.
#[allow(clippy::too_many_arguments)]
pub(crate) fn ghost_value(
    c: &Case,
    g: &Grid,
    fi: usize,
    d: usize,
    side: isize,
    value: f64,
    nut: &[f64],
    cell_u: &[[f64; 3]],
) -> f64 {
    ghost_values(c, g, fi, d, side, [value], nut, cell_u)[0]
}
/// `ghost_value` for several face values at once: the boundary branch, the wall
/// speed and the logarithms are evaluated once, and each value then goes
/// through the same arithmetic as a single call.
#[allow(clippy::too_many_arguments)]
pub(crate) fn ghost_values<const N: usize>(
    c: &Case,
    g: &Grid,
    fi: usize,
    d: usize,
    side: isize,
    values: [f64; N],
    nut: &[f64],
    cell_u: &[[f64; 3]],
) -> [f64; N] {
    let f = &g.faces[fi];
    let at_domain = if side < 0 {
        f.center[d] < g.dx[d]
    } else {
        f.center[d] > c.domain.size_m[d] - g.dx[d]
    };
    let bc = c.boundaries.at(d);
    if at_domain && matches!(bc, Boundary::Slip) {
        return values;
    }
    if at_domain && bc == Boundary::Open {
        let speed = c.flow.vector(f.center[2])[d] * side as f64;
        return if speed < -1e-12 {
            let inflow = c.flow.vector(f.center[2])[f.axis];
            values.map(|value| 2.0 * inflow - value)
        } else {
            values
        };
    }
    if c.flow.rans() {
        if d == 2 && side > 0 && at_domain && bc == Boundary::GroundOpenTop {
            let v = c.flow.vector(c.domain.size_m[2]);
            let speed = (v[0] * v[0] + v[1] * v[1]).sqrt();
            let stress = c.flow.ustar().powi(2) * v[f.axis] / speed.max(1e-30);
            let mu = c.flow.viscosity() + adjacent_mean(f, nut);
            return values.map(|value| value + stress * g.dx[d] / mu);
        }
        let i = f.lo.or(f.hi).unwrap();
        let velocity = cell_u[i];
        let speed = (0..3)
            .filter(|a| *a != d)
            .map(|a| velocity[a].powi(2))
            .sum::<f64>()
            .sqrt();
        if let Flow::NeutralRans { roughness_m, .. } = &c.flow {
            let z = 0.5 * g.dx[d];
            let z0 = if d == 2 && side < 0 && at_domain {
                *roughness_m
            } else {
                roughness_m.min(0.001 * g.dx[d])
            };
            let us = 0.4 * speed / ((z + z0) / z0).ln();
            let mu = c.flow.viscosity() + adjacent_mean(f, nut);
            return values.map(|value| {
                let stress = us * us * value / speed.max(1e-30);
                value - stress * g.dx[d] / mu
            });
        }
    }
    let target = if at_domain {
        c.moving_walls
            .iter()
            .find(|w| w.axis == d && w.upper == (side > 0))
            .map(|w| w.velocity_m_s[f.axis])
            .unwrap_or(0.0)
    } else {
        0.0
    };
    values.map(|value| 2.0 * target - value)
}
#[allow(clippy::too_many_arguments)]
fn sample(
    c: &Case,
    g: &Grid,
    fi: usize,
    d: usize,
    side: isize,
    neighbor: Option<usize>,
    u: &[f64],
    nut: &[f64],
    cell_u: &[[f64; 3]],
) -> f64 {
    let f = &g.faces[fi];
    if let Some(j) = neighbor {
        if matches!(g.faces[j].kind, FaceKind::Wall | FaceKind::Blocked) && d != f.axis {
            wall_ghost(c, g, fi, d, side, u, nut, cell_u)
        } else {
            u[j]
        }
    } else {
        if d == f.axis {
            return u[fi];
        }
        wall_ghost(c, g, fi, d, side, u, nut, cell_u)
    }
}
// Reuse topology within this cell evaluation; no persistent mutable-grid cache.
fn cell_neighbors(g: &Grid, i: usize) -> [[usize; 2]; 3] {
    std::array::from_fn(|d| {
        [
            transport::neighbor(g, i, d, 0).unwrap_or(i),
            transport::neighbor(g, i, d, 1).unwrap_or(i),
        ]
    })
}

/// Face reconstruction of the transported momentum component on a momentum
/// control-volume face, phi_f = phi_U + s(a, b) / 2 with a = phi_U - phi_UU and
/// b = phi_D - phi_U (van Leer's MUSCL, Sweby's limiter notation). Division-free.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Reconstruction {
    /// s = 0: flux-form first-order upwind. A test control only; it is not the
    /// production donor-cell scheme, which uses the advective form.
    FirstOrder,
    /// s = a: unlimited second-order upwind.
    SecondOrder,
    VanAlbada,
    VanLeer,
    MonotonizedCentral,
}
impl Reconstruction {
    pub fn of(numerics: &Numerics) -> Option<Self> {
        match (numerics.momentum_advection, numerics.momentum_limiter) {
            (MomentumAdvection::DonorCell, _) => None,
            (MomentumAdvection::SecondOrderUpwind, _) => Some(Self::SecondOrder),
            (MomentumAdvection::LimitedUpwind, Some(MomentumLimiter::VanAlbada)) => {
                Some(Self::VanAlbada)
            }
            (MomentumAdvection::LimitedUpwind, Some(MomentumLimiter::VanLeer)) => {
                Some(Self::VanLeer)
            }
            (MomentumAdvection::LimitedUpwind, Some(MomentumLimiter::MonotonizedCentral)) => {
                Some(Self::MonotonizedCentral)
            }
            // Rejected by case validation (CFD-E037).
            (MomentumAdvection::LimitedUpwind, None) => Some(Self::FirstOrder),
        }
    }
    pub fn slope(self, a: f64, b: f64) -> f64 {
        match self {
            Self::FirstOrder => 0.0,
            Self::SecondOrder => a,
            _ if a * b <= 0.0 => 0.0,
            Self::VanAlbada => a * b * (a + b) / (a * a + b * b),
            Self::VanLeer => 2.0 * a * b / (a + b),
            Self::MonotonizedCentral => {
                b.signum() * (2.0 * a.abs()).min(0.5 * (a + b).abs()).min(2.0 * b.abs())
            }
        }
    }
}

// A face that carries a real interior velocity sample for the momentum stencil.
fn interior(g: &Grid, face: Option<usize>) -> Option<usize> {
    face.filter(|&j| matches!(g.faces[j].kind, FaceKind::Interior | FaceKind::Outlet))
}

/// Conservative flux-form advection of the face-normal velocities on the
/// staggered grid (Harlow and Welch; Morinishi et al. 1998). Each momentum control
/// volume is centered on its face. The advecting velocity on a control-volume face
/// is the classic MAC average of the two face velocities that meet there, and the
/// transported component is reconstructed upwind with `reconstruction`. Every
/// control-volume face flux is a function of that face alone, so the two momentum
/// cells that share it see the same value and the fluxes telescope. Walls and
/// solids use the viscous ghost values for the near samples; where the far-upwind
/// sample is not an interior face, the face falls back to first order (s = 0).
/// Returns -div(u u_a) on interior faces and zero elsewhere.
pub fn flux_form_advection(
    c: &Case,
    g: &Grid,
    u: &[f64],
    nut: &[f64],
    reconstruction: Reconstruction,
) -> Vec<f64> {
    flux_form_advection_with(c, g, u, nut, &g.cell_velocity(u), reconstruction)
}

// Each control-volume face flux is evaluated once and shared by the two momentum
// cells that meet there: center fluxes per fluid cell and axis, edge fluxes per
// a-face and direction d ≠ a (the edge above the face in d). The arithmetic of
// every flux is unchanged, so the result is bit-identical to evaluating each
// flux from both sides.
fn flux_form_advection_with(
    c: &Case,
    g: &Grid,
    u: &[f64],
    nut: &[f64],
    cell_u: &[[f64; 3]],
    reconstruction: Reconstruction,
) -> Vec<f64> {
    // Flux through the control-volume face at the center of cell `cell`, between
    // the a-faces L (below) and H (above) of that cell.
    let center_flux = |a: usize, cell: usize| -> f64 {
        let [lo, hi] = g.cell_faces[cell][a];
        let advecting = 0.5 * (u[lo] + u[hi]);
        let (up, down, far) = if advecting >= 0.0 {
            (lo, hi, g.faces[lo].lo.map(|k| g.cell_faces[k][a][0]))
        } else {
            (hi, lo, g.faces[hi].hi.map(|k| g.cell_faces[k][a][1]))
        };
        let s = match interior(g, far) {
            Some(far) => reconstruction.slope(u[up] - u[far], u[down] - u[up]),
            None => 0.0,
        };
        advecting * (u[up] + 0.5 * s)
    };
    // Flux through the control-volume face between the a-face at q (L, below in d)
    // and the a-face at q + e_d (H). Either may be missing or a wall face. The
    // faces it needs, as `face_at` finds them: the d-faces at q + e_d and
    // q + e_d − e_a, and the a-faces at q, q + e_d, q − e_d and q + 2e_d.
    let edge_core = |d: usize,
                     d_faces: [Option<usize>; 2],
                     [at_q, above, below, above2]: [Option<usize>; 4]|
     -> f64 {
        // At an outlet's momentum cell only the inside cell's d-face exists; its
        // velocity is extrapolated (zero gradient) to the outer half.
        let advecting = match d_faces {
            [Some(d0), Some(d1)] => 0.5 * (u[d0] + u[d1]),
            [Some(d0), None] | [None, Some(d0)] => u[d0],
            [None, None] => return 0.0,
        };
        let low = interior(g, at_q);
        let high = interior(g, above);
        let value = |own: Option<usize>, other: Option<usize>, side: isize| -> Option<f64> {
            match (own, other) {
                (Some(j), _) => Some(u[j]),
                // The missing sample is the neighbor of `other` on this side.
                (None, Some(j)) => Some(wall_ghost(c, g, j, d, side, u, nut, cell_u)),
                (None, None) => None,
            }
        };
        let (Some(phi_low), Some(phi_high)) = (value(low, high, -1), value(high, low, 1)) else {
            return 0.0;
        };
        let (phi_up, phi_down, far) = if advecting >= 0.0 {
            (phi_low, phi_high, low.and(interior(g, below)))
        } else {
            (phi_high, phi_low, high.and(interior(g, above2)))
        };
        let s = match far {
            Some(far) => reconstruction.slope(phi_up - u[far], phi_down - phi_up),
            None => 0.0,
        };
        advecting * (phi_up + 0.5 * s)
    };
    let edge_flux = |a: usize, d: usize, q: [isize; 3]| -> f64 {
        let at = |axis: usize, offset: [isize; 3]| {
            g.face_at(c, axis, std::array::from_fn(|k| q[k] + offset[k]))
        };
        let shift = |k: isize, back_a: isize| {
            let mut o = [0; 3];
            o[d] = k;
            o[a] += back_a;
            o
        };
        edge_core(
            d,
            [at(d, shift(1, 0)), at(d, shift(1, -1))],
            [
                at(a, [0; 3]),
                at(a, shift(1, 0)),
                at(a, shift(-1, 0)),
                at(a, shift(2, 0)),
            ],
        )
    };
    let neighbor_faces = g.neighbor_faces(c);
    let edge_faces = g.edge_faces(c);
    let centers: Vec<[f64; 3]> = (0..g.count())
        .into_par_iter()
        .map(|cell| {
            if g.fluid[cell] {
                std::array::from_fn(|a| center_flux(a, cell))
            } else {
                [0.0; 3]
            }
        })
        .collect();
    // The edge above each a-face in d, from the cached face tables (the same
    // faces `edge_flux` would look up).
    let edges: Vec<[f64; 3]> = g
        .faces
        .par_iter()
        .enumerate()
        .map(|(fi, f)| {
            std::array::from_fn(|d| {
                if d == f.axis {
                    0.0
                } else {
                    let [below, above] = neighbor_faces[fi][d];
                    let above2 = above.and_then(|j| neighbor_faces[j][d][1]);
                    edge_core(d, edge_faces[fi][d], [Some(fi), above, below, above2])
                }
            })
        })
        .collect();
    g.faces
        .par_iter()
        .enumerate()
        .map(|(fi, f)| {
            if !matches!(f.kind, FaceKind::Interior | FaceKind::Outlet) {
                return 0.0;
            }
            let a = f.axis;
            let q = f.coord.map(|v| v as isize);
            let mut rhs = 0.0;
            for d in 0..3 {
                let (low, high) = if d == a {
                    // Outlet closure: the outer half of an outlet's momentum cell
                    // advects with the outlet velocity and a zero-gradient value
                    // (s = 0); an inflow face is prescribed and has no equation.
                    let outer = u[fi] * u[fi];
                    (
                        f.lo.map_or(outer, |cell| centers[cell][a]),
                        f.hi.map_or(outer, |cell| centers[cell][a]),
                    )
                } else {
                    let mut below = q;
                    below[d] -= 1;
                    // The edge below is the edge above the a-face below, when that
                    // face exists (face_at wraps periodic axes the same way).
                    let low = match neighbor_faces[fi][d][0] {
                        Some(j) => edges[j][d],
                        None => edge_flux(a, d, below),
                    };
                    (low, edges[fi][d])
                };
                rhs -= (high - low) / g.dx[d];
            }
            rhs
        })
        .collect()
}

/// The steady momentum right-hand side on every face (zero on faces without an
/// equation). `nut` enters only with `neutral_rans`; laminar flow has none.
pub fn momentum_rhs(c: &Case, g: &Grid, u: &[f64], nut: &[f64]) -> Vec<f64> {
    let reconstruction = Reconstruction::of(&c.numerics);
    let cell_u = g.cell_velocity(u);
    let advection = reconstruction.map(|r| flux_form_advection_with(c, g, u, nut, &cell_u, r));
    // Remaining variable-viscosity symmetric-stress term:
    // div(mu grad(u)^T)_a = sum_d (d_d mu)(d_a u_d), for divergence-free flow.
    let mut cross = vec![[0.0; 3]; g.count()];
    if c.flow.rans() {
        for i in 0..g.count() {
            if !g.fluid[i] {
                continue;
            }
            let neighbors = cell_neighbors(g, i);
            for a in 0..3 {
                for d in 0..3 {
                    let [im, ip] = neighbors[d];
                    let [jm, jp] = neighbors[a];
                    cross[i][a] += (nut[ip] - nut[im]) / (2.0 * g.dx[d])
                        * (cell_u[jp][d] - cell_u[jm][d])
                        / (2.0 * g.dx[a]);
                }
            }
        }
    }
    let neighbor_faces = g.neighbor_faces(c);
    let nu = c.flow.viscosity();
    let rans = c.flow.rans();
    let mean: Vec<f64> = if rans {
        g.faces.iter().map(|f| adjacent_mean(f, nut)).collect()
    } else {
        Vec::new()
    };
    g.faces
        .par_iter()
        .enumerate()
        .map(|(fi, f)| {
            if !matches!(f.kind, FaceKind::Interior | FaceKind::Outlet) {
                return 0.0;
            }
            let velocity = std::array::from_fn::<_, 3, _>(|a| match (f.lo, f.hi) {
                (Some(i), Some(j)) => 0.5 * (cell_u[i][a] + cell_u[j][a]),
                (Some(i), None) | (None, Some(i)) => cell_u[i][a],
                _ => 0.0,
            });
            let mut rhs = advection.as_ref().map_or(0.0, |adv| adv[fi]);
            for d in 0..3 {
                let [lo_face, hi_face] = neighbor_faces[fi][d];
                let lo = sample(c, g, fi, d, -1, lo_face, u, nut, &cell_u);
                let hi = sample(c, g, fi, d, 1, hi_face, u, nut, &cell_u);
                // Donor-cell momentum, direct second-order viscous stencil on the staggered grid.
                if advection.is_none() {
                    rhs -= velocity[d]
                        * if velocity[d] >= 0.0 {
                            (u[fi] - lo) / g.dx[d]
                        } else {
                            (hi - u[fi]) / g.dx[d]
                        };
                }
                // Variable-viscosity flux includes the derivative of the eddy viscosity.
                // Laminar: nut is zero, so every face viscosity is exactly nu.
                let mu = nu + if rans { mean[fi] } else { 0.0 };
                let mut mu_lo = mu;
                let mut mu_hi = mu;
                if rans {
                    for (neighbor, dst) in [(lo_face, &mut mu_lo), (hi_face, &mut mu_hi)] {
                        if let Some(j) = neighbor
                            && g.faces[j].kind == FaceKind::Interior
                        {
                            *dst = 0.5 * (mu + nu + mean[j]);
                        }
                    }
                }
                rhs += (mu_hi * (hi - u[fi]) - mu_lo * (u[fi] - lo)) / (g.dx[d] * g.dx[d]);
            }
            if let Flow::Laminar {
                acceleration_m_s2, ..
            } = &c.flow
            {
                rhs += acceleration_m_s2[f.axis];
            }
            rhs += match (f.lo, f.hi) {
                (Some(i), Some(j)) => 0.5 * (cross[i][f.axis] + cross[j][f.axis]),
                (Some(i), None) | (None, Some(i)) => cross[i][f.axis],
                _ => 0.0,
            };
            rhs
        })
        .collect()
}
pub fn production(
    c: &Case,
    g: &Grid,
    u: &[f64],
    nut: &[f64],
    k: &[f64],
) -> (Vec<f64>, Vec<Option<f64>>) {
    let v = g.cell_velocity(u);
    let mut p = vec![0.0; g.count()];
    let mut eps_wall = vec![None; g.count()];
    for i in 0..g.count() {
        if !g.fluid[i] {
            continue;
        }
        let neighbors = cell_neighbors(g, i);
        let mut grad = [[0.0; 3]; 3];
        for a in 0..3 {
            for d in 0..3 {
                let lo = v[neighbors[d][0]][a];
                let hi = v[neighbors[d][1]][a];
                grad[a][d] = (hi - lo) / (2.0 * g.dx[d]);
            }
        }
        p[i] = nut[i]
            * (0..3)
                .flat_map(|a| (0..3).map(move |d| 0.5 * (grad[a][d] + grad[d][a]).powi(2)))
                .sum::<f64>();
        if let Flow::NeutralRans { roughness_m, .. } = &c.flow {
            // A cell with several wall faces (a canyon floor corner) averages the wall
            // production and dissipation over those faces, with equal weights.
            let (mut p_sum, mut eps_sum, mut walls) = (0.0, 0.0, 0usize);
            for d in 0..3 {
                for side in 0..2 {
                    let f = &g.faces[g.cell_faces[i][d][side]];
                    if f.kind != FaceKind::Wall {
                        continue;
                    }
                    let speed = (0..3)
                        .filter(|a| *a != d)
                        .map(|a| v[i][a].powi(2))
                        .sum::<f64>()
                        .sqrt();
                    let ground = d == 2 && side == 0 && f.center[2] == 0.0;
                    let z0 = if ground {
                        *roughness_m
                    } else {
                        roughness_m.min(0.001 * g.dx[d])
                    };
                    let distance = 0.5 * g.dx[d] + z0;
                    let us = 0.4 * speed / (distance / z0).ln();
                    // High-Re wall epsilon follows k, including stagnating wall cells.
                    // Using wall speed cubed here would collapse epsilon while k stays finite.
                    let ep = C_MU.powf(0.75) * k[i].max(1e-14).powf(1.5) / (0.4 * distance);
                    p_sum += us * us * C_MU.powf(0.25) * k[i].max(1e-14).sqrt() / (0.4 * distance);
                    eps_sum += ep.max(1e-14);
                    walls += 1;
                }
            }
            if walls > 0 {
                p[i] = p_sum / walls as f64;
                eps_wall[i] = Some(eps_sum / walls as f64);
            }
        }
    }
    (p, eps_wall)
}
/// The k and epsilon transport parts of the turbulence equations, and the
/// terms they need: production, wall epsilon and the diffusivities.
pub(crate) struct TurbulenceTerms {
    pub(crate) production: Vec<f64>,
    pub(crate) wall_epsilon: Vec<Option<f64>>,
    pub(crate) dk: Vec<f64>,
    pub(crate) de: Vec<f64>,
    pub(crate) k_transport: Vec<f64>,
    pub(crate) e_transport: Vec<f64>,
    /// Coefficient of k (or epsilon) in the upper-boundary diffusion term of
    /// each cell, so the transport parts' linear operators can include it.
    pub(crate) k_top: Vec<f64>,
    pub(crate) e_top: Vec<f64>,
}
pub(crate) fn turbulence_terms(
    c: &Case,
    g: &Grid,
    u: &[f64],
    k: &[f64],
    eps: &[f64],
) -> TurbulenceTerms {
    let nut = eddy_viscosity(g, k, eps);
    let (p, walls) = production(c, g, u, &nut, k);
    let zeros = vec![0.0; g.count()];
    let dk: Vec<_> = nut.iter().map(|n| c.flow.viscosity() + n).collect();
    let de: Vec<_> = nut
        .iter()
        .map(|n| c.flow.viscosity() + n / SIGMA_EPSILON)
        .collect();
    let mut kr = transport::rhs(g, k, u, &dk, &zeros, Advection::LinearUpwind, |f| {
        c.flow.turbulence(f.center[2]).0
    });
    let mut er = transport::rhs(g, eps, u, &de, &zeros, Advection::LinearUpwind, |f| {
        c.flow.turbulence(f.center[2]).1
    });
    let mut k_top = vec![0.0; g.count()];
    let mut e_top = vec![0.0; g.count()];
    // The equilibrium ABL has nonzero epsilon diffusion at the upper boundary.
    // Zero-gradient epsilon there destroys horizontal homogeneity.
    for f in &g.faces {
        if f.axis == 2
            && f.hi.is_none()
            && f.kind == FaceKind::Slip
            && c.boundaries.z == Boundary::GroundOpenTop
        {
            let i = f.lo.unwrap();
            let (kb, eb) = c.flow.turbulence(c.domain.size_m[2]);
            let nb = C_MU * kb * kb / eb;
            kr.values[i] += 0.5 * (dk[i] + c.flow.viscosity() + nb) * (kb - k[i]) / f.distance
                * f.area
                / g.volume;
            er.values[i] += 0.5 * (de[i] + c.flow.viscosity() + nb / SIGMA_EPSILON) * (eb - eps[i])
                / f.distance
                * f.area
                / g.volume;
            k_top[i] -= 0.5 * (dk[i] + c.flow.viscosity() + nb) / f.distance * f.area / g.volume;
            e_top[i] -= 0.5 * (de[i] + c.flow.viscosity() + nb / SIGMA_EPSILON) / f.distance
                * f.area
                / g.volume;
        }
    }
    TurbulenceTerms {
        production: p,
        wall_epsilon: walls,
        dk,
        de,
        k_transport: kr.values,
        e_transport: er.values,
        k_top,
        e_top,
    }
}
pub fn turbulence_step(
    c: &Case,
    g: &Grid,
    u: &[f64],
    k: &mut [f64],
    eps: &mut [f64],
    dt: f64,
) -> usize {
    let TurbulenceTerms {
        production: p,
        wall_epsilon: walls,
        k_transport,
        e_transport,
        ..
    } = turbulence_terms(c, g, u, k, eps);
    let mut floors = 0;
    for i in 0..g.count() {
        if !g.fluid[i] {
            continue;
        }
        let oldk = k[i].max(1e-14);
        let olde = eps[i].max(1e-14);
        let nk = (k[i] + dt * (k_transport[i] + p[i])) / (1.0 + dt * olde / oldk);
        let ne = (eps[i] + dt * (e_transport[i] + C1 * p[i] * olde / oldk))
            / (1.0 + dt * C2 * olde / oldk);
        if !nk.is_finite() || !ne.is_finite() {
            k[i] = f64::NAN;
            eps[i] = f64::NAN;
            continue;
        }
        if nk < 1e-14 || ne < 1e-14 {
            floors += 1;
        }
        k[i] = nk.max(1e-14);
        eps[i] = walls[i]
            .map(|v| v * (k[i] / oldk).powf(1.5))
            .unwrap_or(ne.max(1e-14));
    }
    floors
}
