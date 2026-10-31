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
    /// The rate field as declared, with its name (per second, per meter or per cubic meter).
    pub fn declared_rate(&self) -> (&'static str, f64) {
        match self {
            Self::Point { rate_kg_s, .. } => ("rate_kg_s", *rate_kg_s),
            Self::Line { rate_kg_s_m, .. } => ("rate_kg_s_m", *rate_kg_s_m),
            Self::Volume { rate_kg_s_m3, .. } => ("rate_kg_s_m3", *rate_kg_s_m3),
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
        let species = self.constituents.len() as f64;
        // Volume receptors keep sparse (cell, weight) pairs; Vec growth can double them.
        let receptor_bytes: f64 = self
            .receptors
            .iter()
            .map(|r| match r {
                Receptor::Point { .. } => 8.0 * 16.0,
                Receptor::VolumeAverage { min_m, max_m, .. } => {
                    32.0 * self.covered_cells(min_m, max_m)
                }
            })
            .sum();
        // One dense weight vector exists while each source is represented.
        let source_bytes = if self.sources.is_empty() {
            0.0
        } else {
            8.0 * cells as f64
        };
        // The state keeps one monitor row per step for the last three windows: the flow
        // norm, each constituent's mass and receptor values, and mean k and epsilon.
        let monitor_rows = self
            .numerics
            .monitor_window
            .saturating_mul(3)
            .min(self.run.max_steps) as f64;
        let monitor_values = monitor_rows * (3.0 + species * (1.0 + self.receptors.len() as f64));
        let monitor_bytes = 8.0 * monitor_values + 32.0 * monitor_rows;
        // Include contiguous pressure factor construction and a compact per-solve
        // operator allowance (112 bytes/cell), before the existing 25% margin.
        let peak = ((cells as f64) * (880.0 + 96.0 * species) * 1.25
            + receptor_bytes
            + source_bytes
            + monitor_bytes)
            / 1048576.0
            // Process baseline (measured near 19 MiB) and the worker threads' stacks.
            + 24.0
            + self.run.threads as f64;
        // JSON text of f64 values is at most about 24 bytes; fields hold six flow arrays
        // (three face-velocity sets, pressure, k, epsilon) plus one array per constituent,
        // and both fields and checkpoint carry the monitor history.
        let output_fields = (cells as f64) * (24.0 * (6.0 + species) + 4.0) + 26.0 * monitor_values;
        let output_checkpoint =
            (cells as f64) * (26.0 * (6.0 + species) + 4.0) + 27.0 * monitor_values;
        // case.json, summary.json, geometry.json and probes.csv list every receptor, box
        // and source as pretty-printed text, receptor values once per constituent in
        // summary.json and probes.csv; identifiers count twice for JSON escaping.
        let ids: f64 = self.constituents.iter().map(|x| x.id.len() as f64).sum();
        let element_text: f64 = self
            .receptors
            .iter()
            .map(|r| {
                let id = r.id().len() as f64;
                400.0 + 2.0 * id + species * (100.0 + 4.0 * id) + 2.0 * ids
            })
            .chain(
                self.geometry
                    .iter()
                    .map(|b| 500.0 + 4.0 * b.id.len() as f64),
            )
            .chain(
                self.sources
                    .iter()
                    .map(|x| 600.0 + 2.0 * x.id().len() as f64),
            )
            .sum();
        let output = (element_text
            + if self.output.fields {
                output_fields
            } else {
                0.0
            }
            + if self.output.checkpoint {
                output_checkpoint
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
                    &format!("domain.size_m[{a}]"),
                    "Supported lengths are 1e-6..1e9 m.",
                );
            }
            if self.grid.cells[a] < 2 || self.grid.cells[a] > 4096 {
                add(
                    "CFD-E004",
                    "error",
                    &format!("grid.cells[{a}]"),
                    "Each axis needs 2..4096 cells.",
                );
            }
            if a != 2 && self.boundaries.at(a) == Boundary::GroundOpenTop {
                add(
                    "CFD-E005",
                    "error",
                    &format!("boundaries.{}", ["x", "y", "z"][a]),
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
        for (path, ok, message) in [
            (
                "run.threads",
                (1..=64).contains(&self.run.threads),
                "Use 1..64 threads.",
            ),
            (
                "run.max_steps",
                self.run.max_steps > 0,
                "Use a nonzero step budget.",
            ),
            (
                "numerics.pressure_max_iterations",
                self.numerics.pressure_max_iterations > 0,
                "Use a nonzero pressure iteration budget.",
            ),
            (
                "numerics.monitor_window",
                (2..=100000).contains(&self.numerics.monitor_window),
                "Use a monitor window of 2..100000 steps.",
            ),
        ] {
            if !ok {
                add("CFD-E008", "error", path, message);
            }
        }
        if self.run.wall_time_limit_s > 604800.0 {
            add(
                "CFD-E022",
                "error",
                "run.wall_time_limit_s",
                "The wall-time limit may not exceed seven days.",
            );
        }
        if self.run.end_time_s > 1e12 {
            add(
                "CFD-E022",
                "error",
                "run.end_time_s",
                "The physical horizon may not exceed 1e12 seconds.",
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
        if !(self.numerics.advective_cfl_max > 0.0 && self.numerics.advective_cfl_max <= 0.45) {
            add(
                "CFD-E010",
                "error",
                "numerics.advective_cfl_max",
                "Use 0 < CFL <= 0.45; the combined advective and diffusive step allowance is capped at 0.45 for positivity.",
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
        if matches!(self.flow, Flow::Laminar { .. }) && self.boundaries.z == Boundary::GroundOpenTop
        {
            add(
                "CFD-E023",
                "error",
                "boundaries.z",
                "ground_open_top has an open top only with the neutral RANS stress closure; for laminar flow use wall, slip or periodic.",
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
                for (path, x) in [
                    ("flow.speed_m_s", *speed_m_s),
                    ("flow.reference_height_m", *reference_height_m),
                    ("flow.roughness_m", *roughness_m),
                    ("flow.viscosity_m2_s", *viscosity_m2_s),
                    ("flow.turbulent_schmidt", *turbulent_schmidt),
                ] {
                    if !x.is_finite() || x <= 0.0 {
                        add("CFD-E012", "error", path, "Must be finite and positive.");
                    }
                }
                if !direction_deg_from.is_finite() {
                    add(
                        "CFD-E012",
                        "error",
                        "flow.direction_deg_from",
                        "Must be finite.",
                    );
                }
                if *reference_height_m > self.domain.size_m[2] {
                    add(
                        "CFD-E012",
                        "error",
                        "flow.reference_height_m",
                        "The reference height must lie inside the domain.",
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
                        "Laminar viscosity must be positive; initial_velocity_m_s and acceleration_m_s2 must be finite.",
                    );
                }
            }
            Flow::PrescribedUniform { velocity_m_s } => {
                if velocity_m_s.iter().any(|x| !x.is_finite()) {
                    add(
                        "CFD-E012",
                        "error",
                        "flow.velocity_m_s",
                        "Velocity must be finite.",
                    );
                }
                if !self.geometry.is_empty() {
                    add(
                        "CFD-E013",
                        "error",
                        "geometry",
                        "Uniform prescribed flow supports no obstacles; use laminar or neutral_rans flow.",
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
                            "CFD-E024",
                            "error",
                            &format!("flow.velocity_m_s[{a}]"),
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
        for (i, wall) in self.moving_walls.iter().enumerate() {
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
                    &format!("moving_walls[{i}]"),
                    "Use unique tangential moving domain walls in laminar flow only.",
                );
            }
        }
        for (i, b) in self.geometry.iter().enumerate() {
            if b.id.is_empty() || !ids.insert(b.id.clone()) {
                add(
                    "CFD-E014",
                    "error",
                    &format!("geometry[{i}].id"),
                    "Boxes need unique nonempty IDs.",
                );
            }
            if !box_ok(&b.min_m, &b.max_m) {
                add(
                    "CFD-E014",
                    "error",
                    &format!("geometry[{i}]"),
                    "Box bounds must increase on every axis and lie inside the domain.",
                );
                continue;
            }
            let cells_high = (b.max_m[2] - b.min_m[2])
                / (self.domain.size_m[2] / self.grid.cells[2].max(1) as f64);
            if cells_high < 10.0 {
                add(
                    "CFD-W001",
                    "warning",
                    &format!("geometry[{i}]"),
                    &format!(
                        "Box {} spans {cells_high:.1} vertical cells; fewer than 10 across a building height is too coarse for physical interpretation.",
                        b.id
                    ),
                );
            }
        }
        if self.flow.rans() {
            self.domain_warnings(&mut add);
        }
        let mut species = BTreeSet::new();
        for (i, s) in self.constituents.iter().enumerate() {
            if s.id.is_empty() || !species.insert(s.id.clone()) {
                add(
                    "CFD-E015",
                    "error",
                    &format!("constituents[{i}].id"),
                    "Use unique nonempty constituent IDs.",
                );
            }
            if !s.diffusivity_m2_s.is_finite() || s.diffusivity_m2_s < 0.0 {
                add(
                    "CFD-E015",
                    "error",
                    &format!("constituents[{i}].diffusivity_m2_s"),
                    "Use a finite nonnegative diffusivity.",
                );
            }
        }
        let mut source_ids = BTreeSet::new();
        for (i, s) in self.sources.iter().enumerate() {
            if s.id().is_empty() || !source_ids.insert(s.id().to_string()) {
                add(
                    "CFD-E016",
                    "error",
                    &format!("sources[{i}].id"),
                    "Use unique nonempty source IDs.",
                );
            }
            if !species.contains(s.constituent()) {
                add(
                    "CFD-E016",
                    "error",
                    &format!("sources[{i}].constituent"),
                    "The source must name a declared constituent.",
                );
            }
            let (rate_field, declared) = s.declared_rate();
            if !declared.is_finite() || declared < 0.0 {
                add(
                    "CFD-E016",
                    "error",
                    &format!("sources[{i}].{rate_field}"),
                    "Emission rates must be finite and nonnegative.",
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
                    &format!("sources[{i}]"),
                    "Source support must be nondegenerate and inside the domain.",
                );
            }
        }
        let mut initial_species = BTreeSet::new();
        for (i, s) in self.initial_conditions.iter().enumerate() {
            if !species.contains(s.constituent())
                || !initial_species.insert(s.constituent().to_string())
            {
                add(
                    "CFD-E018",
                    "error",
                    &format!("initial_conditions[{i}].constituent"),
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
                            "CFD-E025",
                            "error",
                            &format!("initial_conditions[{i}].concentration_kg_m3"),
                            "Initial concentration must be nonnegative and finite.",
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
                            "CFD-E026",
                            "error",
                            &format!("initial_conditions[{i}]"),
                            "Periodic Gaussian needs three periodic axes, positive sigmas/mass and a center inside the domain.",
                        );
                    }
                }
            }
        }
        let mut receptor_ids = BTreeSet::new();
        for (i, r) in self.receptors.iter().enumerate() {
            if r.id().is_empty() || !receptor_ids.insert(r.id().to_string()) {
                add(
                    "CFD-E019",
                    "error",
                    &format!("receptors[{i}].id"),
                    "Use unique, nonempty receptor IDs.",
                );
            }
            let ok = match r {
                Receptor::Point { point_m, .. } => inside(point_m),
                Receptor::VolumeAverage { min_m, max_m, .. } => box_ok(min_m, max_m),
            };
            if !ok {
                add(
                    "CFD-E027",
                    "error",
                    &format!("receptors[{i}]"),
                    "Receptor support must be nondegenerate and inside the domain.",
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
    /// Number of cells whose control volume intersects a box (for memory estimates).
    fn covered_cells(&self, lo: &[f64; 3], hi: &[f64; 3]) -> f64 {
        (0..3)
            .map(|a| {
                let n = self.grid.cells[a] as f64;
                let h = self.domain.size_m[a] / n.max(1.0);
                if !(h > 0.0 && lo[a].is_finite() && hi[a].is_finite()) {
                    return 0.0;
                }
                let first = (lo[a] / h).floor().clamp(0.0, n);
                let last = (hi[a] / h).ceil().clamp(0.0, n);
                (last - first).max(0.0)
            })
            .product()
    }
    /// Best-practice domain warnings for RANS boundary-layer cases with buildings, following
    /// the COST 732 guideline: about 5 H_max of clearance at the inlet, sides and top, 15 H_max
    /// behind the buildings, and a blockage ratio below 3 %.
    fn domain_warnings(&self, add: &mut impl FnMut(&str, &str, &str, &str)) {
        let boxes: Vec<&Block> = self
            .geometry
            .iter()
            .filter(|b| (0..3).all(|a| b.max_m[a] > b.min_m[a]))
            .collect();
        if boxes.is_empty() {
            return;
        }
        let h = boxes.iter().map(|b| b.max_m[2]).fold(0.0, f64::max);
        let lo: [f64; 3] =
            std::array::from_fn(|a| boxes.iter().map(|b| b.min_m[a]).fold(f64::MAX, f64::min));
        let hi: [f64; 3] =
            std::array::from_fn(|a| boxes.iter().map(|b| b.max_m[a]).fold(0.0, f64::max));
        let wind = self.flow.vector(h.max(1e-9));
        let speed = wind[0].hypot(wind[1]).max(1e-300);
        // Periodic sides repeat the buildings, so clearance does not apply to them; open,
        // slip and wall sides all need it.
        for (a, name) in [(0, "x"), (1, "y")] {
            if self.boundaries.at(a) == Boundary::Periodic {
                continue;
            }
            let along = wind[a] / speed;
            let (low, high) = (lo[a], self.domain.size_m[a] - hi[a]);
            let message = if along.abs() > 0.1 {
                let (upstream, downstream) = if along > 0.0 {
                    (low, high)
                } else {
                    (high, low)
                };
                (upstream < 5.0 * h || downstream < 15.0 * h).then(|| format!(
                    "Along {name} the buildings have {:.1} H_max of clearance upstream and {:.1} H_max downstream; the COST 732 guideline recommends about 5 H_max and 15 H_max.",
                    upstream / h,
                    downstream / h
                ))
            } else {
                (low.min(high) < 5.0 * h).then(|| format!(
                    "Across the wind, along {name}, the buildings have {:.1} H_max and {:.1} H_max of lateral clearance; the COST 732 guideline recommends about 5 H_max on each side.",
                    low / h,
                    high / h
                ))
            };
            if let Some(message) = message {
                add(
                    "CFD-W003",
                    "warning",
                    &format!("domain.size_m[{a}]"),
                    &message,
                );
            }
        }
        if self.domain.size_m[2] - h < 5.0 * h {
            add(
                "CFD-W003",
                "warning",
                "domain.size_m[2]",
                &format!(
                    "The domain top is {:.1} H_max above the tallest building; the COST 732 guideline recommends about 5 H_max.",
                    (self.domain.size_m[2] - h) / h
                ),
            );
        }
        // Frontal area for wind along x (projection onto y-z) and along y (onto x-z),
        // as the union of box shadows, weighted by the wind components.
        let shadow = |u: usize| -> f64 {
            let mut edges: Vec<f64> = boxes
                .iter()
                .flat_map(|b| [b.min_m[u], b.max_m[u]])
                .collect();
            edges.sort_by(f64::total_cmp);
            edges.dedup();
            edges
                .windows(2)
                .map(|w| {
                    let mid = 0.5 * (w[0] + w[1]);
                    let top = boxes
                        .iter()
                        .filter(|b| b.min_m[u] <= mid && mid < b.max_m[u])
                        .map(|b| b.max_m[2])
                        .fold(0.0, f64::max);
                    (w[1] - w[0]) * top
                })
                .sum()
        };
        let (wx, wy) = ((wind[0] / speed).abs(), (wind[1] / speed).abs());
        let frontal = wx * shadow(1) + wy * shadow(0);
        let section =
            (wx * self.domain.size_m[1] + wy * self.domain.size_m[0]) * self.domain.size_m[2];
        let blockage = frontal / section.max(1e-300);
        if blockage > 0.03 {
            add(
                "CFD-W002",
                "warning",
                "geometry",
                &format!(
                    "The blockage ratio is about {:.1} %; the COST 732 guideline recommends below 3 %. Enlarge the domain cross-section.",
                    100.0 * blockage
                ),
            );
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
