//! Matrix-free linear operators on the face-velocity unknowns, for implicit
//! steady pseudo-time (stages P4 and P5a of docs/ACCURACY_STEADY_PLAN.md).
//!
//! The unknowns are the corrections δ on faces that carry a momentum equation
//! (interior and outlet faces). All other faces keep their prescribed velocity,
//! so δ = 0 there. Wall ghosts are affine in the adjacent face value
//! (ghost = A + B·value), so a correction sees the homogeneous relation
//! δ_ghost = B·δ. B is read from the same `wall_ghost` the momentum
//! right-hand side uses, so the two cannot drift apart.
// Explicit tensor indices keep the stencil equations readable.
#![allow(clippy::needless_range_loop)]
use crate::{
    Result,
    case::Case,
    flow,
    grid::{FaceKind, Grid},
    solver::Control,
};

/// One neighbor of a face in one direction and side, as seen by a correction.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Neighbor {
    /// A face whose correction is an unknown.
    Unknown(usize),
    /// A prescribed face (δ = 0) used as a real sample.
    Fixed,
    /// A ghost value: δ_ghost = coefficient · δ_face.
    Ghost(f64),
}

/// Neighbors of every face in the order [direction][side], as `momentum_rhs`
/// samples them, plus the unknown flags.
#[derive(Clone, Debug)]
pub struct Stencil {
    pub unknown: Vec<bool>,
    pub neighbors: Vec<[[Neighbor; 2]; 3]>,
    pub spacing: [f64; 3],
    /// For each unknown face, direction and side of its momentum control
    /// volume: the two face velocities whose mean advects through that
    /// control-volume face (the MAC average of the flux form).
    pub advecting: Vec<[[[usize; 2]; 2]; 3]>,
}

/// B of ghost = A + B·value, read from `flow::ghost_value` with `nut` and
/// `cell_u` held fixed.
fn ghost_coefficient(
    c: &Case,
    g: &Grid,
    fi: usize,
    d: usize,
    side: isize,
    nut: &[f64],
    cell_u: &[[f64; 3]],
) -> f64 {
    let [at0, at1] = flow::ghost_values(c, g, fi, d, side, [0.0, 1.0], nut, cell_u);
    at1 - at0
}

impl Stencil {
    pub fn build(c: &Case, g: &Grid) -> Self {
        let unknown: Vec<_> = g
            .faces
            .iter()
            .map(|f| matches!(f.kind, FaceKind::Interior | FaceKind::Outlet))
            .collect();
        let zeros = vec![0.0; g.count()];
        let cell_u = vec![[0.0; 3]; g.count()];
        let mut neighbors = vec![[[Neighbor::Fixed; 2]; 3]; g.faces.len()];
        for (fi, f) in g.faces.iter().enumerate() {
            if !unknown[fi] {
                continue;
            }
            for d in 0..3 {
                for (k, side) in [(0usize, -1isize), (1, 1)] {
                    let mut q = f.coord.map(|v| v as isize);
                    q[d] += side;
                    let face = g.face_at(c, f.axis, q);
                    let ghost =
                        || Neighbor::Ghost(ghost_coefficient(c, g, fi, d, side, &zeros, &cell_u));
                    neighbors[fi][d][k] = match face {
                        Some(j)
                            if matches!(g.faces[j].kind, FaceKind::Wall | FaceKind::Blocked)
                                && d != f.axis =>
                        {
                            ghost()
                        }
                        Some(j) if unknown[j] => Neighbor::Unknown(j),
                        Some(_) => Neighbor::Fixed,
                        // `sample` returns the face's own value along its axis.
                        None if d == f.axis => Neighbor::Ghost(1.0),
                        None => ghost(),
                    };
                }
            }
        }
        let mut advecting = vec![[[[usize::MAX; 2]; 2]; 3]; g.faces.len()];
        for (fi, f) in g.faces.iter().enumerate() {
            if !unknown[fi] {
                continue;
            }
            let a = f.axis;
            let q = f.coord.map(|v| v as isize);
            for d in 0..3 {
                advecting[fi][d] = if d == a {
                    // Control-volume faces at the centers of the two adjacent cells.
                    // An outlet's outer half lies outside the domain: it advects
                    // with the outlet velocity itself (zero gradient).
                    [
                        f.lo.map_or([fi, fi], |lo| [g.cell_faces[lo][a][0], fi]),
                        f.hi.map_or([fi, fi], |hi| [fi, g.cell_faces[hi][a][1]]),
                    ]
                } else {
                    // Edges below and above in d: the d-faces of the two cells
                    // that share this a-face. At an outlet only the inside cell
                    // exists; its d-face velocity is extrapolated.
                    let at = |offset_d: isize, offset_a: isize| {
                        let mut r = q;
                        r[d] += offset_d;
                        r[a] += offset_a;
                        g.face_at(c, d, r)
                    };
                    let pair = |x: Option<usize>, y: Option<usize>| match (x, y) {
                        (Some(x), Some(y)) => [x, y],
                        (Some(x), None) | (None, Some(x)) => [x, x],
                        (None, None) => unreachable!("an a-face has a cell on one side"),
                    };
                    [pair(at(0, 0), at(0, -1)), pair(at(1, 0), at(1, -1))]
                };
            }
        }
        Self {
            unknown,
            neighbors,
            spacing: g.dx,
            advecting,
        }
    }

    /// y = ν·L x: the constant-viscosity viscous operator on corrections, zero
    /// on prescribed faces. It is symmetric on the unknowns.
    pub fn viscous(&self, viscosity: f64, x: &[f64], y: &mut [f64]) {
        let weights = self.spacing.map(|h| viscosity / (h * h));
        for (fi, out) in y.iter_mut().enumerate() {
            if !self.unknown[fi] {
                *out = 0.0;
                continue;
            }
            let mut sum = 0.0;
            for d in 0..3 {
                let mut along = -2.0 * x[fi];
                for n in self.neighbors[fi][d] {
                    along += match n {
                        Neighbor::Unknown(j) => x[j],
                        Neighbor::Fixed => 0.0,
                        Neighbor::Ghost(b) => b * x[fi],
                    };
                }
                sum += weights[d] * along;
            }
            *out = sum;
        }
    }

    /// Diagonal of ν·L on the unknowns.
    pub fn viscous_diagonal(&self, viscosity: f64) -> Vec<f64> {
        let weights = self.spacing.map(|h| viscosity / (h * h));
        (0..self.unknown.len())
            .map(|fi| {
                if !self.unknown[fi] {
                    return 0.0;
                }
                (0..3)
                    .map(|d| {
                        let mut diagonal = -2.0;
                        for n in self.neighbors[fi][d] {
                            if let Neighbor::Ghost(b) = n {
                                diagonal += b;
                            }
                        }
                        weights[d] * diagonal
                    })
                    .sum()
            })
            .collect()
    }
}

/// Work of one inexact implicit solve.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct SolveInfo {
    pub iterations: usize,
    pub relative_residual: f64,
}

/// Predeclared inner tolerance and iteration cap of the P4 viscous solves.
pub const VISCOUS_RELATIVE_TOLERANCE: f64 = 1e-3;
pub const VISCOUS_MAX_ITERATIONS: usize = 50;

/// Solves (I − Δτ·ν·L) δ = b on the unknowns with Jacobi-preconditioned CG,
/// from δ = 0, to the predeclared relative tolerance or iteration cap. An
/// inexact result is returned as is: in delta form it changes only the path to
/// the fixed point, not the fixed point.
pub fn solve_viscous(
    stencil: &Stencil,
    viscosity: f64,
    dt: f64,
    b: &[f64],
    control: &Control,
) -> Result<(Vec<f64>, SolveInfo)> {
    let mut measured = control.span(crate::profiling::Phase::MomentumSolve);
    let n = b.len();
    let apply = |x: &[f64], y: &mut [f64]| {
        stencil.viscous(viscosity, x, y);
        for i in 0..n {
            y[i] = if stencil.unknown[i] {
                x[i] - dt * y[i]
            } else {
                0.0
            };
        }
    };
    let inverse: Vec<_> = stencil
        .viscous_diagonal(viscosity)
        .iter()
        .zip(&stencil.unknown)
        .map(|(d, u)| if *u { 1.0 / (1.0 - dt * d) } else { 0.0 })
        .collect();
    let dot = |x: &[f64], y: &[f64]| x.iter().zip(y).map(|(a, b)| a * b).sum::<f64>();
    let mut x = vec![0.0; n];
    let mut r: Vec<_> = b
        .iter()
        .zip(&stencil.unknown)
        .map(|(v, u)| if *u { *v } else { 0.0 })
        .collect();
    let norm = dot(&r, &r).sqrt();
    if norm == 0.0 || !norm.is_finite() {
        if !norm.is_finite() {
            return Err("CFD-E056: nonfinite momentum correction system".into());
        }
        return Ok((x, SolveInfo::default()));
    }
    let mut z: Vec<_> = r.iter().zip(&inverse).map(|(a, w)| a * w).collect();
    let mut p = z.clone();
    let mut rz = dot(&r, &z);
    let mut ap = vec![0.0; n];
    let mut info = SolveInfo {
        iterations: 0,
        relative_residual: 1.0,
    };
    while info.iterations < VISCOUS_MAX_ITERATIONS {
        if info.iterations.is_multiple_of(8) {
            control.check()?;
        }
        apply(&p, &mut ap);
        measured.operator_applications += 1;
        measured.work_units += 1;
        info.iterations += 1;
        let denominator = dot(&p, &ap);
        if denominator <= 0.0 || !denominator.is_finite() {
            return Err("CFD-E056: momentum correction CG lost positive definiteness".into());
        }
        let alpha = rz / denominator;
        for i in 0..n {
            x[i] += alpha * p[i];
            r[i] -= alpha * ap[i];
        }
        info.relative_residual = dot(&r, &r).sqrt() / norm;
        if info.relative_residual <= VISCOUS_RELATIVE_TOLERANCE {
            break;
        }
        for i in 0..n {
            z[i] = r[i] * inverse[i];
        }
        measured.preconditioner_applications += 1;
        let next = dot(&r, &z);
        let beta = next / rz;
        for i in 0..n {
            p[i] = z[i] + beta * p[i];
        }
        rz = next;
    }
    Ok((x, info))
}

/// A diagonally dominant correction matrix on the unknowns: one diagonal and
/// one coefficient per stencil neighbor ([direction][side]).
#[derive(Clone, Debug)]
pub struct Matrix {
    pub diagonal: Vec<f64>,
    pub off: Vec<[[f64; 2]; 3]>,
}

impl Stencil {
    /// A = I/Δτ + first-order upwind advection (Picard: advecting velocities
    /// frozen at u) − ν·L, the approximate Jacobian of the implicit steady
    /// iteration (P5a). The second-order part of the advection enters only
    /// through the explicit residual (deferred correction).
    pub fn implicit_matrix(&self, u: &[f64], viscosity: f64, dt: f64) -> Matrix {
        let weights = self.spacing.map(|h| viscosity / (h * h));
        self.assemble(u, dt, |_, d| [weights[d]; 2], |_, _, _, b| b)
    }

    /// The RANS form of `implicit_matrix` (P5c): the viscous part uses the face
    /// viscosities of `flow::momentum_rhs` (ν + ν_t, averaged with an interior
    /// neighbor), and wall-function ghosts are linearized with ν_t and the cell
    /// velocities lagged at u. The variable-viscosity cross term stays explicit.
    pub fn implicit_matrix_rans(
        &self,
        c: &Case,
        g: &Grid,
        u: &[f64],
        nut: &[f64],
        dt: f64,
    ) -> Matrix {
        let cell_u = g.cell_velocity(u);
        let nu = c.flow.viscosity();
        let mean: Vec<_> = g
            .faces
            .iter()
            .map(|f| flow::adjacent_mean(f, nut))
            .collect();
        self.assemble(
            u,
            dt,
            |fi, d| {
                let h2 = self.spacing[d] * self.spacing[d];
                let mu = nu + mean[fi];
                self.neighbors[fi][d].map(|n| match n {
                    Neighbor::Unknown(j) if g.faces[j].kind == FaceKind::Interior => {
                        0.5 * (mu + nu + mean[j]) / h2
                    }
                    _ => mu / h2,
                })
            },
            |fi, d, side, _| ghost_coefficient(c, g, fi, d, [-1, 1][side], nut, &cell_u),
        )
    }

    fn assemble(
        &self,
        u: &[f64],
        dt: f64,
        weights: impl Fn(usize, usize) -> [f64; 2],
        ghost: impl Fn(usize, usize, usize, f64) -> f64,
    ) -> Matrix {
        let mut diagonal = vec![0.0; u.len()];
        let mut off = vec![[[0.0; 2]; 3]; u.len()];
        for fi in 0..u.len() {
            if !self.unknown[fi] {
                continue;
            }
            let mut diag = 1.0 / dt;
            for d in 0..3 {
                let h = self.spacing[d];
                let w = weights(fi, d);
                diag += w[0] + w[1];
                for side in 0..2 {
                    let [f0, f1] = self.advecting[fi][d][side];
                    let advecting = 0.5 * (u[f0] + u[f1]);
                    // + div(F)/h with F = U * phi_upwind on this control-volume face.
                    let (own, other) = if side == 1 {
                        (advecting.max(0.0) / h, advecting.min(0.0) / h)
                    } else {
                        (-advecting.min(0.0) / h, -advecting.max(0.0) / h)
                    };
                    diag += own;
                    let coefficient = other - w[side];
                    match self.neighbors[fi][d][side] {
                        Neighbor::Unknown(_) => off[fi][d][side] = coefficient,
                        Neighbor::Ghost(b) => diag += ghost(fi, d, side, b) * coefficient,
                        Neighbor::Fixed => {}
                    }
                }
            }
            diagonal[fi] = diag;
        }
        Matrix { diagonal, off }
    }
}

impl Matrix {
    pub fn apply(&self, stencil: &Stencil, x: &[f64], y: &mut [f64]) {
        for (fi, out) in y.iter_mut().enumerate() {
            if !stencil.unknown[fi] {
                *out = 0.0;
                continue;
            }
            let mut sum = self.diagonal[fi] * x[fi];
            for d in 0..3 {
                for side in 0..2 {
                    if let Neighbor::Unknown(j) = stencil.neighbors[fi][d][side] {
                        sum += self.off[fi][d][side] * x[j];
                    }
                }
            }
            *out = sum;
        }
    }
    fn relax(&self, stencil: &Stencil, b: &[f64], x: &mut [f64], fi: usize) {
        let mut sum = b[fi];
        for d in 0..3 {
            for side in 0..2 {
                if let Neighbor::Unknown(j) = stencil.neighbors[fi][d][side] {
                    sum -= self.off[fi][d][side] * x[j];
                }
            }
        }
        x[fi] = sum / self.diagonal[fi];
    }
}

/// Inner solve of the implicit steady iteration (P5a), selected by the
/// predeclared pilot (validation/IMPLICIT_STEADY_RESULTS.md): Jacobi-
/// preconditioned BiCGStab (van der Vorst, 1992) from δ = 0, to this relative
/// residual or cap. One iteration is two operator applications.
pub const BICGSTAB_RELATIVE_TOLERANCE: f64 = 0.1;
pub const BICGSTAB_MAX_ITERATIONS: usize = 50;
pub const USE_BICGSTAB: bool = true;
/// The pilot's other candidate: symmetric Gauss–Seidel sweeps, each a forward
/// and a backward pass, counted as one inner iteration.
pub const PROJECTION_SWEEPS: usize = 4;

fn bicgstab(
    stencil: &Stencil,
    matrix: &Matrix,
    b: &[f64],
    control: &Control,
    measured: &mut crate::profiling::Span,
) -> Result<(Vec<f64>, usize)> {
    let inverse: Vec<_> = matrix
        .diagonal
        .iter()
        .zip(&stencil.unknown)
        .map(|(d, u)| if *u { 1.0 / d } else { 0.0 })
        .collect();
    bicgstab_with(
        |x, y| matrix.apply(stencil, x, y),
        &inverse,
        b,
        BICGSTAB_RELATIVE_TOLERANCE,
        BICGSTAB_MAX_ITERATIONS,
        control,
        measured,
    )
}

/// Right-Jacobi-preconditioned BiCGStab from x = 0 for a matrix-free operator.
/// Rows whose `inverse` entry is zero must have zero right-hand side and an
/// operator row that is zero on such a vector; they stay at zero.
pub(crate) fn bicgstab_with(
    apply: impl Fn(&[f64], &mut [f64]),
    inverse: &[f64],
    b: &[f64],
    tolerance: f64,
    max_iterations: usize,
    control: &Control,
    measured: &mut crate::profiling::Span,
) -> Result<(Vec<f64>, usize)> {
    let n = b.len();
    let dot = |x: &[f64], y: &[f64]| x.iter().zip(y).map(|(a, b)| a * b).sum::<f64>();
    let mut x = vec![0.0; n];
    let mut r = b.to_vec();
    let norm = dot(&r, &r).sqrt();
    if norm == 0.0 {
        return Ok((x, 0));
    }
    let r0 = r.clone();
    let (mut rho, mut alpha, mut omega) = (1.0, 1.0, 1.0);
    let mut v = vec![0.0; n];
    let mut p = vec![0.0; n];
    let (mut ph, mut sh, mut s, mut t) = (vec![0.0; n], vec![0.0; n], vec![0.0; n], vec![0.0; n]);
    let mut iterations = 0;
    while iterations < max_iterations {
        if iterations.is_multiple_of(8) {
            control.check()?;
        }
        let next = dot(&r0, &r);
        if next == 0.0 || !next.is_finite() {
            // Breakdown: no operator application, so no iteration is counted.
            break;
        }
        iterations += 1;
        let beta = (next / rho) * (alpha / omega);
        rho = next;
        for i in 0..n {
            p[i] = r[i] + beta * (p[i] - omega * v[i]);
            ph[i] = p[i] * inverse[i];
        }
        apply(&ph, &mut v);
        alpha = rho / dot(&r0, &v);
        for i in 0..n {
            s[i] = r[i] - alpha * v[i];
            sh[i] = s[i] * inverse[i];
        }
        apply(&sh, &mut t);
        measured.operator_applications += 2;
        let tt = dot(&t, &t);
        omega = if tt > 0.0 { dot(&t, &s) / tt } else { 0.0 };
        for i in 0..n {
            x[i] += alpha * ph[i] + omega * sh[i];
            r[i] = s[i] - omega * t[i];
        }
        if dot(&r, &r).sqrt() <= tolerance * norm || omega == 0.0 {
            break;
        }
    }
    Ok((x, iterations))
}

/// Approximately solves A δ = b with BiCGStab (or, if not selected, symmetric
/// Gauss–Seidel sweeps); the relative residual is reported, not gated.
pub fn solve_implicit(
    stencil: &Stencil,
    matrix: &Matrix,
    b: &[f64],
    control: &Control,
) -> Result<(Vec<f64>, SolveInfo)> {
    let mut measured = control.span(crate::profiling::Phase::MomentumSolve);
    let n = b.len();
    let rhs: Vec<_> = b
        .iter()
        .zip(&stencil.unknown)
        .map(|(v, u)| if *u { *v } else { 0.0 })
        .collect();
    if rhs.iter().any(|v| !v.is_finite())
        || matrix
            .diagonal
            .iter()
            .zip(&stencil.unknown)
            .any(|(d, u)| *u && !(d.is_finite() && *d > 0.0))
    {
        return Err("CFD-E056: nonfinite or singular momentum correction system".into());
    }
    let mut x = vec![0.0; n];
    let mut iterations = PROJECTION_SWEEPS;
    if USE_BICGSTAB {
        let (solution, count) = bicgstab(stencil, matrix, &rhs, control, &mut measured)?;
        x = solution;
        iterations = count;
        measured.work_units += count as u64;
    } else {
        for _ in 0..PROJECTION_SWEEPS {
            control.check()?;
            for fi in 0..n {
                if stencil.unknown[fi] {
                    matrix.relax(stencil, &rhs, &mut x, fi);
                }
            }
            for fi in (0..n).rev() {
                if stencil.unknown[fi] {
                    matrix.relax(stencil, &rhs, &mut x, fi);
                }
            }
            measured.work_units += 1;
            measured.operator_applications += 1;
        }
    }
    let mut ax = vec![0.0; n];
    matrix.apply(stencil, &x, &mut ax);
    let norm = rhs.iter().map(|v| v * v).sum::<f64>().sqrt();
    let residual = ax
        .iter()
        .zip(&rhs)
        .map(|(a, b)| (a - b).powi(2))
        .sum::<f64>()
        .sqrt();
    Ok((
        x,
        SolveInfo {
            iterations,
            relative_residual: if norm > 0.0 { residual / norm } else { 0.0 },
        },
    ))
}

/// Predeclared pseudo-time schedule of the implicit steady iteration:
/// CFL_n = min(CFL_MAX, CFL_START * GROWTH^n), Δτ = CFL_n / Σ_a max|u_a|/h_a,
/// capped by `numerics.max_time_step_s`. CFL_MAX was chosen on the development
/// cases (the 24² and 48² cavities and the development canyon): with a
/// non-binding `max_time_step_s`, caps of 5–50 all reach the canyon's gates in
/// 400 outer iterations, and 5 gives the cavities the fewest (180 and 300).
pub const CFL_START: f64 = 1.0;
pub const CFL_GROWTH: f64 = 1.2;
pub const CFL_MAX: f64 = 5.0;

pub fn ramp_cfl(steps: usize) -> f64 {
    CFL_START
        * CFL_GROWTH
            .powi(steps.min(200) as i32)
            .min(CFL_MAX / CFL_START)
}

#[cfg(test)]
mod tests {
    use super::*;

    // A breakdown stops the iteration before its operator applications, so it
    // must not be counted: the profile checker requires two applications per
    // counted iteration. The second product is chosen orthogonal to r0, which
    // makes the next r0·r exactly zero (BiCG keeps r0·s = 0) while r ≠ 0.
    #[test]
    fn a_breakdown_is_not_counted_as_an_iteration() {
        let control = Control::new(10.0);
        let mut measured = control.span(crate::profiling::Phase::MomentumSolve);
        let calls = std::cell::Cell::new(0);
        let (_, iterations) = bicgstab_with(
            |x, y| {
                calls.set(calls.get() + 1);
                if calls.get() == 1 {
                    y.copy_from_slice(&[x[0], 3.0 * x[1], x[2]]);
                } else {
                    y.copy_from_slice(&[1.0, -1.0, 1.0]);
                }
            },
            &[1.0; 3],
            &[1.0, 1.0, 0.0],
            0.1,
            50,
            &control,
            &mut measured,
        )
        .unwrap();
        assert_eq!(iterations, 1);
        assert_eq!(measured.operator_applications, 2 * iterations as u64);
    }
}
