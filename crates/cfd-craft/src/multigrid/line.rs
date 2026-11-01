//! Exact principal-line solves for paired block Gauss--Seidel relaxation.
use super::Matrix;
use crate::{Result, grid::Grid, solver::Control};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct BlockSmootherStats {
    pub level: usize,
    pub axes: Vec<usize>,
    pub block_unknowns: usize,
    pub block_count: usize,
    pub half_bandwidth: usize,
    pub allocated_bytes: usize,
}

#[derive(Debug)]
pub(super) struct BlockSmoother {
    axes: Vec<usize>,
    length: usize,
    bandwidth: usize,
    nodes: Vec<usize>,
    outside_offsets: Vec<usize>,
    outside_columns: Vec<usize>,
    outside_values: Vec<f64>,
    factor: Vec<f64>,
    scratch: Vec<f64>,
}
impl BlockSmoother {
    pub fn build(
        matrix: &Matrix,
        n: [usize; 3],
        axes: &[usize],
        periodic: [bool; 3],
        control: &Control,
    ) -> Result<Self> {
        let count = matrix.diagonal.len();
        let length = axes.iter().map(|a| n[*a]).product();
        let mut nodes = Vec::with_capacity(count);
        for i in 0..count {
            let mut q = [i % n[0], i / n[0] % n[1], i / (n[0] * n[1])];
            if axes.iter().any(|a| q[*a] != 0) {
                continue;
            }
            for at in 0..length {
                // Fold a cycle to bandwidth two (and its wider Galerkin stencil
                // to a narrow band), rather than factoring a dense cyclic block.
                let mut remainder = at;
                for &axis in axes {
                    let at = remainder % n[axis];
                    remainder /= n[axis];
                    q[axis] = if !periodic[axis] {
                        at
                    } else if at.is_multiple_of(2) {
                        at / 2
                    } else {
                        n[axis] - 1 - at / 2
                    };
                }
                nodes.push(Grid::index(n, q));
            }
        }
        let mut position = vec![0; count];
        for (at, &cell) in nodes.iter().enumerate() {
            position[cell] = at;
        }
        let mut bandwidth = 0;
        let mut outside_count = 0;
        for i in 0..count {
            let pi = position[i];
            for at in matrix.offsets[i]..matrix.offsets[i + 1] {
                let pj = position[matrix.columns[at]];
                if pi / length == pj / length {
                    bandwidth = bandwidth.max(pi.abs_diff(pj));
                } else {
                    outside_count += 1;
                }
            }
        }
        let stride = bandwidth + 1;
        // Cached outside rows remove division/branching from inner sweeps.
        let mut outside_offsets = Vec::with_capacity(count + 1);
        let mut outside_columns = Vec::with_capacity(outside_count);
        let mut outside_values = Vec::with_capacity(outside_count);
        outside_offsets.push(0);
        for (at, &cell) in nodes.iter().enumerate() {
            for entry in matrix.offsets[cell]..matrix.offsets[cell + 1] {
                let col = matrix.columns[entry];
                if position[col] / length != at / length {
                    outside_columns.push(col);
                    outside_values.push(matrix.values[entry]);
                }
            }
            outside_offsets.push(outside_columns.len());
        }

        let mut factor = vec![0.0; count * stride];
        for (at, &cell) in nodes.iter().enumerate() {
            factor[at * stride] = matrix.diagonal[cell];
            for entry in matrix.offsets[cell]..matrix.offsets[cell + 1] {
                let col = position[matrix.columns[entry]];
                if col / length == at / length && col < at {
                    factor[at * stride + at - col] += matrix.values[entry];
                }
            }
        }
        for line in 0..count / length {
            if line.is_multiple_of(128) {
                control.check()?;
            }
            let base = line * length * stride;
            for i in 0..length {
                for j in i.saturating_sub(bandwidth)..=i {
                    let row = base + i * stride;
                    let other = base + j * stride;
                    let mut value = factor[row + i - j];
                    for k in i.saturating_sub(bandwidth)..j {
                        value -= factor[row + i - k] * factor[other + j - k];
                    }
                    if i == j {
                        if !value.is_finite() || value <= 0.0 {
                            return Err("CFD-E036: numerics.pressure_preconditioner: multigrid line Cholesky lost positive definiteness".into());
                        }
                        factor[row] = value.sqrt();
                    } else {
                        factor[row + i - j] = value / factor[other];
                    }
                }
            }
        }
        // The same rounded reciprocal is used in both adjoint triangular solves.
        for row in 0..count {
            factor[row * stride] = 1.0 / factor[row * stride];
        }
        Ok(Self {
            axes: axes.to_vec(),
            length,
            bandwidth,
            nodes,
            outside_offsets,
            outside_columns,
            outside_values,
            factor,
            scratch: vec![0.0; length],
        })
    }
    pub fn sweep(&mut self, _matrix: &Matrix, rhs: &[f64], x: &mut [f64], backward: bool) -> u64 {
        let count = self.nodes.len() / self.length;
        let stride = self.bandwidth + 1;
        for at in 0..count {
            let line = if backward { count - 1 - at } else { at };
            let start = line * self.length;
            let base = start * stride;
            for i in 0..self.length {
                let cell = self.nodes[start + i];
                let mut value = rhs[cell];
                for entry in self.outside_offsets[start + i]..self.outside_offsets[start + i + 1] {
                    value -= self.outside_values[entry] * x[self.outside_columns[entry]];
                }
                self.scratch[i] = value;
            }
            for i in 0..self.length {
                let row = base + i * stride;
                let mut value = self.scratch[i];
                for j in i.saturating_sub(self.bandwidth)..i {
                    value -= self.factor[row + i - j] * self.scratch[j];
                }
                self.scratch[i] = value * self.factor[row];
            }
            for i in (0..self.length).rev() {
                let mut value = self.scratch[i];
                for j in i + 1..self.length.min(i + self.bandwidth + 1) {
                    value -= self.factor[base + j * stride + j - i] * self.scratch[j];
                }
                self.scratch[i] = value * self.factor[base + i * stride];
            }
            for i in 0..self.length {
                x[self.nodes[start + i]] = self.scratch[i];
            }
        }
        count as u64
    }
    pub fn allocated_bytes(&self) -> usize {
        8 * (self.nodes.capacity()
            + self.axes.capacity()
            + self.outside_offsets.capacity()
            + self.outside_columns.capacity()
            + self.outside_values.capacity()
            + self.factor.capacity()
            + self.scratch.capacity())
    }
    pub fn stats(&self, level: usize) -> BlockSmootherStats {
        BlockSmootherStats {
            level,
            axes: self.axes.clone(),
            block_unknowns: self.length,
            block_count: self.nodes.len() / self.length,
            half_bandwidth: self.bandwidth,
            allocated_bytes: self.allocated_bytes(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::super::Hierarchy;
    use super::*;
    use crate::case::{Boundary, Case, Flow};
    fn grid(n: [usize; 3], boundary: Boundary) -> Grid {
        let mut c: Case = serde_json::from_str(include_str!(
            "../../../../cases/verification/lid-cavity.json"
        ))
        .unwrap();
        c.grid.cells = n;
        c.moving_walls.clear();
        c.boundaries.x = boundary;
        c.flow = Flow::Laminar {
            initial_velocity_m_s: [1., 0., 0.],
            viscosity_m2_s: 0.01,
            acceleration_m_s2: [0.; 3],
        };
        Grid::build(&c).unwrap()
    }
    fn dense(m: &Matrix) -> Vec<Vec<f64>> {
        let n = m.diagonal.len();
        let mut a = vec![vec![0.; n]; n];
        for j in 0..n {
            let mut x = vec![0.; n];
            let mut y = x.clone();
            x[j] = 1.;
            m.product(&x, &mut y);
            for (row, value) in a.iter_mut().zip(y) {
                row[j] = value;
            }
        }
        a
    }
    // Independent pivoted dense elimination, without band/folded storage.
    fn solve(mut a: Vec<Vec<f64>>, mut b: Vec<f64>) -> Vec<f64> {
        let n = b.len();
        for k in 0..n {
            let pivot = (k..n)
                .max_by(|i, j| a[*i][k].abs().total_cmp(&a[*j][k].abs()))
                .unwrap();
            a.swap(k, pivot);
            b.swap(k, pivot);
            assert!(a[k][k].abs() > 0.);
            for i in k + 1..n {
                let s = a[i][k] / a[k][k];
                let (before, after) = a.split_at_mut(i);
                for (entry, pivot) in after[0].iter_mut().zip(&before[k]).skip(k + 1) {
                    *entry -= s * pivot;
                }
                b[i] -= s * b[k];
            }
        }
        for i in (0..n).rev() {
            b[i] = (b[i] - (i + 1..n).map(|j| a[i][j] * b[j]).sum::<f64>()) / a[i][i];
        }
        b
    }
    fn reference(
        a: &[Vec<f64>],
        n: [usize; 3],
        axes: &[usize],
        rhs: &[f64],
        x: &mut [f64],
        back: bool,
    ) {
        let mut groups = vec![];
        let length = axes.iter().map(|a| n[*a]).product();
        for i in 0..x.len() {
            let mut q = [i % n[0], i / n[0] % n[1], i / (n[0] * n[1])];
            if axes.iter().any(|a| q[*a] != 0) {
                continue;
            }
            let mut nodes = vec![];
            for k in 0..length {
                let mut at = k;
                for &axis in axes {
                    q[axis] = at % n[axis];
                    at /= n[axis];
                }
                nodes.push(Grid::index(n, q));
            }
            groups.push(nodes);
        }
        if back {
            groups.reverse();
        }
        for nodes in groups {
            let b = nodes
                .iter()
                .map(|i| {
                    rhs[*i]
                        - (0..x.len())
                            .filter(|j| !nodes.contains(j))
                            .map(|j| a[*i][j] * x[j])
                            .sum::<f64>()
                })
                .collect();
            let block = nodes
                .iter()
                .map(|i| nodes.iter().map(|j| a[*i][*j]).collect())
                .collect();
            for (i, value) in nodes.iter().zip(solve(block, b)) {
                x[*i] = value;
            }
        }
    }
    #[test]
    fn banded_lines_and_small_planes_match_independent_dense_sweeps() {
        for boundary in [Boundary::Wall, Boundary::Periodic, Boundary::Open] {
            for n in [[7, 3, 5], [2, 3, 5]] {
                let g = grid(n, boundary);
                let h = Hierarchy::build(&g, &Control::new(20.)).unwrap();
                let mut dims = n;
                for level in &h.levels {
                    let a = dense(&level.matrix);
                    for axes in [vec![0], vec![1], vec![2], vec![0, 2]] {
                        let periodic = [boundary == Boundary::Periodic, true, false];
                        let mut smoother = BlockSmoother::build(
                            &level.matrix,
                            dims,
                            &axes,
                            periodic,
                            &Control::new(20.),
                        )
                        .unwrap();
                        for backward in [false, true] {
                            let rhs: Vec<_> =
                                (0..a.len()).map(|i| (i as f64 * 0.31).sin()).collect();
                            let mut x: Vec<_> =
                                (0..a.len()).map(|i| (i as f64 * 0.19).cos()).collect();
                            let mut expected = x.clone();
                            reference(&a, dims, &axes, &rhs, &mut expected, backward);
                            smoother.sweep(&level.matrix, &rhs, &mut x, backward);
                            for (v, r) in x.iter().zip(expected) {
                                assert!((v - r).abs() < 1e-9 * r.abs().max(1.));
                            }
                        }
                    }
                    dims = dims.map(|n| if n <= 2 { n } else { n.div_ceil(2) });
                }
            }
        }
    }
    #[test]
    fn folded_periodic_lines_keep_a_narrow_band() {
        let g = grid([17, 3, 3], Boundary::Periodic);
        let h = Hierarchy::build(&g, &Control::new(20.)).unwrap();
        let mut n = g.n;
        for (level, l) in h.levels.iter().enumerate() {
            let block =
                BlockSmoother::build(&l.matrix, n, &[0], [true, true, false], &Control::new(20.))
                    .unwrap();
            assert!(block.bandwidth <= if level == 0 { 2 } else { 4 });
            n = n.map(|v| if v <= 2 { v } else { v.div_ceil(2) });
        }
    }
    #[test]
    fn invalid_block_pivot_fails_without_a_shift_or_fallback() {
        let m = Matrix::build(&[], &[-1.; 8]);
        assert!(
            BlockSmoother::build(&m, [2, 2, 2], &[0], [false; 3], &Control::new(20.))
                .unwrap_err()
                .contains("CFD-E036: numerics.pressure_preconditioner")
        );
    }
}
