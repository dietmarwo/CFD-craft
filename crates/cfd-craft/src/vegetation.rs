//! Porous canopy sources on the unchanged uniform-grid pressure operator.
//! Green1992 and Sanz2003 select source coefficients only; see the flow model card.
use crate::{case::Case, grid::Grid};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Whether any nonzero leaf area is declared. This early return preserves all
/// arithmetic and state bytes of cases with only zero-LAD volumes.
pub fn active(c: &Case) -> bool {
    c.vegetation.iter().any(|v| v.leaf_area_density_m2_m3 > 0.0)
}
#[derive(Clone, Copy, Default)]
struct Coefficients {
    drag: f64,
    k_source: f64,
    k_sink: f64,
    e_source: f64,
    e_sink: f64,
    leaf: f64,
}
fn coefficients(c: &Case, g: &Grid) -> Vec<Coefficients> {
    (0..g.count())
        .map(|i| {
            let mut r = Coefficients::default();
            if !g.fluid[i] {
                return r;
            }
            let p = g.center(i);
            for v in &c.vegetation {
                if v.leaf_area_density_m2_m3 == 0.0
                    || !(0..3).all(|a| v.min_m[a] <= p[a] && p[a] < v.max_m[a])
                {
                    continue;
                }
                let d = v.drag_coefficient * v.leaf_area_density_m2_m3;
                let [bp, bd, c4, c5] = v.turbulence_closure.coefficients();
                r.drag += d;
                r.k_source += bp * d;
                r.k_sink += bd * d;
                r.e_source += c4 * bp * d;
                r.e_sink += c5 * bd * d;
                r.leaf += v.leaf_area_density_m2_m3 * v.leaf_deposition_velocity_m_s;
            }
            r
        })
        .collect()
}
fn speed(u: [f64; 3]) -> f64 {
    u.iter().map(|v| v * v).sum::<f64>().sqrt()
}
/// Frozen nonnegative drag coefficient at each staggered face (1/s), obtained
/// by averaging the represented cell coefficients Cd*LAD*|U|. Empty if inactive.
pub fn face_drag(c: &Case, g: &Grid, u: &[f64]) -> Vec<f64> {
    if !active(c) {
        return Vec::new();
    }
    let cells = g.cell_velocity(u);
    let d: Vec<_> = coefficients(c, g)
        .iter()
        .zip(cells)
        .map(|(v, u)| v.drag * speed(u))
        .collect();
    g.faces
        .iter()
        .map(|f| match (f.lo, f.hi) {
            (Some(i), Some(j)) => 0.5 * (d[i] + d[j]),
            (Some(i), None) | (None, Some(i)) => d[i],
            _ => 0.0,
        })
        .collect()
}
/// Canopy production and implicit loss rates for the k and epsilon equations.
pub(crate) struct TurbulenceSources {
    pub k_source: Vec<f64>,
    pub k_sink: Vec<f64>,
    pub e_source: Vec<f64>,
    pub e_sink: Vec<f64>,
}
pub(crate) fn turbulence(
    c: &Case,
    g: &Grid,
    u: &[f64],
    k: &[f64],
    eps: &[f64],
) -> Option<TurbulenceSources> {
    if !active(c) {
        return None;
    }
    let cells = g.cell_velocity(u);
    let mut r = TurbulenceSources {
        k_source: vec![0.0; g.count()],
        k_sink: vec![0.0; g.count()],
        e_source: vec![0.0; g.count()],
        e_sink: vec![0.0; g.count()],
    };
    for (i, (v, u)) in coefficients(c, g).iter().zip(cells).enumerate() {
        let q = speed(u);
        r.k_source[i] = v.k_source * q.powi(3);
        r.k_sink[i] = v.k_sink * q;
        r.e_source[i] = v.e_source * q.powi(3) * eps[i].max(1e-14) / k[i].max(1e-14);
        r.e_sink[i] = v.e_sink * q;
    }
    Some(r)
}
/// Additional explicit particle sink rate max(LAD*v_leaf), in 1/s.
pub fn maximum_leaf_loss(c: &Case, g: &Grid) -> f64 {
    if !active(c) {
        return 0.0;
    }
    coefficients(c, g)
        .iter()
        .map(|v| v.leaf)
        .fold(0.0, f64::max)
}
/// Add a leaf-collection sink to an existing particle RHS and return its
/// integrated mass removal rate (kg/s). Overlapping boxes add leaf area.
pub fn leaf_terms(c: &Case, g: &Grid, concentrations: &[f64], rhs: &mut [f64]) -> f64 {
    if !active(c) {
        return 0.0;
    }
    let mut removal = 0.0;
    for (i, v) in coefficients(c, g).iter().enumerate() {
        let sink = v.leaf * concentrations[i];
        rhs[i] -= sink;
        removal += sink * g.volume;
    }
    removal
}
/// Instantaneous canopy evidence; integrated drag is per unit air density.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Evidence {
    /// Positive rate of work against canopy drag, divided by density (m5/s3).
    pub drag_power_per_density_m5_s3: f64,
    /// Integral of drag acceleration over fluid volume (m4/s2), with its sign.
    pub integrated_drag_acceleration_m4_s2: [f64; 3],
    /// Number of represented fluid cells per vegetation ID; overlaps count twice.
    pub volume_fluid_cells: BTreeMap<String, usize>,
    /// Quadrature of the actual staggered momentum sink over active face
    /// dual volumes (area times face gradient distance).
    pub drag_quadrature: String,
    /// The model remains numerically verified and physically unvalidated.
    pub validation: String,
}
/// Recompute current canopy drag and coverage from the returned flow field.
pub fn evidence(c: &Case, g: &Grid, u: &[f64]) -> Option<Evidence> {
    if !active(c) {
        return None;
    }
    let drag = face_drag(c, g, u);
    let mut r = Evidence {
        drag_power_per_density_m5_s3: 0.0,
        integrated_drag_acceleration_m4_s2: [0.0; 3],
        volume_fluid_cells: BTreeMap::new(),
        drag_quadrature: "staggered_active_faces_dual_volumes".into(),
        validation: "verified_numerics_unvalidated_physics".into(),
    };
    for (fi, face) in g.faces.iter().enumerate() {
        if matches!(
            face.kind,
            crate::grid::FaceKind::Interior | crate::grid::FaceKind::Outlet
        ) {
            let dual_volume = face.area * face.distance;
            r.drag_power_per_density_m5_s3 += drag[fi] * u[fi] * u[fi] * dual_volume;
            r.integrated_drag_acceleration_m4_s2[face.axis] -= drag[fi] * u[fi] * dual_volume;
        }
    }
    for v in &c.vegetation {
        let count = (0..g.count())
            .filter(|i| {
                g.fluid[*i]
                    && (0..3).all(|a| {
                        let x = g.center(*i)[a];
                        v.min_m[a] <= x && x < v.max_m[a]
                    })
            })
            .count();
        r.volume_fluid_cells.insert(v.id.clone(), count);
    }
    Some(r)
}
