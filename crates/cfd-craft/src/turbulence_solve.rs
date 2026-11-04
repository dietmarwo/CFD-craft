//! Implicit k–ε pseudo-time steps in delta form for the implicit steady
//! iteration with RANS (stage P5c of the
//! [accuracy and steady-solver plan](https://github.com/dietmarwo/CFD-craft/blob/main/docs/ACCURACY_STEADY_PLAN.md)).
//!
//! Each outer iteration solves, after the momentum–pressure update,
//!
//! (I/Δτ − T_k + ε/k) δk = T_k(k) + P − ε,
//! (I/Δτ − T_ε + C2 ε/k) δε = T_ε(ε) + C1 P ε/k − C2 ε²/k,
//!
//! with T the first-order upwind transport operator of `flow::turbulence_step`
//! (its linear part, including the upper-boundary diffusion term), and P, the
//! diffusivities, ε/k and the wall functions lagged at the start of the
//! iteration. The implicit destruction terms are the ones the explicit step
//! uses. Wall-function cells keep their algebraic ε, as a row δε = ε_wall − ε.
//! At a fixed point δ = 0, so the residuals the explicit step drives to zero
//! are zero too.
// Explicit indices keep the cell and face loops readable.
#![allow(clippy::needless_range_loop)]
use crate::{
    Result,
    case::Case,
    flow::{self, C1, C2},
    grid::{FaceKind, Grid},
    profiling::Phase,
    solver::Control,
};

/// Predeclared inner tolerance and cap of each k and ε solve, the same as
/// the momentum correction's (momentum_solve::BICGSTAB_*).
pub const TURBULENCE_RELATIVE_TOLERANCE: f64 = 0.1;
/// Iteration cap of each k and ε BiCGStab solve.
pub const TURBULENCE_MAX_ITERATIONS: usize = 50;
/// Floor of k and ε, as in `flow::turbulence_step`.
const FLOOR: f64 = 1e-14;

/// One transporting face of `transport::rhs`, with the values that stay fixed
/// during a solve.
struct TransportFace {
    lo: Option<usize>,
    hi: Option<usize>,
    velocity: f64,
    /// Face diffusivity, as `transport::rhs` averages it; unused at outlets.
    diffusivity: f64,
    outlet: bool,
    distance: f64,
    area: f64,
}

/// The linear part of the first-order upwind transport of one turbulence
/// quantity: fixed boundary values and sources are zero, so it acts on a
/// correction. `apply` repeats the arithmetic of `transport::rhs` with
/// `Advection::LinearUpwind`, zero sources and zero inlet values, face by face
/// in the same order, so it returns the same bits without allocating.
struct Transport<'a> {
    g: &'a Grid,
    top: &'a [f64],
    faces: Vec<TransportFace>,
}

impl<'a> Transport<'a> {
    fn new(g: &'a Grid, u: &[f64], d: &[f64], top: &'a [f64]) -> Self {
        let faces = g
            .faces
            .iter()
            .enumerate()
            .filter(|(_, f)| {
                matches!(
                    f.kind,
                    FaceKind::Interior | FaceKind::Inlet | FaceKind::Outlet
                )
            })
            .map(|(fi, f)| TransportFace {
                lo: f.lo,
                hi: f.hi,
                velocity: u[fi],
                diffusivity: match (f.lo, f.hi) {
                    (Some(i), Some(j)) => 0.5 * (d[i] + d[j]),
                    (Some(i), None) | (None, Some(i)) => d[i],
                    _ => 0.0,
                },
                outlet: f.kind == FaceKind::Outlet,
                distance: f.distance,
                area: f.area,
            })
            .collect();
        Self { g, top, faces }
    }

    fn apply(&self, x: &[f64], y: &mut [f64]) {
        y.fill(0.0);
        let volume = self.g.volume;
        for f in &self.faces {
            let cl = f.lo.map(|i| x[i]).unwrap_or(0.0);
            let cr = f.hi.map(|i| x[i]).unwrap_or(0.0);
            // `+ 0.0` as in `transport::rhs`, which adds the (zero) MUSCL slope.
            let donor = if f.velocity >= 0.0 {
                f.lo.map(|_| cl + 0.0).unwrap_or(cl)
            } else {
                f.hi.map(|_| cr - 0.0).unwrap_or(cr)
            };
            let diff = if f.outlet {
                0.0
            } else {
                f.diffusivity * (cl - cr) / f.distance
            };
            let flux = (f.velocity * donor + diff) * f.area;
            if let Some(i) = f.lo {
                y[i] -= flux / volume;
            }
            if let Some(i) = f.hi {
                y[i] += flux / volume;
            }
        }
        for i in 0..y.len() {
            y[i] += self.top[i] * x[i];
        }
    }

    /// Diagonal of `apply`, face by face as `transport::rhs` forms its fluxes.
    fn diagonal(&self) -> Vec<f64> {
        let mut diagonal = self.top.to_vec();
        for f in &self.faces {
            let diffusion = if f.outlet {
                0.0
            } else {
                f.diffusivity / f.distance
            };
            let u = f.velocity;
            if let Some(i) = f.lo {
                diagonal[i] -= (u.max(0.0) + diffusion) * f.area / self.g.volume;
            }
            if let Some(i) = f.hi {
                diagonal[i] -= ((-u).max(0.0) + diffusion) * f.area / self.g.volume;
            }
        }
        diagonal
    }
}

/// Solves (I/Δτ − T + sink) δ = b on fluid cells; rows with `fixed` set are
/// identity rows. Returns δ and the inner iteration count.
#[allow(clippy::too_many_arguments)]
fn solve(
    g: &Grid,
    operator: &Transport,
    sink: &[f64],
    fixed: &[bool],
    dt: f64,
    b: &[f64],
    control: &Control,
    measured: &mut crate::profiling::Span,
) -> Result<(Vec<f64>, usize)> {
    let n = g.count();
    let active = |i: usize| g.fluid[i] && !fixed[i];
    let transport_diagonal = operator.diagonal();
    let mut inverse = vec![0.0; n];
    for i in 0..n {
        if !g.fluid[i] {
            continue;
        }
        let diagonal = if fixed[i] {
            1.0
        } else {
            1.0 / dt - transport_diagonal[i] + sink[i]
        };
        if !(diagonal.is_finite() && diagonal > 0.0) {
            return Err("CFD-E057: nonfinite or singular turbulence correction system".into());
        }
        inverse[i] = 1.0 / diagonal;
    }
    let rhs: Vec<_> = (0..n)
        .map(|i| if g.fluid[i] { b[i] } else { 0.0 })
        .collect();
    if rhs.iter().any(|v| !v.is_finite()) {
        return Err("CFD-E057: nonfinite or singular turbulence correction system".into());
    }
    let apply = |x: &[f64], y: &mut [f64]| {
        operator.apply(x, y);
        for i in 0..n {
            y[i] = if active(i) {
                x[i] / dt - y[i] + sink[i] * x[i]
            } else if g.fluid[i] {
                x[i]
            } else {
                0.0
            };
        }
    };
    crate::momentum_solve::bicgstab_with(
        apply,
        &inverse,
        &rhs,
        TURBULENCE_RELATIVE_TOLERANCE,
        TURBULENCE_MAX_ITERATIONS,
        control,
        measured,
    )
}

/// Work of one implicit k–ε step.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct StepInfo {
    /// Fluid cells whose k or ε hit the 1e-14 floor, one event per cell, as
    /// in `flow::turbulence_step`.
    pub floor_events: usize,
    /// Inner BiCGStab iterations of the k and the ε solve together.
    pub iterations: usize,
}

/// One implicit k–ε pseudo-time step of size `dt` on the velocity `u`.
///
/// Updates `k` and `eps` in place: first the k correction, then the ε
/// correction with the new k. A nonfinite cell value is stored as NaN for the
/// state check to reject. Errors are `CFD-E057` (a nonfinite or singular
/// correction system) and the control's `cancelled` / `wall_time_limit`.
pub fn implicit_step(
    c: &Case,
    g: &Grid,
    u: &[f64],
    k: &mut [f64],
    eps: &mut [f64],
    dt: f64,
    control: &Control,
) -> Result<StepInfo> {
    let mut measured = control.span(Phase::TurbulenceSolve);
    let n = g.count();
    let terms = flow::turbulence_terms(c, g, u, k, eps);
    let old_k: Vec<_> = k.iter().map(|v| v.max(FLOOR)).collect();
    let old_e: Vec<_> = eps.iter().map(|v| v.max(FLOOR)).collect();
    let mut info = StepInfo::default();

    let no_fixed = vec![false; n];
    let k_sink: Vec<_> = (0..n).map(|i| old_e[i] / old_k[i]).collect();
    let k_rhs: Vec<_> = (0..n)
        .map(|i| terms.k_transport[i] + terms.production[i] - old_e[i] * k[i] / old_k[i])
        .collect();
    let k_operator = Transport::new(g, u, &terms.dk, &terms.k_top);
    let (dk, iterations) = solve(
        g,
        &k_operator,
        &k_sink,
        &no_fixed,
        dt,
        &k_rhs,
        control,
        &mut measured,
    )?;
    info.iterations += iterations;

    let wall: Vec<_> = terms.wall_epsilon.iter().map(Option::is_some).collect();
    let mut new_k = vec![0.0; n];
    let mut floored = vec![false; n];
    for i in 0..n {
        if g.fluid[i] {
            let value = k[i] + dk[i];
            floored[i] = value < FLOOR;
            new_k[i] = if value.is_finite() {
                value.max(FLOOR)
            } else {
                f64::NAN
            };
        } else {
            new_k[i] = k[i];
        }
    }
    let e_sink: Vec<_> = (0..n).map(|i| C2 * old_e[i] / old_k[i]).collect();
    let e_rhs: Vec<_> = (0..n)
        .map(|i| match terms.wall_epsilon[i] {
            Some(value) => value * (new_k[i] / old_k[i]).powf(1.5) - eps[i],
            None => {
                terms.e_transport[i] + C1 * terms.production[i] * old_e[i] / old_k[i]
                    - C2 * old_e[i] * eps[i] / old_k[i]
            }
        })
        .collect();
    let e_operator = Transport::new(g, u, &terms.de, &terms.e_top);
    let (de, iterations) = solve(
        g,
        &e_operator,
        &e_sink,
        &wall,
        dt,
        &e_rhs,
        control,
        &mut measured,
    )?;
    info.iterations += iterations;
    measured.work_units += info.iterations as u64;

    for i in 0..n {
        if !g.fluid[i] {
            continue;
        }
        let value = if wall[i] {
            terms.wall_epsilon[i].unwrap() * (new_k[i] / old_k[i]).powf(1.5)
        } else {
            eps[i] + de[i]
        };
        if !value.is_finite() || !new_k[i].is_finite() {
            k[i] = f64::NAN;
            eps[i] = f64::NAN;
            continue;
        }
        // One event per cell, as in `flow::turbulence_step`.
        if floored[i] || (!wall[i] && value < FLOOR) {
            info.floor_events += 1;
        }
        k[i] = new_k[i];
        eps[i] = value.max(FLOOR);
    }
    Ok(info)
}
