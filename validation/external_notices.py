#!/usr/bin/env python3
"""Print GitHub Actions notices with the key numbers of an external tutorial report.

The notices make a CI run's results readable in the checks view and through the
check-run annotations API. They summarize report.json; they decide nothing.
"""

import json
import sys
from pathlib import Path


def escape(text, title=False):
    text = str(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if title else text


def notice(title, message):
    print(f"::notice title={escape(title, True)}::{escape(message)}")


def number(value, digits=6):
    return "null" if value is None else f"{value:.{digits}g}"


def backstep_lines(row):
    execution = row.get("execution") or {}
    numerical = execution.get("numerical") or {}
    progress = execution.get("progress") or {}
    trend = (numerical.get("residual_trend") or {}).get("p") or {}
    lines = [
        f"cells {execution.get('case_metadata', {}).get('cells')}",
        f"execution {execution.get('execution_status')}"
        + (f"; error {execution['error']}" if execution.get("error") else ""),
        f"started iterations {progress.get('started_iterations')}",
        f"wall {number(execution.get('wall_s'), 5)} s",
        f"numerical passed {numerical.get('passed')}",
        "final p residual "
        + number((numerical.get("initial_residuals_final_iteration") or {}).get("p")),
        f"p median last/previous window {number(trend.get('median_last_window'))}"
        f" / {number(trend.get('median_previous_window'))}",
    ]
    if "stages" in row:
        lines.append(
            f"stages {len(row['stages'])}; completed solver iterations across stages "
            f"{row.get('completed_solver_iterations')}; started {row.get('started_iterations')}; "
            f"stop {row.get('continuation_stop_reason')}"
        )
        for stage in row["stages"]:
            run = stage.get("execution") or {}
            work = run.get("numerical") or {}
            state = run.get("initial_state") or {}
            source = state.get("source_local_continuity") or {}
            balance = source.get("maximum_abs_divergence_h_over_u")
            lines.append(
                f"stage {stage.get('stage')}: {run.get('execution_status')}; iterations "
                f"{work.get('iterations')}; converged {work.get('solver_reported_convergence')}; "
                f"wall {number(run.get('wall_s'), 5)} s"
                + (f"; source max div(phi)*H/U {number(balance, 3)}" if state else "")
                + (f"; error {run['error']}" if run.get("error") else "")
            )
    comparison = row.get("comparison") or {}
    if comparison.get("status") != "evaluated":
        lines.append(
            f"comparison {comparison.get('status')}: "
            + str(comparison.get("error") or comparison.get("reason"))
        )
        return lines
    for station, m in comparison["profiles"].items():
        lines.append(
            f"x/H={station}: RMSE {number(m['rmse_u_ref'])}, max {number(m['maximum_absolute_error_u_ref'])}, "
            f"y<2 {number(m.get('rmse_u_ref_below_y2'))}, no-step baseline {number(m.get('baseline_no_step_rmse_u_ref'))}"
        )
    friction = comparison["skin_friction"]
    lines.append(
        f"Cf RMSE {number(friction['rmse'])} over {friction['samples']} points"
        f" (Cf=0 baseline {number(friction.get('baseline_zero_cf_rmse'))})"
    )
    lines.append(
        f"reattachment {number(comparison['reattachment']['predicted_x_over_h'])} H"
    )
    wall = comparison.get("near_wall_resolution") or {}
    scored = wall.get("scored_1_to_12") or {}
    lines.append(
        f"first-cell y+ in 1<x/H<12: median {number(scored.get('median'), 3)},"
        f" range {number(scored.get('minimum'), 3)}-{number(scored.get('maximum'), 3)}"
    )
    lines.append(
        f"measurement screen {comparison.get('measurement_screen')}"
        f" (passed {comparison.get('measurement_screen_passed')})"
    )
    return lines


def audit_lines(audit):
    if not audit:
        return ["independent audit not run"]
    if audit.get("status") != "evaluated":
        return [
            f"independent audit {audit.get('status')}: "
            + str(audit.get("error") or audit.get("reason"))
        ]
    continuity = audit["local_continuity"]
    lines = [
        f"independent audit passed {audit['passed']}; max div(phi)*H/U "
        f"{number(continuity['maximum_abs_divergence_h_over_u'])}, max relative cell imbalance "
        f"{number(continuity.get('maximum_relative_cell_imbalance'))}"
    ]
    for name, wall in (
        (audit.get("wall_resolution") or {}).get("patches") or {}
    ).items():
        at = wall.get("maximum_y_plus_at_xy_over_h") or [None, None]
        lines.append(
            f"{name}: max y+ {number(wall['maximum_y_plus'], 4)} at x/H={number(at[0], 4)},"
            f" y/H={number(at[1], 4)}; median {number(wall['median_y_plus'], 4)}"
        )
    return lines


def resolution(report):
    for row in report["rows"]:
        title = f"resolution {row.get('name')}"
        if row.get("status") == "not_started":
            notice(title, f"not started: {row.get('reason')}")
            continue
        lines = [f"accepted {row.get('accepted')}; passed {row.get('passed')}"]
        lines += backstep_lines(row)
        lines += audit_lines(row.get("independent"))
        notice(title, "\n".join(lines))
    notice(
        "resolution study",
        f"preset {report.get('preset')}; stage limits {json.dumps(report.get('stage_limits'))}; "
        f"passed {report.get('passed')}; "
        f"workflow completed {report.get('workflow_completed')}; error {report.get('error')}; "
        f"mesh sensitivity {json.dumps(report.get('mesh_sensitivity'))}\n"
        + "\n".join(
            f"{k} {v}" for k, v in (report.get("implementation_sha256") or {}).items()
        ),
    )
    return 0


def restart_comparison(report, title):
    if report.get("status") == "invalid":
        notice(title, f"invalid: {report.get('error')}")
        return 0
    lines = [
        f"mode {report['mode']}; passed {report['passed']}; checks {json.dumps(report['checks'])}",
        f"work {json.dumps(report['work'])}; numerical passed {json.dumps(report['numerical_passed'])}",
    ]
    for name, field in report["fields"].items():
        lines.append(
            f"{name}: max abs {number(field['maximum_absolute'])}, over control max "
            f"{number(field['maximum_over_control_maximum'])}, max cell relative "
            f"{number(field['maximum_cell_relative'])}"
        )
    for side, found in (report.get("local_continuity") or {}).items():
        lines.append(
            f"{side}: final max div(phi)*H/U "
            f"{number(found['maximum_abs_divergence_h_over_u'])}"
        )
    for side, found in (report.get("metrics") or {}).items():
        lines.append(
            f"{side}: reattachment {number(found['reattachment_x_over_h'], 8)} H; Cf RMSE "
            f"{number(found['cf_rmse'], 8)}; profiles "
            + ", ".join(f"{k} {number(v, 8)}" for k, v in found["profile_rmse"].items())
            + "; max y+ "
            + ", ".join(
                f"{k} {number(v, 6)}" for k, v in found["maximum_y_plus"].items()
            )
        )
    lines.append(f"implementation {report.get('implementation_sha256')}")
    notice(title, "\n".join(lines))
    return 0


def main():
    report = json.loads(Path(sys.argv[1]).read_text())
    title = sys.argv[2] if len(sys.argv) > 2 else "restart comparison"
    if "rows" in report:
        return resolution(report)
    if str(report.get("schema_version", "")).startswith(
        "cfd-craft.restart-equivalence"
    ):
        notice(
            title + " runs",
            f"{report['case']} {report['mesh_family']}/{report['solver_profile']}; "
            f"iterations {json.dumps(report['iterations'])}; runs {json.dumps(report['runs'])}; "
            f"error {report.get('error')}",
        )
        if report.get("comparison"):
            return restart_comparison(report["comparison"], title)
        return 0
    if str(report.get("schema_version", "")).startswith(
        "cfd-craft.restart-comparison"
    ) or ("mode" not in report and report.get("status") == "invalid"):
        return restart_comparison(report, title)
    cavity = report.get("cavity") or {}
    errors = cavity.get("maximum_absolute_errors_lid_speed") or {}
    notice(
        "cavity",
        f"passed {cavity.get('passed')}; "
        + "; ".join(f"{k} {number(v)}" for k, v in errors.items())
        + f"; OpenFOAM iterations {cavity.get('external_steady_iterations')}"
        + (f"; error {cavity['error']}" if cavity.get("error") else ""),
    )
    for row in report.get("backstep") or []:
        notice(f"backstep level {row.get('level')}", "\n".join(backstep_lines(row)))
    if report.get("backstep"):
        notice("mesh sensitivity", json.dumps(report.get("mesh_sensitivity")))
    hashes = {"workflow": report.get("workflow_implementation_sha256")}
    for row in report.get("backstep") or []:
        hashes.update((row.get("execution") or {}).get("implementation_sha256") or {})
        hashes.update((row.get("comparison") or {}).get("implementation_sha256") or {})
    notice(
        "implementation",
        f"preset {report.get('preset')}; passed {report.get('passed')}; "
        f"workflow completed {report.get('workflow_completed')}; error {report.get('error')}\n"
        + "\n".join(f"{k} {v}" for k, v in hashes.items()),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
