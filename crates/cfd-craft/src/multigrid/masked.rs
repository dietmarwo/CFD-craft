//! Topology-preserving aggregation for masked Cartesian pressure systems.
//!
//! Piecewise-constant P has one nonzero per row. Aggregates are connected
//! subsets of a geometric 2x2x2 bin, never just cells with the same bin ID.
//! R=P^T and A_c=P^T A P, assembled from the original edge energies. This
//! retains narrow connections and every closed-component constant exactly.
use super::{Edge, Matrix, MultigridStats, MultigridWork, SWEEPS};
use crate::{
    Result,
    grid::{FaceKind, Grid},
    solver::Control,
};
use std::collections::{BTreeMap, VecDeque};

#[derive(Debug)]
struct Direct {
    indices: Vec<usize>,
    factor: Vec<f64>,
}
impl Direct {
    fn build(a: &Matrix, component: &[usize], anchored: bool) -> Result<Self> {
        let indices = component[usize::from(!anchored)..].to_vec();
        let n = indices.len();
        let local: BTreeMap<_, _> = indices.iter().enumerate().map(|(j, &i)| (i, j)).collect();
        let mut factor = vec![0.; n * n];
        for (i, &row) in indices.iter().enumerate() {
            factor[i * n + i] = a.diagonal[row];
            for at in a.offsets[row]..a.offsets[row + 1] {
                if let Some(&j) = local.get(&a.columns[at]) {
                    factor[i * n + j] += a.values[at];
                }
            }
        }
        for i in 0..n {
            for j in 0..=i {
                let mut v = factor[i * n + j];
                for k in 0..j {
                    v -= factor[i * n + k] * factor[j * n + k];
                }
                if i == j {
                    if !v.is_finite() || v <= 0. {
                        return Err("CFD-E035: numerics.pressure_preconditioner: masked coarse Cholesky lost positive definiteness".into());
                    }
                    factor[i * n + j] = v.sqrt();
                } else {
                    factor[i * n + j] = v / factor[j * n + j];
                }
            }
        }
        Ok(Self { indices, factor })
    }
    fn solve(&self, rhs: &[f64], x: &mut [f64]) {
        let n = self.indices.len();
        for (i, &row) in self.indices.iter().enumerate() {
            let mut v = rhs[row];
            for j in 0..i {
                v -= self.factor[i * n + j] * x[self.indices[j]];
            }
            x[row] = v / self.factor[i * n + i];
        }
        for i in (0..n).rev() {
            let row = self.indices[i];
            let mut v = x[row];
            for j in i + 1..n {
                v -= self.factor[j * n + i] * x[self.indices[j]];
            }
            x[row] = v / self.factor[i * n + i];
        }
    }
}

#[derive(Debug)]
struct MaskedLevel {
    a: Matrix,
    parent: Vec<usize>,
    closed: Vec<Vec<usize>>,
    rhs: Vec<f64>,
    x: Vec<f64>,
    residual: Vec<f64>,
    direct: Vec<Direct>,
}
fn center_components(x: &mut [f64], closed: &[Vec<usize>]) {
    for cells in closed {
        let mean = cells.iter().map(|&i| x[i]).sum::<f64>() / cells.len() as f64;
        for &i in cells {
            x[i] -= mean;
        }
    }
}
fn components(
    a: &Matrix,
    anchors: &[f64],
    control: &Control,
) -> Result<(Vec<Vec<usize>>, Vec<bool>)> {
    let mut seen = vec![false; anchors.len()];
    let mut result = vec![];
    let mut anchored = vec![];
    for start in 0..seen.len() {
        if start % 1024 == 0 {
            control.check()?;
        }
        if seen[start] {
            continue;
        }
        seen[start] = true;
        let mut queue = VecDeque::from([start]);
        let mut cells = vec![];
        let mut fixed = false;
        while let Some(i) = queue.pop_front() {
            if cells.len() % 1024 == 0 {
                control.check()?;
            }
            cells.push(i);
            fixed |= anchors[i] > 0.;
            for &j in &a.columns[a.offsets[i]..a.offsets[i + 1]] {
                if !seen[j] {
                    seen[j] = true;
                    queue.push_back(j);
                }
            }
        }
        result.push(cells);
        anchored.push(fixed);
    }
    Ok((result, anchored))
}
fn aggregate(
    a: &Matrix,
    coords: &[[usize; 3]],
    control: &Control,
) -> Result<(Vec<usize>, Vec<[usize; 3]>)> {
    let bins: Vec<_> = coords.iter().map(|p| p.map(|v| v / 2)).collect();
    let mut parent = vec![usize::MAX; coords.len()];
    let mut coarse = vec![];
    for start in 0..parent.len() {
        if start % 1024 == 0 {
            control.check()?;
        }
        if parent[start] != usize::MAX {
            continue;
        }
        let id = coarse.len();
        coarse.push(bins[start]);
        parent[start] = id;
        let mut queue = VecDeque::from([start]);
        while let Some(i) = queue.pop_front() {
            for &j in &a.columns[a.offsets[i]..a.offsets[i + 1]] {
                if parent[j] == usize::MAX && bins[j] == bins[start] {
                    parent[j] = id;
                    queue.push_back(j);
                }
            }
        }
    }
    Ok((parent, coarse))
}
impl MaskedLevel {
    fn sweep(&mut self, backward: bool) {
        for at in 0..self.x.len() {
            let i = if backward { self.x.len() - 1 - at } else { at };
            // An isolated sealed cell is an entirely null pressure space.
            if self.a.diagonal[i] == 0. {
                self.x[i] = 0.;
                continue;
            }
            let mut v = self.rhs[i];
            for k in self.a.offsets[i]..self.a.offsets[i + 1] {
                v -= self.a.values[k] * self.x[self.a.columns[k]];
            }
            self.x[i] = v / self.a.diagonal[i];
        }
    }
}
#[derive(Debug)]
pub(super) struct MaskedHierarchy {
    levels: Vec<MaskedLevel>,
    fluid_indices: Vec<usize>,
    pub stats: MultigridStats,
}
impl MaskedHierarchy {
    pub fn build(g: &Grid, control: &Control) -> Result<Self> {
        let fluid_indices: Vec<_> = (0..g.count()).filter(|&i| g.fluid[i]).collect();
        let mut compact = vec![usize::MAX; g.count()];
        for (j, &i) in fluid_indices.iter().enumerate() {
            compact[i] = j;
        }
        let mut coords: Vec<_> = fluid_indices.iter().map(|&i| g.coord(i)).collect();
        let mut anchors = vec![0.; coords.len()];
        let mut edges = vec![];
        for f in &g.faces {
            let w = f.area / (f.distance * g.volume);
            match f.kind {
                FaceKind::Interior if f.lo != f.hi => {
                    edges.push((compact[f.lo.unwrap()], compact[f.hi.unwrap()], w))
                }
                FaceKind::Outlet => anchors[compact[f.lo.or(f.hi).unwrap()]] += w,
                _ => {}
            }
        }
        let mut levels = vec![];
        loop {
            control.check()?;
            let a = Matrix::build(&edges, &anchors);
            let (regions, anchored) = components(&a, &anchors, control)?;
            let closed = regions
                .iter()
                .zip(&anchored)
                .filter(|(_, b)| !**b)
                .map(|(v, _)| v.clone())
                .collect();
            let n = coords.len();
            let mut level = MaskedLevel {
                a,
                parent: vec![],
                closed,
                rhs: vec![0.; n],
                x: vec![0.; n],
                residual: vec![0.; n],
                direct: vec![],
            };
            if regions.iter().all(|v| v.len() <= super::COARSE_CELLS) {
                for (region, fixed) in regions.iter().zip(anchored) {
                    level.direct.push(Direct::build(&level.a, region, fixed)?);
                }
                levels.push(level);
                break;
            }
            let (parent, mut coarse) = aggregate(&level.a, &coords, control)?;
            // A thin or widely spaced graph may need more geometric bin growth.
            if coarse.len() == n {
                for p in &mut coords {
                    *p = p.map(|v| v / 2);
                }
                if coords.iter().all(|p| *p == [0; 3]) {
                    return Err("CFD-E035: numerics.pressure_preconditioner: masked aggregation failed to reduce a connected component".into());
                }
                continue;
            }
            let mut sums = BTreeMap::<(usize, usize), f64>::new();
            for (i, j, w) in edges {
                let (i, j) = (parent[i], parent[j]);
                if i != j {
                    *sums.entry((i.min(j), i.max(j))).or_default() += w;
                }
            }
            edges = sums
                .into_iter()
                .map(|((i, j), w)| (i, j, w))
                .collect::<Vec<Edge>>();
            let mut ac = vec![0.; coarse.len()];
            for (i, w) in anchors.into_iter().enumerate() {
                ac[parent[i]] += w;
            }
            anchors = ac;
            coords = std::mem::take(&mut coarse);
            level.parent = parent;
            levels.push(level);
        }
        let stats = MultigridStats {
            level_cells: levels.iter().map(|l| l.x.len()).collect(),
            // Masked aggregates are irregular, so rectangular dimensions are omitted.
            level_dimensions: vec![],
            level_nonzeros: levels
                .iter()
                .map(|l| l.a.values.len() + l.x.len())
                .collect(),
            allocated_bytes: 8 * fluid_indices.capacity()
                + levels.capacity() * std::mem::size_of::<MaskedLevel>()
                + levels
                    .iter()
                    .map(|l| {
                        l.a.allocated_bytes()
                            + 8 * (l.parent.capacity()
                                + l.rhs.capacity()
                                + l.x.capacity()
                                + l.residual.capacity())
                            + l.closed.iter().map(|v| 8 * v.capacity()).sum::<usize>()
                            + l.direct
                                .iter()
                                .map(|d| 8 * (d.indices.capacity() + d.factor.capacity()))
                                .sum::<usize>()
                    })
                    .sum::<usize>(),
            block_smoothers: vec![],
        };
        Ok(Self {
            levels,
            fluid_indices,
            stats,
        })
    }
    pub fn apply(&mut self, rhs: &[f64], z: &mut [f64], work: &mut MultigridWork) {
        for (j, &i) in self.fluid_indices.iter().enumerate() {
            self.levels[0].rhs[j] = rhs[i];
        }
        cycle(&mut self.levels, work);
        z.fill(0.);
        for (j, &i) in self.fluid_indices.iter().enumerate() {
            z[i] = self.levels[0].x[j];
        }
        work.cycles += 1;
    }
}
fn cycle(levels: &mut [MaskedLevel], work: &mut MultigridWork) {
    let (level, rest) = levels.split_first_mut().unwrap();
    center_components(&mut level.rhs, &level.closed);
    level.x.fill(0.);
    if rest.is_empty() {
        for d in &level.direct {
            d.solve(&level.rhs, &mut level.x);
        }
        center_components(&mut level.x, &level.closed);
        work.coarse_solves += 1;
        return;
    }
    for _ in 0..SWEEPS {
        level.sweep(false);
    }
    center_components(&mut level.x, &level.closed);
    level.a.product(&level.x, &mut level.residual);
    for (v, b) in level.residual.iter_mut().zip(&level.rhs) {
        *v = b - *v;
    }
    center_components(&mut level.residual, &level.closed);
    rest[0].rhs.fill(0.);
    for (i, &r) in level.residual.iter().enumerate() {
        rest[0].rhs[level.parent[i]] += r;
    }
    cycle(rest, work);
    for (i, x) in level.x.iter_mut().enumerate() {
        *x += rest[0].x[level.parent[i]];
    }
    for _ in 0..SWEEPS {
        level.sweep(true);
    }
    center_components(&mut level.x, &level.closed);
    let n = level.x.len() as u64;
    work.smoothing_cell_updates += 2 * SWEEPS as u64 * n;
    work.residual_cell_updates += n;
    work.restriction_cell_updates += n;
    work.prolongation_cell_updates += n;
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::case::{Block, Case, PressurePreconditioner};
    fn grid() -> Grid {
        let mut c: Case = serde_json::from_str(include_str!(
            "../../../../cases/verification/lid-cavity.json"
        ))
        .unwrap();
        c.domain.size_m = [8., 2., 6.];
        c.grid.cells = [8, 2, 6];
        c.moving_walls.clear();
        c.geometry = vec![Block {
            id: "barrier".into(),
            min_m: [3., 0., 0.],
            max_m: [4., 2., 6.],
            footprint_m: None,
        }];
        c.numerics.pressure_preconditioner = PressurePreconditioner::Multigrid;
        Grid::build(&c).unwrap()
    }
    #[test]
    fn every_aggregate_is_connected_and_galerkin_never_bridges_components() {
        let g = grid();
        let h = MaskedHierarchy::build(&g, &Control::new(20.)).unwrap();
        assert!(h.levels.len() > 1);
        for pair in h.levels.windows(2) {
            let (fine, coarse) = (&pair[0], &pair[1]);
            let mut dense = vec![vec![0.; coarse.x.len()]; coarse.x.len()];
            for i in 0..fine.x.len() {
                dense[fine.parent[i]][fine.parent[i]] += fine.a.diagonal[i];
                for at in fine.a.offsets[i]..fine.a.offsets[i + 1] {
                    dense[fine.parent[i]][fine.parent[fine.a.columns[at]]] += fine.a.values[at];
                }
            }
            for j in 0..coarse.x.len() {
                let mut e = vec![0.; coarse.x.len()];
                e[j] = 1.;
                let mut out = e.clone();
                coarse.a.product(&e, &mut out);
                for i in 0..e.len() {
                    assert!((out[i] - dense[i][j]).abs() < 1e-12);
                }
            }
            assert_eq!(fine.closed.len(), coarse.closed.len());
            for id in 0..coarse.x.len() {
                let members: Vec<_> = (0..fine.x.len())
                    .filter(|&i| fine.parent[i] == id)
                    .collect();
                let mut seen = vec![members[0]];
                let mut at = 0;
                while at < seen.len() {
                    let i = seen[at];
                    for k in fine.a.offsets[i]..fine.a.offsets[i + 1] {
                        let j = fine.a.columns[k];
                        if fine.parent[j] == id && !seen.contains(&j) {
                            seen.push(j);
                        }
                    }
                    at += 1;
                }
                assert_eq!(seen.len(), members.len());
            }
        }
    }
    #[test]
    fn complete_masked_cycle_is_symmetric_and_positive_on_all_gauged_directions() {
        let g = grid();
        let mut h = MaskedHierarchy::build(&g, &Control::new(20.)).unwrap();
        let mut basis = vec![];
        for region in &g.components {
            for &i in &region[1..] {
                let mut v = vec![0.; g.count()];
                v[i] = 1.;
                v[region[0]] = -1.;
                basis.push(v);
            }
        }
        let n = basis.len();
        let mut m = vec![0.; n * n];
        for (j, b) in basis.iter().enumerate() {
            let mut y = vec![0.; g.count()];
            h.apply(b, &mut y, &mut MultigridWork::default());
            for (i, v) in basis.iter().enumerate() {
                m[i * n + j] = v.iter().zip(&y).map(|(a, b)| a * b).sum();
            }
        }
        for i in 0..n {
            for j in 0..=i {
                assert!((m[i * n + j] - m[j * n + i]).abs() < 2e-11);
            }
        }
        // Independent dense Cholesky of the whole compatible-space cycle.
        for i in 0..n {
            for j in 0..=i {
                let mut v = m[i * n + j];
                for k in 0..j {
                    v -= m[i * n + k] * m[j * n + k];
                }
                if i == j {
                    assert!(v > 0.);
                    m[i * n + j] = v.sqrt();
                } else {
                    m[i * n + j] = v / m[j * n + j];
                }
            }
        }
    }
}
