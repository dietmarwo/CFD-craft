//! Fixed symmetric geometric multigrid for the unmasked pressure equation.
//! This is an original implementation; no external CFD implementation is used.
use crate::{
    Result,
    grid::{FaceKind, Grid},
    solver::Control,
};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

const COARSE_CELLS: usize = 32;
const SWEEPS: usize = 2;

/// Retained hierarchy and scratch storage, excluding allocator overhead, the
/// grid, outer PCG vectors and temporary hierarchy-construction storage.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct MultigridStats {
    pub level_cells: Vec<usize>,
    pub level_nonzeros: Vec<usize>,
    pub allocated_bytes: usize,
}

/// Attempted work, accumulated locally without timers or locks inside PCG.
/// Hierarchy dimensions/storage are maxima, not sums over repeated solves.
#[derive(Clone, Debug, Default, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct MultigridWork {
    pub hierarchy_builds: u64,
    pub hierarchy_levels: u64,
    pub hierarchy_cells: u64,
    pub hierarchy_nonzeros: u64,
    pub hierarchy_bytes: u64,
    pub cycles: u64,
    pub smoothing_cell_updates: u64,
    pub residual_cell_updates: u64,
    pub restriction_cell_updates: u64,
    pub prolongation_cell_updates: u64,
    pub coarse_solves: u64,
}
impl MultigridWork {
    pub(crate) fn merge(&mut self, other: &Self) {
        self.hierarchy_builds += other.hierarchy_builds;
        self.hierarchy_levels = self.hierarchy_levels.max(other.hierarchy_levels);
        self.hierarchy_cells = self.hierarchy_cells.max(other.hierarchy_cells);
        self.hierarchy_nonzeros = self.hierarchy_nonzeros.max(other.hierarchy_nonzeros);
        self.hierarchy_bytes = self.hierarchy_bytes.max(other.hierarchy_bytes);
        self.cycles += other.cycles;
        self.smoothing_cell_updates += other.smoothing_cell_updates;
        self.residual_cell_updates += other.residual_cell_updates;
        self.restriction_cell_updates += other.restriction_cell_updates;
        self.prolongation_cell_updates += other.prolongation_cell_updates;
        self.coarse_solves += other.coarse_solves;
    }
}

#[derive(Debug)]
pub(crate) struct Cached {
    pub key: [u8; 32],
    pub hierarchy: Hierarchy,
}

/// Check current public grid coefficients before reusing a hierarchy. The fine
/// PCG operator and final residual are still built/evaluated independently.
pub(crate) fn key(g: &Grid) -> Result<[u8; 32]> {
    if g.fluid.iter().any(|v| !v) || g.components.len() != 1 {
        return Err("CFD-E034: numerics.pressure_preconditioner: multigrid requires an unmasked connected Cartesian grid".into());
    }
    let mut hash = Sha256::new();
    for n in g.n {
        hash.update((n as u64).to_le_bytes());
    }
    hash.update([u8::from(g.anchored[0])]);
    for f in &g.faces {
        let kind = match f.kind {
            FaceKind::Interior => 1,
            FaceKind::Outlet => 2,
            _ => continue,
        };
        let weight = f.area / (f.distance * g.volume);
        if !weight.is_finite() || weight <= 0.0 {
            return Err("CFD-E034: numerics.pressure_preconditioner: multigrid requires finite positive pressure face weights".into());
        }
        hash.update([kind]);
        hash.update((f.lo.unwrap_or(usize::MAX) as u64).to_le_bytes());
        hash.update((f.hi.unwrap_or(usize::MAX) as u64).to_le_bytes());
        hash.update(weight.to_bits().to_le_bytes());
    }
    Ok(hash.finalize().into())
}

#[derive(Debug)]
struct Matrix {
    offsets: Vec<usize>,
    columns: Vec<usize>,
    values: Vec<f64>,
    diagonal: Vec<f64>,
}
type Edge = (usize, usize, f64);
impl Matrix {
    fn build(edges: &[Edge], anchors: &[f64]) -> Self {
        let n = anchors.len();
        let mut offsets = vec![0; n + 1];
        for &(i, j, _) in edges {
            offsets[i + 1] += 1;
            offsets[j + 1] += 1;
        }
        for i in 0..n {
            offsets[i + 1] += offsets[i];
        }
        let mut columns = vec![0; offsets[n]];
        let mut values = vec![0.0; offsets[n]];
        let mut next = offsets[..n].to_vec();
        let mut diagonal = anchors.to_vec();
        for &(i, j, w) in edges {
            for (row, col) in [(i, j), (j, i)] {
                diagonal[row] += w;
                let at = next[row];
                columns[at] = col;
                values[at] = -w;
                next[row] += 1;
            }
        }
        Self {
            offsets,
            columns,
            values,
            diagonal,
        }
    }
    fn product(&self, x: &[f64], y: &mut [f64]) {
        for i in 0..x.len() {
            let mut value = self.diagonal[i] * x[i];
            for at in self.offsets[i]..self.offsets[i + 1] {
                value += self.values[at] * x[self.columns[at]];
            }
            y[i] = value;
        }
    }
    fn sweep(&self, rhs: &[f64], x: &mut [f64], backward: bool) {
        for at in 0..x.len() {
            let i = if backward { x.len() - 1 - at } else { at };
            let mut value = rhs[i];
            for entry in self.offsets[i]..self.offsets[i + 1] {
                value -= self.values[entry] * x[self.columns[entry]];
            }
            x[i] = value / self.diagonal[i];
        }
    }
    fn allocated_bytes(&self) -> usize {
        8 * (self.offsets.capacity()
            + self.columns.capacity()
            + self.values.capacity()
            + self.diagonal.capacity())
    }
}

#[derive(Debug, Default)]
struct Transfer {
    offsets: Vec<usize>,
    columns: Vec<usize>,
    weights: Vec<f64>,
}
fn axis_weights(x: f64, centers: &[f64], periodic: bool, extent: f64) -> Vec<(usize, f64)> {
    let n = centers.len();
    if n == 1 {
        return vec![(0, 1.0)];
    }
    let hi = centers.partition_point(|v| *v < x);
    let (lo, hi, left, right) = if hi == 0 {
        if !periodic {
            return vec![(0, 1.0)];
        }
        (n - 1, 0, centers[n - 1] - extent, centers[0])
    } else if hi == n {
        if !periodic {
            return vec![(n - 1, 1.0)];
        }
        (n - 1, 0, centers[n - 1], centers[0] + extent)
    } else {
        (hi - 1, hi, centers[hi - 1], centers[hi])
    };
    let t = (x - left) / (right - left);
    [(lo, 1.0 - t), (hi, t)]
        .into_iter()
        .filter(|(_, w)| *w != 0.0)
        .collect()
}
impl Transfer {
    fn build(
        n: [usize; 3],
        centers: &[Vec<f64>; 3],
        periodic: [bool; 3],
        extent: [f64; 3],
    ) -> (Self, [Vec<f64>; 3]) {
        let coarse: [Vec<f64>; 3] = std::array::from_fn(|a| {
            centers[a]
                .chunks(if n[a] <= 2 { 1 } else { 2 })
                .map(|s| s.iter().sum::<f64>() / s.len() as f64)
                .collect()
        });
        let nc = coarse.each_ref().map(|v| v.len());
        let weights: [Vec<_>; 3] = std::array::from_fn(|a| {
            centers[a]
                .iter()
                .map(|x| axis_weights(*x, &coarse[a], periodic[a], extent[a]))
                .collect()
        });
        let mut p = Self::default();
        let mut row = Vec::with_capacity(8);
        p.offsets.push(0);
        for i in 0..n.iter().product() {
            let q = [i % n[0], i / n[0] % n[1], i / (n[0] * n[1])];
            row.clear();
            for &(z, wz) in &weights[2][q[2]] {
                for &(y, wy) in &weights[1][q[1]] {
                    for &(x, wx) in &weights[0][q[0]] {
                        row.push((Grid::index(nc, [x, y, z]), wx * wy * wz));
                    }
                }
            }
            row.sort_unstable_by_key(|v| v.0);
            for &(j, w) in &row {
                p.columns.push(j);
                p.weights.push(w);
            }
            p.offsets.push(p.columns.len());
        }
        (p, coarse)
    }
    fn row(&self, i: usize) -> impl Iterator<Item = (usize, f64)> + '_ {
        let range = self.offsets[i]..self.offsets[i + 1];
        self.columns[range.clone()]
            .iter()
            .copied()
            .zip(self.weights[range].iter().copied())
    }
    fn galerkin(&self, edges: &[Edge], anchors: &[f64], nc: usize) -> (Vec<Edge>, Vec<f64>) {
        let mut off = BTreeMap::new();
        let mut delta = Vec::with_capacity(16);
        // Assemble symmetric off-diagonals from edge energies w(P_i-P_j)^2.
        // Row sums are transferred separately, preserving the constant mode.
        for &(i, j, w) in edges {
            delta.clear();
            let mut lo = self.row(i).peekable();
            let mut hi = self.row(j).peekable();
            while lo.peek().is_some() || hi.peek().is_some() {
                let a = lo.peek().map(|v| v.0).unwrap_or(usize::MAX);
                let b = hi.peek().map(|v| v.0).unwrap_or(usize::MAX);
                let (col, value) = if a == b {
                    (a, lo.next().unwrap().1 - hi.next().unwrap().1)
                } else if a < b {
                    lo.next().unwrap()
                } else {
                    let (c, v) = hi.next().unwrap();
                    (c, -v)
                };
                if value != 0.0 {
                    delta.push((col, value));
                }
            }
            for (at, &(a, u)) in delta.iter().enumerate() {
                for &(b, v) in &delta[at + 1..] {
                    *off.entry((a, b)).or_insert(0.0) += w * u * v;
                }
            }
        }
        let mut coarse_anchors = vec![0.0; nc];
        for (i, &w) in anchors.iter().enumerate() {
            if w == 0.0 {
                continue;
            }
            delta.clear();
            delta.extend(self.row(i));
            for (at, &(a, u)) in delta.iter().enumerate() {
                coarse_anchors[a] += w * u;
                for &(b, v) in &delta[at + 1..] {
                    *off.entry((a, b)).or_insert(0.0) += w * u * v;
                }
            }
        }
        (
            off.into_iter()
                .filter_map(|((i, j), v)| (v != 0.0).then_some((i, j, -v)))
                .collect(),
            coarse_anchors,
        )
    }
    fn allocated_bytes(&self) -> usize {
        8 * (self.offsets.capacity() + self.columns.capacity() + self.weights.capacity())
    }
}
#[derive(Debug)]
struct Level {
    matrix: Matrix,
    transfer: Transfer,
    rhs: Vec<f64>,
    x: Vec<f64>,
    residual: Vec<f64>,
    // Dense lower Cholesky at the terminal level, with one gauge removed if closed.
    cholesky: Vec<f64>,
    anchored: bool,
}
fn center(x: &mut [f64], anchored: bool) {
    if !anchored {
        let mean = x.iter().sum::<f64>() / x.len() as f64;
        for v in x {
            *v -= mean;
        }
    }
}
impl Level {
    fn new(matrix: Matrix, transfer: Transfer, anchored: bool) -> Self {
        let n = matrix.diagonal.len();
        Self {
            matrix,
            transfer,
            rhs: vec![0.0; n],
            x: vec![0.0; n],
            residual: vec![0.0; n],
            cholesky: vec![],
            anchored,
        }
    }
    fn factor(&mut self) -> Result<()> {
        let skip = usize::from(!self.anchored);
        let n = self.x.len() - skip;
        let mut l = vec![0.0; n * n];
        for row in skip..self.x.len() {
            let i = row - skip;
            l[i * n + i] = self.matrix.diagonal[row];
            for at in self.matrix.offsets[row]..self.matrix.offsets[row + 1] {
                let col = self.matrix.columns[at];
                if col >= skip {
                    l[i * n + col - skip] += self.matrix.values[at];
                }
            }
        }
        for i in 0..n {
            for j in 0..=i {
                let mut value = l[i * n + j];
                for k in 0..j {
                    value -= l[i * n + k] * l[j * n + k];
                }
                if i == j {
                    if !value.is_finite() || value <= 0.0 {
                        return Err("CFD-E035: numerics.pressure_preconditioner: multigrid coarse Cholesky lost positive definiteness".into());
                    }
                    l[i * n + j] = value.sqrt();
                } else {
                    l[i * n + j] = value / l[j * n + j];
                }
            }
        }
        self.cholesky = l;
        Ok(())
    }
    fn direct(&mut self) {
        let skip = usize::from(!self.anchored);
        let n = self.x.len() - skip;
        self.x.fill(0.0);
        for i in 0..n {
            let mut value = self.rhs[i + skip];
            for j in 0..i {
                value -= self.cholesky[i * n + j] * self.x[j + skip];
            }
            self.x[i + skip] = value / self.cholesky[i * n + i];
        }
        for i in (0..n).rev() {
            let mut value = self.x[i + skip];
            for j in i + 1..n {
                value -= self.cholesky[j * n + i] * self.x[j + skip];
            }
            self.x[i + skip] = value / self.cholesky[i * n + i];
        }
        center(&mut self.x, self.anchored);
    }
}

#[derive(Debug)]
pub(crate) struct Hierarchy {
    levels: Vec<Level>,
    pub stats: MultigridStats,
}
impl Hierarchy {
    pub fn build(g: &Grid, control: &Control) -> Result<Self> {
        let mut n = g.n;
        let mut centers: [Vec<f64>; 3] =
            std::array::from_fn(|a| (0..n[a]).map(|i| i as f64 + 0.5).collect());
        let extent = n.map(|v| v as f64);
        let periodic = std::array::from_fn(|a| {
            g.faces
                .iter()
                .any(|f| f.axis == a && f.coord[a] == 0 && f.kind == FaceKind::Interior)
        });
        let anchored = g.anchored[0];
        let mut anchors = vec![0.0; g.count()];
        let mut edges = Vec::with_capacity(g.faces.len());
        for f in &g.faces {
            let w = f.area / (f.distance * g.volume);
            match f.kind {
                FaceKind::Interior => edges.push((f.lo.unwrap(), f.hi.unwrap(), w)),
                FaceKind::Outlet => anchors[f.lo.or(f.hi).unwrap()] += w,
                _ => {}
            }
        }
        let mut levels = Vec::new();
        loop {
            control.check()?;
            let matrix = Matrix::build(&edges, &anchors);
            let count = anchors.len();
            if count <= COARSE_CELLS {
                let mut last = Level::new(matrix, Transfer::default(), anchored);
                last.factor()?;
                levels.push(last);
                break;
            }
            let (transfer, coarse) = Transfer::build(n, &centers, periodic, extent);
            n = coarse.each_ref().map(|v| v.len());
            let (coarse_edges, coarse_anchors) =
                transfer.galerkin(&edges, &anchors, n.iter().product());
            edges = coarse_edges;
            centers = coarse;
            levels.push(Level::new(matrix, transfer, anchored));
            anchors = coarse_anchors;
        }
        let stats = MultigridStats {
            level_cells: levels.iter().map(|l| l.x.len()).collect(),
            level_nonzeros: levels
                .iter()
                .map(|l| l.matrix.values.len() + l.x.len())
                .collect(),
            allocated_bytes: levels.capacity() * std::mem::size_of::<Level>()
                + levels
                    .iter()
                    .map(|l| {
                        l.matrix.allocated_bytes()
                            + l.transfer.allocated_bytes()
                            + 8 * (l.rhs.capacity()
                                + l.x.capacity()
                                + l.residual.capacity()
                                + l.cholesky.capacity())
                    })
                    .sum::<usize>(),
        };
        Ok(Self { levels, stats })
    }
    pub fn work(&self, built: bool) -> MultigridWork {
        MultigridWork {
            hierarchy_builds: u64::from(built),
            hierarchy_levels: self.levels.len() as u64,
            hierarchy_cells: self.stats.level_cells.iter().sum::<usize>() as u64,
            hierarchy_nonzeros: self.stats.level_nonzeros.iter().sum::<usize>() as u64,
            hierarchy_bytes: self.stats.allocated_bytes as u64,
            ..MultigridWork::default()
        }
    }
    pub fn apply(&mut self, rhs: &[f64], z: &mut [f64], work: &mut MultigridWork) {
        self.levels[0].rhs.copy_from_slice(rhs);
        cycle(&mut self.levels, work);
        z.copy_from_slice(&self.levels[0].x);
        work.cycles += 1;
    }
}
fn cycle(levels: &mut [Level], work: &mut MultigridWork) {
    let (level, rest) = levels.split_first_mut().expect("nonempty hierarchy");
    center(&mut level.rhs, level.anchored);
    if rest.is_empty() {
        level.direct();
        work.coarse_solves += 1;
        return;
    }
    level.x.fill(0.0);
    for _ in 0..SWEEPS {
        level.matrix.sweep(&level.rhs, &mut level.x, false);
    }
    center(&mut level.x, level.anchored);
    level.matrix.product(&level.x, &mut level.residual);
    for (r, b) in level.residual.iter_mut().zip(&level.rhs) {
        *r = b - *r;
    }
    center(&mut level.residual, level.anchored);
    rest[0].rhs.fill(0.0);
    for (i, &r) in level.residual.iter().enumerate() {
        for (j, w) in level.transfer.row(i) {
            rest[0].rhs[j] += w * r;
        }
    }
    cycle(rest, work);
    for (i, x) in level.x.iter_mut().enumerate() {
        *x += level
            .transfer
            .row(i)
            .map(|(j, w)| w * rest[0].x[j])
            .sum::<f64>();
    }
    for _ in 0..SWEEPS {
        level.matrix.sweep(&level.rhs, &mut level.x, true);
    }
    center(&mut level.x, level.anchored);
    let cells = level.x.len() as u64;
    work.smoothing_cell_updates += 2 * SWEEPS as u64 * cells;
    work.residual_cell_updates += cells;
    work.restriction_cell_updates += cells;
    work.prolongation_cell_updates += cells;
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::case::{Boundary, Case, Flow, PressurePreconditioner};

    fn grid(n: [usize; 3], boundary: Boundary) -> Grid {
        let mut c: Case =
            serde_json::from_str(include_str!("../../../cases/verification/lid-cavity.json"))
                .unwrap();
        c.grid.cells = n;
        c.domain.size_m = [2.7, 1.9, 3.1];
        c.moving_walls.clear();
        c.boundaries.x = boundary;
        c.boundaries.y = Boundary::Periodic;
        c.boundaries.z = Boundary::Wall;
        c.flow = Flow::Laminar {
            initial_velocity_m_s: [1.0, 0.0, 0.0],
            viscosity_m2_s: 0.01,
            acceleration_m_s2: [0.0; 3],
        };
        c.numerics.pressure_preconditioner = PressurePreconditioner::Multigrid;
        Grid::build(&c).unwrap()
    }
    fn dense(g: &Grid) -> Vec<Vec<f64>> {
        let n = g.count();
        let mut a = vec![vec![0.0; n]; n];
        for j in 0..n {
            let mut e = vec![0.0; n];
            e[j] = 1.0;
            for (i, v) in g.divergence(&g.gradient(&e)).iter().enumerate() {
                a[i][j] = -v;
            }
        }
        a
    }
    fn close(a: f64, b: f64) {
        assert!(
            (a - b).abs() <= 2e-11 * a.abs().max(b.abs()).max(1.0),
            "{a} != {b}"
        );
    }
    #[test]
    fn interpolation_preserves_constants_linear_interior_and_short_axes() {
        for periodic in [false, true] {
            for n in [3, 4, 7, 8, 17] {
                let fine = (0..n).map(|i| i as f64 + 0.5).collect::<Vec<_>>();
                let coarse = fine
                    .chunks(2)
                    .map(|c| c.iter().sum::<f64>() / c.len() as f64)
                    .collect::<Vec<_>>();
                for &x in &fine {
                    let w = axis_weights(x, &coarse, periodic, n as f64);
                    close(w.iter().map(|p| p.1).sum(), 1.0);
                    assert!(w.iter().all(|p| p.1 > 0.0));
                    if x >= coarse[0] && x <= coarse[coarse.len() - 1] {
                        close(w.iter().map(|(j, w)| coarse[*j] * w).sum(), x);
                    }
                }
            }
        }
        let n = [8, 2, 6];
        let centers = std::array::from_fn(|a| (0..n[a]).map(|i| i as f64 + 0.5).collect());
        let (p, coarse) = Transfer::build(n, &centers, [false, true, false], n.map(|v| v as f64));
        assert_eq!(coarse[1], vec![0.5, 1.5]);
        let nc = coarse.each_ref().map(|a| a.len());
        for i in 0..n.iter().product() {
            let span = i / n[0] % n[1];
            assert!(p.row(i).all(|(j, _)| j / nc[0] % nc[1] == span));
        }
    }
    #[test]
    fn every_level_is_independent_galerkin_with_constants_and_outlet_anchors() {
        // Odd aggregates, unequal spacings, periodic duplicates and multiple levels.
        for n in [[9, 2, 7], [5, 3, 3], [2, 2, 9]] {
            for boundary in [Boundary::Wall, Boundary::Periodic, Boundary::Open] {
                let g = grid(n, boundary);
                let h = Hierarchy::build(&g, &Control::new(20.0)).unwrap();
                let mut a = dense(&g);
                for l in &h.levels {
                    for j in 0..a.len() {
                        let mut e = vec![0.0; a.len()];
                        let mut y = e.clone();
                        e[j] = 1.0;
                        l.matrix.product(&e, &mut y);
                        for i in 0..a.len() {
                            close(y[i], a[i][j]);
                        }
                    }
                    let ones = vec![1.0; a.len()];
                    let mut y = vec![0.0; a.len()];
                    l.matrix.product(&ones, &mut y);
                    if boundary == Boundary::Open {
                        assert!(y.iter().sum::<f64>() > 0.0);
                    } else {
                        for v in y {
                            close(v, 0.0);
                        }
                    }
                    if !l.transfer.offsets.is_empty() {
                        let nc = 1 + *l.transfer.columns.iter().max().unwrap();
                        let mut ac = vec![vec![0.0; nc]; nc];
                        for (i, row) in a.iter().enumerate() {
                            for (j, &aij) in row.iter().enumerate() {
                                for (ci, wi) in l.transfer.row(i) {
                                    for (cj, wj) in l.transfer.row(j) {
                                        ac[ci][cj] += wi * aij * wj;
                                    }
                                }
                            }
                        }
                        a = ac;
                    }
                }
            }
        }
    }
    #[test]
    fn the_fixed_cycle_is_linear_symmetric_and_positive_on_its_entire_subspace() {
        for boundary in [Boundary::Wall, Boundary::Periodic, Boundary::Open] {
            let g = grid([5, 3, 3], boundary);
            let mut h = Hierarchy::build(&g, &Control::new(20.0)).unwrap();
            let n = g.count();
            let mut m = vec![vec![0.0; n]; n];
            // Form the complete projected preconditioner, not just random probes.
            for j in 0..n {
                let mut e = vec![0.0; n];
                let mut y = e.clone();
                e[j] = 1.0;
                center(&mut e, g.anchored[0]);
                h.apply(&e, &mut y, &mut MultigridWork::default());
                for i in 0..n {
                    m[i][j] = y[i];
                }
            }
            for (i, row) in m.iter().enumerate() {
                for (j, &mij) in row.iter().enumerate() {
                    close(mij, m[j][i]);
                }
            }
            let anchored = g.anchored[0];
            let rank = n - usize::from(!anchored);
            let mut a = vec![vec![0.0; rank]; rank];
            for i in 0..rank {
                for j in 0..rank {
                    // Basis e_i-e_last spans the closed compatible subspace.
                    a[i][j] = if anchored {
                        m[i][j]
                    } else {
                        m[i][j] - m[i][n - 1] - m[n - 1][j] + m[n - 1][n - 1]
                    };
                }
            }
            for i in 0..rank {
                for j in 0..=i {
                    let v = a[i][j] - (0..j).map(|k| a[i][k] * a[j][k]).sum::<f64>();
                    if i == j {
                        assert!(v > 0.0);
                        a[i][j] = v.sqrt();
                    } else {
                        a[i][j] = v / a[j][j];
                    }
                }
            }
            let r: Vec<_> = (0..n).map(|i| (0.73 * i as f64).sin()).collect();
            let mut compatible = r.clone();
            center(&mut compatible, anchored);
            let mut y = vec![0.0; n];
            h.apply(&compatible, &mut y, &mut MultigridWork::default());
            for i in 0..n {
                close(y[i], (0..n).map(|j| m[i][j] * r[j]).sum());
            }
            assert!(compatible.iter().zip(y).map(|(a, b)| a * b).sum::<f64>() > 0.0);
        }
    }
    #[test]
    fn a_collapsed_closed_coarse_cell_has_no_pressure_unknown() {
        let mut l = Level::new(Matrix::build(&[], &[0.0]), Transfer::default(), false);
        l.factor().unwrap();
        l.rhs[0] = 0.0;
        l.direct();
        assert!(l.cholesky.is_empty());
        assert_eq!(l.x, vec![0.0]);
    }
    #[test]
    fn an_invalid_coarse_factor_is_a_coded_error() {
        let mut l = Level::new(Matrix::build(&[], &[-1.0]), Transfer::default(), true);
        assert!(
            l.factor()
                .unwrap_err()
                .contains("CFD-E035: numerics.pressure_preconditioner")
        );
    }
}
