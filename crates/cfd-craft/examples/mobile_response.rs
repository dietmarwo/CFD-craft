//! Prepare one accepted flow per wind, then export independent cold scalar columns.
use cfd_craft::{Result, case::*, mobile_response::PreparedFlow, output, solver::Control};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
    time::Instant,
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Group {
    id: String,
    source_ids: Vec<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: String,
    case: Case,
    groups: Vec<Group>,
    truth_multipliers: Vec<f64>,
    campaign_wall_time_limit_s: f64,
}
fn write(path: &Path, value: &impl serde::Serialize) -> Result<()> {
    fs::write(
        path,
        serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())
}
fn scaled(source: &Source, q: f64) -> Source {
    let mut s = source.clone();
    match &mut s {
        Source::Point { rate_kg_s, .. } => *rate_kg_s *= q,
        Source::Line { rate_kg_s_m, .. } => *rate_kg_s_m *= q,
        Source::Volume { rate_kg_s_m3, .. } => *rate_kg_s_m3 *= q,
    };
    s
}
fn observations(
    case: &Case,
    result: &cfd_craft::solver::RunResult,
) -> Result<(Vec<Value>, Vec<f64>)> {
    let mut rows = vec![];
    let mut values = vec![];
    for sp in &case.constituents {
        let scalar = result
            .summary
            .constituents
            .iter()
            .find(|x| x.id == sp.id)
            .ok_or("missing constituent evidence")?;
        for r in &case.receptors {
            if let Receptor::Path { .. } = r {
                let path = &scalar.paths[r.id()];
                for (j, &v) in path.concentrations_kg_m3.iter().enumerate() {
                    rows.push(json!({"constituent":sp.id,"receptor":r.id(),"sample_index":j,"point_m":path.points_m[j],"distance_m":path.distance_m[j],"kind":"path"}));
                    values.push(v);
                }
            } else {
                rows.push(json!({"constituent":sp.id,"receptor":r.id(),"sample_index":Value::Null,"kind":"station"}));
                values.push(scalar.receptors_kg_m3[r.id()]);
            }
        }
    }
    Ok((rows, values))
}
fn execute(input: &Path, out: &Path) -> Result<()> {
    let bytes = fs::read(input).map_err(|e| e.to_string())?;
    let request: Request = serde_json::from_slice(&bytes)
        .map_err(|e| format!("CFD-E089: mobile_response.request: {e}"))?;
    if request.schema_version != "cfd-craft.mobile-response/1"
        || request.groups.is_empty()
        || request.groups.len() > 16
        || request.groups.len() != request.truth_multipliers.len()
        || request
            .truth_multipliers
            .iter()
            .any(|q| !q.is_finite() || *q < 0.)
        || !request.campaign_wall_time_limit_s.is_finite()
        || !(0.0..=3600.).contains(&request.campaign_wall_time_limit_s)
        || request.campaign_wall_time_limit_s == 0.
    {
        return Err(
            "CFD-E089: mobile_response.request: invalid groups,truth,version or campaign budget"
                .into(),
        );
    }
    let mut names = BTreeSet::new();
    let mut ids = BTreeSet::new();
    for group in &request.groups {
        if group.id.is_empty() || !names.insert(group.id.clone()) || group.source_ids.is_empty() {
            return Err("CFD-E089: mobile_response.groups: nonempty unique groups required".into());
        }
        for id in &group.source_ids {
            if !ids.insert(id.clone()) || !request.case.sources.iter().any(|s| s.id() == id) {
                return Err(
                    "CFD-E089: mobile_response.groups.source_ids: every source must occur once"
                        .into(),
                );
            }
        }
    }
    if ids.len() != request.case.sources.len() {
        return Err("CFD-E089: mobile_response.groups: ungrouped source".into());
    }
    output::create_run_dir(out)?;
    fs::write(out.join("request.json"), &bytes).map_err(|e| e.to_string())?;
    let mut report = json!({"schema_version":"cfd-craft.mobile-response-result/1","passed":false,"request_sha256":hash_bytes(&bytes),"driver_sha256":hash_bytes(include_bytes!("mobile_response.rs")),"core_source_sha256":cfd_craft::SOURCE_SHA256,"columns":[],"observations":[],"flow_solves":0,"flow_updates_per_response":0,"experimental_validation":"not_validated","scope":"linear scalar response on an accepted immutable flow; local-source increments"});
    let start = Instant::now();
    let result = (|| -> Result<()> {
        let remaining =
            || {
                request.case.run.wall_time_limit_s.min(
                    (request.campaign_wall_time_limit_s - start.elapsed().as_secs_f64()).max(0.),
                )
            };
        let flow_case = PreparedFlow::preparation_case(&request.case)?;
        report["flow_solves"] = json!(usize::from(!request.case.flow.prescribed()));
        report["flow_preparations"] = json!(1);
        let flow_result = cfd_craft::solver::run(&flow_case, &Control::new(remaining()), None)?;
        let flow_dir = out.join("flow");
        output::create_run_dir(&flow_dir)?;
        output::write_run(
            &flow_case,
            &flow_result,
            &flow_dir,
            &hash_bytes(&serde_json::to_vec(&flow_case).unwrap()),
        )?;
        report["flow_assessment"] = json!(flow_result.summary.assessment);
        let prepared = PreparedFlow::from_accepted(&request.case, flow_result)?;
        report["flow_assessment"] = json!(prepared.result.summary.assessment);
        report["flow_state_sha256"] = json!(cfd_craft::mobile_response::flow_state_hash(
            &prepared.result.state
        ));
        let mut expected_rows: Option<Vec<Value>> = None;
        for (i, group) in request.groups.iter().enumerate() {
            let mut c = request.case.clone();
            c.name = format!("response-{}", group.id);
            c.sources
                .retain(|s| group.source_ids.iter().any(|id| id == s.id()));
            let r = prepared.run(&c, &Control::new(remaining()))?;
            let folder = out.join(format!("column-{i}"));
            output::create_run_dir(&folder)?;
            output::write_run(
                &c,
                &r,
                &folder,
                &hash_bytes(&serde_json::to_vec(&c).unwrap()),
            )?;
            let (rows, values) = observations(&c, &r)?;
            if let Some(expected) = &expected_rows {
                if expected != &rows {
                    return Err(
                        "CFD-E089: mobile_response.rows: observations changed between columns"
                            .into(),
                    );
                }
            } else {
                expected_rows = Some(rows.clone());
                report["observations"] = json!(rows);
            }
            let accepted = r.summary.assessment == "steady_discrete_solution"
                && r.summary.checks.iter().all(|x| x.passed);
            report["columns"].as_array_mut().unwrap().push(json!({"id":group.id,"source_ids":group.source_ids,"integrated_reference_rate_kg_s":c.sources.iter().map(Source::rate).sum::<f64>(),"values_kg_m3":values,"accepted":accepted,"archive":format!("column-{i}"),"steps":r.state.steps,"elapsed_s":r.summary.elapsed_s}));
            write(&out.join("report.json"), &report)?;
            if !accepted {
                return Err(format!(
                    "CFD-E089: mobile_response.columns[{i}]: {} / {}",
                    r.summary.termination, r.summary.assessment
                ));
            }
        }
        let mut truth = request.case.clone();
        truth.name = "independent-combined-truth".into();
        truth.sources = request
            .case
            .sources
            .iter()
            .map(|s| {
                let j = request
                    .groups
                    .iter()
                    .position(|g| g.source_ids.iter().any(|id| id == s.id()))
                    .unwrap();
                scaled(s, request.truth_multipliers[j])
            })
            .collect();
        let r = prepared.run(&truth, &Control::new(remaining()))?;
        let folder = out.join("truth");
        output::create_run_dir(&folder)?;
        output::write_run(
            &truth,
            &r,
            &folder,
            &hash_bytes(&serde_json::to_vec(&truth).unwrap()),
        )?;
        let (rows, values) = observations(&truth, &r)?;
        if expected_rows.as_ref() != Some(&rows) {
            return Err("CFD-E089: mobile_response.truth: row identity mismatch".into());
        }
        let accepted = r.summary.assessment == "steady_discrete_solution"
            && r.summary.checks.iter().all(|x| x.passed);
        report["truth"] = json!({"multipliers":request.truth_multipliers,"values_kg_m3":values,"accepted":accepted,"archive":"truth","steps":r.state.steps,"elapsed_s":r.summary.elapsed_s});
        if !accepted {
            return Err(format!(
                "CFD-E089: mobile_response.truth: {} / {}",
                r.summary.termination, r.summary.assessment
            ));
        }
        report["passed"] = json!(true);
        Ok(())
    })();
    if let Err(e) = &result {
        report["error"] = json!(e);
    }
    report["elapsed_s"] = json!(start.elapsed().as_secs_f64());
    write(&out.join("report.json"), &report)?;
    result
}
fn main() {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: mobile_response REQUEST.json NEW_OUTPUT_DIR");
        std::process::exit(1);
    }
    if let Err(e) = execute(&PathBuf::from(&args[1]), &PathBuf::from(&args[2])) {
        eprintln!("{e}");
        std::process::exit(2);
    }
}
