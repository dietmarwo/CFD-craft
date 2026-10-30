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
        f"preset {report.get('preset')}; passed {report.get('passed')}; "
        f"workflow completed {report.get('workflow_completed')}; error {report.get('error')}; "
        f"mesh sensitivity {json.dumps(report.get('mesh_sensitivity'))}\n"
        + "\n".join(
            f"{k} {v}" for k, v in (report.get("implementation_sha256") or {}).items()
        ),
    )
    return 0


def main():
    report = json.loads(Path(sys.argv[1]).read_text())
    if "rows" in report:
        return resolution(report)
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
