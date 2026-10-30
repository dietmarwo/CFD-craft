#!/usr/bin/env python3
"""Print per-stage notices of a staged resolution report (temporary helper)."""
import json, sys
from pathlib import Path

def notice(title, lines):
    text = "\n".join(lines).replace("%", "%25").replace("\n", "%0A")
    print(f"::notice title={title}::{text}", flush=True)

out = Path(sys.argv[1])
report = json.loads((out / "report.json").read_text())
for row in report["rows"]:
    lines = [f"accepted {row.get('accepted')} passed {row.get('passed')} stop {row.get('continuation_stop_reason')}",
             f"completed {row.get('completed_solver_iterations')} started {row.get('started_iterations')}"]
    for s in row.get("stages", []):
        e = s["execution"]; n = e.get("numerical") or {}
        lines.append(f"stage {s['stage']}: {e.get('execution_status')} err {e.get('error')} wall {e.get('wall_s')} its {n.get('iterations')} conv {n.get('solver_reported_convergence')} passed {e.get('passed')} res {json.dumps(n.get('initial_residuals_final_iteration'))}")
        st = e.get("initial_state")
        if st:
            lines.append(f"  receipt: source_time {st.get('source_time')} cumulative {st.get('source_completed_iterations')} local {json.dumps(st.get('source_local_continuity'))}")
    c = row.get("comparison") or {}
    if c.get("status") == "evaluated":
        lines.append(f"reattachment {c['reattachment']['predicted_x_over_h']} Cf {c['skin_friction']['rmse']} screen {c.get('measurement_screen_passed')}")
        lines.append("profiles " + "; ".join(f"{k} {v['rmse_u_ref']:.6g}" for k, v in c["profiles"].items()))
    else:
        lines.append(f"comparison {c.get('status')} {c.get('error') or c.get('reason')}")
    a = row.get("independent") or {}
    if a.get("status") == "evaluated":
        lines.append(f"audit {a['passed']} div {a['local_continuity']['maximum_abs_divergence_h_over_u']} y+ " + json.dumps({k: round(v['maximum_y_plus'], 4) for k, v in (a.get('wall_resolution') or {}).get('patches', {}).items()}))
    notice(f"stages {row.get('name')}", lines)
notice("study", [f"passed {report.get('passed')} completed {report.get('workflow_completed')} error {report.get('error')} limits {json.dumps(report.get('stage_limits'))}"])
