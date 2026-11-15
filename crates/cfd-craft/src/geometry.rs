//! Simple polygon prisms use the same cell-center mask and face operators as boxes.
use crate::case::{Block, Case};
use crate::grid::Grid;
use std::ops::Range;

/// Even-odd crossing test of a ray toward +x. Half-open ray crossings agree
/// with box masks for axis-aligned footprints; the bounding box handles upper
/// boundaries. A point exactly on an edge belongs to the footprint whose
/// interior lies on the +x side of that edge (for a horizontal edge, the +y
/// side). Every crossing is evaluated from the edge's lower endpoint, so the
/// result does not depend on the winding, on the first vertex, or on which of
/// two abutting footprints lists a shared edge: such a point is in exactly one.
pub fn contains(polygon: &[[f64; 2]], p: [f64; 2]) -> bool {
    let mut inside = false;
    for i in 0..polygon.len() {
        let a = polygon[i];
        let b = polygon[(i + 1) % polygon.len()];
        if (a[1] > p[1]) != (b[1] > p[1]) {
            let (lo, hi) = if a[1] < b[1] { (a, b) } else { (b, a) };
            if p[0] < lo[0] + (p[1] - lo[1]) * (hi[0] - lo[0]) / (hi[1] - lo[1]) {
                inside = !inside;
            }
        }
    }
    inside
}
/// Shoelace area of a footprint in m2, independent of winding.
pub fn area(p: &[[f64; 2]]) -> f64 {
    (0..p.len())
        .map(|i| {
            let j = (i + 1) % p.len();
            p[i][0] * p[j][1] - p[j][0] * p[i][1]
        })
        .sum::<f64>()
        .abs()
        * 0.5
}
fn cross(a: [f64; 2], b: [f64; 2], c: [f64; 2]) -> f64 {
    (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
}
fn on_segment(a: [f64; 2], b: [f64; 2], p: [f64; 2]) -> bool {
    cross(a, b, p) == 0. && (0..2).all(|d| p[d] >= a[d].min(b[d]) && p[d] <= a[d].max(b[d]))
}
fn intersects(a: [f64; 2], b: [f64; 2], c: [f64; 2], d: [f64; 2]) -> bool {
    let (u, v, w, x) = (
        cross(a, b, c),
        cross(a, b, d),
        cross(c, d, a),
        cross(c, d, b),
    );
    ((u > 0.) != (v > 0.) && (w > 0.) != (x > 0.))
        || on_segment(a, b, c)
        || on_segment(a, b, d)
        || on_segment(c, d, a)
        || on_segment(c, d, b)
}
/// Validate simple geometry and exact footprint bounding-box agreement.
pub fn valid_polygon(p: &[[f64; 2]], lo: &[f64; 3], hi: &[f64; 3]) -> bool {
    if !(3..=2048).contains(&p.len()) || p.iter().flatten().any(|v| !v.is_finite()) || area(p) <= 0.
    {
        return false;
    }
    for d in 0..2 {
        let a = p.iter().map(|v| v[d]).fold(f64::INFINITY, f64::min);
        let b = p.iter().map(|v| v[d]).fold(f64::NEG_INFINITY, f64::max);
        if (a - lo[d]).abs() > 1e-10 * hi[d].abs().max(1.)
            || (b - hi[d]).abs() > 1e-10 * hi[d].abs().max(1.)
        {
            return false;
        }
    }
    for i in 0..p.len() {
        let j = (i + 1) % p.len();
        if p[i] == p[j] {
            return false;
        }
        for k in i + 1..p.len() {
            let l = (k + 1) % p.len();
            if j == k || l == i {
                continue;
            }
            if intersects(p[i], p[j], p[k], p[l]) {
                return false;
            }
        }
    }
    true
}
/// Center coordinate of cell `q` along an axis of cell width `dx`, the same
/// expression as [`Grid::center`](crate::grid::Grid::center).
fn center(q: usize, dx: f64) -> f64 {
    (q as f64 + 0.5) * dx
}
/// Number of leading indices in `0..n` for which `pred` holds; `pred` must
/// hold on a prefix only.
fn partition_point(n: usize, pred: impl Fn(usize) -> bool) -> usize {
    let (mut lo, mut hi) = (0, n);
    while lo < hi {
        let mid = lo + (hi - lo) / 2;
        if pred(mid) {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    lo
}
/// The cells of one shape on a uniform grid: the index box of the cell centers
/// within its bounds and, per column of that box, whether
/// [`Block::contains`] holds there. Together they select exactly the cells
/// whose centers the shape contains, so the work is the shape's bounding box,
/// not the grid.
pub(crate) struct Raster {
    range: [Range<usize>; 3],
    /// Footprint membership of the columns of `range`, x fastest.
    columns: Vec<bool>,
}
impl Raster {
    /// Needs finite positive cell widths `dx`: cell centers then never
    /// decrease with the index, so the centers with `min <= x < max` on an
    /// axis form one index range (empty for NaN or inverted bounds).
    pub(crate) fn new(b: &Block, n: [usize; 3], dx: [f64; 3]) -> Self {
        debug_assert!(dx.iter().all(|v| v.is_finite() && *v > 0.0));
        let range: [Range<usize>; 3] = std::array::from_fn(|a| {
            let lo = b.min_m[a];
            let first = partition_point(n[a], |q| center(q, dx[a]) < lo || lo.is_nan());
            let end = partition_point(n[a], |q| center(q, dx[a]) < b.max_m[a]);
            first..end.max(first)
        });
        // Every center of the z range is within the z bounds, so one
        // evaluation per column decides the whole column.
        let columns = if range.iter().any(|r| r.is_empty()) {
            vec![]
        } else {
            let z = center(range[2].start, dx[2]);
            range[1]
                .clone()
                .flat_map(|j| range[0].clone().map(move |i| (i, j)))
                .map(|(i, j)| b.contains([center(i, dx[0]), center(j, dx[1]), z]))
                .collect()
        };
        Self { range, columns }
    }
    /// Calls `f(q, index)` for every contained cell, in cell index order.
    pub(crate) fn for_each(&self, n: [usize; 3], mut f: impl FnMut([usize; 3], usize)) {
        if self.columns.is_empty() {
            return;
        }
        let [rx, ry, rz] = &self.range;
        for k in rz.clone() {
            for (jj, j) in ry.clone().enumerate() {
                for (ii, i) in rx.clone().enumerate() {
                    if self.columns[jj * rx.len() + ii] {
                        let q = [i, j, k];
                        f(q, Grid::index(n, q));
                    }
                }
            }
        }
    }
    /// Number of contained cells.
    pub(crate) fn count(&self) -> usize {
        self.columns.iter().filter(|v| **v).count() * self.range[2].len()
    }
}
/// Calls `f(index)` for every cell whose center lies in a shape of the case,
/// once per containing shape (overlapping shapes repeat a cell). Rasterizes
/// each shape over its bounding box; with cell widths that are not finite and
/// positive (an invalid domain, still checked for its other diagnostics) it
/// tests every cell against every shape instead.
pub(crate) fn for_each_solid(c: &Case, mut f: impl FnMut(usize)) {
    let n = c.grid.cells;
    let dx: [f64; 3] = std::array::from_fn(|a| c.domain.size_m[a] / n[a] as f64);
    if dx.iter().all(|v| v.is_finite() && *v > 0.0) {
        for b in &c.geometry {
            Raster::new(b, n, dx).for_each(n, |_, i| f(i));
        }
        return;
    }
    for k in 0..n[2] {
        for j in 0..n[1] {
            for i in 0..n[0] {
                let q = [i, j, k];
                let p = std::array::from_fn(|d| center(q[d], dx[d]));
                if c.geometry.iter().any(|g| g.contains(p)) {
                    f(Grid::index(n, q));
                }
            }
        }
    }
}
/// Minimum represented horizontal fluid run bounded by solids on both ends.
/// Exterior clearances and vertical roof gaps are deliberately excluded.
/// Holds the cell mask, one byte per cell, while it runs.
pub fn minimum_passage(c: &Case) -> Option<usize> {
    if c.geometry.is_empty() {
        return None;
    }
    let n = c.grid.cells;
    let mut solid = vec![false; n.iter().product()];
    for_each_solid(c, |i| solid[i] = true);
    let mut best = None;
    for z in 0..n[2] {
        for a in 0..2 {
            let b = 1 - a;
            for j in 0..n[b] {
                let mut after_solid = false;
                let mut width = 0;
                for i in 0..n[a] {
                    let mut q = [0; 3];
                    q[a] = i;
                    q[b] = j;
                    q[2] = z;
                    if solid[Grid::index(n, q)] {
                        if after_solid && width > 0 {
                            best = Some(best.map_or(width, |old: usize| old.min(width)));
                        }
                        after_solid = true;
                        width = 0;
                    } else {
                        width += 1;
                    }
                }
            }
        }
    }
    best
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn crossings_spikes_and_touching_vertices_are_rejected_with_nonzero_area() {
        // A symmetric bow tie has zero shoelace area and is rejected for that
        // alone. These footprints have positive area, so only the edge tests
        // can reject them.
        let bounds = |p: &[[f64; 2]]| {
            let lo = [0, 1].map(|d| p.iter().map(|v| v[d]).fold(f64::INFINITY, f64::min));
            let hi = [0, 1].map(|d| p.iter().map(|v| v[d]).fold(f64::NEG_INFINITY, f64::max));
            ([lo[0], lo[1], 0.], [hi[0], hi[1], 1.])
        };
        let crossing = [[0., 0.], [4., 0.], [1., 3.], [3., 3.]];
        let spike = [[2., 2.], [4., 2.], [6., 2.], [4., 2.], [4., 4.], [2., 4.]];
        let touching = [[2., 2.], [6., 2.], [6., 6.], [4., 2.], [2., 6.]];
        let overlap = [
            [0., 0.],
            [4., 0.],
            [4., 2.],
            [1., 2.],
            [3., 2.],
            [3., 4.],
            [0., 4.],
        ];
        for p in [&crossing[..], &spike, &touching, &overlap] {
            assert!(area(p) > 0.5);
            let (lo, hi) = bounds(p);
            assert!(!valid_polygon(p, &lo, &hi), "{p:?}");
        }
        // The same outline without the defect is accepted, in both windings,
        // with collinear vertices and with an edge far shorter than a cell.
        let mut simple = vec![
            [2., 2.],
            [4., 2.],
            [6., 2.],
            [6., 6.],
            [6., 6.000001],
            [2., 6.000001],
        ];
        let (lo, hi) = bounds(&simple);
        assert!(valid_polygon(&simple, &lo, &hi));
        simple.reverse();
        assert!(valid_polygon(&simple, &lo, &hi));
        // A repeated neighbor, including a repeated closing vertex, is rejected.
        simple.push(simple[0]);
        assert!(!valid_polygon(&simple, &lo, &hi));
    }
    #[test]
    fn centers_on_a_shared_slanted_edge_are_in_exactly_one_abutting_footprint() {
        // Cell centers of a uniform grid that lie on the common edge A-B of two
        // footprints. Evaluating the crossing from A in one footprint and from
        // B in the other rounded differently, leaving one-cell fluid holes.
        let mut checked = 0;
        for dx in [0.1, 0.3, 0.7] {
            for (i0, j0, steps, slope) in [
                (28usize, 30usize, 12usize, [2isize, -1isize]),
                (27, 0, 10, [2, 1]),
                (3, 5, 9, [1, 3]),
                (11, 40, 7, [3, -1]),
                (0, 0, 12, [1, 1]),
            ] {
                let at = |m: usize| {
                    [
                        (i0 as f64 + 0.5 + (m as isize * slope[0]) as f64) * dx,
                        (j0 as f64 + 0.5 + (m as isize * slope[1]) as f64) * dx,
                    ]
                };
                let (a, b) = (at(0), at(steps));
                let left = [a, b, [b[0] - 50., b[1]], [a[0] - 50., a[1]]];
                let right = [b, a, [a[0] + 50., a[1]], [b[0] + 50., b[1]]];
                for m in 1..steps {
                    let p = at(m);
                    assert_ne!(contains(&left, p), contains(&right, p), "{dx} {p:?}");
                    // Winding and first vertex do not change the answer.
                    let mut reversed = left;
                    reversed.reverse();
                    assert_eq!(contains(&left, p), contains(&reversed, p));
                    let mut rotated = left;
                    rotated.rotate_left(1);
                    assert_eq!(contains(&left, p), contains(&rotated, p));
                    checked += 1;
                }
            }
        }
        assert!(checked > 100);
        // The first recorded failure: dx = 0.7, in neither footprint.
        let (a, b) = ([19.95, 21.349999999999998], [36.75, 12.95]);
        let p = [21.349999999999998, 20.65];
        let left = [a, b, [b[0] - 50., b[1]], [a[0] - 50., a[1]]];
        let right = [b, a, [a[0] + 50., a[1]], [b[0] + 50., b[1]]];
        assert_ne!(contains(&left, p), contains(&right, p));
    }
    #[test]
    fn simple_concave_and_invalid_crossing() {
        let p = [[0., 0.], [2., 0.], [2., 1.], [1., 1.], [1., 2.], [0., 2.]];
        assert!(valid_polygon(&p, &[0., 0., 0.], &[2., 2., 1.]));
        assert_eq!(area(&p), 3.);
        assert!(contains(&p, [0.5, 1.5]));
        assert!(!contains(&p, [1.5, 1.5]));
        assert!(!valid_polygon(
            &[[0., 0.], [2., 2.], [0., 2.], [2., 0.]],
            &[0.; 3],
            &[2., 2., 1.]
        ));
    }
}
