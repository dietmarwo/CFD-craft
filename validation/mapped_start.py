#!/usr/bin/env python3
"""A mapped and a cold start of the next finer level, at equal fine-grid work.

The accepted coarse SOURCE initializes the next level with `prepare-mapped`; a
cold case of the same recipe and iteration limit is the control. Both run with
the same budget, and the report states what each returned: execution status,
nonlinear residuals and their trend, the independent audit and, for the
backstep, the measurement metrics of the final iterate.

This is a report, not an acceptance test: it decides no numerical, mesh or
physical verdict, and a run that stops at its iteration limit is evidence, not
an error. Exit 0 when both runs returned verifiable archives, 1 otherwise.
"""

import argparse
import json
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "integrations"), str(ROOT / "validation")]
import openfoam_backend as backend
import openfoam_mapping as mapping

SCHEMA = "cfd-craft.mapped-start/0.1"
RUN_LIMITS = {"output_mib": 1024, "memory_mib": 4096}


def summarize(run, record, data):
    """What one returned run shows, from its verified archive."""
    from audit_openfoam_mesh import audit

    verified = backend.verify(run)
    numerical = verified.get("numerical") or {}
    found = {
        "execution_status": verified["execution_status"],
        "error": verified.get("error"),
        "wall_s": record.get("wall_s"),
        "numerically_accepted": verified["passed"],
        "iterations": numerical.get("iterations"),
        "solver_reported_convergence": numerical.get("solver_reported_convergence"),
        "initial_residuals_final_iteration": numerical.get(
            "initial_residuals_final_iteration"
        ),
        "residual_trend": numerical.get("residual_trend"),
        "manifest_sha256": backend.sha256(Path(run) / "manifest.json"),
    }
    if not numerical:
        return found
    independent = audit(run)
    found["audit"] = {
        "passed": independent["passed"],
        "maximum_abs_divergence_h_over_u": independent["local_continuity"][
            "maximum_abs_divergence_h_over_u"
        ],
        "maximum_y_plus": {
            name: patch["maximum_y_plus"]
            for name, patch in (
                (independent.get("wall_resolution") or {}).get("patches") or {}
            ).items()
        },
    }
    if verified["case"] == "backstep":
        from compare_backstep import assess

        comparison = assess(run, data, independent=independent)
        found["final_iterate_metrics"] = {
            "measurement_screen_passed": comparison.get("measurement_screen_passed"),
            "reattachment_x_over_h": comparison["reattachment"]["predicted_x_over_h"],
            "cf_rmse": comparison["skin_friction"]["rmse"],
            "profile_rmse": {
                k: v["rmse_u_ref"] for k, v in comparison["profiles"].items()
            },
        }
    return found


def experiment(source, iterations, foam_root, output, data=None, timeout_s=3500):
    backend.require(
        mapping.finite(timeout_s) and 0 < timeout_s <= 3600,
        "mapped_start.timeout_s",
        "expected (0,3600]",
    )
    source, output = Path(source), Path(output)
    parent = backend.verify(source)
    original = json.loads((source / "case/case.json").read_text())
    metadata = original["metadata"]
    level = original["level"] + 1
    backend.claim_directory(output)
    start = time.monotonic()
    report = {
        "schema_version": SCHEMA,
        "meaning": "report only: equal fine-grid iteration limits and budgets; no acceptance, mesh-sensitivity or physical verdict",
        "source": {
            "manifest_sha256": backend.sha256(source / "manifest.json"),
            "case": parent["case"],
            "level": original["level"],
            "iterations": (parent.get("numerical") or {}).get("iterations"),
            "numerically_accepted": parent["passed"],
        },
        "target": {
            "level": level,
            "iterations": iterations,
            "mesh_family": metadata.get("mesh_family", "legacy"),
            "solver_profile": metadata.get("solver_profile", "legacy"),
            "timeout_s": timeout_s,
            **RUN_LIMITS,
        },
        "runs": {},
        "implementation_sha256": {
            p.name: backend.sha256(p)
            for p in [
                Path(__file__),
                ROOT / "integrations/openfoam_mapping.py",
                ROOT / "integrations/openfoam_backend.py",
                ROOT / "integrations/openfoam_cases.py",
                ROOT / "validation/audit_openfoam_mesh.py",
                ROOT / "validation/compare_backstep.py",
            ]
        },
    }
    stop = backend.Stop()
    old = {s: signal.signal(s, stop.signal) for s in [signal.SIGINT, signal.SIGTERM]}
    try:
        began = time.monotonic()
        mapping.prepare(
            source,
            level,
            iterations,
            output / "mapped-input",
            foam_root,
            data,
            timeout_s=min(timeout_s, 900),
            output_mib=1024,
            memory_mib=4096,
            stop=stop,
        )
        report["preparation_wall_s"] = time.monotonic() - began
        backend.prepare(
            parent["case"],
            level,
            iterations,
            output / "cold-input",
            data,
            report["target"]["mesh_family"],
            report["target"]["solver_profile"],
        )
        for name in ["mapped", "cold"]:
            record = backend.run(
                output / (name + "-input"),
                output / name,
                foam_root,
                timeout_s=timeout_s,
                stop=stop,
                **RUN_LIMITS,
            )
            report["runs"][name] = summarize(output / name, record, data)
            backend.write_json(output / "report.json", report)
            if stop.cancelled:
                break
        report["workflow_completed"] = len(report["runs"]) == 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        report["error"] = backend.diagnostic(exc, "mapped_start")
        report["workflow_completed"] = False
    finally:
        for s, handler in old.items():
            signal.signal(s, handler)
        report["total_wall_s"] = time.monotonic() - start
        backend.write_json(output / "report.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True, help="accepted coarse run")
    ap.add_argument("--iterations", type=int, required=True)
    ap.add_argument("--foam-root", type=Path, required=True)
    ap.add_argument("--data", type=Path, help="verified measurements (backstep)")
    ap.add_argument("--timeout-s", type=float, default=3500)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        report = experiment(
            args.source,
            args.iterations,
            args.foam_root,
            args.output,
            args.data,
            args.timeout_s,
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": backend.diagnostic(exc, "mapped_start")}))
        return 1
    print(json.dumps({k: report.get(k) for k in ["workflow_completed", "error"]}))
    return 0 if report.get("workflow_completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
