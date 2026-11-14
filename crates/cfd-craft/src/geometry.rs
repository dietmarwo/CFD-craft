//! Simple polygon prisms use the same cell-center mask and face operators as boxes.
use crate::case::Case;

/// Signed-crossing point test. Half-open ray crossings agree with box masks
/// for axis-aligned footprints; the bounding box handles upper boundaries.
pub fn contains(polygon: &[[f64; 2]], p: [f64; 2]) -> bool {
    let mut inside = false;
    for i in 0..polygon.len() {
        let a = polygon[i];
        let b = polygon[(i + 1) % polygon.len()];
        if (a[1] > p[1]) != (b[1] > p[1])
            && p[0] < a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
        {
            inside = !inside;
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
/// Minimum represented horizontal fluid run bounded by solids on both ends.
/// Exterior clearances and vertical roof gaps are deliberately excluded.
pub fn minimum_passage(c: &Case) -> Option<usize> {
    if c.geometry.is_empty() {
        return None;
    }
    let n = c.grid.cells;
    let dx: [f64; 3] = std::array::from_fn(|a| c.domain.size_m[a] / n[a] as f64);
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
                    let p = std::array::from_fn(|d| (q[d] as f64 + 0.5) * dx[d]);
                    if c.geometry.iter().any(|g| g.contains(p)) {
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
