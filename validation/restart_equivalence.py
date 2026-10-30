#!/usr/bin/env python3
"""Fixed-work continuation check: FIRST + SECOND iterations against FIRST + SECOND.

Runs a cold source stage of FIRST iterations, continues it for SECOND
iterations with `prepare-restart`, runs an uninterrupted control of
FIRST + SECOND iterations of the same recipe, and compares the two final fields
(`compare_restart.py --mode fixed-work`). Equivalence is not convergence: the
fields need not pass the nonlinear gate, and no measurement screen is implied.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
sys.path.insert(0, str(ROOT / "validation"))
import openfoam_backend as backend
import openfoam_restart as restart
from compare_restart import compare


def experiment(case, profile, first, second, foam_root, output, data, timeout_s):
    output = Path(output)
    backend.claim_directory(output)
    mesh = "wall-resolved" if case == "backstep" else "legacy"
    profile = profile or ("simplec" if case == "backstep" else "legacy")
    report = {
        "schema_version": "cfd-craft.restart-equivalence/0.1",
        "case": case,
        "mesh_family": mesh,
        "solver_profile": profile,
        "iterations": {"first": first, "second": second},
        "runs": {},
        "passed": False,
    }
    try:
        for name, steps in [("source", first), ("continuous", first + second)]:
            backend.prepare(
                case, 1, steps, output / (name + "-input"), data, mesh, profile
            )
        for name in ["source", "split", "continuous"]:
            if name == "split":
                restart.prepare(output / "source", second, output / "split-input")
            record = backend.run(
                output / (name + "-input"),
                output / name,
                foam_root,
                timeout_s=timeout_s,
                output_mib=512,
            )
            report["runs"][name] = {
                k: record.get(k) for k in ["execution_status", "error", "wall_s"]
            } | {"iterations": (record.get("numerical") or {}).get("iterations")}
            backend.require(
                record["execution_status"] == "completed"
                and record["numerical"] is not None,
                f"equivalence.{name}",
                "stage did not complete with a final field",
            )
        report["comparison"] = compare(
            output / "split", output / "continuous", "fixed-work"
        )
        report["passed"] = report["comparison"]["passed"]
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        report["error"] = backend.diagnostic(exc, "equivalence")
    finally:
        backend.write_json(output / "report.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", choices=["cavity", "backstep"], required=True)
    ap.add_argument("--solver-profile", choices=["legacy", "simplec", "simple"])
    ap.add_argument("--first", type=int, required=True)
    ap.add_argument("--second", type=int, required=True)
    ap.add_argument("--foam-root", type=Path, required=True)
    ap.add_argument("--data", type=Path)
    ap.add_argument("--timeout-s", type=float, default=600)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        report = experiment(
            args.case,
            args.solver_profile,
            args.first,
            args.second,
            args.foam_root,
            args.output,
            args.data,
            args.timeout_s,
        )
    except (ValueError, OSError) as exc:
        print(json.dumps({"passed": False, "error": backend.diagnostic(exc, "output")}))
        return 1
    print(json.dumps({k: report.get(k) for k in ["passed", "runs", "error"]}, indent=2))
    return 0 if report["passed"] else 1 if report.get("error") else 2


if __name__ == "__main__":
    raise SystemExit(main())
