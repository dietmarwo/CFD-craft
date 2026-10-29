use crate::Result;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Case {
    pub schema_version: String,
    pub name: String,
    pub domain: Domain,
    pub grid: GridSpec,
    pub boundaries: Boundaries,
    pub flow: Flow,
    #[serde(default)]
    pub geometry: Vec<Block>,
    #[serde(default)]
    pub moving_walls: Vec<MovingWall>,
    #[serde(default)]
    pub constituents: Vec<Constituent>,
    #[serde(default)]
    pub sources: Vec<Source>,
    #[serde(default)]
    pub initial_conditions: Vec<Initial>,
    #[serde(default)]
    pub receptors: Vec<Receptor>,
    pub numerics: Numerics,
    pub run: Run,
    pub output: Output,
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Domain {
    pub size_m: [f64; 3],
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct GridSpec {
    pub cells: [usize; 3],
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Boundary {
    Periodic,
    Open,
    Wall,
    Slip,
    GroundOpenTop,
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Boundaries {
    pub x: Boundary,
    pub y: Boundary,
    pub z: Boundary,
}
impl Boundaries {
    pub fn at(&self, a: usize) -> Boundary {
        [self.x, self.y, self.z][a]
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Flow {
    PrescribedUniform {
        velocity_m_s: [f64; 3],
    },
    Laminar {
        initial_velocity_m_s: [f64; 3],
        viscosity_m2_s: f64,
        #[serde(default)]
        acceleration_m_s2: [f64; 3],
    },
    NeutralRans {
        speed_m_s: f64,
        reference_height_m: f64,
        roughness_m: f64,
        direction_deg_from: f64,
        viscosity_m2_s: f64,
        turbulent_schmidt: f64,
    },
}
impl Flow {
    pub fn prescribed(&self) -> bool {
        matches!(self, Self::PrescribedUniform { .. })
    }
    pub fn rans(&self) -> bool {
        matches!(self, Self::NeutralRans { .. })
    }
    pub fn viscosity(&self) -> f64 {
        match self {
            Self::PrescribedUniform { .. } => 0.0,
            Self::Laminar { viscosity_m2_s, .. } | Self::NeutralRans { viscosity_m2_s, .. } => {
                *viscosity_m2_s
            }
        }
    }
    pub fn vector(&self, z: f64) -> [f64; 3] {
        match self {
            Self::PrescribedUniform { velocity_m_s } => *velocity_m_s,
            Self::Laminar {
                initial_velocity_m_s,
                ..
            } => *initial_velocity_m_s,
            Self::NeutralRans {
                speed_m_s,
                reference_height_m,
                roughness_m,
                direction_deg_from,
                ..
            } => {
                let u = speed_m_s * ((z.max(0.0) + roughness_m) / roughness_m).ln()
                    / ((reference_height_m + roughness_m) / roughness_m).ln();
                let t = direction_deg_from.to_radians();
                [-u * t.sin(), -u * t.cos(), 0.0]
            }
        }
    }
    pub fn reference_speed(&self) -> f64 {
        match self {
            Self::NeutralRans { speed_m_s, .. } => *speed_m_s,
            _ => self
                .vector(1.0)
                .iter()
                .map(|v| v * v)
                .sum::<f64>()
                .sqrt()
                .max(1.0),
        }
    }
    pub fn ustar(&self) -> f64 {
        match self {
            Self::NeutralRans {
                speed_m_s,
                reference_height_m,
                roughness_m,
                ..
            } => 0.4 * speed_m_s / ((reference_height_m + roughness_m) / roughness_m).ln(),
            _ => 0.0,
        }
    }
    pub fn turbulence(&self, z: f64) -> (f64, f64) {
        if let Self::NeutralRans { roughness_m, .. } = self {
            let u = self.ustar();
            (u * u / 0.3, u.powi(3) / (0.4 * (z + roughness_m)))
        } else {
            (0.0, 0.0)
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Block {
    pub id: String,
    pub min_m: [f64; 3],
    pub max_m: [f64; 3],
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct MovingWall {
    pub axis: usize,
    pub upper: bool,
    pub velocity_m_s: [f64; 3],
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Constituent {
    pub id: String,
    pub diffusivity_m2_s: f64,
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Source {
    Point {
        id: String,
        constituent: String,
        point_m: [f64; 3],
        rate_kg_s: f64,
    },
    Line {
        id: String,
        constituent: String,
        from_m: [f64; 3],
        to_m: [f64; 3],
        rate_kg_s_m: f64,
    },
    Volume {
        id: String,
        constituent: String,
        min_m: [f64; 3],
        max_m: [f64; 3],
        rate_kg_s_m3: f64,
    },
}
impl Source {
    pub fn id(&self) -> &str {
        match self {
            Self::Point { id, .. } | Self::Line { id, .. } | Self::Volume { id, .. } => id,
        }
    }
    pub fn constituent(&self) -> &str {
        match self {
            Self::Point { constituent, .. }
            | Self::Line { constituent, .. }
            | Self::Volume { constituent, .. } => constituent,
        }
    }
    pub fn rate(&self) -> f64 {
        match self {
            Self::Point { rate_kg_s, .. } => *rate_kg_s,
            Self::Line {
                rate_kg_s_m,
                from_m,
                to_m,
                ..
            } => {
                rate_kg_s_m
                    * (0..3)
                        .map(|a| (to_m[a] - from_m[a]).powi(2))
                        .sum::<f64>()
                        .sqrt()
            }
            Self::Volume {
                rate_kg_s_m3,
                min_m,
                max_m,
                ..
            } => rate_kg_s_m3 * (0..3).map(|a| max_m[a] - min_m[a]).product::<f64>(),
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Initial {
    Uniform {
        constituent: String,
        concentration_kg_m3: f64,
    },
    PeriodicGaussian {
        constituent: String,
        center_m: [f64; 3],
        sigma_m: [f64; 3],
        total_mass_kg: f64,
    },
}
impl Initial {
    pub fn constituent(&self) -> &str {
        match self {
            Self::Uniform { constituent, .. } | Self::PeriodicGaussian { constituent, .. } => {
                constituent
            }
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Receptor {
    Point {
        id: String,
        point_m: [f64; 3],
    },
    VolumeAverage {
        id: String,
        min_m: [f64; 3],
        max_m: [f64; 3],
    },
}
impl Receptor {
    pub fn id(&self) -> &str {
        match self {
            Self::Point { id, .. } | Self::VolumeAverage { id, .. } => id,
        }
    }
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Advection {
    LinearUpwind,
    Muscl,
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Numerics {
    pub transport: Advection,
    pub max_time_step_s: f64,
    pub advective_cfl_max: f64,
    pub pressure_relative_tolerance: f64,
    pub pressure_max_iterations: usize,
    pub steady_residual_tolerance: f64,
    pub steady_monitor_tolerance: f64,
    pub monitor_window: usize,
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    Steady,
    Transient,
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Run {
    pub mode: Mode,
    pub end_time_s: f64,
    pub max_steps: usize,
    pub wall_time_limit_s: f64,
    pub threads: usize,
    pub memory_limit_mib: usize,
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Output {
    pub fields: bool,
    pub checkpoint: bool,
    pub max_total_mib: usize,
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Diagnostic {
    pub code: String,
    pub severity: String,
    pub path: String,
    pub message: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
pub struct CheckReport {
    pub schema_version: String,
    pub valid: bool,
    pub cells: usize,
    pub estimated_peak_mib: f64,
    pub estimated_output_mib: f64,
    pub diagnostics: Vec<Diagnostic>,
}
impl Case {
    pub fn physics_hash(&self) -> String {
        let mut v = serde_json::to_value(self).expect("serializable case");
        for k in ["run", "output", "name"] {
            v.as_object_mut().unwrap().remove(k);
        }
        hash_bytes(&serde_json::to_vec(&v).unwrap())
    }
    pub fn check(&self) -> CheckReport {
        let cells = self
            .grid
            .cells
            .iter()
            .try_fold(1usize, |x, n| x.checked_mul(*n))
            .unwrap_or(usize::MAX);
        let peak = (cells as f64) * (768.0 + 96.0 * self.constituents.len() as f64) * 1.25
            / 1048576.0
            + 16.0;
        let output = (cells as f64)
            * (if self.output.fields { 220.0 } else { 0.0 }
                + if self.output.checkpoint {
                    200.0 + 26.0 * self.constituents.len() as f64
                } else {
                    0.0
                })
            / 1048576.0
            + 2.0;
        let mut d = Vec::new();
        let mut add = |code: &str, severity: &str, path: &str, message: &str| {
            d.push(Diagnostic {
                code: code.into(),
                severity: severity.into(),
                path: path.into(),
                message: message.into(),
            })
        };
        if self.schema_version != "cfd-craft.case/0.1" {
            add(
                "CFD-E001",
                "error",
                "schema_version",
                "Use cfd-craft.case/0.1.",
            );
        }
        if self.name.is_empty() {
            add("CFD-E002", "error", "name", "Supply a nonempty case name.");
        }
        for a in 0..3 {
            if !(self.domain.size_m[a].is_finite()
                && self.domain.size_m[a] >= 1e-6
                && self.domain.size_m[a] <= 1e9)
            {
                add(
                    "CFD-E003",
                    "error",
                    "domain.size_m",
                    "Supported lengths are 1e-6..1e9 m.",
                );
            }
            if self.grid.cells[a] < 2 || self.grid.cells[a] > 4096 {
                add(
                    "CFD-E004",
                    "error",
                    "grid.cells",
                    "Each axis needs 2..4096 cells.",
                );
            }
            if a != 2 && self.boundaries.at(a) == Boundary::GroundOpenTop {
                add(
                    "CFD-E005",
                    "error",
                    "boundaries",
                    "ground_open_top is supported on z only.",
                );
            }
        }
        if cells > 100_000_000 || peak > self.run.memory_limit_mib as f64 {
            add(
                "CFD-E006",
                "error",
                "run.memory_limit_mib",
                "Estimated memory exceeds the budget; reduce grid/constituents or raise an available budget.",
            );
        }
        if output > self.output.max_total_mib as f64 {
            add(
                "CFD-E007",
                "error",
                "output.max_total_mib",
                "Estimated artifacts exceed the output budget.",
            );
        }
        if self.run.threads == 0
            || self.run.threads > 64
            || self.run.max_steps == 0
            || self.numerics.pressure_max_iterations == 0
            || self.numerics.monitor_window < 2
            || self.numerics.monitor_window > 100000
        {
            add(
                "CFD-E008",
                "error",
                "run/numerics",
                "Threads 1..64, nonzero step/pressure budgets and monitor_window 2..100000 are required.",
            );
        }
        if self.run.wall_time_limit_s > 604800.0 || self.run.end_time_s > 1e12 {
            add(
                "CFD-E008",
                "error",
                "run",
                "Wall limit may not exceed seven days; physical horizon may not exceed 1e12 seconds.",
            );
        }
        for (path, x) in [
            ("run.end_time_s", self.run.end_time_s),
            ("run.wall_time_limit_s", self.run.wall_time_limit_s),
            ("numerics.max_time_step_s", self.numerics.max_time_step_s),
            (
                "numerics.pressure_relative_tolerance",
                self.numerics.pressure_relative_tolerance,
            ),
            (
                "numerics.steady_residual_tolerance",
                self.numerics.steady_residual_tolerance,
            ),
            (
                "numerics.steady_monitor_tolerance",
                self.numerics.steady_monitor_tolerance,
            ),
        ] {
            if !x.is_finite() || x <= 0.0 {
                add("CFD-E009", "error", path, "Must be finite and positive.");
            }
        }
        if !(self.numerics.advective_cfl_max > 0.0 && self.numerics.advective_cfl_max <= 0.8) {
            add(
                "CFD-E010",
                "error",
                "numerics.advective_cfl_max",
                "Use 0 < CFL <= 0.8.",
            );
        }
        if self.flow.rans() && self.boundaries.z != Boundary::GroundOpenTop {
            add(
                "CFD-E011",
                "error",
                "boundaries.z",
                "Neutral RANS requires ground_open_top.",
            );
        }
        match &self.flow {
            Flow::NeutralRans {
                speed_m_s,
                reference_height_m,
                roughness_m,
                direction_deg_from,
                viscosity_m2_s,
                turbulent_schmidt,
            } => {
                if [
                    *speed_m_s,
                    *reference_height_m,
                    *roughness_m,
                    *viscosity_m2_s,
                    *turbulent_schmidt,
                ]
                .iter()
                .any(|x| !x.is_finite() || *x <= 0.0)
                    || !direction_deg_from.is_finite()
                    || *reference_height_m > self.domain.size_m[2]
                {
                    add(
                        "CFD-E012",
                        "error",
                        "flow",
                        "Require positive finite speed, reference height, roughness, viscosity and Schmidt number, and a reference height inside the domain.",
                    );
                }
            }
            Flow::Laminar {
                initial_velocity_m_s,
                viscosity_m2_s,
                acceleration_m_s2,
            } => {
                if !viscosity_m2_s.is_finite()
                    || *viscosity_m2_s <= 0.0
                    || initial_velocity_m_s
                        .iter()
                        .chain(acceleration_m_s2)
                        .any(|x| !x.is_finite())
                {
                    add(
                        "CFD-E012",
                        "error",
                        "flow",
                        "Laminar viscosity must be positive; vectors must be finite.",
                    );
                }
            }
            Flow::PrescribedUniform { velocity_m_s } => {
                if velocity_m_s.iter().any(|x| !x.is_finite()) {
                    add("CFD-E012", "error", "flow", "Velocity must be finite.");
                }
                if !self.geometry.is_empty() {
                    add(
                        "CFD-E013",
                        "error",
                        "geometry",
                        "Uniform prescribed flow supports no obstacles; use the projected flow solver.",
                    );
                }
                for (a, &v) in velocity_m_s.iter().enumerate() {
                    if v != 0.0
                        && matches!(
                            self.boundaries.at(a),
                            Boundary::Wall | Boundary::Slip | Boundary::GroundOpenTop
                        )
                    {
                        add(
                            "CFD-E013",
                            "error",
                            "boundaries",
                            "Prescribed velocity must have zero normal component at impermeable boundaries.",
                        );
                    }
                }
            }
        }
        let inside = |p: &[f64; 3]| {
            (0..3).all(|a| p[a].is_finite() && p[a] >= 0.0 && p[a] < self.domain.size_m[a])
        };
        let box_ok = |lo: &[f64; 3], hi: &[f64; 3]| {
            (0..3).all(|a| {
                lo[a].is_finite()
                    && hi[a].is_finite()
                    && lo[a] >= 0.0
                    && hi[a] <= self.domain.size_m[a]
                    && hi[a] > lo[a]
            })
        };
        let mut ids = BTreeSet::new();
        let mut wall_ids = BTreeSet::new();
        for wall in &self.moving_walls {
            if wall.axis > 2
                || !wall_ids.insert((wall.axis, wall.upper))
                || wall.velocity_m_s.iter().any(|v| !v.is_finite())
                || (wall.axis < 3
                    && (self.boundaries.at(wall.axis) != Boundary::Wall
                        || wall.velocity_m_s[wall.axis] != 0.0))
                || !matches!(self.flow, Flow::Laminar { .. })
            {
                add(
                    "CFD-E021",
                    "error",
                    "moving_walls",
                    "Use unique tangential moving domain walls in laminar flow only.",
                );
            }
        }
        for b in &self.geometry {
            if !ids.insert(b.id.clone()) || b.id.is_empty() || !box_ok(&b.min_m, &b.max_m) {
                add(
                    "CFD-E014",
                    "error",
                    "geometry",
                    "Boxes need unique nonempty IDs and increasing bounds inside the domain.",
                );
            }
            let h = b.max_m[2] - b.min_m[2];
            if h / (self.domain.size_m[2] / self.grid.cells[2].max(1) as f64) < 10.0 {
                add(
                    "CFD-W001",
                    "warning",
                    "geometry",
                    "Fewer than 10 vertical cells across a building; refine before physical interpretation.",
                );
            }
        }
        let mut species = BTreeSet::new();
        for s in &self.constituents {
            if s.id.is_empty()
                || !species.insert(s.id.clone())
                || !s.diffusivity_m2_s.is_finite()
                || s.diffusivity_m2_s < 0.0
            {
                add(
                    "CFD-E015",
                    "error",
                    "constituents",
                    "Use unique IDs and finite nonnegative diffusivity.",
                );
            }
        }
        let mut source_ids = BTreeSet::new();
        for s in &self.sources {
            if !source_ids.insert(s.id().to_string())
                || s.id().is_empty()
                || !species.contains(s.constituent())
                || !s.rate().is_finite()
                || s.rate() < 0.0
            {
                add(
                    "CFD-E016",
                    "error",
                    "sources",
                    "Source IDs, species and nonnegative finite emission rates must be valid.",
                );
            }
            let ok = match s {
                Source::Point { point_m, .. } => inside(point_m),
                Source::Line { from_m, to_m, .. } => {
                    inside(from_m) && inside(to_m) && from_m != to_m
                }
                Source::Volume { min_m, max_m, .. } => box_ok(min_m, max_m),
            };
            if !ok {
                add(
                    "CFD-E017",
                    "error",
                    "sources",
                    "Source support must be nondegenerate and inside the domain.",
                );
            }
        }
        let mut initial_species = BTreeSet::new();
        for s in &self.initial_conditions {
            if !species.contains(s.constituent())
                || !initial_species.insert(s.constituent().to_string())
            {
                add(
                    "CFD-E018",
                    "error",
                    "initial_conditions",
                    "One initial condition per declared constituent is supported.",
                );
            }
            match s {
                Initial::Uniform {
                    concentration_kg_m3,
                    ..
                } => {
                    if !concentration_kg_m3.is_finite() || *concentration_kg_m3 < 0.0 {
                        add(
                            "CFD-E018",
                            "error",
                            "initial_conditions",
                            "Initial mass must be nonnegative and finite.",
                        );
                    }
                }
                Initial::PeriodicGaussian {
                    center_m,
                    sigma_m,
                    total_mass_kg,
                    ..
                } => {
                    if !inside(center_m)
                        || (0..3).any(|a| {
                            !sigma_m[a].is_finite()
                                || sigma_m[a] <= 0.0
                                || sigma_m[a] > 2.0 * self.domain.size_m[a]
                        })
                        || !total_mass_kg.is_finite()
                        || *total_mass_kg <= 0.0
                        || (0..3).any(|a| self.boundaries.at(a) != Boundary::Periodic)
                    {
                        add(
                            "CFD-E018",
                            "error",
                            "initial_conditions",
                            "Periodic Gaussian needs three periodic axes, positive sigmas/mass and a center inside the domain.",
                        );
                    }
                }
            }
        }
        let mut receptor_ids = BTreeSet::new();
        for r in &self.receptors {
            if r.id().is_empty() || !receptor_ids.insert(r.id().to_string()) {
                add(
                    "CFD-E019",
                    "error",
                    "receptors",
                    "Use unique, nonempty receptor IDs.",
                );
            }
            let ok = match r {
                Receptor::Point { point_m, .. } => inside(point_m),
                Receptor::VolumeAverage { min_m, max_m, .. } => box_ok(min_m, max_m),
            };
            if !ok {
                add(
                    "CFD-E019",
                    "error",
                    "receptors",
                    "Receptor support must be inside the domain.",
                );
            }
        }
        if self.run.mode == Mode::Steady
            && !self.sources.is_empty()
            && !(0..3).any(|a| self.boundaries.at(a) == Boundary::Open)
        {
            add(
                "CFD-E020",
                "error",
                "run.mode",
                "Positive continuous sources need an open removal boundary for steady transport.",
            );
        }
        CheckReport {
            schema_version: "cfd-craft.check/0.1".into(),
            valid: !d.iter().any(|d| d.severity == "error"),
            cells,
            estimated_peak_mib: peak,
            estimated_output_mib: output,
            diagnostics: d,
        }
    }
    pub fn validate(&self) -> Result<CheckReport> {
        let r = self.check();
        if r.valid {
            Ok(r)
        } else {
            Err(serde_json::to_string(&r).unwrap())
        }
    }
}
pub fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
