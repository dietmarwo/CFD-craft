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
from backstep_data import fetch, load, sha256
from compare_backstep import assess, save
from audit_openfoam_mesh import audit
from external_cfd import mesh_sensitivity


def scenarios(preset):
    backend.require(
        preset in {"smoke", "controls", "study"}, "study.preset", "unsupported preset"
    )
    if preset == "controls":
        return [
            ("legacy", "legacy", 1),
            ("legacy", "simplec", 1),
            ("wall-resolved", "legacy", 1),
            ("wall-resolved", "simple", 1),
        ]
    return [
        ("wall-resolved", "simple", level)
        for level in ([1] if preset == "smoke" else [1, 2, 3])
    ]


def study(foam_root, output, data=None, preset="smoke", timeout_s=900, iterations=6000):
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
    requested = scenarios(preset)
    output = Path(output)
    backend.claim_directory(output)
    report = {
        "schema_version": "cfd-craft.wall-resolution-study/0.1",
        "preset": preset,
        "rows": [],
        "workflow_completed": False,
        "passed": False,
        "implementation_sha256": {
            p.name: sha256(p)
            for p in [
                Path(__file__),
                ROOT / "integrations/openfoam_cases.py",
                ROOT / "integrations/openfoam_backend.py",
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
            try:
                backend.prepare(
                    "backstep",
                    level,
                    iterations,
                    output / (name + "-input"),
                    data,
                    mesh,
                    solver,
                )
                execution = backend.run(
                    output / (name + "-input"),
                    output / name,
                    foam_root,
                    timeout_s=timeout_s,
                    output_mib=512,
                    stop=stop,
                )
                row["execution"] = execution
                if execution["numerical"] is not None:
                    row["independent"] = audit(output / name)
                    row["comparison"] = assess(output / name, data)
                    row["accepted"] = (
                        execution["passed"] and row["independent"]["passed"]
                    )
                    row["passed"] = row["accepted"] and row["comparison"]["passed"]
                    save(output / (name + "-comparison"), row["comparison"])
                else:
                    row["comparison"] = {
                        "status": "not_assessed",
                        "passed": False,
                        "reason": "no final iteration field; execution "
                        + execution["execution_status"],
                    }
            except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
                row["error"] = backend.diagnostic(exc, "study." + name)
            backend.write_json(output / "report.json", report)
        selected = [
            {"level": r["level"], "comparison": r["comparison"]}
            for r in report["rows"]
            if r["accepted"]
            and r["mesh_family"] == "wall-resolved"
            and r["solver_profile"] == "simple"
        ]
        report["mesh_sensitivity"] = mesh_sensitivity(selected)
        report["workflow_completed"] = not stop.cancelled and len(
            report["rows"]
        ) == len(requested)
        report["passed"] = report["workflow_completed"] and all(
            r["passed"] for r in report["rows"]
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
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
    args = ap.parse_args()
    try:
        report = study(
            args.foam_root,
            args.output,
            args.data,
            args.preset,
            args.timeout_s,
            args.iterations,
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
