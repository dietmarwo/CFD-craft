use crate::{Result, case::*};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;

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
    pub pressure_factor: std::sync::OnceLock<crate::pressure::Factor>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GeometryEvidence {
    pub fluid_cells: usize,
    pub solid_cells: usize,
    pub fluid_components: usize,
    pub solid_volume_m3: f64,
    pub mask_sha256: String,
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
            pressure_factor: std::sync::OnceLock::new(),
        };
        for i in 0..count {
            let p = g.center(i);
            g.fluid[i] = !c
                .geometry
                .iter()
                .any(|b| (0..3).all(|a| p[a] >= b.min_m[a] && p[a] < b.max_m[a]));
        }
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
    pub fn evidence(&self) -> GeometryEvidence {
        let fluid_cells = self.fluid.iter().filter(|v| **v).count();
        GeometryEvidence {
            fluid_cells,
            solid_cells: self.count() - fluid_cells,
            fluid_components: self.components.len(),
            solid_volume_m3: (self.count() - fluid_cells) as f64 * self.volume,
            mask_sha256: hash_bytes(&self.fluid.iter().map(|v| u8::from(*v)).collect::<Vec<_>>()),
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
