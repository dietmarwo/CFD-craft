use crate::{
    Result,
    case::PressurePreconditioner,
    grid::{FaceKind, Grid},
    solver::Control,
};
use serde::{Deserialize, Serialize};
use std::sync::MutexGuard;
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct LinearInfo {
    pub iterations: usize,
    pub relative_residual: f64,
}

enum Preconditioner<'a> {
    Ic0(&'a Factor),
    Multigrid(MutexGuard<'a, Option<crate::multigrid::Cached>>),
}
impl Preconditioner<'_> {
    fn apply(&mut self, r: &[f64], z: &mut [f64], measured: &mut crate::profiling::Span) {
        match self {
            Self::Ic0(factor) => factor.apply(r, z),
            Self::Multigrid(cache) => cache.as_mut().expect("built hierarchy").hierarchy.apply(
                r,
                z,
                measured.multigrid.as_mut().expect("multigrid work"),
            ),
        }
        measured.preconditioner_applications += 1;
    }
}
fn preconditioner<'a>(
    g: &'a Grid,
    control: &Control,
    measured: &mut crate::profiling::Span,
) -> Result<Preconditioner<'a>> {
    match g.pressure_preconditioner {
        PressurePreconditioner::Ic0 => {
            Ok(Preconditioner::Ic0(g.pressure_factor.get_or_init(|| {
                let _setup = control.span(crate::profiling::Phase::PressureFactorSetup);
                Factor::build(g)
            })))
        }
        PressurePreconditioner::Multigrid => {
            measured.multigrid = Some(Default::default());
            control.check()?;
            crate::multigrid::validate(g)?;
            // One cache owns its reusable scratch vectors. Cloned grids can share
            // it safely; a changed operator rebuilds it before the next application.
            let mut cache = g
                .pressure_multigrid
                .hierarchy
                .lock()
                .unwrap_or_else(|e| e.into_inner());
            let built = !cache.as_ref().is_some_and(|c| c.signature.matches(g));
            if built {
                let signature = crate::multigrid::Signature::of(g)?;
                measured.multigrid.as_mut().unwrap().hierarchy_builds = 1;
                let _setup = control.span(crate::profiling::Phase::PressureMultigridSetup);
                let hierarchy = crate::multigrid::Hierarchy::build(g, control)?;
                *g.pressure_multigrid
                    .stats
                    .lock()
                    .unwrap_or_else(|e| e.into_inner()) = Some(hierarchy.stats.clone());
                *cache = Some(crate::multigrid::Cached {
                    signature,
                    hierarchy,
                });
            }
            measured.multigrid = Some(cache.as_ref().unwrap().hierarchy.work(built));
            Ok(Preconditioner::Multigrid(cache))
        }
    }
}
/// Current allocated hierarchy dimensions/storage; absent before its first setup.
/// It does not wait for a running solve, so a poll callback may call it.
pub fn multigrid_stats(g: &Grid) -> Option<crate::multigrid::MultigridStats> {
    g.pressure_multigrid
        .stats
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .clone()
}

/// IC(0) of a slightly shifted matrix, used only as a preconditioner.
/// The solved operator and the recomputed residual remain unshifted.
#[derive(Clone, Debug)]
pub struct Factor {
    row_offsets: Vec<usize>,
    columns: Vec<usize>,
    lower: Vec<f64>,
    diagonal: Vec<f64>,
}
impl Factor {
    fn build(g: &Grid) -> Self {
        // Reserve row segments with two linear face passes. A short periodic
        // direction can connect a pair twice, so capacity and live count differ.
        let mut row_offsets = vec![0; g.count() + 1];
        for f in &g.faces {
            if f.kind == FaceKind::Interior {
                let row = f.lo.unwrap().max(f.hi.unwrap());
                row_offsets[row + 1] += 1;
            }
        }
        for row in 0..g.count() {
            row_offsets[row + 1] += row_offsets[row];
        }
        let capacity = row_offsets[g.count()];
        let mut columns = vec![0; capacity];
        let mut lower = vec![0.0; capacity];
        let mut counts = vec![0; g.count()];
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
                    let start = row_offsets[row];
                    let end = start + counts[row];
                    if let Some(offset) = (start..end).find(|&k| columns[k] == col) {
                        lower[offset] -= w;
                    } else {
                        columns[end] = col;
                        lower[end] = -w;
                        counts[row] += 1;
                    }
                }
                FaceKind::Outlet => diag[f.lo.or(f.hi).unwrap()] += w,
                _ => {}
            }
        }
        // Sort each tiny row in place, then close duplicate-capacity gaps.
        // Diagonal and duplicate accumulation above retain the original face order.
        let mut write = 0;
        let mut read = 0;
        for row in 0..g.count() {
            let next = row_offsets[row + 1];
            let end = read + counts[row];
            for offset in read + 1..end {
                let (column, value) = (columns[offset], lower[offset]);
                let mut at = offset;
                while at > read && columns[at - 1] > column {
                    columns[at] = columns[at - 1];
                    lower[at] = lower[at - 1];
                    at -= 1;
                }
                columns[at] = column;
                lower[at] = value;
            }
            row_offsets[row] = write;
            for offset in read..end {
                columns[write] = columns[offset];
                lower[write] = lower[offset];
                write += 1;
            }
            read = next;
        }
        row_offsets[g.count()] = write;
        columns.truncate(write);
        lower.truncate(write);
        let maxdiag = diag.iter().copied().fold(1.0, f64::max);
        for row in 0..g.count() {
            let start = row_offsets[row];
            let end = row_offsets[row + 1];
            for offset in start..end {
                let col = columns[offset];
                let mut dot = 0.0;
                let mut other = row_offsets[col];
                let other_end = row_offsets[col + 1];
                for previous in start..offset {
                    let k = columns[previous];
                    while other < other_end && columns[other] < k {
                        other += 1;
                    }
                    if other < other_end && columns[other] == k {
                        dot += lower[previous] * lower[other];
                    }
                }
                lower[offset] = (lower[offset] - dot) / diag[col];
            }
            let squared = lower[start..end].iter().map(|v| v * v).sum::<f64>();
            diag[row] = (diag[row] + 1e-6 * maxdiag - squared)
                .max(1e-12 * maxdiag)
                .sqrt();
        }
        Self {
            row_offsets,
            columns,
            lower,
            diagonal: diag,
        }
    }
    fn apply(&self, r: &[f64], z: &mut [f64]) {
        assert_eq!(r.len(), z.len());
        for i in 0..z.len() {
            let range = self.row_offsets[i]..self.row_offsets[i + 1];
            let mut value = r[i];
            for (&column, &lower) in self.columns[range.clone()].iter().zip(&self.lower[range]) {
                value -= lower * z[column];
            }
            z[i] = value / self.diagonal[i];
        }
        for i in (0..z.len()).rev() {
            let value = z[i] / self.diagonal[i];
            z[i] = value;
            let range = self.row_offsets[i]..self.row_offsets[i + 1];
            for (&column, &lower) in self.columns[range.clone()].iter().zip(&self.lower[range]) {
                z[column] -= lower * value;
            }
        }
    }
}

// Local to one solve: Grid's public face coefficients may be changed by callers.
// Keep the original face order, including outlets interleaved with interiors.
enum PressureEntry {
    Interior { lo: usize, hi: usize, weight: f64 },
    Outlet { cell: usize, weight: f64 },
}
struct Operator {
    entries: Vec<PressureEntry>,
}
impl Operator {
    fn build(g: &Grid) -> Self {
        let mut entries = Vec::with_capacity(g.faces.len());
        entries.extend(g.faces.iter().filter_map(|f| {
            let weight = f.area / (f.distance * g.volume);
            match f.kind {
                FaceKind::Interior => Some(PressureEntry::Interior {
                    lo: f.lo.unwrap(),
                    hi: f.hi.unwrap(),
                    weight,
                }),
                FaceKind::Outlet => Some(PressureEntry::Outlet {
                    cell: f.lo.or(f.hi).unwrap(),
                    weight,
                }),
                _ => None,
            }
        }));
        Self { entries }
    }
    fn apply(&self, x: &[f64], y: &mut [f64]) {
        y.fill(0.0);
        for entry in &self.entries {
            match *entry {
                PressureEntry::Interior { lo, hi, weight } => {
                    let d = weight * (x[lo] - x[hi]);
                    y[lo] += d;
                    y[hi] -= d;
                }
                PressureEntry::Outlet { cell, weight } => y[cell] += weight * x[cell],
            }
        }
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
    let mut measured = control.span(crate::profiling::Phase::PressureSolve);
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
    let mut preconditioner = preconditioner(g, control, &mut measured)?;
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
    let mut z = vec![0.0; g.count()];
    preconditioner.apply(&r, &mut z, &mut measured);
    center_nullspaces(g, &mut z);
    let mut p = z.clone();
    let mut rz = dot(&r, &z);
    let mut ap = vec![0.0; g.count()];
    let operator = {
        let _setup = control.span(crate::profiling::Phase::PressureOperatorSetup);
        Operator::build(g)
    };
    for it in 0..max {
        if it % 8 == 0 {
            control.check()?;
        }
        measured.work_units += 1;
        operator.apply(&p, &mut ap);
        measured.operator_applications += 1;
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
            measured.operator_applications += 1;
            measured.true_residual_checks += 1;
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
        preconditioner.apply(&r, &mut z, &mut measured);
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
/// The projection's right-hand side, -div(u)/dt, and the per-cell magnitude of the
/// terms it differences, sum(|u_lo| + |u_hi|)/dx/dt, which scales its round-off.
/// Both are formed in one cell pass with the axis order of `Grid::divergence`.
fn projection_rhs(g: &Grid, u: &[f64], dt: f64) -> (Vec<f64>, Vec<f64>) {
    let mut b = vec![-0.0; g.count()];
    let mut terms = vec![0.0; g.count()];
    for i in 0..g.count() {
        if !g.fluid[i] {
            continue;
        }
        let mut divergence = 0.0;
        let mut scale = 0.0;
        for a in 0..3 {
            let [lo, hi] = g.cell_faces[i][a];
            divergence += (u[hi] - u[lo]) / g.dx[a];
            scale += (u[lo].abs() + u[hi].abs()) / g.dx[a];
        }
        b[i] = -divergence / dt;
        // Round-off scales with the terms differenced, not with their small sum.
        terms[i] = scale / dt;
    }
    (b, terms)
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
    let _projection = control.span(crate::profiling::Phase::PressureProjection);
    let (b, terms) = projection_rhs(g, u, dt);
    let (correction, info) = solve_scaled(g, &b, Some(&terms), tol, max, control)?;
    for (v, f) in u.iter_mut().zip(&g.faces) {
        let d = match f.kind {
            FaceKind::Interior => {
                (correction[f.hi.unwrap()] - correction[f.lo.unwrap()]) / f.distance
            }
            FaceKind::Outlet => {
                if let Some(i) = f.lo {
                    -correction[i] / f.distance
                } else {
                    correction[f.hi.unwrap()] / f.distance
                }
            }
            _ => 0.0,
        };
        *v -= dt * d;
    }
    for (p, q) in p.iter_mut().zip(correction) {
        *p += q;
    }
    center_nullspaces(g, p);
    Ok(info)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::case::{Block, Boundary, Case, Flow};

    fn case(n: [usize; 3]) -> Case {
        let mut c: Case = serde_json::from_str(include_str!(
            "../../../cases/verification/periodic-tracer.json"
        ))
        .unwrap();
        c.grid.cells = n;
        c.domain.size_m = n.map(|v| v as f64);
        c.flow = Flow::Laminar {
            initial_velocity_m_s: [0.0; 3],
            viscosity_m2_s: 0.01,
            acceleration_m_s2: [0.0; 3],
        };
        c.constituents.clear();
        c.initial_conditions.clear();
        c.sources.clear();
        c.receptors.clear();
        c
    }

    // Assemble -D G from the grid's gradient/divergence, then form a dense IC(0)
    // reference. This does not use the factor's sparse storage or face assembly.
    fn dense_reference(g: &Grid, rhs: &[f64]) -> Vec<f64> {
        let n = g.count();
        let mut a = vec![vec![0.0; n]; n];
        for j in 0..n {
            let mut basis = vec![0.0; n];
            basis[j] = 1.0;
            for (i, v) in g.divergence(&g.gradient(&basis)).into_iter().enumerate() {
                a[i][j] = -v;
            }
        }
        let maximum = (0..n).map(|i| a[i][i]).fold(1.0, f64::max);
        let mut l = vec![vec![0.0; n]; n];
        for i in 0..n {
            for j in 0..i {
                if a[i][j] != 0.0 {
                    let dot = (0..j).map(|k| l[i][k] * l[j][k]).sum::<f64>();
                    l[i][j] = (a[i][j] - dot) / l[j][j];
                }
            }
            let squared = (0..i).map(|j| l[i][j] * l[i][j]).sum::<f64>();
            l[i][i] = (a[i][i] + 1e-6 * maximum - squared)
                .max(1e-12 * maximum)
                .sqrt();
        }
        let mut y = vec![0.0; n];
        for i in 0..n {
            y[i] = (rhs[i] - (0..i).map(|j| l[i][j] * y[j]).sum::<f64>()) / l[i][i];
        }
        let mut x = vec![0.0; n];
        for i in (0..n).rev() {
            x[i] = (y[i] - (i + 1..n).map(|j| l[j][i] * x[j]).sum::<f64>()) / l[i][i];
        }
        x
    }

    #[test]
    fn compact_ic0_matches_dense_reference_with_periodic_duplicates_and_triangles() {
        for n in [[2, 3, 2], [3, 3, 3], [4, 2, 3]] {
            let c = case(n);
            let g = Grid::build(&c).unwrap();
            let r: Vec<_> = (0..g.count()).map(|i| (0.7 * i as f64).sin()).collect();
            let expected = dense_reference(&g, &r);
            let factor = Factor::build(&g);
            for seed in [0.0, 42.0] {
                let mut z = vec![seed; g.count()];
                factor.apply(&r, &mut z);
                for (a, b) in z.iter().zip(&expected) {
                    assert!((a - b).abs() <= 1e-10 * b.abs().max(1.0));
                }
            }
        }
    }

    #[test]
    fn compact_ic0_matches_dense_reference_for_masked_closed_and_outlet_components() {
        for open in [false, true] {
            let mut c = case([6, 3, 2]);
            c.boundaries.x = if open { Boundary::Open } else { Boundary::Wall };
            if let Flow::Laminar {
                initial_velocity_m_s,
                ..
            } = &mut c.flow
                && open
            {
                *initial_velocity_m_s = [1.0, 0.0, 0.0];
            }
            c.geometry.push(Block {
                id: "barrier".into(),
                min_m: [2.0, 0.0, 0.0],
                max_m: [3.0, 3.0, 2.0],
            });
            let g = Grid::build(&c).unwrap();
            let r: Vec<_> = (0..g.count())
                .map(|i| {
                    if g.fluid[i] {
                        (i as f64 * 0.73).cos()
                    } else {
                        0.0
                    }
                })
                .collect();
            let expected = dense_reference(&g, &r);
            let mut actual = vec![0.0; g.count()];
            Factor::build(&g).apply(&r, &mut actual);
            for (a, b) in actual.iter().zip(expected) {
                assert!((a - b).abs() <= 1e-10 * b.abs().max(1.0));
            }
        }
    }

    #[test]
    fn compact_operator_retains_face_order_on_periodic_masked_and_open_grids() {
        for periodic in [false, true] {
            let mut c = case([6, 3, 2]);
            if !periodic {
                c.boundaries.x = Boundary::Open;
                if let Flow::Laminar {
                    initial_velocity_m_s,
                    ..
                } = &mut c.flow
                {
                    *initial_velocity_m_s = [1.0, 0.0, 0.0];
                }
            }
            c.geometry.push(Block {
                id: "barrier".into(),
                min_m: [2.0, 0.0, 0.0],
                max_m: [3.0, 3.0, 2.0],
            });
            let g = Grid::build(&c).unwrap();
            let x: Vec<_> = (0..g.count()).map(|i| (0.73 * i as f64).sin()).collect();
            let mut raw = vec![0.0; g.count()];
            let mut compact = vec![42.0; g.count()];
            apply(&g, &x, &mut raw);
            Operator::build(&g).apply(&x, &mut compact);
            assert_eq!(raw, compact);
        }
    }

    #[test]
    fn compact_operator_matches_the_public_operator_bitwise_on_unequal_spacing() {
        // Unit spacing hides a reassociated weight; this grid has three spacings.
        for open in [false, true] {
            let mut c = case([18, 9, 33]);
            c.domain.size_m = [7.15, 42.45, 38.31];
            if open {
                c.boundaries.x = Boundary::Open;
                if let Flow::Laminar {
                    initial_velocity_m_s,
                    ..
                } = &mut c.flow
                {
                    *initial_velocity_m_s = [1.0, 0.0, 0.0];
                }
            }
            let g = Grid::build(&c).unwrap();
            let x: Vec<_> = (0..g.count()).map(|i| (0.73 * i as f64).sin()).collect();
            let mut raw = vec![0.0; g.count()];
            let mut compact = vec![0.0; g.count()];
            apply(&g, &x, &mut raw);
            Operator::build(&g).apply(&x, &mut compact);
            let bits = |v: &[f64]| v.iter().map(|x| x.to_bits()).collect::<Vec<_>>();
            assert_eq!(bits(&raw), bits(&compact));
        }
    }

    #[test]
    fn projection_rhs_and_roundoff_scale_match_their_definitions() {
        let mut c = case([18, 9, 33]);
        c.domain.size_m = [7.15, 42.45, 38.31];
        c.geometry.push(Block {
            id: "barrier".into(),
            min_m: [2.0, 0.0, 0.0],
            max_m: [3.0, 20.0, 15.0],
        });
        let g = Grid::build(&c).unwrap();
        // Mixed signs on opposite faces make |u_lo + u_hi| differ from |u_lo| + |u_hi|.
        let u: Vec<_> = (0..g.faces.len())
            .map(|i| 3.0 * (0.61 * i as f64).sin() - 0.4)
            .collect();
        let dt = 0.125;
        let (b, terms) = projection_rhs(&g, &u, dt);
        let divergence = g.divergence(&u);
        for i in 0..g.count() {
            assert_eq!(b[i], -divergence[i] / dt);
            let expected = if g.fluid[i] {
                (0..3)
                    .map(|a| {
                        let [lo, hi] = g.cell_faces[i][a];
                        (u[lo].abs() + u[hi].abs()) / g.dx[a]
                    })
                    .sum::<f64>()
                    / dt
            } else {
                0.0
            };
            assert_eq!(terms[i].to_bits(), expected.to_bits());
        }
        assert!(g.fluid.iter().any(|f| !f));
    }

    #[test]
    fn a_second_solve_uses_changed_public_face_coefficients() {
        let mut c = case([5, 4, 3]);
        c.boundaries.x = Boundary::Open;
        if let Flow::Laminar {
            initial_velocity_m_s,
            ..
        } = &mut c.flow
        {
            *initial_velocity_m_s = [1.0, 0.0, 0.0];
        }
        let mut g = Grid::build(&c).unwrap();
        let exact: Vec<_> = (0..g.count()).map(|i| (0.73 * i as f64).sin()).collect();
        for changed in [false, true] {
            if changed {
                // The cached factor remains an approximate preconditioner. The
                // solved operator and independent residual must use current faces.
                for (i, f) in g.faces.iter_mut().enumerate() {
                    f.area *= 1.0 + (i % 7) as f64 * 0.025;
                }
            }
            let mut b = vec![0.0; g.count()];
            apply(&g, &exact, &mut b);
            let (solved, info) = solve(&g, &b, 1e-12, 2000, &Control::new(20.0)).unwrap();
            assert!(info.relative_residual <= 1.1e-11);
            for (a, b) in solved.iter().zip(&exact) {
                assert!((a - b).abs() < 1e-10);
            }
        }
    }

    #[test]
    fn fused_projection_matches_composed_divergence_and_gradient() {
        for boundary in [Boundary::Periodic, Boundary::Wall, Boundary::Open] {
            let mut c = case([6, 3, 2]);
            c.boundaries.x = boundary;
            if let Flow::Laminar {
                initial_velocity_m_s,
                ..
            } = &mut c.flow
            {
                *initial_velocity_m_s = [1.0, 0.0, 0.0];
            }
            c.geometry.push(Block {
                id: "barrier".into(),
                min_m: [2.0, 0.0, 0.0],
                max_m: [3.0, 3.0, 2.0],
            });
            let g = Grid::build(&c).unwrap();
            let potential: Vec<_> = (0..g.count()).map(|i| (i as f64 * 0.37).sin()).collect();
            // A compatible gradient perturbation works for both closed components
            // and pressure outlets without manufacturing net inlet flux.
            let mut u = g.gradient(&potential);
            let mut reference_u = u.clone();
            let mut p = vec![0.0; g.count()];
            let dt = 0.125;
            let b: Vec<_> = g.divergence(&u).iter().map(|x| -x / dt).collect();
            let terms: Vec<_> = (0..g.count())
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
            let (mut reference_p, reference_info) =
                solve_scaled(&g, &b, Some(&terms), 1e-12, 2000, &Control::new(20.0)).unwrap();
            for (v, d) in reference_u.iter_mut().zip(g.gradient(&reference_p)) {
                *v -= dt * d;
            }
            center_nullspaces(&g, &mut reference_p);
            let info = project(&g, &mut u, &mut p, dt, 1e-12, 2000, &Control::new(20.0)).unwrap();
            assert_eq!(info.iterations, reference_info.iterations);
            assert_eq!(info.relative_residual, reference_info.relative_residual);
            assert_eq!(u, reference_u);
            assert_eq!(p, reference_p);
        }
    }
}
