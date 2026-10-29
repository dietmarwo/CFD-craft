use crate::{Result, case::*, grid::Grid, pressure, solver::Control};
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
