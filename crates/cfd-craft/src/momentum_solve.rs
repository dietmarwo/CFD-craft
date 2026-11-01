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

impl Stencil {
    pub fn build(c: &Case, g: &Grid) -> Self {
        let unknown: Vec<_> = g
            .faces
            .iter()
            .map(|f| matches!(f.kind, FaceKind::Interior | FaceKind::Outlet))
            .collect();
        let zeros = vec![0.0; g.count()];
        let cell_u = vec![[0.0; 3]; g.count()];
        let mut probe = vec![0.0; g.faces.len()];
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
                    let mut ghost = || {
                        probe[fi] = 0.0;
                        let at0 = flow::wall_ghost(c, g, fi, d, side, &probe, &zeros, &cell_u);
                        probe[fi] = 1.0;
                        let at1 = flow::wall_ghost(c, g, fi, d, side, &probe, &zeros, &cell_u);
                        probe[fi] = 0.0;
                        Neighbor::Ghost(at1 - at0)
                    };
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
        let mut diagonal = vec![0.0; u.len()];
        let mut off = vec![[[0.0; 2]; 3]; u.len()];
        for fi in 0..u.len() {
            if !self.unknown[fi] {
                continue;
            }
            let mut diag = 1.0 / dt;
            for d in 0..3 {
                let h = self.spacing[d];
                let w = viscosity / (h * h);
                diag += 2.0 * w;
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
                    let coefficient = other - w;
                    match self.neighbors[fi][d][side] {
                        Neighbor::Unknown(_) => off[fi][d][side] = coefficient,
                        Neighbor::Ghost(b) => diag += b * coefficient,
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
    let n = b.len();
    let dot = |x: &[f64], y: &[f64]| x.iter().zip(y).map(|(a, b)| a * b).sum::<f64>();
    let inverse: Vec<_> = matrix
        .diagonal
        .iter()
        .zip(&stencil.unknown)
        .map(|(d, u)| if *u { 1.0 / d } else { 0.0 })
        .collect();
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
    while iterations < BICGSTAB_MAX_ITERATIONS {
        if iterations.is_multiple_of(8) {
            control.check()?;
        }
        iterations += 1;
        let next = dot(&r0, &r);
        if next == 0.0 || !next.is_finite() {
            break;
        }
        let beta = (next / rho) * (alpha / omega);
        rho = next;
        for i in 0..n {
            p[i] = r[i] + beta * (p[i] - omega * v[i]);
            ph[i] = p[i] * inverse[i];
        }
        matrix.apply(stencil, &ph, &mut v);
        alpha = rho / dot(&r0, &v);
        for i in 0..n {
            s[i] = r[i] - alpha * v[i];
            sh[i] = s[i] * inverse[i];
        }
        matrix.apply(stencil, &sh, &mut t);
        measured.operator_applications += 2;
        let tt = dot(&t, &t);
        omega = if tt > 0.0 { dot(&t, &s) / tt } else { 0.0 };
        for i in 0..n {
            x[i] += alpha * ph[i] + omega * sh[i];
            r[i] = s[i] - omega * t[i];
        }
        if dot(&r, &r).sqrt() <= BICGSTAB_RELATIVE_TOLERANCE * norm || omega == 0.0 {
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
/// capped by `numerics.max_time_step_s`.
pub const CFL_START: f64 = 1.0;
pub const CFL_GROWTH: f64 = 1.2;
pub const CFL_MAX: f64 = 1e6;

pub fn ramp_cfl(steps: usize) -> f64 {
    CFL_START
        * CFL_GROWTH
            .powi(steps.min(200) as i32)
            .min(CFL_MAX / CFL_START)
}
