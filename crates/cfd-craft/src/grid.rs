//! The uniform staggered grid of a case: cells, faces, the solid mask and
//! the fluid components.
//!
//! [`Grid::build`] turns a valid [`Case`] into the represented topology.
//! Cells are uniform boxes of size `dx`; a cell is solid when its center lies
//! inside a geometry box. Cell index `(k * ny + j) * nx + i` runs x fastest
//! ([`Grid::index`]). Velocities live on faces: `faces` holds the x-faces,
//! then the y-faces, then the z-faces, each block x fastest over its
//! [`face_dims`](Grid::face_dims), with one extra face along a nonperiodic
//! axis; a periodic axis wraps and has no duplicate end face. Every face has
//! a [`FaceKind`] that fixes its role in the equations.
//!
//! Cells joined through interior faces form fluid components. A component
//! touching an outlet is *anchored*; any other has a mean-zero pressure gauge
//! and needs compatible net flux. [`GeometryEvidence`] summarizes the mask
//! for geometry.json, and [`Grid::mask_topology`] counts components without
//! building faces.
//!
//! The public fields are the representation the solver uses. Callers can
//! read them freely; changing them breaks the invariants the operators rely
//! on (rebuild the grid instead).
//!
//! ```
//! # let json = r#"{"schema_version": "cfd-craft.case/0.1", "name": "tiny",
//! #   "domain": {"size_m": [4.0, 1.0, 1.0]}, "grid": {"cells": [8, 2, 2]},
//! #   "boundaries": {"x": "open", "y": "periodic", "z": "periodic"},
//! #   "flow": {"kind": "prescribed_uniform", "velocity_m_s": [1.0, 0.0, 0.0]},
//! #   "numerics": {"transport": "linear_upwind", "max_time_step_s": 1.0,
//! #     "advective_cfl_max": 0.4, "pressure_relative_tolerance": 1e-10,
//! #     "pressure_max_iterations": 100, "steady_residual_tolerance": 1e-5,
//! #     "steady_monitor_tolerance": 1e-3, "monitor_window": 10},
//! #   "run": {"mode": "steady", "end_time_s": 1.0, "max_steps": 1000,
//! #     "wall_time_limit_s": 30.0, "threads": 1, "memory_limit_mib": 64},
//! #   "output": {"fields": false, "checkpoint": false, "max_total_mib": 4}}"#;
//! use cfd_craft::{case::Case, grid::{FaceKind, Grid}};
//!
//! let case: Case = serde_json::from_str(json).unwrap();
//! let g = Grid::build(&case)?;
//! assert_eq!((g.count(), g.dx), (32, [0.5, 0.5, 0.5]));
//! // Open x: 9 x 2 x 2 x-faces; periodic y and z: 8 x 2 x 2 each.
//! assert_eq!(g.faces.len(), 36 + 32 + 32);
//! let i = Grid::index(g.n, [3, 1, 0]);
//! assert_eq!(g.coord(i), [3, 1, 0]);
//! assert_eq!(g.center(i), [1.75, 0.75, 0.25]);
//! // The flow enters at x = 0 and leaves at x = 4 m, which anchors the
//! // single fluid component.
//! let [lower, upper] = g.cell_faces[Grid::index(g.n, [0, 0, 0])][0];
//! assert_eq!(g.faces[lower].kind, FaceKind::Inlet);
//! assert_eq!(g.faces[g.cell_faces[Grid::index(g.n, [7, 0, 0])][0][1]].kind, FaceKind::Outlet);
//! assert_eq!(g.faces[upper].kind, FaceKind::Interior);
//! assert_eq!((g.components.len(), g.anchored[0]), (1, true));
//! # Ok::<(), String>(())
//! ```
use crate::{Result, case::*};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, VecDeque};

/// The role of a face in the equations.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FaceKind {
    /// Fluid cells on both sides: carries a momentum equation and fluxes.
    Interior,
    /// Impermeable no-slip face: between a fluid and a solid cell, on a
    /// `wall` boundary, or the ground of `ground_open_top`. Normal velocity
    /// zero; the tangential condition enters through wall ghost values
    /// (moving walls, wall functions with `neutral_rans`).
    Wall,
    /// Impermeable stress-free face: a `slip` boundary, the top of
    /// `ground_open_top`, or an `open` boundary face without normal case flow.
    Slip,
    /// `open` boundary face where the case flow enters: the velocity is
    /// prescribed from [`Flow::vector`] and the inflow concentration is zero.
    Inlet,
    /// `open` boundary face where the case flow leaves: carries a momentum
    /// equation, fixes the pressure level (zero outside) and anchors its
    /// fluid component.
    Outlet,
    /// No fluid on either side, for example inside a solid or on a domain
    /// face of a solid cell. Velocity zero; no flux.
    Blocked,
}
/// One staggered face. The face normal is `axis`; `lo` and `hi` are the fluid
/// cells below and above it along that axis.
#[derive(Clone, Debug)]
pub struct Face {
    /// Normal axis: 0 (x), 1 (y) or 2 (z).
    pub axis: usize,
    /// Integer position in this axis's face array, of dimensions
    /// `Grid::face_dims[axis]`. It is the lower face of the cell with the
    /// same coordinates; the last face of a nonperiodic axis is the upper face
    /// of the last cell.
    pub coord: [usize; 3],
    /// Face center in meters.
    pub center: [f64; 3],
    /// Fluid cell below the face along `axis`; `None` for a solid cell or
    /// outside the domain. Across a periodic boundary it is the wrapped cell.
    pub lo: Option<usize>,
    /// Fluid cell above the face along `axis`; `None` for a solid cell or
    /// outside the domain.
    pub hi: Option<usize>,
    /// Role of the face.
    pub kind: FaceKind,
    /// Face area in m2.
    pub area: f64,
    /// Distance in meters over which the face gradient is taken: the cell
    /// width for interior faces, half of it (cell center to face) otherwise.
    pub distance: f64,
}
/// The represented topology of a case: uniform cells, the solid mask,
/// staggered faces and the fluid components, plus lazily built caches of the
/// pressure and implicit-momentum operators. Build it with
/// [`build`](Self::build); see the [module docs](self) for the layout.
#[derive(Clone, Debug)]
pub struct Grid {
    /// Cell counts along x, y and z.
    pub n: [usize; 3],
    /// Cell sizes in meters: domain length over cell count.
    pub dx: [f64; 3],
    /// Cell volume in m3.
    pub volume: f64,
    /// Per cell, true for fluid and false for solid.
    pub fluid: Vec<bool>,
    /// All faces: x-faces, then y-faces, then z-faces, each block x fastest.
    pub faces: Vec<Face>,
    /// Per cell and axis, the indices of its lower and upper faces in
    /// `faces`. `usize::MAX` for solid cells. On a one-cell periodic axis
    /// both entries are the same face.
    pub cell_faces: Vec<[[usize; 2]; 3]>,
    /// Per cell, the index of its fluid component; `usize::MAX` for solid
    /// cells.
    pub component: Vec<usize>,
    /// The cells of each fluid component, in breadth-first order from its
    /// lowest cell index.
    pub components: Vec<Vec<usize>>,
    /// Per component, whether it touches an outlet face, which fixes its
    /// pressure level. Other components get a mean-zero pressure gauge and
    /// must receive zero net flux (CFD-E031).
    pub anchored: Vec<bool>,
    /// Dimensions of the face array of each axis: `n`, plus one along that
    /// axis when it is not periodic.
    pub face_dims: [[usize; 3]; 3],
    offsets: [usize; 3],
    /// Per geometry box ID, the number of cells whose center lies inside it;
    /// overlapping boxes share cells.
    pub box_cells: BTreeMap<String, usize>,
    /// IC(0) factor of the pressure operator, built by the first IC(0)
    /// pressure solve and reused afterwards. It is only a preconditioner and
    /// is not rebuilt if face coefficients change.
    pub pressure_factor: std::sync::OnceLock<crate::pressure::Factor>,
    /// Preconditioner of the pressure solves on this grid, copied from
    /// `numerics.pressure_preconditioner`.
    pub pressure_preconditioner: PressurePreconditioner,
    pub(crate) pressure_multigrid: std::sync::Arc<crate::multigrid::Cache>,
    /// Built on first use by the implicit pseudo-time algorithms.
    pub(crate) momentum_stencil: std::sync::OnceLock<crate::momentum_solve::Stencil>,
    /// Same-axis neighbor faces of every face, [direction][side], from `face_at`.
    pub(crate) neighbor_faces: std::sync::OnceLock<Vec<[[Option<usize>; 2]; 3]>>,
    /// For an a-face at q and d ≠ a, the d-faces at q + e_d and q + e_d − e_a.
    pub(crate) edge_faces: std::sync::OnceLock<Vec<[[Option<usize>; 2]; 3]>>,
}
/// Summary of the represented mask, written as geometry.json. The mask
/// itself is not archived; it is rebuilt from the case boxes and checked
/// against `mask_sha256`.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GeometryEvidence {
    /// Number of fluid cells.
    pub fluid_cells: usize,
    /// Number of solid cells.
    pub solid_cells: usize,
    /// Number of face-connected fluid regions.
    pub fluid_components: usize,
    /// Represented solid volume in m3: solid cells times the cell volume.
    pub solid_volume_m3: f64,
    /// SHA-256 of the mask as one byte per cell (1 fluid, 0 solid), in cell
    /// order.
    pub mask_sha256: String,
    /// Cells whose center lies inside each box, by box ID; overlapping boxes share cells.
    pub box_cells: BTreeMap<String, usize>,
}
/// Topology of a case's cell mask, from [`Grid::mask_topology`].
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MaskTopology {
    /// Number of face-connected fluid regions, including periodic wraps.
    pub fluid_components: usize,
    /// Number of solid cells.
    pub solid_cells: usize,
    /// Solid cells times the cell volume, in m3.
    pub solid_volume_m3: f64,
}
impl Grid {
    /// Number of cells, fluid and solid.
    pub fn count(&self) -> usize {
        self.fluid.len()
    }
    /// Linear index of cell `p = [i, j, k]` in a grid of `n` cells:
    /// `(k * n[1] + j) * n[0] + i`, x fastest. Also indexes a face array with
    /// its `face_dims`.
    pub fn index(n: [usize; 3], p: [usize; 3]) -> usize {
        (p[2] * n[1] + p[1]) * n[0] + p[0]
    }
    /// The `[i, j, k]` coordinates of cell index `i`; the inverse of
    /// [`index`](Self::index).
    pub fn coord(&self, i: usize) -> [usize; 3] {
        [
            i % self.n[0],
            i / self.n[0] % self.n[1],
            i / (self.n[0] * self.n[1]),
        ]
    }
    /// Center of cell `i` in meters.
    pub fn center(&self, i: usize) -> [f64; 3] {
        let q = self.coord(i);
        std::array::from_fn(|a| (q[a] as f64 + 0.5) * self.dx[a])
    }
    /// Builds the grid of a case: validates it (an invalid case returns the
    /// serialized check report), masks the cells whose centers lie in a box,
    /// classifies every face and finds the fluid components.
    ///
    /// # Errors
    ///
    /// `CFD-E028` when a box contains no cell center (the grid would not
    /// represent it) and `CFD-E030` when no fluid cell remains. Source and
    /// receptor support are checked separately, by
    /// [`transport::source_fields`](crate::transport::source_fields) and
    /// [`transport::receptor_weights`](crate::transport::receptor_weights).
    pub fn build(c: &Case) -> Result<Self> {
        c.validate()?;
        let n = c.grid.cells;
        let dx = std::array::from_fn(|a| c.domain.size_m[a] / n[a] as f64);
        let volume = dx.iter().product();
        let count = n.iter().product();
        let mut g = Self {
            n,
            dx,
            volume,
            fluid: vec![true; count],
            faces: vec![],
            cell_faces: vec![[[usize::MAX; 2]; 3]; count],
            component: vec![usize::MAX; count],
            components: vec![],
            anchored: vec![],
            face_dims: [n; 3],
            offsets: [0; 3],
            box_cells: BTreeMap::new(),
            pressure_factor: std::sync::OnceLock::new(),
            pressure_preconditioner: c.numerics.pressure_preconditioner,
            pressure_multigrid: Default::default(),
            momentum_stencil: std::sync::OnceLock::new(),
            neighbor_faces: std::sync::OnceLock::new(),
            edge_faces: std::sync::OnceLock::new(),
        };
        let mut box_cells = vec![0usize; c.geometry.len()];
        for i in 0..count {
            let p = g.center(i);
            for (b, n) in c.geometry.iter().zip(box_cells.iter_mut()) {
                if (0..3).all(|a| p[a] >= b.min_m[a] && p[a] < b.max_m[a]) {
                    g.fluid[i] = false;
                    *n += 1;
                }
            }
        }
        for (i, (b, n)) in c.geometry.iter().zip(&box_cells).enumerate() {
            if *n == 0 {
                return Err(format!(
                    "CFD-E028: geometry[{i}] (box {}) contains no cell center, so the grid does not represent it; enlarge it or refine the grid",
                    b.id
                ));
            }
        }
        g.box_cells = c
            .geometry
            .iter()
            .map(|b| b.id.clone())
            .zip(box_cells)
            .collect();
        if !g.fluid.iter().any(|b| *b) {
            return Err("CFD-E030: geometry contains no fluid cells".into());
        }
        for a in 0..3 {
            g.offsets[a] = g.faces.len();
            let periodic = c.boundaries.at(a) == Boundary::Periodic;
            if !periodic {
                g.face_dims[a][a] += 1;
            }
            let dims = g.face_dims[a];
            for k in 0..dims[2] {
                for j in 0..dims[1] {
                    for i in 0..dims[0] {
                        let q = [i, j, k];
                        let t = q[a];
                        let lo0 = if t > 0 {
                            let mut p = q;
                            p[a] -= 1;
                            Some(Self::index(n, p))
                        } else if periodic {
                            let mut p = q;
                            p[a] = n[a] - 1;
                            Some(Self::index(n, p))
                        } else {
                            None
                        };
                        let hi0 = if t < n[a] {
                            Some(Self::index(n, q))
                        } else {
                            None
                        };
                        let lo = lo0.filter(|x| g.fluid[*x]);
                        let hi = hi0.filter(|x| g.fluid[*x]);
                        let center = std::array::from_fn(|d| {
                            (q[d] as f64 + if d == a { 0.0 } else { 0.5 }) * dx[d]
                        });
                        let kind = if lo.is_some() && hi.is_some() {
                            FaceKind::Interior
                        } else if lo.is_none() && hi.is_none() {
                            FaceKind::Blocked
                        } else if lo0.is_some() && hi0.is_some() {
                            FaceKind::Wall
                        } else {
                            match c.boundaries.at(a) {
                                Boundary::Wall => FaceKind::Wall,
                                Boundary::Slip => FaceKind::Slip,
                                Boundary::GroundOpenTop => {
                                    if t == 0 {
                                        FaceKind::Wall
                                    } else {
                                        FaceKind::Slip
                                    }
                                }
                                Boundary::Open => {
                                    let normal = if t == 0 { -1.0 } else { 1.0 };
                                    let v = c.flow.vector(center[2])[a] * normal;
                                    if v < -1e-12 {
                                        FaceKind::Inlet
                                    } else if v > 1e-12 {
                                        FaceKind::Outlet
                                    } else {
                                        FaceKind::Slip
                                    }
                                }
                                Boundary::Periodic => unreachable!(),
                            }
                        };
                        let f = g.faces.len();
                        if let Some(x) = lo {
                            g.cell_faces[x][a][1] = f;
                        }
                        if let Some(x) = hi {
                            g.cell_faces[x][a][0] = f;
                        }
                        g.faces.push(Face {
                            axis: a,
                            coord: q,
                            center,
                            lo,
                            hi,
                            kind,
                            area: volume / dx[a],
                            distance: if kind == FaceKind::Interior {
                                dx[a]
                            } else {
                                0.5 * dx[a]
                            },
                        });
                    }
                }
            }
        }
        for start in 0..count {
            if !g.fluid[start] || g.component[start] != usize::MAX {
                continue;
            }
            let id = g.components.len();
            let mut members = vec![];
            let mut queue = VecDeque::from([start]);
            g.component[start] = id;
            let mut anchored = false;
            while let Some(i) = queue.pop_front() {
                members.push(i);
                for pair in g.cell_faces[i] {
                    for fi in pair {
                        let f = &g.faces[fi];
                        anchored |= f.kind == FaceKind::Outlet;
                        if f.kind != FaceKind::Interior {
                            continue;
                        }
                        let j = if f.lo == Some(i) {
                            f.hi.unwrap()
                        } else {
                            f.lo.unwrap()
                        };
                        if g.component[j] == usize::MAX {
                            g.component[j] = id;
                            queue.push_back(j);
                        }
                    }
                }
            }
            g.components.push(members);
            g.anchored.push(anchored);
        }
        Ok(g)
    }
    /// Fluid-component and solid-cell counts of the case's grid, computed from the cell
    /// mask with a union-find over 4 bytes per cell, without building faces or the pressure
    /// operator. Cells connect through shared faces, including periodic wraps, as in
    /// [`Grid::build`]. Needs only valid axes (2..4096 cells, or 1..4096 on a
    /// periodic axis, at most 1e8 in total).
    pub fn mask_topology(c: &Case) -> Result<MaskTopology> {
        let n = c.grid.cells;
        let count = n.iter().try_fold(1usize, |p, v| p.checked_mul(*v));
        let valid = (0..3).all(|a| {
            let minimum = if c.boundaries.at(a) == Boundary::Periodic {
                1
            } else {
                2
            };
            (minimum..=4096).contains(&n[a])
        });
        let count = match count {
            Some(v) if valid && v <= 100_000_000 => v,
            _ => {
                return Err(
                    "the grid needs 2..4096 cells per axis (1..4096 on a periodic axis) and at most 1e8 cells"
                        .into(),
                );
            }
        };
        const SOLID: u32 = u32::MAX;
        let dx: [f64; 3] = std::array::from_fn(|a| c.domain.size_m[a] / n[a] as f64);
        let mut parent: Vec<u32> = (0..count as u32).collect();
        let mut solid_cells = 0usize;
        for (i, p) in parent.iter_mut().enumerate() {
            let q = [i % n[0], i / n[0] % n[1], i / (n[0] * n[1])];
            let x: [f64; 3] = std::array::from_fn(|a| (q[a] as f64 + 0.5) * dx[a]);
            if c.geometry
                .iter()
                .any(|b| (0..3).all(|a| x[a] >= b.min_m[a] && x[a] < b.max_m[a]))
            {
                *p = SOLID;
                solid_cells += 1;
            }
        }
        fn root(parent: &mut [u32], mut i: u32) -> u32 {
            while parent[i as usize] != i {
                let up = parent[parent[i as usize] as usize];
                parent[i as usize] = up;
                i = up;
            }
            i
        }
        for i in 0..count {
            if parent[i] == SOLID {
                continue;
            }
            let q = [i % n[0], i / n[0] % n[1], i / (n[0] * n[1])];
            for a in 0..3 {
                let lo = if q[a] > 0 {
                    q[a] - 1
                } else if c.boundaries.at(a) == Boundary::Periodic {
                    n[a] - 1
                } else {
                    continue;
                };
                let mut p = q;
                p[a] = lo;
                let j = Self::index(n, p);
                if parent[j] == SOLID {
                    continue;
                }
                let (ri, rj) = (root(&mut parent, i as u32), root(&mut parent, j as u32));
                if ri != rj {
                    parent[ri.max(rj) as usize] = ri.min(rj);
                }
            }
        }
        let fluid_components = (0..count)
            .filter(|i| parent[*i] != SOLID && root(&mut parent, *i as u32) == *i as u32)
            .count();
        Ok(MaskTopology {
            fluid_components,
            solid_cells,
            solid_volume_m3: solid_cells as f64 * dx.iter().product::<f64>(),
        })
    }
    /// The geometry evidence of this grid, as written to geometry.json.
    pub fn evidence(&self) -> GeometryEvidence {
        let fluid_cells = self.fluid.iter().filter(|v| **v).count();
        GeometryEvidence {
            fluid_cells,
            solid_cells: self.count() - fluid_cells,
            fluid_components: self.components.len(),
            solid_volume_m3: (self.count() - fluid_cells) as f64 * self.volume,
            mask_sha256: hash_bytes(&self.fluid.iter().map(|v| u8::from(*v)).collect::<Vec<_>>()),
            box_cells: self.box_cells.clone(),
        }
    }
    /// The same-axis neighbors of every face in direction d and side (lower,
    /// upper), as `face_at` finds them; built once per grid.
    pub(crate) fn neighbor_faces(&self, c: &Case) -> &[[[Option<usize>; 2]; 3]] {
        self.neighbor_faces.get_or_init(|| {
            self.faces
                .iter()
                .map(|f| {
                    std::array::from_fn(|d| {
                        std::array::from_fn(|side| {
                            let mut q = f.coord.map(|v| v as isize);
                            q[d] += if side == 0 { -1 } else { 1 };
                            self.face_at(c, f.axis, q)
                        })
                    })
                })
                .collect()
        })
    }
    /// For every a-face at q and direction d ≠ a, the two d-faces whose mean
    /// advects through the momentum control-volume edge above it: the d-faces
    /// at q + e_d and q + e_d − e_a, as `face_at` finds them; built once.
    pub(crate) fn edge_faces(&self, c: &Case) -> &[[[Option<usize>; 2]; 3]] {
        self.edge_faces.get_or_init(|| {
            self.faces
                .iter()
                .map(|f| {
                    std::array::from_fn(|d| {
                        if d == f.axis {
                            return [None; 2];
                        }
                        let mut q = f.coord.map(|v| v as isize);
                        q[d] += 1;
                        let upper = self.face_at(c, d, q);
                        q[f.axis] -= 1;
                        [upper, self.face_at(c, d, q)]
                    })
                })
                .collect()
        })
    }
    /// Index in `faces` of the axis-`a` face at integer position `q` of that
    /// axis's face array. Periodic axes wrap; a position outside a
    /// nonperiodic face array is `None`. `c` must be the case the grid was
    /// built from.
    pub fn face_at(&self, c: &Case, a: usize, mut q: [isize; 3]) -> Option<usize> {
        for (d, qd) in q.iter_mut().enumerate() {
            if c.boundaries.at(d) == Boundary::Periodic {
                *qd = qd.rem_euclid(self.n[d] as isize);
            } else if *qd < 0 || *qd >= self.face_dims[a][d] as isize {
                return None;
            }
        }
        Some(self.offsets[a] + Self::index(self.face_dims[a], q.map(|v| v as usize)))
    }
    /// Discrete divergence of the face velocities `u` (one per face) in 1/s,
    /// per cell; zero for solid cells. The same definition is used by the
    /// pressure operator and the continuity checks.
    pub fn divergence(&self, u: &[f64]) -> Vec<f64> {
        (0..self.count())
            .map(|i| {
                if self.fluid[i] {
                    (0..3)
                        .map(|a| {
                            let [lo, hi] = self.cell_faces[i][a];
                            (u[hi] - u[lo]) / self.dx[a]
                        })
                        .sum()
                } else {
                    0.0
                }
            })
            .collect()
    }
    /// Cell-centered velocity in m/s: per axis the mean of the cell's two
    /// face velocities; zero for solid cells. Prefer it to reshaping the
    /// face arrays by hand.
    pub fn cell_velocity(&self, u: &[f64]) -> Vec<[f64; 3]> {
        (0..self.count())
            .map(|i| {
                if self.fluid[i] {
                    std::array::from_fn(|a| {
                        let [lo, hi] = self.cell_faces[i][a];
                        0.5 * (u[lo] + u[hi])
                    })
                } else {
                    [0.0; 3]
                }
            })
            .collect()
    }
    /// Face-normal gradient of the cell field `p`, per face: the difference
    /// across interior faces over `distance`, the difference to a zero value
    /// outside an outlet, and zero on every other face. Its negated
    /// [`divergence`](Self::divergence) is the operator of
    /// [`pressure::apply`](crate::pressure::apply).
    pub fn gradient(&self, p: &[f64]) -> Vec<f64> {
        self.faces
            .iter()
            .map(|f| match f.kind {
                FaceKind::Interior => (p[f.hi.unwrap()] - p[f.lo.unwrap()]) / f.distance,
                FaceKind::Outlet => {
                    if let Some(i) = f.lo {
                        -p[i] / f.distance
                    } else {
                        p[f.hi.unwrap()] / f.distance
                    }
                }
                _ => 0.0,
            })
            .collect()
    }
    /// Initial face velocities from [`Flow::vector`] at each face center;
    /// zero on wall, slip and blocked faces.
    pub fn initial_velocity(&self, c: &Case) -> Vec<f64> {
        self.faces
            .iter()
            .map(|f| {
                if matches!(f.kind, FaceKind::Wall | FaceKind::Slip | FaceKind::Blocked) {
                    0.0
                } else {
                    c.flow.vector(f.center[2])[f.axis]
                }
            })
            .collect()
    }
    /// Reapplies the fixed face velocities in place: zero on wall, slip and
    /// blocked faces and the case inflow on inlet faces. Interior and outlet
    /// faces are left unchanged.
    pub fn enforce_velocity(&self, c: &Case, u: &mut [f64]) {
        for (v, f) in u.iter_mut().zip(&self.faces) {
            match f.kind {
                FaceKind::Wall | FaceKind::Slip | FaceKind::Blocked => *v = 0.0,
                FaceKind::Inlet => *v = c.flow.vector(f.center[2])[f.axis],
                _ => {}
            }
        }
    }
}
