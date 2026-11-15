//! Conservative passive-gas transport: source densities, receptor weights,
//! initial fields and the finite-volume right-hand side.
//!
//! Each face flux is advective (upwind or MUSCL) plus diffusive, applied with
//! opposite signs to the two cells, so interior fluxes cancel and mass
//! changes only through sources and boundary faces. Inlets bring zero
//! concentration; outlets have no diffusive flux; walls, slip faces and
//! solids have no flux at all. Concentrations are never clipped: a negative
//! value beyond round-off fails the step (CFD-E053). See the
//! [transport model card](https://github.com/dietmarwo/CFD-craft/blob/main/docs/model-cards/transport.md).
use crate::{
    Result,
    case::*,
    grid::{FaceKind, Grid},
};

/// Sparse receptor weights: `(cell index, weight)` pairs over fluid cells,
/// summing to one. A receptor value is the weighted sum of the cell
/// concentrations.
pub type Weights = Vec<(usize, f64)>;
/// Index of the cell that contains point `p` (meters). Coordinates beyond
/// the domain are clamped to the boundary cells.
pub fn cell_at(g: &Grid, p: [f64; 3]) -> usize {
    Grid::index(
        g.n,
        std::array::from_fn(|a| ((p[a] / g.dx[a]).floor() as usize).min(g.n[a] - 1)),
    )
}
/// Whether a particle has a represented positive removal mechanism in each
/// fluid component. This is a connectivity/admissibility screen, not proof of
/// scalar reachability or numerical convergence. Gases keep the outlet rule.
fn particle_component_sinks(c: &Case, g: &Grid, particle: &ParticleBin) -> Vec<bool> {
    let mut sinks = vec![false; g.components.len()];
    let settling = particle.settling_speed();
    for face in &g.faces {
        if face.axis != 2 || face.lo.is_some() {
            continue;
        }
        let Some(cell) = face.hi else {
            continue;
        };
        let rate = match face.kind {
            FaceKind::Wall => {
                let ground = face.coord[2] == 0 && c.boundaries.z != Boundary::Periodic;
                settling
                    + if ground {
                        particle.ground_deposition_velocity_m_s
                    } else {
                        particle.roof_deposition_velocity_m_s
                    }
            }
            FaceKind::Inlet | FaceKind::Outlet | FaceKind::Slip
                if c.boundaries.z == Boundary::Open && face.coord[2] == 0 =>
            {
                settling
            }
            _ => 0.0,
        };
        if rate > 0.0 {
            sinks[g.component[cell]] = true;
        }
    }
    for (cell, fluid) in g.fluid.iter().enumerate() {
        if !fluid {
            continue;
        }
        let point = g.center(cell);
        if c.vegetation.iter().any(|v| {
            v.leaf_area_density_m2_m3 > 0.0
                && v.leaf_deposition_velocity_m_s > 0.0
                && (0..3).all(|axis| v.min_m[axis] <= point[axis] && point[axis] < v.max_m[axis])
        }) {
            sinks[g.component[cell]] = true;
        }
    }
    sinks
}
/// The represented source density of each constituent, in kg/(m3 s) per
/// cell and in case order. Each source's integrated [`Source::rate`] is
/// distributed over its support (the point's cell, the cells a line crosses,
/// or the overlap of a volume), so the density integrates to that rate.
///
/// # Errors
///
/// `CFD-E040` when the support touches a solid cell (mass is never
/// redistributed), `CFD-E041` without support, `CFD-E043` for a steady
/// source in a fluid component without an outlet, `CFD-E044` for a nonfinite
/// density.
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
        let particle_sinks = if c.run.mode == Mode::Steady && s.rate() > 0.0 {
            c.constituents[si]
                .particle
                .as_ref()
                .map(|particle| particle_component_sinks(c, g, particle))
        } else {
            None
        };
        if c.run.mode == Mode::Steady
            && s.rate() > 0.0
            && weights.iter().enumerate().any(|(i, w)| {
                *w > 1e-14
                    && !g.anchored[g.component[i]]
                    && !particle_sinks
                        .as_ref()
                        .is_some_and(|sinks| sinks[g.component[i]])
            })
        {
            return Err(format!(
                "CFD-E043: steady source {} has no outlet or represented particle deposition sink in its fluid component",
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
/// Geometry and arc-length quadrature of a path receptor.
#[derive(Clone, Debug)]
pub struct PathSamples {
    /// Ordered three-dimensional positions, in local meters.
    pub points_m: Vec<[f64; 3]>,
    /// Distance from the first vertex, in meters, including zero and full length.
    pub distance_m: Vec<f64>,
    /// Normalized trapezoidal coefficient of each sample in the path mean.
    pub mean_weights: Vec<f64>,
}
/// A path's geometry and ordinary linear interpolation weights for every sample.
#[derive(Clone, Debug)]
pub struct PathWeights {
    /// Generated sample geometry and path-mean quadrature.
    pub samples: PathSamples,
    /// Cell interpolation weights, one sparse vector per generated sample.
    pub weights: Vec<Weights>,
}
/// Generate equally spaced arc-length samples with both endpoints included.
/// The actual spacing is length/ceil(length/requested_spacing). No flow or
/// transport equation is changed. Invalid paths/sample counts are CFD-E086/88.
pub fn path_samples(receptor: &Receptor) -> Result<PathSamples> {
    let Receptor::Path {
        polyline_m,
        height_m,
        ..
    } = receptor
    else {
        return Err("CFD-E086: receptors: path sampling requires a path receptor".into());
    };
    let count = receptor.path_sample_count().unwrap_or(usize::MAX);
    if count > PATH_SAMPLES_MAX {
        return Err(format!(
            "CFD-E088: receptor {} exceeds 20001 path samples",
            receptor.id()
        ));
    }
    if !(2..=4097).contains(&polyline_m.len())
        || !height_m.is_finite()
        || polyline_m.iter().flatten().any(|v| !v.is_finite())
    {
        return Err(format!(
            "CFD-E086: receptor {} has invalid path vertices/height",
            receptor.id()
        ));
    }
    let mut cumulative = vec![0.0];
    for segment in polyline_m.windows(2) {
        let length = (segment[1][0] - segment[0][0]).hypot(segment[1][1] - segment[0][1]);
        if length <= 0.0 {
            return Err(format!(
                "CFD-E086: receptor {} has a zero-length segment",
                receptor.id()
            ));
        }
        cumulative.push(cumulative.last().unwrap() + length);
    }
    let length = *cumulative.last().unwrap();
    let intervals = count - 1;
    let mut result = PathSamples {
        points_m: Vec::with_capacity(count),
        distance_m: Vec::with_capacity(count),
        mean_weights: Vec::with_capacity(count),
    };
    let mut segment = 0;
    for sample in 0..count {
        let distance = if sample == intervals {
            length
        } else {
            length * sample as f64 / intervals as f64
        };
        while segment + 2 < cumulative.len() && cumulative[segment + 1] < distance {
            segment += 1;
        }
        let t = ((distance - cumulative[segment])
            / (cumulative[segment + 1] - cumulative[segment]))
            .clamp(0.0, 1.0);
        let point = if sample == intervals {
            let p = polyline_m.last().unwrap();
            [p[0], p[1], *height_m]
        } else {
            let from = polyline_m[segment];
            let to = polyline_m[segment + 1];
            [
                from[0] + t * (to[0] - from[0]),
                from[1] + t * (to[1] - from[1]),
                *height_m,
            ]
        };
        result.points_m.push(point);
        result.distance_m.push(distance);
        result
            .mean_weights
            .push(if sample == 0 || sample == intervals {
                0.5 / intervals as f64
            } else {
                1.0 / intervals as f64
            });
    }
    Ok(result)
}
fn check_path_segments(g: &Grid, receptor: &Receptor) -> Result<()> {
    let Receptor::Path {
        polyline_m,
        height_m,
        ..
    } = receptor
    else {
        return Ok(());
    };
    if polyline_m.iter().any(|p| {
        p[0] < 0.0
            || p[1] < 0.0
            || p[0] >= g.n[0] as f64 * g.dx[0]
            || p[1] >= g.n[1] as f64 * g.dx[1]
    }) || *height_m < 0.0
        || *height_m >= g.n[2] as f64 * g.dx[2]
    {
        return Err(format!(
            "CFD-E086: receptor {} path is outside the domain",
            receptor.id()
        ));
    }
    for (segment_index, segment) in polyline_m.windows(2).enumerate() {
        let mut crossings = vec![0.0, 1.0];
        for (axis, (&start, &end)) in segment[0].iter().zip(&segment[1]).enumerate() {
            let delta = end - start;
            if delta == 0.0 {
                continue;
            }
            for k in 1..g.n[axis] {
                let t = (k as f64 * g.dx[axis] - start) / delta;
                if t > 0.0 && t < 1.0 {
                    crossings.push(t);
                }
            }
        }
        crossings.sort_by(f64::total_cmp);
        for pair in crossings.windows(2) {
            if pair[1] <= pair[0] {
                continue;
            }
            let t = 0.5 * (pair[0] + pair[1]);
            let point = [
                segment[0][0] + t * (segment[1][0] - segment[0][0]),
                segment[0][1] + t * (segment[1][1] - segment[0][1]),
                *height_m,
            ];
            if !g.fluid[cell_at(g, point)] {
                return Err(format!(
                    "CFD-E087: receptor {} path segment {segment_index} crosses a represented solid cell",
                    receptor.id()
                ));
            }
        }
    }
    Ok(())
}
/// Build the ordinary point interpolation weights of every generated path
/// sample. Entire segments are checked for solid crossings, including between
/// sample positions; each point also retains the strict through-wall stencil rule.
pub fn receptor_path_weights(g: &Grid, receptor: &Receptor) -> Result<PathWeights> {
    let samples = path_samples(receptor)?;
    check_path_segments(g, receptor)?;
    let weights = samples
        .points_m
        .iter()
        .map(|point| {
            receptor_weights(
                g,
                &Receptor::Point {
                    id: receptor.id().to_string(),
                    point_m: *point,
                },
            )
            .map_err(|e| {
                format!(
                    "CFD-E087: receptor {} path sample has invalid interpolation support: {e}",
                    receptor.id()
                )
            })
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(PathWeights { samples, weights })
}
/// The normalized sampling weights of a receptor: trilinear interpolation
/// between cell centers (clamped at the domain boundary) for a point, exact
/// cell overlap for a volume average.
///
/// # Errors
///
/// `CFD-E042` when the receptor has no weight or a positive weight on a
/// solid cell.
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
        Receptor::Path { .. } => {
            let path = receptor_path_weights(g, r)?;
            let mut combined = std::collections::BTreeMap::<usize, f64>::new();
            for (weights, coefficient) in path.weights.iter().zip(&path.samples.mean_weights) {
                for (cell, value) in weights {
                    *combined.entry(*cell).or_default() += coefficient * value;
                }
            }
            result = combined.into_iter().collect();
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
/// Initial concentration of each constituent in kg/m3, per cell and in case
/// order, from the case's initial conditions; zero without one and always
/// zero in solid cells.
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
/// The fluid cell across the lower (`side = 0`) or upper (`side = 1`) face
/// of cell `i` along axis `a`, or `None` when that face is not interior. On
/// a one-cell periodic axis the neighbor is `i` itself.
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

/// The transport right-hand side of one constituent and its mass rates.
pub struct Rhs {
    /// Rate of change of the concentration per cell, in kg/(m3 s).
    pub values: Vec<f64>,
    /// Emission rate of the source density over the domain, in kg/s.
    pub source: f64,
    /// Mass entering through boundary faces, in kg/s, nonnegative.
    pub inflow: f64,
    /// Mass leaving through boundary faces, in kg/s, nonnegative.
    pub outflow: f64,
}
/// Finite-volume right-hand side `dc/dt` of concentration `c` for face
/// velocities `u`, cell diffusivities `d` (m2/s, averaged to the faces), the
/// source density `source` (kg/(m3 s)) and the advection scheme. `inlet`
/// gives the concentration outside a boundary face, used for inflow
/// including backflow at an outlet; the solver uses zero. Interior, inlet
/// and outlet faces carry flux; outlets carry no diffusion.
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

/// Add conservative downward settling and absorbing ground/roof fluxes to an
/// already evaluated gas RHS. Returns additional open-boundary outflow and
/// deposition rates by surface. Interior settling uses first-order upwind;
/// the same flux is applied with opposite signs to neighboring fluid cells.
pub fn particle_terms(
    case: &Case,
    g: &Grid,
    particle: &ParticleBin,
    concentrations: &[f64],
    values: &mut [f64],
) -> (f64, std::collections::BTreeMap<String, f64>) {
    let settling = particle.settling_speed();
    let mut outflow = 0.0;
    let mut deposited = std::collections::BTreeMap::new();
    for f in &g.faces {
        if f.axis != 2 {
            continue;
        }
        match f.kind {
            FaceKind::Interior => {
                let (Some(lo), Some(hi)) = (f.lo, f.hi) else {
                    continue;
                };
                if lo == hi {
                    continue; // one-cell periodic axis: exactly zero drift operator
                }
                let flux = settling * concentrations[hi] * f.area / g.volume;
                values[lo] += flux;
                values[hi] -= flux;
            }
            FaceKind::Inlet | FaceKind::Outlet | FaceKind::Slip
                if case.boundaries.z == Boundary::Open =>
            {
                // Downward drift carries zero incremental concentration into the
                // upper boundary, and removes mass at an open lower boundary.
                if let (None, Some(hi)) = (f.lo, f.hi) {
                    let flux = settling * concentrations[hi] * f.area;
                    values[hi] -= flux / g.volume;
                    outflow += flux;
                }
            }
            FaceKind::Wall => {
                if let (None, Some(hi)) = (f.lo, f.hi) {
                    let (name, extra) =
                        if f.coord[2] == 0 && case.boundaries.z != Boundary::Periodic {
                            ("ground", particle.ground_deposition_velocity_m_s)
                        } else {
                            ("roof", particle.roof_deposition_velocity_m_s)
                        };
                    let flux = (settling + extra) * concentrations[hi] * f.area;
                    values[hi] -= flux / g.volume;
                    if flux != 0.0 {
                        *deposited.entry(name.to_string()).or_insert(0.0) += flux;
                    }
                }
            }
            _ => {}
        }
    }
    (outflow, deposited)
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
            footprint_m: None,
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
