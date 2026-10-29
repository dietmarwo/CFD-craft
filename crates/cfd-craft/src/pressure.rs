use crate::{
    Result,
    grid::{FaceKind, Grid},
    solver::Control,
};
use serde::{Deserialize, Serialize};
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct LinearInfo {
    pub iterations: usize,
    pub relative_residual: f64,
}

/// IC(0) of a slightly shifted matrix, used only as a preconditioner.
/// The solved operator and the recomputed residual remain unshifted.
#[derive(Clone, Debug)]
pub struct Factor {
    lower: Vec<Vec<(usize, f64)>>,
    diagonal: Vec<f64>,
}
impl Factor {
    fn build(g: &Grid) -> Self {
        let mut lower = vec![Vec::<(usize, f64)>::new(); g.count()];
        let mut diag = vec![0.0; g.count()];
        for f in &g.faces {
            let w = f.area / (f.distance * g.volume);
            match f.kind {
                FaceKind::Interior => {
                    let i = f.lo.unwrap();
                    let j = f.hi.unwrap();
                    diag[i] += w;
                    diag[j] += w;
                    let (row, col) = if i > j { (i, j) } else { (j, i) };
                    if let Some((_, v)) = lower[row].iter_mut().find(|(c, _)| *c == col) {
                        *v -= w;
                    } else {
                        lower[row].push((col, -w));
                    }
                }
                FaceKind::Outlet => {
                    diag[f.lo.or(f.hi).unwrap()] += w;
                }
                _ => {}
            }
        }
        let maxdiag = diag.iter().copied().fold(1.0, f64::max);
        for row in 0..g.count() {
            lower[row].sort_by_key(|x| x.0);
            for offset in 0..lower[row].len() {
                let (col, value) = lower[row][offset];
                let mut dot = 0.0;
                for &(k, lik) in &lower[row][..offset] {
                    if let Some((_, ljk)) = lower[col].iter().find(|(j, _)| *j == k) {
                        dot += lik * ljk;
                    }
                }
                lower[row][offset].1 = (value - dot) / diag[col];
            }
            let squared = lower[row].iter().map(|(_, v)| v * v).sum::<f64>();
            diag[row] = (diag[row] + 1e-6 * maxdiag - squared)
                .max(1e-12 * maxdiag)
                .sqrt();
        }
        Self {
            lower,
            diagonal: diag,
        }
    }
    fn apply(&self, r: &[f64]) -> Vec<f64> {
        let mut z = r.to_vec();
        for i in 0..z.len() {
            for &(j, l) in &self.lower[i] {
                z[i] -= l * z[j];
            }
            z[i] /= self.diagonal[i];
        }
        for i in (0..z.len()).rev() {
            z[i] /= self.diagonal[i];
            for &(j, l) in &self.lower[i] {
                z[j] -= l * z[i];
            }
        }
        z
    }
}

pub fn apply(g: &Grid, x: &[f64], y: &mut [f64]) {
    y.fill(0.0);
    for f in &g.faces {
        let w = f.area / (f.distance * g.volume);
        match f.kind {
            FaceKind::Interior => {
                let i = f.lo.unwrap();
                let j = f.hi.unwrap();
                let d = w * (x[i] - x[j]);
                y[i] += d;
                y[j] -= d;
            }
            FaceKind::Outlet => {
                let i = f.lo.or(f.hi).unwrap();
                y[i] += w * x[i];
            }
            _ => {}
        }
    }
}
pub fn center_nullspaces(g: &Grid, x: &mut [f64]) {
    for (id, m) in g.components.iter().enumerate() {
        if !g.anchored[id] {
            let mean = m.iter().map(|i| x[*i]).sum::<f64>() / m.len() as f64;
            for i in m {
                x[*i] -= mean;
            }
        }
    }
}
pub fn solve(
    g: &Grid,
    b: &[f64],
    tol: f64,
    max: usize,
    control: &Control,
) -> Result<(Vec<f64>, LinearInfo)> {
    solve_scaled(g, b, None, tol, max, control)
}
/// Solves the pressure equation. A closed fluid component must have a compatible
/// right-hand side: its net flux must be round-off relative to `roundoff_scale` (per cell,
/// the magnitude of the terms that formed `b`) or, without a scale, relative to `|b|`.
/// There is no absolute floor, so a small but entirely incompatible system is rejected.
pub fn solve_scaled(
    g: &Grid,
    b: &[f64],
    roundoff_scale: Option<&[f64]>,
    tol: f64,
    max: usize,
    control: &Control,
) -> Result<(Vec<f64>, LinearInfo)> {
    for (id, m) in g.components.iter().enumerate() {
        if !g.anchored[id] {
            let sum = m.iter().map(|i| b[*i]).sum::<f64>();
            let scale = m
                .iter()
                .map(|i| b[*i].abs().max(roundoff_scale.map_or(0.0, |s| s[*i])))
                .sum::<f64>();
            if sum.abs() > 1e-9 * scale {
                return Err("CFD-E031: incompatible flux in a closed fluid component".into());
            }
        }
    }
    let factor = g.pressure_factor.get_or_init(|| Factor::build(g));
    let dot = |x: &[f64], y: &[f64]| x.iter().zip(y).map(|(a, b)| a * b).sum::<f64>();
    let mut x = vec![0.0; g.count()];
    let mut r = b.to_vec();
    center_nullspaces(g, &mut r);
    // A closed component is solved in its compatible mean-zero subspace.
    // Rechecking against the unprojected round-off mean can make convergence
    // impossible even though the Poisson equation in that subspace is solved.
    let compatible_b = r.clone();
    let norm = dot(&r, &r).sqrt();
    if norm < 1e-24 {
        return Ok((x, LinearInfo::default()));
    }
    let mut z = factor.apply(&r);
    center_nullspaces(g, &mut z);
    let mut p = z.clone();
    let mut rz = dot(&r, &z);
    let mut ap = vec![0.0; g.count()];
    for it in 0..max {
        if it % 8 == 0 {
            control.check()?;
        }
        apply(g, &p, &mut ap);
        let denom = dot(&p, &ap);
        if denom <= 0.0 || !denom.is_finite() {
            return Err("CFD-E032: pressure CG lost positive definiteness".into());
        }
        let alpha = rz / denom;
        for i in 0..g.count() {
            x[i] += alpha * p[i];
            r[i] -= alpha * ap[i];
        }
        let rel = dot(&r, &r).sqrt() / norm;
        if rel <= tol {
            // Recompute, do not trust only the recurrent CG residual.
            apply(g, &x, &mut ap);
            let true_rel = ap
                .iter()
                .zip(&compatible_b)
                .map(|(a, b)| (a - b).powi(2))
                .sum::<f64>()
                .sqrt()
                / norm;
            if true_rel <= tol * 10.0 + 1e-12 {
                center_nullspaces(g, &mut x);
                return Ok((
                    x,
                    LinearInfo {
                        iterations: it + 1,
                        relative_residual: true_rel,
                    },
                ));
            }
        }
        z = factor.apply(&r);
        center_nullspaces(g, &mut z);
        let next = dot(&r, &z);
        let beta = next / rz;
        for i in 0..p.len() {
            p[i] = z[i] + beta * p[i];
        }
        rz = next;
    }
    Err(format!("CFD-E033: pressure iteration limit {max}"))
}
pub fn project(
    g: &Grid,
    u: &mut [f64],
    p: &mut [f64],
    dt: f64,
    tol: f64,
    max: usize,
    control: &Control,
) -> Result<LinearInfo> {
    let b: Vec<_> = g.divergence(u).iter().map(|x| -x / dt).collect();
    // Round-off in a divergence scales with the face velocities it differences.
    let terms: Vec<f64> = (0..g.count())
        .map(|i| {
            if !g.fluid[i] {
                return 0.0;
            }
            (0..3)
                .map(|a| {
                    let [lo, hi] = g.cell_faces[i][a];
                    (u[lo].abs() + u[hi].abs()) / g.dx[a]
                })
                .sum::<f64>()
                / dt
        })
        .collect();
    let (correction, info) = solve_scaled(g, &b, Some(&terms), tol, max, control)?;
    let grad = g.gradient(&correction);
    for (v, d) in u.iter_mut().zip(grad) {
        *v -= dt * d;
    }
    for (p, q) in p.iter_mut().zip(correction) {
        *p += q;
    }
    center_nullspaces(g, p);
    Ok(info)
}
