#![forbid(unsafe_code)]
use cfd_craft::{
    case::{Case, Source},
    solver::{self, Control},
};
use fcmaes_job_worker::{
    Adapter,
    registry::{Example, Registry, Scalar},
};
use serde_json::json;
fn scale(source: &mut Source, value: f64) {
    match source {
        Source::Point { rate_kg_s, .. } => *rate_kg_s *= value,
        Source::Line { rate_kg_s_m, .. } => *rate_kg_s_m *= value,
        Source::Volume { rate_kg_s_m3, .. } => *rate_kg_s_m3 *= value,
    }
}
fn registry() -> Registry {
    let mut r = Registry::new();
    r.scalar("app.cfd.source-allocation","1",json!({
        "simulation":true,"dimensions":2,
        "objective":"maximum receptor concentration / 1e-8 kg/m3; three source multipliers x0,x1,3-x0-x1",
        "scope":"prescribed-flow passive transport, fixed total emissions; synthetic research objective"
    }),|model|{
        model.require_dimension(2..=2)?;
        let case:Case=serde_json::from_slice(&model.input("case")?).map_err(|e|e.to_string())?;
        case.validate()?;
        if !case.flow.prescribed()||case.sources.len()!=3||case.constituents.len()!=1||case.receptors.is_empty(){
            return Err("requires prescribed flow, three sources, one constituent and receptors".into());
        }
        let rate=case.sources[0].rate();
        if rate<=0.0 || case.sources.iter().any(|s|(s.rate()/rate-1.0).abs()>1e-12) {
            return Err("fixed-total allocation requires three equal positive base emission rates".into());
        }
        Ok(Scalar::simulation(move|x,context|{
            context.checkpoint()?;
            let mut c=case.clone();c.run.threads=context.threads();
            for (source,value) in c.sources.iter_mut().zip([x[0],x[1],3.0-x[0]-x[1]]){scale(source,value);}
            let ctx=context.clone();
            let control=Control::with_poll(context.remaining_seconds().min(c.run.wall_time_limit_s),move||ctx.checkpoint());
            let run=solver::run(&c,&control,None)?;
            if run.summary.assessment!="steady_discrete_solution"{
                return Err(format!("CFD {}: {}",run.summary.termination,run.summary.assessment));
            }
            let value=run.summary.constituents[0].receptors_kg_m3.values().copied().fold(0.0,f64::max)/1e-8;
            if !value.is_finite(){return Err("nonfinite receptor objective".into());}Ok(value)
        }).domain(vec![0.1,0.1],vec![1.4,1.4]))
    });
    r.example(
        "app.cfd.source-allocation",
        Example::new(2)
            .bounds(vec![0.1, 0.1], vec![1.4, 1.4])
            .input_text(
                "case",
                "case.json",
                include_str!("../../../cases/verification/source-response.json"),
            ),
    );
    r
}
fn main() {
    optimization_job_api::worker::run(Adapter::new(registry()));
}
