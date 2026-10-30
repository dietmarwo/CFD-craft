#!/usr/bin/env python3
"""Controlled convergence and mesh-resolution study; failed rows are retained."""

import argparse
import json
import math
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
sys.path.insert(0, str(ROOT / "validation"))
import openfoam_backend as backend
from openfoam_restart import prepare as prepare_restart
from backstep_data import fetch, load, sha256
from compare_backstep import assess, save
from audit_openfoam_mesh import audit
from external_cfd import mesh_sensitivity


# The wall-resolved reference recipe: its mesh family and solver profile.
REFERENCE = ("wall-resolved", "simplec")


def scenarios(preset):
    backend.require(
        preset in {"smoke", "controls", "study"}, "study.preset", "unsupported preset"
    )
    if preset == "controls":
        # Two meshes times two pressure-coupling profiles, all at level 1.
        return [
            (mesh, solver, 1)
            for mesh in ["legacy", "wall-resolved"]
            for solver in ["legacy", "simplec"]
        ]
    return [
        (REFERENCE[0], REFERENCE[1], level)
        for level in ([1] if preset == "smoke" else [1, 2, 3])
    ]


def checked(function, run, label, *args, **kwargs):
    """An audit or comparison of one returned archive; its failure is recorded."""
    try:
        return function(run, *args, **kwargs)
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        return {
            "status": "invalid",
            "passed": False,
            "error": backend.diagnostic(exc, label),
        }


def study(
    foam_root,
    output,
    data=None,
    preset="smoke",
    timeout_s=900,
    iterations=6000,
    max_stages=1,
):
    backend.require(
        math.isfinite(timeout_s) and 0 < timeout_s <= 3600,
        "study.timeout_s",
        "expected (0,3600]",
    )
    backend.require(
        type(iterations) is int and 50 <= iterations <= 20000,
        "study.iterations",
        "expected 50..20000",
    )
    backend.require(
        type(max_stages) is int and 1 <= max_stages <= 8,
        "study.max_stages",
        "expected 1..8",
    )
    requested = scenarios(preset)
    output = Path(output)
    backend.claim_directory(output)
    report = {
        "schema_version": "cfd-craft.wall-resolution-study/0.1",
        "preset": preset,
        "rows": [],
        "workflow_completed": False,
        "passed": False,
        "stage_limits": {
            "max_stages_per_case": max_stages,
            "iterations_per_stage": iterations,
            "wall_s_per_stage": timeout_s,
        },
        "implementation_sha256": {
            p.name: sha256(p)
            for p in [
                Path(__file__),
                ROOT / "integrations/openfoam_cases.py",
                ROOT / "integrations/openfoam_backend.py",
                ROOT / "integrations/openfoam_restart.py",
                ROOT / "validation/audit_openfoam_mesh.py",
                ROOT / "validation/compare_backstep.py",
            ]
        },
        "physical_qualification": {"passed": False, "status": "not_qualified"},
    }
    stop = backend.Stop()
    previous = {
        s: signal.signal(s, stop.signal) for s in [signal.SIGINT, signal.SIGTERM]
    }
    try:
        if data is None:
            data = output / "measurements"
            fetch(data)
        report["reference_sha256"] = load(data)["raw_sha256"]
        for mesh, solver, level in requested:
            if stop.cancelled:
                break
            name = f"{mesh}-{solver}-level{level}"
            row = {
                "name": name,
                "mesh_family": mesh,
                "solver_profile": solver,
                "level": level,
                "accepted": False,
                "passed": False,
                "comparison": None,
                "independent": None,
            }
            report["rows"].append(row)
            if preset == "study" and level > 1 and not report["rows"][-2]["accepted"]:
                row.update(status="not_started", reason="coarser_level_not_accepted")
                backend.write_json(output / "report.json", report)
                continue
            # Input, runtime and I/O errors stop the workflow (exit 1). A failed
            # execution is a returned record; a failed audit or comparison of
            # its archive is row evidence.
            row["stages"] = []
            run_directory = None
            for stage in range(1, max_stages + 1):
                if stop.cancelled:
                    break
                stage_name = name if stage == 1 else f"{name}-stage{stage}"
                prepared = output / (stage_name + "-input")
                if stage == 1:
                    backend.prepare(
                        "backstep", level, iterations, prepared, data, mesh, solver
                    )
                else:
                    try:
                        prepare_restart(run_directory, iterations, prepared)
                    except ValueError as exc:
                        if not str(exc).startswith(
                            "CFD-X012 initial_state.phi.local_continuity:"
                        ):
                            raise
                        # A valid completed stage can still fail this scientific
                        # prerequisite. Assess it, stop continuation and retain
                        # normal unaccepted-row/finer-grid gating semantics.
                        row["continuation_stop_reason"] = str(exc)
                        break
                run_directory = output / stage_name
                execution = backend.run(
                    prepared,
                    run_directory,
                    foam_root,
                    timeout_s=timeout_s,
                    output_mib=512,
                    stop=stop,
                )
                row["execution"] = execution
                row["stages"].append(
                    {
                        "stage": stage,
                        "run_directory": stage_name,
                        "execution": execution,
                    }
                )
                row["completed_solver_iterations"] = sum(
                    (s["execution"].get("numerical") or {}).get("iterations", 0)
                    for s in row["stages"]
                )
                row["started_iterations"] = sum(
                    (s["execution"].get("progress") or {}).get("started_iterations", 0)
                    for s in row["stages"]
                )
                backend.write_json(output / "report.json", report)
                if (
                    execution["passed"]
                    or execution["execution_status"] != "completed"
                    or execution["numerical"] is None
                ):
                    break
            if not row["stages"]:
                break
            if execution["numerical"] is not None:
                row["independent"] = checked(audit, run_directory, "audit")
                reuse = row["independent"]
                row["comparison"] = checked(
                    assess,
                    run_directory,
                    "comparison",
                    data,
                    independent=reuse if reuse["status"] == "evaluated" else None,
                )
                row["accepted"] = execution["passed"] and reuse["passed"]
                row["passed"] = row["accepted"] and row["comparison"]["passed"]
                save(output / (name + "-comparison"), row["comparison"])
            else:
                row["comparison"] = {
                    "status": "not_assessed",
                    "passed": False,
                    "reason": "no final iteration field; execution "
                    + execution["execution_status"],
                }
            backend.write_json(output / "report.json", report)
        selected = [
            {"level": r["level"], "comparison": r["comparison"]}
            for r in report["rows"]
            if r["accepted"] and (r["mesh_family"], r["solver_profile"]) == REFERENCE
        ]
        report["mesh_sensitivity"] = mesh_sensitivity(selected)
        report["workflow_completed"] = not stop.cancelled and len(
            report["rows"]
        ) == len(requested)
        report["passed"] = report["workflow_completed"] and all(
            r["passed"] for r in report["rows"]
        )
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        report["error"] = backend.diagnostic(exc, "study")
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)
        backend.write_json(output / "report.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--foam-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--data", type=Path)
    ap.add_argument("--preset", choices=["smoke", "controls", "study"], default="smoke")
    ap.add_argument("--timeout-s", type=float, default=900)
    ap.add_argument("--iterations", type=int, default=6000)
    ap.add_argument("--max-stages", type=int, default=1)
    args = ap.parse_args()
    try:
        report = study(
            args.foam_root,
            args.output,
            args.data,
            args.preset,
            args.timeout_s,
            args.iterations,
            args.max_stages,
        )
    except (ValueError, OSError) as exc:
        print(json.dumps({"passed": False, "error": backend.diagnostic(exc, "study")}))
        return 1
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "workflow_completed": report["workflow_completed"],
                "error": report.get("error"),
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1 if report.get("error") else 2


if __name__ == "__main__":
    raise SystemExit(main())
