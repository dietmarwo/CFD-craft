use crate::{Result, case::*};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, VecDeque};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FaceKind {
    Interior,
    Wall,
    Slip,
    Inlet,
    Outlet,
    Blocked,
}
#[derive(Clone, Debug)]
pub struct Face {
    pub axis: usize,
    pub coord: [usize; 3],
    pub center: [f64; 3],
    pub lo: Option<usize>,
    pub hi: Option<usize>,
    pub kind: FaceKind,
    pub area: f64,
    pub distance: f64,
}
#[derive(Clone, Debug)]
pub struct Grid {
    pub n: [usize; 3],
    pub dx: [f64; 3],
    pub volume: f64,
    pub fluid: Vec<bool>,
    pub faces: Vec<Face>,
    pub cell_faces: Vec<[[usize; 2]; 3]>,
    pub component: Vec<usize>,
    pub components: Vec<Vec<usize>>,
    pub anchored: Vec<bool>,
    pub face_dims: [[usize; 3]; 3],
    offsets: [usize; 3],
    pub box_cells: BTreeMap<String, usize>,
    pub pressure_factor: std::sync::OnceLock<crate::pressure::Factor>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GeometryEvidence {
    pub fluid_cells: usize,
    pub solid_cells: usize,
    pub fluid_components: usize,
    pub solid_volume_m3: f64,
    pub mask_sha256: String,
    /// Cells whose center lies inside each box, by box ID; overlapping boxes share cells.
    pub box_cells: BTreeMap<String, usize>,
}
/// Topology of a case's cell mask, from [`Grid::mask_topology`].
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MaskTopology {
    pub fluid_components: usize,
    pub solid_cells: usize,
    pub solid_volume_m3: f64,
}
impl Grid {
    pub fn count(&self) -> usize {
        self.fluid.len()
    }
    pub fn index(n: [usize; 3], p: [usize; 3]) -> usize {
        (p[2] * n[1] + p[1]) * n[0] + p[0]
    }
    pub fn coord(&self, i: usize) -> [usize; 3] {
        [
            i % self.n[0],
            i / self.n[0] % self.n[1],
            i / (self.n[0] * self.n[1]),
        ]
    }
    pub fn center(&self, i: usize) -> [f64; 3] {
        let q = self.coord(i);
        std::array::from_fn(|a| (q[a] as f64 + 0.5) * self.dx[a])
    }
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
    /// [`Grid::build`]. Needs only valid axes (2..4096 cells, at most 1e8 in total).
    pub fn mask_topology(c: &Case) -> Result<MaskTopology> {
        let n = c.grid.cells;
        let count = n.iter().try_fold(1usize, |p, v| p.checked_mul(*v));
        let count = match count {
            Some(v) if n.iter().all(|v| (2..=4096).contains(v)) && v <= 100_000_000 => v,
            _ => return Err("the grid needs 2..4096 cells per axis and at most 1e8 cells".into()),
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
