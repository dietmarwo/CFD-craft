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
fn adjacent_mean(f: &crate::grid::Face, v: &[f64]) -> f64 {
    match (f.lo, f.hi) {
        (Some(i), Some(j)) => 0.5 * (v[i] + v[j]),
        (Some(i), None) | (None, Some(i)) => v[i],
        _ => 0.0,
    }
}
#[allow(clippy::too_many_arguments)]
fn wall_ghost(
    c: &Case,
    g: &Grid,
    fi: usize,
    d: usize,
    side: isize,
    u: &[f64],
    nut: &[f64],
    cell_u: &[[f64; 3]],
) -> f64 {
    let f = &g.faces[fi];
    let value = u[fi];
    let at_domain = if side < 0 {
        f.center[d] < g.dx[d]
    } else {
        f.center[d] > c.domain.size_m[d] - g.dx[d]
    };
    let bc = c.boundaries.at(d);
    if at_domain && matches!(bc, Boundary::Slip) {
        return value;
    }
    if at_domain && bc == Boundary::Open {
        let speed = c.flow.vector(f.center[2])[d] * side as f64;
        return if speed < -1e-12 {
            2.0 * c.flow.vector(f.center[2])[f.axis] - value
        } else {
            value
        };
    }
    if c.flow.rans() {
        if d == 2 && side > 0 && at_domain && bc == Boundary::GroundOpenTop {
            let v = c.flow.vector(c.domain.size_m[2]);
            let speed = (v[0] * v[0] + v[1] * v[1]).sqrt();
            let stress = c.flow.ustar().powi(2) * v[f.axis] / speed.max(1e-30);
            return value + stress * g.dx[d] / (c.flow.viscosity() + adjacent_mean(f, nut));
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
            let stress = us * us * value / speed.max(1e-30);
            return value - stress * g.dx[d] / (c.flow.viscosity() + adjacent_mean(f, nut));
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
    2.0 * target - value
}
#[allow(clippy::too_many_arguments)]
fn sample(
    c: &Case,
    g: &Grid,
    fi: usize,
    d: usize,
    side: isize,
    u: &[f64],
    nut: &[f64],
    cell_u: &[[f64; 3]],
) -> f64 {
    let f = &g.faces[fi];
    let mut q = f.coord.map(|v| v as isize);
    q[d] += side;
    if let Some(j) = g.face_at(c, f.axis, q) {
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

pub fn momentum_rhs(c: &Case, g: &Grid, u: &[f64], nut: &[f64]) -> Vec<f64> {
    let cell_u = g.cell_velocity(u);
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
            let mut rhs = 0.0;
            for d in 0..3 {
                let lo = sample(c, g, fi, d, -1, u, nut, &cell_u);
                let hi = sample(c, g, fi, d, 1, u, nut, &cell_u);
                // Donor-cell momentum, direct second-order viscous stencil on the staggered grid.
                rhs -= velocity[d]
                    * if velocity[d] >= 0.0 {
                        (u[fi] - lo) / g.dx[d]
                    } else {
                        (hi - u[fi]) / g.dx[d]
                    };
                // Variable-viscosity flux includes the derivative of the eddy viscosity.
                let mu = c.flow.viscosity() + adjacent_mean(f, nut);
                let mut mu_lo = mu;
                let mut mu_hi = mu;
                for (side, dst) in [(-1, &mut mu_lo), (1, &mut mu_hi)] {
                    let mut q = f.coord.map(|v| v as isize);
                    q[d] += side;
                    if let Some(j) = g.face_at(c, f.axis, q)
                        && g.faces[j].kind == FaceKind::Interior
                    {
                        *dst = 0.5 * (mu + c.flow.viscosity() + adjacent_mean(&g.faces[j], nut));
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
pub fn turbulence_step(
    c: &Case,
    g: &Grid,
    u: &[f64],
    k: &mut [f64],
    eps: &mut [f64],
    dt: f64,
) -> usize {
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
        }
    }
    let mut floors = 0;
    for i in 0..g.count() {
        if !g.fluid[i] {
            continue;
        }
        let oldk = k[i].max(1e-14);
        let olde = eps[i].max(1e-14);
        let nk = (k[i] + dt * (kr.values[i] + p[i])) / (1.0 + dt * olde / oldk);
        let ne = (eps[i] + dt * (er.values[i] + C1 * p[i] * olde / oldk))
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
