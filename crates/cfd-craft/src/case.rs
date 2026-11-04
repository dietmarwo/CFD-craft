//! The case contract `cfd-craft.case/0.1`: the typed JSON input of a native
//! run, its semantic checks and its identities.
//!
//! A [`Case`] describes one calculation completely: domain and grid, boundary
//! conditions, the flow model, solid boxes, passive constituents with their
//! sources, initial conditions and receptors, numerics, run budgets and the
//! output policy. Nothing outside the case configures the solver.
//!
//! Checking happens in three layers:
//!
//! 1. Deserialization is strict: unknown fields and variants are rejected.
//!    [`input::parse_case`](crate::input::parse_case) reports a failure as
//!    `CFD-E000` with the JSON path of the offending element.
//! 2. [`Case::check`] applies the semantic checks (units, ranges, budgets,
//!    geometry, physical combinations) and returns a [`CheckReport`] of coded
//!    [`Diagnostic`]s; [`Case::validate`] turns an invalid report into an
//!    error.
//! 3. Checks that need the built grid (box representation, source and
//!    receptor support) run in [`Grid::build`](crate::grid::Grid::build),
//!    [`transport::source_fields`](crate::transport::source_fields) and
//!    [`input::full_check`](crate::input::full_check).
//!
//! Every code is listed in the
//! [diagnostics catalog](https://github.com/dietmarwo/CFD-craft/blob/main/docs/diagnostics.md).
//!
//! Units follow the field names: `_m` meters, `_m_s` m/s, `_m2_s` m2/s,
//! `_kg_s` kg/s, `_kg_m3` kg/m3, `_s` seconds, `_mib` MiB. Coordinates are
//! local east (x), north (y) and up (z) from the lower domain corner.
//!
//! These types derive `JsonSchema`, and `cfd-craft describe` prints the
//! generated `case_schema`; the schemas there are authoritative for JSON
//! clients. [`Case::physics_hash`] identifies the physical and numerical
//! problem for restarts, and [`hash_bytes`] is the digest used for every
//! identity.
//!
//! # Example
//!
//! ```
//! use cfd_craft::case::Case;
//!
//! let json = r#"{
//!   "schema_version": "cfd-craft.case/0.1", "name": "tiny",
//!   "domain": {"size_m": [4.0, 1.0, 1.0]}, "grid": {"cells": [8, 2, 2]},
//!   "boundaries": {"x": "open", "y": "periodic", "z": "periodic"},
//!   "flow": {"kind": "prescribed_uniform", "velocity_m_s": [1.0, 0.0, 0.0]},
//!   "constituents": [{"id": "tracer", "diffusivity_m2_s": 0.01}],
//!   "sources": [{"kind": "point", "id": "S0", "constituent": "tracer",
//!                "point_m": [0.5, 0.5, 0.5], "rate_kg_s": 1e-6}],
//!   "receptors": [{"kind": "point", "id": "R1", "point_m": [3.0, 0.5, 0.5]}],
//!   "numerics": {"transport": "linear_upwind", "max_time_step_s": 1.0,
//!     "advective_cfl_max": 0.4, "pressure_relative_tolerance": 1e-10,
//!     "pressure_max_iterations": 100, "steady_residual_tolerance": 1e-5,
//!     "steady_monitor_tolerance": 1e-3, "monitor_window": 10},
//!   "run": {"mode": "steady", "end_time_s": 1.0, "max_steps": 1000,
//!     "wall_time_limit_s": 30.0, "threads": 1, "memory_limit_mib": 64},
//!   "output": {"fields": false, "checkpoint": false, "max_total_mib": 4}
//! }"#;
//! let case: Case = serde_json::from_str(json).unwrap();
//! let report = case.validate().unwrap();
//! assert!(report.valid);
//! assert_eq!(report.cells, 32);
//!
//! // Unknown fields are a deserialization error, not a semantic warning.
//! let typo = json.replace("\"point_m\": [0.5", "\"position_m\": [0.5");
//! assert!(serde_json::from_str::<Case>(&typo).is_err());
//! ```

// Doc comments on these types become `description` entries of the generated
// case schema. Two kinds of item carry rustdoc-only docs
// (`#[cfg_attr(doc, doc = ...)]`) instead: unit variants of string enums, where
// a `///` comment would turn the schema's `enum` into a `oneOf`, and fields
// whose type is another schema type, where it would wrap the field's `$ref` in
// an `allOf`. Both would change the schema's shape. The meaning of those items
// is also stated in the documented container, which the schema keeps.
use crate::Result;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

/// A complete native case, schema version `cfd-craft.case/0.1`. Nothing
/// outside the case configures the solver. Unknown fields are rejected; the
/// lists default to empty when omitted. Deserialization checks only the
/// types: the semantic checks (ranges, units, budgets, geometry) are those of
/// `cfd-craft check`, which reports coded diagnostics with field paths.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Case {
    /// Contract version; must be `cfd-craft.case/0.1` (CFD-E001).
    pub schema_version: String,
    /// Nonempty experiment label (CFD-E002), copied into the result. It is
    /// excluded from the physics hash, so renaming keeps checkpoints
    /// compatible.
    pub name: String,
    #[cfg_attr(doc, doc = "Physical extent of the domain; see [`Domain`].")]
    #[allow(missing_docs)]
    pub domain: Domain,
    #[cfg_attr(doc, doc = "Uniform cell counts per axis; see [`GridSpec`].")]
    #[allow(missing_docs)]
    pub grid: GridSpec,
    #[cfg_attr(doc, doc = "Boundary condition per axis; see [`Boundaries`].")]
    #[allow(missing_docs)]
    pub boundaries: Boundaries,
    #[cfg_attr(doc, doc = "Flow model; see [`Flow`].")]
    #[allow(missing_docs)]
    pub flow: Flow,
    /// Axis-aligned solid boxes (buildings, obstacles). A cell is solid when
    /// its center lies inside a box. Not allowed with `prescribed_uniform`
    /// flow (CFD-E013) or with the `multigrid` pressure preconditioner
    /// (CFD-E034). Default: empty.
    #[serde(default)]
    pub geometry: Vec<Block>,
    /// Tangentially moving `wall` faces of the domain, such as a cavity lid;
    /// laminar flow only (CFD-E021). Default: empty.
    #[serde(default)]
    pub moving_walls: Vec<MovingWall>,
    /// Passive gases transported by the flow. Default: empty, which solves
    /// the flow only.
    #[serde(default)]
    pub constituents: Vec<Constituent>,
    /// Continuous emissions into the constituents. Default: empty.
    #[serde(default)]
    pub sources: Vec<Source>,
    /// Initial concentration fields, at most one per constituent (CFD-E018);
    /// a constituent without one starts at zero. Default: empty.
    #[serde(default)]
    pub initial_conditions: Vec<Initial>,
    /// Named concentration samples, reported for every constituent in the
    /// result's `receptors_kg_m3` and in probes.csv. Default: empty.
    #[serde(default)]
    pub receptors: Vec<Receptor>,
    #[cfg_attr(
        doc,
        doc = "Discretization choices, tolerances and the steady monitor window; see [`Numerics`]."
    )]
    #[allow(missing_docs)]
    pub numerics: Numerics,
    #[cfg_attr(doc, doc = "Mode, endpoint and execution budgets; see [`Run`].")]
    #[allow(missing_docs)]
    pub run: Run,
    #[cfg_attr(doc, doc = "Artifact retention and output budget; see [`Output`].")]
    #[allow(missing_docs)]
    pub output: Output,
}
/// Physical extent of the domain: a box from the origin to `size_m`.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Domain {
    /// Lengths along x (east), y (north) and z (up) in meters, each finite
    /// and within 1e-6..1e9 (CFD-E003).
    pub size_m: [f64; 3],
}
/// Uniform Cartesian grid: the cell size along an axis is the domain length
/// divided by the cell count.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct GridSpec {
    /// Cell counts along x, y and z: 2..4096 per axis, or 1..4096 on a
    /// periodic axis, which makes a two-dimensional run (CFD-E004). The total
    /// enters the memory estimate and may not exceed 1e8 cells (CFD-E006).
    pub cells: [usize; 3],
}
/// Boundary condition of the pair of domain faces normal to one axis.
/// `periodic` identifies the two faces. `open` lets flow in or out: each face
/// is an inlet or an outlet by the sign of the case flow's normal velocity
/// there; inlets prescribe that velocity and a zero concentration increment,
/// outlets fix the pressure level, and faces without normal flow are slip
/// faces. `wall` is impermeable and no-slip (a rough wall with
/// `neutral_rans`). `slip` is impermeable and stress-free. `ground_open_top`
/// (z only, CFD-E005) is a rough ground with a top that applies the
/// boundary-layer shear stress; `neutral_rans` requires it (CFD-E011) and
/// laminar flow may not use it (CFD-E023).
#[derive(Clone, Copy, Debug, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Boundary {
    #[cfg_attr(
        doc,
        doc = "The two faces are identified, so flow and constituents leaving one enter the other. A periodic axis may have one cell."
    )]
    #[allow(missing_docs)]
    Periodic,
    #[cfg_attr(
        doc,
        doc = "Inflow or outflow, decided per face by the normal component of [`Flow::vector`] at the face center: inlets prescribe that velocity and a zero concentration increment, outlets fix the pressure level and anchor their fluid component, and faces without normal flow act as slip faces."
    )]
    #[allow(missing_docs)]
    Open,
    #[cfg_attr(
        doc,
        doc = "Impermeable no-slip wall, optionally moving tangentially ([`MovingWall`]); with `neutral_rans` a rough wall with the wall functions of the flow model card."
    )]
    #[allow(missing_docs)]
    Wall,
    #[cfg_attr(
        doc,
        doc = "Impermeable and stress-free: zero normal velocity and zero tangential gradient."
    )]
    #[allow(missing_docs)]
    Slip,
    #[cfg_attr(
        doc,
        doc = "z only: a rough ground at z = 0 with roughness `roughness_m`, and an impermeable top that applies the equilibrium shear stress of the `neutral_rans` inflow. Required by `neutral_rans`, rejected for laminar flow, where the top would act as a no-slip lid."
    )]
    #[allow(missing_docs)]
    GroundOpenTop,
}
/// Boundary conditions of the domain: `x`, `y` and `z` each set the condition
/// of the two domain faces normal to that axis (west and east, south and
/// north, ground and top).
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Boundaries {
    #[cfg_attr(doc, doc = "Condition at x = 0 and x = Lx (west and east).")]
    #[allow(missing_docs)]
    pub x: Boundary,
    #[cfg_attr(doc, doc = "Condition at y = 0 and y = Ly (south and north).")]
    #[allow(missing_docs)]
    pub y: Boundary,
    #[cfg_attr(doc, doc = "Condition at z = 0 and z = Lz (ground and top).")]
    #[allow(missing_docs)]
    pub z: Boundary,
}
impl Boundaries {
    /// The condition of axis `a` (0 = x, 1 = y, 2 = z).
    ///
    /// # Panics
    ///
    /// If `a > 2`.
    pub fn at(&self, a: usize) -> Boundary {
        [self.x, self.y, self.z][a]
    }
}
/// Flow model, selected by `kind`: `prescribed_uniform` (a fixed uniform
/// velocity; only the constituents are solved), `laminar` (incompressible
/// flow with constant viscosity) or `neutral_rans` (a neutral atmospheric
/// boundary layer with the k-epsilon model). The numeric fields are checked
/// as CFD-E012.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Flow {
    /// A fixed uniform velocity with no flow solve. Its normal component must
    /// be zero at impermeable boundaries (CFD-E024), and solid boxes are not
    /// allowed (CFD-E013).
    PrescribedUniform {
        /// Velocity [u, v, w] in m/s, finite.
        velocity_m_s: [f64; 3],
    },
    /// Incompressible laminar flow with constant kinematic viscosity, started
    /// from a uniform velocity.
    Laminar {
        /// Uniform initial velocity [u, v, w] in m/s, finite. It also sets
        /// the velocity of `open` inlet faces and decides which open faces are
        /// inlets or outlets.
        initial_velocity_m_s: [f64; 3],
        /// Kinematic viscosity in m2/s, finite and positive.
        viscosity_m2_s: f64,
        /// Uniform body acceleration [x, y, z] in m/s2, for example the
        /// pressure-gradient drive of a periodic channel. Default: zero.
        #[serde(default)]
        acceleration_m_s2: [f64; 3],
    },
    /// Neutral atmospheric boundary layer with the k-epsilon model (C_mu 0.09,
    /// C_epsilon1 1.44, C_epsilon2 1.92, kappa 0.4). Inflow and initial fields
    /// are the logarithmic equilibrium profiles U = u*/kappa ln((z + z0)/z0),
    /// k = u*^2/sqrt(C_mu) and epsilon = u*^3/(kappa (z + z0)), with u* set by
    /// `speed_m_s` at `reference_height_m`. Requires `boundaries.z =
    /// ground_open_top` (CFD-E011).
    NeutralRans {
        /// Mean wind speed at `reference_height_m` in m/s, finite and
        /// positive. It is also the velocity scale of the normalized checks.
        speed_m_s: f64,
        /// Height of `speed_m_s` above the ground in meters, positive and not
        /// above the domain top. It is also the length scale of the
        /// normalized checks.
        reference_height_m: f64,
        /// Aerodynamic roughness length z0 of the ground in meters, positive.
        /// Building and other wall faces use min(z0, 0.001 cell width), which
        /// ties that wall roughness to the grid (see the flow model card).
        roughness_m: f64,
        /// Meteorological wind direction in degrees: where the wind blows
        /// from, clockwise from north. 270 blows toward +x (east), 180 toward
        /// +y (north). Finite; any value is accepted.
        direction_deg_from: f64,
        /// Molecular kinematic viscosity in m2/s, positive; the eddy viscosity
        /// C_mu k^2/epsilon is added to it.
        viscosity_m2_s: f64,
        /// Turbulent Schmidt number Sc_t, positive: constituents diffuse with
        /// their molecular diffusivity plus nu_t / Sc_t.
        turbulent_schmidt: f64,
    },
}
impl Flow {
    /// True for `prescribed_uniform`, whose velocity stays fixed: no
    /// momentum or pressure equations are solved.
    pub fn prescribed(&self) -> bool {
        matches!(self, Self::PrescribedUniform { .. })
    }
    /// True for `neutral_rans`, which adds the k and epsilon fields.
    pub fn rans(&self) -> bool {
        matches!(self, Self::NeutralRans { .. })
    }
    /// Molecular kinematic viscosity in m2/s; zero for prescribed flow.
    pub fn viscosity(&self) -> f64 {
        match self {
            Self::PrescribedUniform { .. } => 0.0,
            Self::Laminar { viscosity_m2_s, .. } | Self::NeutralRans { viscosity_m2_s, .. } => {
                *viscosity_m2_s
            }
        }
    }
    /// The case's reference velocity at height `z` (meters), in m/s: the
    /// prescribed velocity, the laminar initial velocity, or the logarithmic
    /// `neutral_rans` profile in the wind direction (negative heights are
    /// evaluated at the ground).
    ///
    /// It initializes the face velocities, sets the velocity of `open` inlet
    /// faces and decides whether an open face is an inlet, an outlet or a
    /// slip face.
    ///
    /// ```
    /// use cfd_craft::case::Flow;
    ///
    /// let flow: Flow = serde_json::from_str(
    ///     r#"{"kind": "neutral_rans", "speed_m_s": 3.0, "reference_height_m": 10.0,
    ///         "roughness_m": 0.1, "direction_deg_from": 270.0,
    ///         "viscosity_m2_s": 1.5e-5, "turbulent_schmidt": 0.7}"#,
    /// )
    /// .unwrap();
    /// let [u, v, w] = flow.vector(10.0);
    /// // A wind from the west blows toward +x, at the declared reference speed.
    /// assert!((u - 3.0).abs() < 1e-12 && v.abs() < 1e-12 && w == 0.0);
    /// assert!(flow.vector(1.0)[0] < u);
    /// ```
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
    /// Velocity scale of the normalized checks and divergence limits, in m/s:
    /// `speed_m_s` for `neutral_rans`, otherwise the magnitude of
    /// [`vector`](Self::vector) at z = 1 m, but at least 1 m/s.
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
    /// Friction velocity of the `neutral_rans` inflow profile in m/s,
    /// u* = kappa speed / ln((z_ref + z0)/z0) with kappa = 0.4; zero for the
    /// other flow models.
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
    /// Equilibrium `(k, epsilon)` of the `neutral_rans` inflow at height `z`
    /// (meters): k = u*^2/sqrt(C_mu) in m2/s2 and epsilon = u*^3/(kappa (z +
    /// z0)) in m2/s3. `(0, 0)` for the other flow models. These values
    /// initialize the fields and set the inlet and top values.
    pub fn turbulence(&self, z: f64) -> (f64, f64) {
        if let Self::NeutralRans { roughness_m, .. } = self {
            let u = self.ustar();
            (u * u / 0.3, u.powi(3) / (0.4 * (z + roughness_m)))
        } else {
            (0.0, 0.0)
        }
    }
}
/// An axis-aligned solid box. Cells whose centers lie inside it (lower bound
/// inclusive, upper bound exclusive) are solid; boxes may overlap. The bounds
/// must increase on every axis and lie inside the domain (CFD-E014), and the
/// box must contain at least one cell center (CFD-E028). Fewer than ten cells
/// across its height draws warning CFD-W001.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Block {
    /// Unique nonempty ID (CFD-E014); the key of the box's cell count in
    /// geometry.json.
    pub id: String,
    /// Lower corner [x, y, z] in meters.
    pub min_m: [f64; 3],
    /// Upper corner [x, y, z] in meters.
    pub max_m: [f64; 3],
}
/// A tangential velocity of one `wall` face of the domain, such as a cavity
/// lid. Laminar flow only, at most one per face, and the velocity component
/// normal to the wall must be zero (CFD-E021).
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct MovingWall {
    /// Axis normal to the wall: 0 (x), 1 (y) or 2 (z). That axis must have
    /// `wall` boundaries.
    pub axis: usize,
    /// True for the face at the upper end of the axis (for example z = Lz),
    /// false for the face at 0.
    pub upper: bool,
    /// Wall velocity [u, v, w] in m/s, finite; the component along `axis`
    /// must be zero.
    pub velocity_m_s: [f64; 3],
}
/// A passive gas: transported and diffused by the flow without affecting it.
/// Concentrations are in kg/m3.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Constituent {
    /// Unique nonempty ID (CFD-E015), referenced by sources and initial
    /// conditions and used in the result.
    pub id: String,
    /// Molecular diffusivity in m2/s, finite and nonnegative (CFD-E015).
    /// With `neutral_rans` the turbulent diffusivity nu_t/Sc_t is added.
    pub diffusivity_m2_s: f64,
}
/// A continuous emission into one constituent, selected by `kind`. Rates are
/// finite and nonnegative (CFD-E016); the support is nondegenerate and inside
/// the domain (CFD-E017). The integrated rate is distributed over the cells
/// the support covers. Support touching a solid cell is rejected (CFD-E040),
/// as is a steady source in a fluid region without an outlet (CFD-E043, and
/// CFD-E020 when no boundary is open).
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Source {
    /// A point emission, deposited in the cell that contains the point.
    Point {
        /// Unique nonempty source ID (CFD-E016).
        id: String,
        /// ID of the emitted constituent (CFD-E016).
        constituent: String,
        /// Position [x, y, z] in meters, inside the domain (each coordinate
        /// at least 0 and below the domain length).
        point_m: [f64; 3],
        /// Emission rate in kg/s.
        rate_kg_s: f64,
    },
    /// A straight line emission. The integrated rate is `rate_kg_s_m` times
    /// the line length, distributed over the cells the segment crosses in
    /// proportion to its length in each.
    Line {
        /// Unique nonempty source ID (CFD-E016).
        id: String,
        /// ID of the emitted constituent (CFD-E016).
        constituent: String,
        /// Start point [x, y, z] in meters, inside the domain.
        from_m: [f64; 3],
        /// End point [x, y, z] in meters, inside the domain and different
        /// from `from_m`.
        to_m: [f64; 3],
        /// Emission rate per meter of line, kg/(s m).
        rate_kg_s_m: f64,
    },
    /// A uniform emission over a box. The integrated rate is `rate_kg_s_m3`
    /// times the box volume, distributed over the cells by their exact overlap
    /// with the box.
    Volume {
        /// Unique nonempty source ID (CFD-E016).
        id: String,
        /// ID of the emitted constituent (CFD-E016).
        constituent: String,
        /// Lower corner [x, y, z] in meters.
        min_m: [f64; 3],
        /// Upper corner [x, y, z] in meters; every bound above `min_m` and
        /// inside the domain.
        max_m: [f64; 3],
        /// Emission rate per cubic meter, kg/(s m3).
        rate_kg_s_m3: f64,
    },
}
impl Source {
    /// The source ID.
    pub fn id(&self) -> &str {
        match self {
            Self::Point { id, .. } | Self::Line { id, .. } | Self::Volume { id, .. } => id,
        }
    }
    /// ID of the constituent the source emits.
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
    /// Integrated emission rate in kg/s: `rate_kg_s`, `rate_kg_s_m` times the
    /// line length, or `rate_kg_s_m3` times the box volume. The represented
    /// source fields emit exactly this rate.
    ///
    /// ```
    /// use cfd_craft::case::Source;
    ///
    /// let line: Source = serde_json::from_str(
    ///     r#"{"kind": "line", "id": "road", "constituent": "tracer",
    ///         "from_m": [1.0, 1.0, 2.0], "to_m": [1.0, 6.0, 2.0], "rate_kg_s_m": 2e-8}"#,
    /// )
    /// .unwrap();
    /// // 2e-8 kg/s per meter over 5 m.
    /// assert!((line.rate() - 1e-7).abs() < 1e-20);
    /// assert_eq!(line.declared_rate(), ("rate_kg_s_m", 2e-8));
    /// ```
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
/// Initial concentration of one constituent, selected by `kind`. Each
/// constituent has at most one (CFD-E018); without one it starts at zero.
/// Solid cells always hold zero.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Initial {
    /// The same concentration in every fluid cell.
    Uniform {
        /// ID of the initialized constituent.
        constituent: String,
        /// Concentration in kg/m3, finite and nonnegative (CFD-E025).
        concentration_kg_m3: f64,
    },
    /// A Gaussian puff, periodized over the domain, integrated per cell and
    /// scaled to exactly `total_mass_kg` of fluid mass. Needs periodic
    /// boundaries on all three axes (CFD-E026); used by the transport
    /// verification fixtures.
    PeriodicGaussian {
        /// ID of the initialized constituent.
        constituent: String,
        /// Center [x, y, z] in meters, inside the domain.
        center_m: [f64; 3],
        /// Standard deviations along x, y and z in meters, each positive and
        /// at most twice the domain length.
        sigma_m: [f64; 3],
        /// Mass of the puff in kg, positive.
        total_mass_kg: f64,
    },
}
impl Initial {
    /// ID of the constituent this condition initializes.
    pub fn constituent(&self) -> &str {
        match self {
            Self::Uniform { constituent, .. } | Self::PeriodicGaussian { constituent, .. } => {
                constituent
            }
        }
    }
}
/// A named concentration sample, selected by `kind` and reported in kg/m3 for
/// every constituent (`receptors_kg_m3` of the result, probes.csv). IDs are
/// unique and nonempty (CFD-E019); the support is nondegenerate and inside the
/// domain (CFD-E027) and may not sample a solid cell (CFD-E042).
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Receptor {
    /// Trilinear interpolation between the eight surrounding cell centers,
    /// clamped at the domain boundary.
    Point {
        /// Unique nonempty receptor ID (CFD-E019).
        id: String,
        /// Position [x, y, z] in meters, inside the domain.
        point_m: [f64; 3],
    },
    /// The average over a box, weighted by the exact overlap of each cell
    /// with the box. Not a point sample or a peak bound.
    VolumeAverage {
        /// Unique nonempty receptor ID (CFD-E019).
        id: String,
        /// Lower corner [x, y, z] in meters.
        min_m: [f64; 3],
        /// Upper corner [x, y, z] in meters; every bound above `min_m` and
        /// inside the domain.
        max_m: [f64; 3],
    },
}
impl Receptor {
    /// The receptor ID.
    pub fn id(&self) -> &str {
        match self {
            Self::Point { id, .. } | Self::VolumeAverage { id, .. } => id,
        }
    }
}
/// Advection scheme of the constituents. `linear_upwind` is first-order
/// upwind; it is linear in the concentrations, so responses to sources
/// superpose exactly in a fixed flow. `muscl` adds a second-order slope with
/// the bounded monotonized-central limiter; it is nonlinear, so superposition
/// is not exact.
#[derive(Clone, Copy, Debug, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Advection {
    #[cfg_attr(
        doc,
        doc = "First-order upwind, linear in the concentrations: exact source superposition in a fixed flow."
    )]
    #[allow(missing_docs)]
    LinearUpwind,
    #[cfg_attr(
        doc,
        doc = "MUSCL with the monotonized-central limiter: second order in smooth regions and bounded, but nonlinear."
    )]
    #[allow(missing_docs)]
    Muscl,
}
/// Preconditioner of the pressure PCG solve. `ic0` (the default) is an
/// incomplete Cholesky factor built once per grid and works on every grid.
/// `multigrid` is a fixed symmetric geometric multigrid cycle for unmasked
/// grids only (CFD-E034); strongly anisotropic spacings select line or plane
/// smoothing and draw warning CFD-W004. Both solve the same equation to the
/// same tolerance and recomputed residual.
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PressurePreconditioner {
    #[cfg_attr(
        doc,
        doc = "Incomplete Cholesky IC(0) of a slightly shifted operator, built on the first pressure solve and cached in the grid (default)."
    )]
    #[allow(missing_docs)]
    #[default]
    Ic0,
    #[cfg_attr(
        doc,
        doc = "Fixed symmetric geometric multigrid cycle; unmasked grids only (CFD-E034). See the [pressure multigrid guide](https://github.com/dietmarwo/CFD-craft/blob/main/docs/PRESSURE_MULTIGRID.md)."
    )]
    #[allow(missing_docs)]
    Multigrid,
}
impl PressurePreconditioner {
    fn is_default(&self) -> bool {
        *self == Self::Ic0
    }
}
/// Momentum advection on the staggered grid. Donor-cell (advective form) is the
/// default; the others are conservative flux forms with an upwind-biased
/// reconstruction of the transported component (van Leer's MUSCL in Sweby's notation).
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MomentumAdvection {
    /// First-order donor-cell upwind in advective form (default).
    #[default]
    DonorCell,
    /// Unlimited second-order upwind: face value 1.5 phi_U - 0.5 phi_UU. Not bounded.
    SecondOrderUpwind,
    /// Second-order upwind with the limiter in `numerics.momentum_limiter`.
    LimitedUpwind,
}
impl MomentumAdvection {
    fn is_default(&self) -> bool {
        *self == Self::DonorCell
    }
}
/// Steady pseudo-time algorithm. `explicit` is the SSPRK2 march of the earlier
/// release. The implicit options solve for a correction driven by the full
/// steady residual (delta form), so they share its fixed point.
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SteadyAlgorithm {
    /// SSPRK2 pseudo-time steps with a projection per stage, limited by
    /// advection and diffusion together (default).
    #[default]
    Explicit,
    /// SSPRK2 stages with an implicit viscous term: (I − Δτ L_ν) δ = Δτ R.
    ImplicitViscous,
    /// One implicit correction per outer iteration, A δ = R with a Picard
    /// first-order upwind and viscous Jacobian and a CFL ramp, followed by a
    /// projection at the pseudo-time step (a SIMPLEC-type coupling).
    ImplicitProjection,
}
impl SteadyAlgorithm {
    fn is_default(&self) -> bool {
        *self == Self::Explicit
    }
}
/// Limiter of `limited_upwind` momentum advection, in Sweby's notation
/// s(a, b) with a and b the upwind and downwind differences: `van_albada`
/// s = ab(a + b)/(a^2 + b^2), `van_leer` s = 2ab/(a + b), or
/// `monotonized_central` s = sign(b) min(2|a|, |a + b|/2, 2|b|). Each is zero
/// where a and b differ in sign.
#[derive(Clone, Copy, Debug, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MomentumLimiter {
    #[cfg_attr(doc, doc = "van Albada: s = ab(a + b)/(a² + b²).")]
    #[allow(missing_docs)]
    VanAlbada,
    #[cfg_attr(doc, doc = "van Leer: s = 2ab/(a + b).")]
    #[allow(missing_docs)]
    VanLeer,
    #[cfg_attr(
        doc,
        doc = "Monotonized central: s = sign(b) min(2|a|, |a + b|/2, 2|b|)."
    )]
    #[allow(missing_docs)]
    MonotonizedCentral,
}
/// Discretization choices, tolerances and the steady monitor window. The
/// optional selections `pressure_preconditioner`, `momentum_advection`,
/// `momentum_limiter` and `steady_algorithm` are left out of the normalized
/// case when they have their default, so cases written before they existed
/// keep their case and physics hashes.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Numerics {
    #[cfg_attr(doc, doc = "Advection scheme of the constituents; see [`Advection`].")]
    #[allow(missing_docs)]
    pub transport: Advection,
    /// Upper bound of the time step in seconds, finite and positive
    /// (CFD-E009). The step is the smaller of this and the stability limit;
    /// in transient mode the last step is clipped to end at `run.end_time_s`.
    pub max_time_step_s: f64,
    /// Stability factor of explicit steps, 0 < CFL <= 0.45 (CFD-E010): with
    /// the explicit algorithm and for constituent sub-steps, dt = CFL / (sum
    /// of max|u|/dx + 2 D sum of 1/dx^2), D the largest viscosity or
    /// diffusivity. `implicit_viscous` applies it to advection only;
    /// `implicit_projection` uses its own CFL ramp for the flow.
    pub advective_cfl_max: f64,
    /// Relative residual target of each pressure solve, finite and positive
    /// (CFD-E009). A solve is accepted when the recomputed residual is within
    /// 10 times this plus 1e-12. A loose value changes the path to a steady
    /// state, not the steady checks.
    pub pressure_relative_tolerance: f64,
    /// PCG iteration limit of each pressure solve, nonzero (CFD-E008).
    /// Reaching it fails the step with CFD-E033.
    pub pressure_max_iterations: usize,
    /// Preconditioner of the pressure solve: `ic0` (default) or `multigrid`.
    /// Omitted from the normalized case when `ic0`, which keeps existing case
    /// and checkpoint hashes.
    #[serde(default, skip_serializing_if = "PressurePreconditioner::is_default")]
    pub pressure_preconditioner: PressurePreconditioner,
    /// Momentum advection: `donor_cell` (default), `second_order_upwind` or
    /// `limited_upwind`. Omitted from the normalized case when `donor_cell`,
    /// which keeps existing case and checkpoint hashes.
    #[serde(default, skip_serializing_if = "MomentumAdvection::is_default")]
    pub momentum_advection: MomentumAdvection,
    /// Limiter of `limited_upwind`: required with it and rejected otherwise
    /// (CFD-E037). Omitted when absent.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub momentum_limiter: Option<MomentumLimiter>,
    /// Pseudo-time algorithm of steady runs: `explicit` (default),
    /// `implicit_viscous` (laminar only) or `implicit_projection` (laminar or
    /// `neutral_rans`). The implicit options need `run.mode = steady`
    /// (CFD-E045) and a solved flow (CFD-E047). Omitted from the normalized
    /// case when `explicit`, which keeps existing hashes.
    #[serde(default, skip_serializing_if = "SteadyAlgorithm::is_default")]
    pub steady_algorithm: SteadyAlgorithm,
    /// Threshold of the normalized steady equation residuals (momentum,
    /// turbulence and each constituent), finite and positive (CFD-E009).
    /// Steady mode only.
    pub steady_residual_tolerance: f64,
    /// Threshold of `monitor_stability`, the largest relative change between
    /// the means of three successive monitor windows; finite and positive
    /// (CFD-E009). Steady mode only.
    pub steady_monitor_tolerance: f64,
    /// Steps per monitor window, 2..100000 (CFD-E008). A steady run assesses
    /// its checks every `monitor_window` steps and needs three full windows
    /// before `monitor_stability` can pass.
    pub monitor_window: usize,
}
/// Run mode. `steady` iterates in pseudo-time until every steady check passes;
/// `run.end_time_s` does not bound it. `transient` integrates the physical
/// interval up to `run.end_time_s`.
#[derive(Clone, Copy, Debug, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    #[cfg_attr(
        doc,
        doc = "Pseudo-time iteration until every steady check passes; success is `completed` / `steady_discrete_solution`."
    )]
    #[allow(missing_docs)]
    Steady,
    #[cfg_attr(
        doc,
        doc = "Time-accurate integration up to `run.end_time_s`; success is `completed` / `transient_interval_completed`."
    )]
    #[allow(missing_docs)]
    Transient,
}
/// Mode, endpoint and execution budgets. The whole group is excluded from the
/// physics hash, so budgets can change between a run and its restart.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Run {
    #[cfg_attr(doc, doc = "Steady or transient; see [`Mode`].")]
    #[allow(missing_docs)]
    pub mode: Mode,
    /// Physical end time of a transient run in seconds: finite, positive and
    /// at most 1e12 (CFD-E009, CFD-E022). It does not bound a steady run.
    pub end_time_s: f64,
    /// Maximum number of retained steps (outer iterations with an implicit
    /// steady algorithm), counted from the cold start including the steps of
    /// a restart checkpoint; nonzero (CFD-E008). Reaching it ends the run as
    /// `iteration_limit`.
    pub max_steps: usize,
    /// Wall-time allowance in seconds: finite, positive and at most seven
    /// days (CFD-E009, CFD-E022). The CLI and the Python binding enforce it;
    /// a Rust caller passes it, or its own limit, to `Control::new`.
    pub wall_time_limit_s: f64,
    /// Worker threads, 1..64 (CFD-E008). The CLI and the Python binding solve
    /// on a pool of this size; the Rust library does not create one.
    pub threads: usize,
    /// Memory budget in MiB for the preflight estimate (CFD-E006); a restart
    /// checkpoint may be at most half of it (CFD-E065). An estimate check, not
    /// an enforced process limit.
    pub memory_limit_mib: usize,
}
/// Which optional artifacts a run archive keeps, and its output budget.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Output {
    /// Write fields.json, the full final state including the native face
    /// velocities.
    pub fields: bool,
    /// Write checkpoint.json, a checksummed restart state.
    pub checkpoint: bool,
    /// Budget for all artifacts in MiB. The preflight estimate must fit
    /// (CFD-E007); at publication, fields and checkpoint are omitted and
    /// listed in the manifest when they would exceed it (CFD-E061).
    pub max_total_mib: usize,
}
/// One finding of a check: a stable code, its severity, the path of the
/// offending field and a message.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Diagnostic {
    /// Stable code such as `CFD-E010` (error) or `CFD-W001` (warning), listed
    /// in docs/diagnostics.md.
    pub code: String,
    /// `error`, which makes the case invalid, or `warning`.
    pub severity: String,
    /// Path of the offending field, for example `numerics.advective_cfl_max`
    /// or `sources[0].rate_kg_s`; empty for a document-level parse error.
    pub path: String,
    /// Explanation for people. Programs should match `code` and `path`, not
    /// this text.
    pub message: String,
}
/// Result of a case check (schema `cfd-craft.check/0.1`), as `cfd-craft
/// check` prints it: validity, the size and resource estimates, and every
/// diagnostic.
#[derive(Clone, Debug, Serialize, Deserialize, JsonSchema)]
pub struct CheckReport {
    /// Always `cfd-craft.check/0.1`.
    pub schema_version: String,
    /// True when no diagnostic has severity `error`.
    pub valid: bool,
    /// Total cell count (saturating at `usize::MAX`); 0 in the report of an
    /// unparsable case.
    pub cells: usize,
    /// Conservative estimate of the solver's peak memory in MiB, checked
    /// against `run.memory_limit_mib`; not measured process memory.
    pub estimated_peak_mib: f64,
    /// Estimated size of all archive artifacts in MiB, checked against
    /// `output.max_total_mib`.
    pub estimated_output_mib: f64,
    /// Every error and warning, in check order.
    pub diagnostics: Vec<Diagnostic>,
}
impl Case {
    /// SHA-256 (lowercase hex) of the case's compact JSON without `name`,
    /// `run` and `output`: the identity of the physical and numerical
    /// problem. A checkpoint restarts only a case with the same physics hash
    /// (CFD-E060), so budgets, the endpoint and the output policy may change
    /// between a run and its restart, while grid, physics, sources, receptors
    /// and numerics may not.
    ///
    /// ```
    /// # let json = r#"{"schema_version": "cfd-craft.case/0.1", "name": "tiny",
    /// #   "domain": {"size_m": [4.0, 1.0, 1.0]}, "grid": {"cells": [8, 2, 2]},
    /// #   "boundaries": {"x": "open", "y": "periodic", "z": "periodic"},
    /// #   "flow": {"kind": "prescribed_uniform", "velocity_m_s": [1.0, 0.0, 0.0]},
    /// #   "constituents": [{"id": "tracer", "diffusivity_m2_s": 0.01}],
    /// #   "sources": [{"kind": "point", "id": "S0", "constituent": "tracer",
    /// #                "point_m": [0.5, 0.5, 0.5], "rate_kg_s": 1e-6}],
    /// #   "numerics": {"transport": "linear_upwind", "max_time_step_s": 1.0,
    /// #     "advective_cfl_max": 0.4, "pressure_relative_tolerance": 1e-10,
    /// #     "pressure_max_iterations": 100, "steady_residual_tolerance": 1e-5,
    /// #     "steady_monitor_tolerance": 1e-3, "monitor_window": 10},
    /// #   "run": {"mode": "steady", "end_time_s": 1.0, "max_steps": 1000,
    /// #     "wall_time_limit_s": 30.0, "threads": 1, "memory_limit_mib": 64},
    /// #   "output": {"fields": false, "checkpoint": false, "max_total_mib": 4}}"#;
    /// use cfd_craft::case::{Case, Source};
    ///
    /// let case: Case = serde_json::from_str(json).unwrap();
    /// let mut longer = case.clone();
    /// longer.name = "tiny, longer budget".into();
    /// longer.run.max_steps *= 10;
    /// assert_eq!(case.physics_hash(), longer.physics_hash());
    ///
    /// let mut weaker = case.clone();
    /// if let Source::Point { rate_kg_s, .. } = &mut weaker.sources[0] {
    ///     *rate_kg_s *= 0.5;
    /// }
    /// assert_ne!(case.physics_hash(), weaker.physics_hash());
    /// ```
    pub fn physics_hash(&self) -> String {
        let mut v = serde_json::to_value(self).expect("serializable case");
        for k in ["run", "output", "name"] {
            v.as_object_mut().unwrap().remove(k);
        }
        hash_bytes(&serde_json::to_vec(&v).unwrap())
    }
    /// The semantic checks that need no grid: schema version, ranges and
    /// units, budgets, physical combinations, IDs, and that geometry, sources,
    /// receptors and initial conditions lie inside the domain. It also
    /// estimates peak memory and output size and checks them against
    /// `run.memory_limit_mib` (CFD-E006) and `output.max_total_mib`
    /// (CFD-E007).
    ///
    /// Every problem is reported at once; the report is invalid when any
    /// diagnostic is an error. It never fails or allocates the grid. The
    /// checks that need the built grid are in
    /// [`input::full_check`](crate::input::full_check), which the CLI and
    /// the Python binding run, and are repeated by
    /// [`solver::run`](crate::solver::run).
    ///
    /// ```
    /// # let json = r#"{"schema_version": "cfd-craft.case/0.1", "name": "tiny",
    /// #   "domain": {"size_m": [4.0, 1.0, 1.0]}, "grid": {"cells": [8, 2, 2]},
    /// #   "boundaries": {"x": "open", "y": "periodic", "z": "periodic"},
    /// #   "flow": {"kind": "prescribed_uniform", "velocity_m_s": [1.0, 0.0, 0.0]},
    /// #   "numerics": {"transport": "linear_upwind", "max_time_step_s": 1.0,
    /// #     "advective_cfl_max": 0.4, "pressure_relative_tolerance": 1e-10,
    /// #     "pressure_max_iterations": 100, "steady_residual_tolerance": 1e-5,
    /// #     "steady_monitor_tolerance": 1e-3, "monitor_window": 10},
    /// #   "run": {"mode": "steady", "end_time_s": 1.0, "max_steps": 1000,
    /// #     "wall_time_limit_s": 30.0, "threads": 1, "memory_limit_mib": 64},
    /// #   "output": {"fields": false, "checkpoint": false, "max_total_mib": 4}}"#;
    /// use cfd_craft::case::Case;
    ///
    /// let mut case: Case = serde_json::from_str(json).unwrap();
    /// case.numerics.advective_cfl_max = 0.9;
    /// case.run.threads = 0;
    /// let report = case.check();
    /// assert!(!report.valid);
    /// let found: Vec<_> = report
    ///     .diagnostics
    ///     .iter()
    ///     .map(|d| (d.code.as_str(), d.path.as_str()))
    ///     .collect();
    /// assert!(found.contains(&("CFD-E010", "numerics.advective_cfl_max")));
    /// assert!(found.contains(&("CFD-E008", "run.threads")));
    /// ```
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
        // Extra hierarchy, reusable cycle vectors and construction peak allowance.
        // This is a conservative preflight allowance, not measured process RSS.
        let multigrid_bytes =
            if self.numerics.pressure_preconditioner == PressurePreconditioner::Multigrid {
                let dx = std::array::from_fn(|a| self.domain.size_m[a] / self.grid.cells[a] as f64);
                1024.0
                    + if crate::multigrid::line_axes(self.grid.cells, dx).is_empty() {
                        0.0
                    } else {
                        512.0
                    }
            } else {
                0.0
            };
        let peak = ((cells as f64) * (880.0 + multigrid_bytes + 96.0 * species) * 1.25
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
        if self.numerics.pressure_preconditioner == PressurePreconditioner::Multigrid
            && !self.geometry.is_empty()
        {
            add(
                "CFD-E034",
                "error",
                "numerics.pressure_preconditioner",
                "Multigrid currently requires an unmasked Cartesian grid; use ic0 for geometry masks.",
            );
        }
        match (
            self.numerics.momentum_advection,
            self.numerics.momentum_limiter,
        ) {
            (MomentumAdvection::LimitedUpwind, None) => add(
                "CFD-E037",
                "error",
                "numerics.momentum_limiter",
                "limited_upwind needs a limiter: van_albada, van_leer or monotonized_central.",
            ),
            (MomentumAdvection::DonorCell | MomentumAdvection::SecondOrderUpwind, Some(_)) => add(
                "CFD-E037",
                "error",
                "numerics.momentum_limiter",
                "A momentum limiter is used only with momentum_advection = limited_upwind.",
            ),
            _ => {}
        }
        if self.numerics.steady_algorithm != SteadyAlgorithm::Explicit {
            let path = "numerics.steady_algorithm";
            if self.run.mode != Mode::Steady {
                add(
                    "CFD-E045",
                    "error",
                    path,
                    "Implicit pseudo-time changes the time accuracy; use it only with run.mode = steady.",
                );
            }
            if self.flow.prescribed()
                || (self.flow.rans()
                    && self.numerics.steady_algorithm == SteadyAlgorithm::ImplicitViscous)
            {
                add(
                    "CFD-E047",
                    "error",
                    path,
                    "Prescribed flow needs no steady algorithm, and implicit_viscous supports laminar flow only; use explicit, or implicit_projection for neutral_rans.",
                );
            }
        }
        if self.numerics.pressure_preconditioner == PressurePreconditioner::Multigrid {
            let dx = std::array::from_fn(|a| self.domain.size_m[a] / self.grid.cells[a] as f64);
            let axes = crate::multigrid::line_axes(self.grid.cells, dx);
            if !axes.is_empty() {
                add(
                    "CFD-W004",
                    "warning",
                    "numerics.pressure_preconditioner",
                    "Strong pressure anisotropy selects symmetric line-block smoothing with additional setup and memory; compare measured cost with ic0. Extreme anisotropy can still reach the pressure limit (CFD-E033).",
                );
            }
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
            let minimum = if self.boundaries.at(a) == Boundary::Periodic {
                1
            } else {
                2
            };
            if self.grid.cells[a] < minimum || self.grid.cells[a] > 4096 {
                add(
                    "CFD-E004",
                    "error",
                    &format!("grid.cells[{a}]"),
                    "Each axis needs 2..4096 cells; a periodic axis may have one (a two-dimensional run).",
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
    /// [`check`](Self::check) as a `Result`: the report when the case is
    /// valid (it may still carry warnings), otherwise an error whose text is
    /// the report serialized as JSON, so its codes and paths can be parsed
    /// back.
    ///
    /// ```
    /// # let json = r#"{"schema_version": "cfd-craft.case/0.1", "name": "tiny",
    /// #   "domain": {"size_m": [4.0, 1.0, 1.0]}, "grid": {"cells": [8, 2, 2]},
    /// #   "boundaries": {"x": "open", "y": "periodic", "z": "periodic"},
    /// #   "flow": {"kind": "prescribed_uniform", "velocity_m_s": [1.0, 0.0, 0.0]},
    /// #   "numerics": {"transport": "linear_upwind", "max_time_step_s": 1.0,
    /// #     "advective_cfl_max": 0.4, "pressure_relative_tolerance": 1e-10,
    /// #     "pressure_max_iterations": 100, "steady_residual_tolerance": 1e-5,
    /// #     "steady_monitor_tolerance": 1e-3, "monitor_window": 10},
    /// #   "run": {"mode": "steady", "end_time_s": 1.0, "max_steps": 1000,
    /// #     "wall_time_limit_s": 30.0, "threads": 1, "memory_limit_mib": 64},
    /// #   "output": {"fields": false, "checkpoint": false, "max_total_mib": 4}}"#;
    /// use cfd_craft::case::{Case, CheckReport};
    ///
    /// let mut case: Case = serde_json::from_str(json).unwrap();
    /// assert!(case.validate().is_ok());
    /// case.schema_version = "cfd-craft.case/9".into();
    /// let error = case.validate().unwrap_err();
    /// let report: CheckReport = serde_json::from_str(&error).unwrap();
    /// assert_eq!(report.diagnostics[0].code, "CFD-E001");
    /// assert_eq!(report.diagnostics[0].path, "schema_version");
    /// ```
    pub fn validate(&self) -> Result<CheckReport> {
        let r = self.check();
        if r.valid {
            Ok(r)
        } else {
            Err(serde_json::to_string(&r).unwrap())
        }
    }
}
/// Lowercase hex SHA-256 of `bytes`: the digest behind the case, physics,
/// state, mask, checkpoint and archive identities.
pub fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
