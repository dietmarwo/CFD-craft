//! Numerical verification fixtures that run on a case's own grid, used by
//! `cfd-craft verify`.
use crate::{Result, case::*, grid::Grid, pressure, solver::Control};
/// Discrete pressure recovery on the case's grid: builds the field
/// sin(2 pi x / Lx), removes its gauge, applies the pressure operator and
/// solves for it again to a relative tolerance of 1e-11 (at most 5000
/// iterations, 60 s).
///
/// Returns a `cfd-craft.verification/0.1` JSON record with the RMS error,
/// the relative residual, the iterations and `passed` (RMS error below
/// 1e-9). This checks the pressure solve on that grid, not the flow solution
/// of the case. Errors are those of [`Grid::build`] and
/// [`pressure::solve`].
pub fn pressure_fixture(c: &Case) -> Result<serde_json::Value> {
    let g = Grid::build(c)?;
    let mut exact: Vec<_> = (0..g.count())
        .map(|i| {
            let p = g.center(i);
            (2.0 * std::f64::consts::PI * p[0] / c.domain.size_m[0]).sin()
        })
        .collect();
    pressure::center_nullspaces(&g, &mut exact);
    let mut b = vec![0.0; g.count()];
    pressure::apply(&g, &exact, &mut b);
    let (x, info) = pressure::solve(&g, &b, 1e-11, 5000, &Control::new(60.0))?;
    let error = x
        .iter()
        .zip(exact)
        .map(|(x, y)| (x - y).powi(2))
        .sum::<f64>()
        .sqrt()
        / ((g.count() as f64).sqrt());
    Ok(
        serde_json::json!({"schema_version":"cfd-craft.verification/0.1","fixture":"pressure_discrete_recovery","rms_error":error,"relative_residual":info.relative_residual,"iterations":info.iterations,"passed":error<1e-9}),
    )
}
