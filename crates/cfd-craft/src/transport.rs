use crate::{
    Result,
    case::*,
    grid::{FaceKind, Grid},
};

pub type Weights = Vec<(usize, f64)>;
pub fn cell_at(g: &Grid, p: [f64; 3]) -> usize {
    Grid::index(
        g.n,
        std::array::from_fn(|a| ((p[a] / g.dx[a]).floor() as usize).min(g.n[a] - 1)),
    )
}
pub fn source_fields(c: &Case, g: &Grid) -> Result<Vec<Vec<f64>>> {
    let mut fields = vec![vec![0.0; g.count()]; c.constituents.len()];
    for s in &c.sources {
        let si = c
            .constituents
            .iter()
            .position(|x| x.id == s.constituent())
            .ok_or("unknown source constituent")?;
        let mut weights = vec![0.0; g.count()];
        match s {
            Source::Point { point_m, .. } => weights[cell_at(g, *point_m)] = 1.0,
            Source::Line { from_m, to_m, .. } => {
                let mut ts = vec![0.0, 1.0];
                for a in 0..3 {
                    let d = to_m[a] - from_m[a];
                    if d.abs() > 1e-14 {
                        for j in 1..g.n[a] {
                            let t = (j as f64 * g.dx[a] - from_m[a]) / d;
                            if t > 0.0 && t < 1.0 {
                                ts.push(t);
                            }
                        }
                    }
                }
                ts.sort_by(f64::total_cmp);
                ts.dedup_by(|a, b| (*a - *b).abs() < 1e-14);
                for p in ts.windows(2) {
                    let t = 0.5 * (p[0] + p[1]);
                    let center = std::array::from_fn(|a| from_m[a] + t * (to_m[a] - from_m[a]));
                    weights[cell_at(g, center)] += p[1] - p[0];
                }
            }
            Source::Volume { min_m, max_m, .. } => {
                for (i, w) in weights.iter_mut().enumerate() {
                    let p = g.center(i);
                    *w = (0..3)
                        .map(|a| {
                            (max_m[a].min(p[a] + 0.5 * g.dx[a])
                                - min_m[a].max(p[a] - 0.5 * g.dx[a]))
                            .max(0.0)
                        })
                        .product();
                }
            }
        }
        if weights
            .iter()
            .zip(&g.fluid)
            .any(|(w, fluid)| *w > 1e-14 && !*fluid)
        {
            return Err(format!(
                "CFD-E040: source {} intersects masked solid; no implicit redistribution",
                s.id()
            ));
        }
        if c.run.mode == Mode::Steady
            && s.rate() > 0.0
            && weights
                .iter()
                .enumerate()
                .any(|(i, w)| *w > 1e-14 && !g.anchored[g.component[i]])
        {
            return Err(format!(
                "CFD-E043: steady source {} has no outlet in its fluid component",
                s.id()
            ));
        }
        let norm = weights.iter().sum::<f64>();
        if norm <= 0.0 {
            return Err(format!("CFD-E041: source {} has no support", s.id()));
        }
        for (dst, w) in fields[si].iter_mut().zip(weights) {
            *dst += s.rate() * w / norm / g.volume;
        }
    }
    if fields.iter().flatten().any(|v| !v.is_finite()) {
        return Err("CFD-E044: represented source density is nonfinite".into());
    }
    Ok(fields)
}
pub fn receptor_weights(g: &Grid, r: &Receptor) -> Result<Weights> {
    let mut result = vec![];
    match r {
        Receptor::Point { point_m, .. } => {
            let base: [isize; 3] =
                std::array::from_fn(|a| (point_m[a] / g.dx[a] - 0.5).floor() as isize);
            let frac: [f64; 3] =
                std::array::from_fn(|a| point_m[a] / g.dx[a] - 0.5 - base[a] as f64);
            for k in 0..2 {
                for j in 0..2 {
                    for i in 0..2 {
                        let b = [i, j, k];
                        let q = std::array::from_fn(|a| {
                            (base[a] + b[a]).clamp(0, g.n[a] as isize - 1) as usize
                        });
                        let w = (0..3)
                            .map(|a| if b[a] == 0 { 1.0 - frac[a] } else { frac[a] })
                            .product::<f64>();
                        if w > 1e-14 {
                            result.push((Grid::index(g.n, q), w));
                        }
                    }
                }
            }
        }
        Receptor::VolumeAverage { min_m, max_m, .. } => {
            for i in 0..g.count() {
                let p = g.center(i);
                let w = (0..3)
                    .map(|a| {
                        (max_m[a].min(p[a] + 0.5 * g.dx[a]) - min_m[a].max(p[a] - 0.5 * g.dx[a]))
                            .max(0.0)
                    })
                    .product::<f64>();
                if w > 1e-14 {
                    result.push((i, w));
                }
            }
        }
    }
    if result.is_empty() || result.iter().any(|(i, _)| !g.fluid[*i]) {
        return Err(format!(
            "CFD-E042: receptor {} is empty or samples through a solid",
            r.id()
        ));
    }
    let norm = result.iter().map(|(_, w)| w).sum::<f64>();
    for (_, w) in &mut result {
        *w /= norm;
    }
    Ok(result)
}
pub fn initial_fields(c: &Case, g: &Grid) -> Vec<Vec<f64>> {
    c.constituents
        .iter()
        .map(|sp| {
            let mut v = vec![0.0; g.count()];
            if let Some(init) = c
                .initial_conditions
                .iter()
                .find(|x| x.constituent() == sp.id)
            {
                match init {
                    Initial::Uniform {
                        concentration_kg_m3,
                        ..
                    } => {
                        for (i, x) in v.iter_mut().enumerate() {
                            if g.fluid[i] {
                                *x = *concentration_kg_m3;
                            }
                        }
                    }
                    Initial::PeriodicGaussian {
                        center_m,
                        sigma_m,
                        total_mass_kg,
                        ..
                    } => {
                        // Integrate a periodized Gaussian by 2-point Gauss quadrature in each cell.
                        for (i, x) in v.iter_mut().enumerate() {
                            if !g.fluid[i] {
                                continue;
                            }
                            let p = g.center(i);
                            let mut value = 1.0;
                            for a in 0..3 {
                                let mut part = 0.0;
                                let images =
                                    (8.0 * sigma_m[a] / c.domain.size_m[a]).ceil() as isize + 1;
                                for sign in [-1.0, 1.0] {
                                    let z = p[a] + sign * g.dx[a] / (2.0 * 3.0f64.sqrt());
                                    for im in -images..=images {
                                        let d = z - center_m[a] + im as f64 * c.domain.size_m[a];
                                        part += 0.5 * (-0.5 * (d / sigma_m[a]).powi(2)).exp();
                                    }
                                }
                                value *= part;
                            }
                            *x = value;
                        }
                        let sum = v.iter().sum::<f64>() * g.volume;
                        for x in &mut v {
                            *x *= total_mass_kg / sum;
                        }
                    }
                }
            }
            v
        })
        .collect()
}
pub fn neighbor(g: &Grid, i: usize, a: usize, side: usize) -> Option<usize> {
    let f = &g.faces[g.cell_faces[i][a][side]];
    if f.kind == FaceKind::Interior {
        if side == 0 { f.lo } else { f.hi }
    } else {
        None
    }
}
fn minmod(a: f64, b: f64) -> f64 {
    if a * b <= 0.0 {
        0.0
    } else {
        a.signum() * a.abs().min(b.abs())
    }
}
fn slope(g: &Grid, c: &[f64], i: usize, a: usize) -> f64 {
    let lo = neighbor(g, i, a, 0).map(|j| c[j]).unwrap_or(c[i]);
    let hi = neighbor(g, i, a, 1).map(|j| c[j]).unwrap_or(c[i]);
    // Monotonized-central limiter: bounded reconstruction with a less diffusive
    // smooth-region slope than the two-argument minmod reference.
    minmod(
        0.5 * (hi - lo),
        minmod(2.0 * (c[i] - lo), 2.0 * (hi - c[i])),
    )
}
/// One transporting face of `rhs` with the velocity and diffusivity fixed.
struct FixedFace {
    lo: Option<usize>,
    hi: Option<usize>,
    velocity: f64,
    diffusivity: f64,
    outlet: bool,
    distance: f64,
    area: f64,
}

/// `rhs` with `Advection::LinearUpwind`, zero inlet values and a fixed velocity
/// and diffusivity, for repeated evaluation (the scalar sub-steps of the
/// implicit steady algorithm). The faces are gathered once; `eval` repeats
/// `rhs_into`'s arithmetic face by face in the same order, so it returns the
/// same bits.
pub(crate) struct FixedRhs<'a> {
    g: &'a Grid,
    faces: Vec<FixedFace>,
}

impl<'a> FixedRhs<'a> {
    pub(crate) fn new(g: &'a Grid, u: &[f64], d: &[f64]) -> Self {
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
            .map(|(fi, f)| FixedFace {
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
        Self { g, faces }
    }

    /// The rates and `v`, as `rhs_into(g, c, u, d, source, LinearUpwind, |_| 0.0, v)`.
    pub(crate) fn eval(&self, c: &[f64], source: &[f64], v: &mut Vec<f64>) -> (f64, f64, f64) {
        v.clear();
        v.extend_from_slice(source);
        let mut inflow = 0.0;
        let mut outflow = 0.0;
        let volume = self.g.volume;
        for f in &self.faces {
            let cl = f.lo.map(|i| c[i]).unwrap_or(0.0);
            let cr = f.hi.map(|i| c[i]).unwrap_or(0.0);
            // `+ 0.0` and `- 0.0` as in `rhs_into`, which adds the zero slope.
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
            let per_volume = flux / volume;
            if let Some(i) = f.lo {
                v[i] -= per_volume;
            }
            if let Some(i) = f.hi {
                v[i] += per_volume;
            }
            if f.lo.is_none() || f.hi.is_none() {
                let outward = if f.lo.is_some() { flux } else { -flux };
                outflow += outward.max(0.0);
                inflow += (-outward).max(0.0);
            }
        }
        (source.iter().sum::<f64>() * volume, inflow, outflow)
    }
}

pub struct Rhs {
    pub values: Vec<f64>,
    pub source: f64,
    pub inflow: f64,
    pub outflow: f64,
}
pub fn rhs(
    g: &Grid,
    c: &[f64],
    u: &[f64],
    d: &[f64],
    source: &[f64],
    advection: Advection,
    inlet: impl Fn(&crate::grid::Face) -> f64,
) -> Rhs {
    let mut values = Vec::new();
    let (source, inflow, outflow) = rhs_into(g, c, u, d, source, advection, inlet, &mut values);
    Rhs {
        values,
        source,
        inflow,
        outflow,
    }
}

/// `rhs` into a reused buffer; returns the source, inflow and outflow rates.
/// The flux of each face is divided by the cell volume once and applied to
/// both cells, which is the same value `rhs` computed for each.
#[allow(clippy::too_many_arguments)]
pub(crate) fn rhs_into(
    g: &Grid,
    c: &[f64],
    u: &[f64],
    d: &[f64],
    source: &[f64],
    advection: Advection,
    inlet: impl Fn(&crate::grid::Face) -> f64,
    v: &mut Vec<f64>,
) -> (f64, f64, f64) {
    v.clear();
    v.extend_from_slice(source);
    let mut inflow = 0.0;
    let mut outflow = 0.0;
    let muscl = advection == Advection::Muscl;
    for (fi, f) in g.faces.iter().enumerate() {
        if !matches!(
            f.kind,
            FaceKind::Interior | FaceKind::Inlet | FaceKind::Outlet
        ) {
            continue;
        }
        let cl = f.lo.map(|i| c[i]).unwrap_or_else(|| inlet(f));
        let cr = f.hi.map(|i| c[i]).unwrap_or_else(|| inlet(f));
        let donor = if u[fi] >= 0.0 {
            f.lo.map(|i| {
                cl + if muscl {
                    0.5 * slope(g, c, i, f.axis)
                } else {
                    0.0
                }
            })
            .unwrap_or(cl)
        } else {
            f.hi.map(|i| {
                cr - if muscl {
                    0.5 * slope(g, c, i, f.axis)
                } else {
                    0.0
                }
            })
            .unwrap_or(cr)
        };
        let diffusivity = match (f.lo, f.hi) {
            (Some(i), Some(j)) => 0.5 * (d[i] + d[j]),
            (Some(i), None) | (None, Some(i)) => d[i],
            _ => 0.0,
        };
        let diff = if f.kind == FaceKind::Outlet {
            0.0
        } else {
            diffusivity * (cl - cr) / f.distance
        };
        let flux = (u[fi] * donor + diff) * f.area;
        let per_volume = flux / g.volume;
        if let Some(i) = f.lo {
            v[i] -= per_volume;
        }
        if let Some(i) = f.hi {
            v[i] += per_volume;
        }
        if f.lo.is_none() || f.hi.is_none() {
            let outward = if f.lo.is_some() { flux } else { -flux };
            outflow += outward.max(0.0);
            inflow += (-outward).max(0.0);
        }
    }
    (source.iter().sum::<f64>() * g.volume, inflow, outflow)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::case::{Block, Boundary, Case};

    // The gathered-face evaluation must return the bits of `rhs` with linear
    // upwind and zero inlet values, on open, periodic, masked and RANS grids.
    #[test]
    fn fixed_rhs_returns_the_bits_of_rhs() {
        let canyon: Case =
            serde_json::from_str(include_str!("../../../cases/canyon/wh1-wind270.json")).unwrap();
        let mut periodic: Case = serde_json::from_str(include_str!(
            "../../../cases/verification/periodic-tracer.json"
        ))
        .unwrap();
        periodic.grid.cells = [6, 1, 5];
        let mut masked = canyon.clone();
        masked.boundaries.y = Boundary::Periodic;
        masked.geometry.push(Block {
            id: "extra".into(),
            min_m: [12.0, 0.0, 0.0],
            max_m: [13.0, 16.0, 2.0],
        });
        for c in [canyon, periodic, masked] {
            let g = Grid::build(&c).unwrap();
            let n = g.count();
            let u: Vec<_> = (0..g.faces.len())
                .map(|i| (0.37 * i as f64).sin() * 2.0)
                .collect();
            let d: Vec<_> = (0..n)
                .map(|i| 0.01 + 0.005 * (0.11 * i as f64).cos())
                .collect();
            let x: Vec<_> = (0..n)
                .map(|i| {
                    if g.fluid[i] {
                        (0.23 * i as f64).cos().abs()
                    } else {
                        0.0
                    }
                })
                .collect();
            let source: Vec<_> = (0..n).map(|i| 1e-3 * (i % 7) as f64).collect();
            let expected = rhs(&g, &x, &u, &d, &source, Advection::LinearUpwind, |_| 0.0);
            let mut values = vec![1.0; 3];
            let (s, inflow, outflow) = FixedRhs::new(&g, &u, &d).eval(&x, &source, &mut values);
            let bits = |v: &[f64]| v.iter().map(|x| x.to_bits()).collect::<Vec<_>>();
            assert_eq!(bits(&values), bits(&expected.values), "{}", c.name);
            assert_eq!(
                [s, inflow, outflow].map(f64::to_bits),
                [expected.source, expected.inflow, expected.outflow].map(f64::to_bits)
            );
        }
    }
}
