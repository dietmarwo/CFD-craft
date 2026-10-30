#!/usr/bin/env python3
"""Actual coarse-to-fine cavity initialization against a cold fine control.

Both final fine fields must converge and pass the unchanged local/Ghia gates.
This is a cavity verification experiment, not turbulent-flow validation.
"""

import argparse
import json
import signal
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "integrations"), str(ROOT / "validation")]
import openfoam_backend as backend
import openfoam_mapping as mapping
from audit_openfoam_mesh import audit
from compare_backstep import samples
from compare_restart import field_differences, same_recipe


class UnacceptedRun(ValueError):
    """A bounded returned run, separate from a workflow/input error."""


def ghia(run, record):
    # The checked sample reader: column order, finite values, increasing y.
    rows = samples(run, "centerline", ["y", "U_x", "U_y", "U_z"], record)
    observed = np.loadtxt(
        ROOT / "validation/ghia-re100-u.csv", delimiter=",", skiprows=1
    )
    predicted = np.interp(
        observed[:, 0], np.r_[0, rows[:, 0], 1], np.r_[0, rows[:, 1], 1]
    )
    error = float(max(abs(predicted - observed[:, 1])))
    return {
        "maximum_centerline_error": error,
        "target_max": 0.06,
        "passed": error <= 0.06,
    }


def experiment(foam_root, output, timeout_s=120):
    backend.require(
        0 < timeout_s <= 3600, "mapping_experiment.timeout_s", "expected (0,3600]"
    )
    output = Path(output)
    backend.claim_directory(output)
    start = time.monotonic()
    report = {
        "schema_version": "cfd-craft.mapping-experiment/0.1",
        "passed": False,
        "physical_qualification": False,
        "runs": {},
        "target_U_p_max_difference": 1e-4,
        "implementation_sha256": {
            p.name: backend.sha256(p)
            for p in [
                Path(__file__),
                ROOT / "integrations/openfoam_mapping.py",
                ROOT / "integrations/openfoam_restart.py",
                ROOT / "integrations/openfoam_backend.py",
                ROOT / "integrations/openfoam_cases.py",
                ROOT / "validation/audit_openfoam_mesh.py",
                ROOT / "validation/compare_restart.py",
            ]
        },
        "ghia_reference_sha256": backend.sha256(ROOT / "validation/ghia-re100-u.csv"),
    }
    stop = backend.Stop()
    old = {s: signal.signal(s, stop.signal) for s in [signal.SIGINT, signal.SIGTERM]}
    try:

        def solve(name, prepared):
            record = backend.run(
                prepared,
                output / name,
                foam_root,
                timeout_s=timeout_s,
                output_mib=512,
                stop=stop,
            )
            report["runs"][name] = record
            backend.write_json(output / "report.json", report)
            if not record["passed"]:
                raise UnacceptedRun(
                    name
                    + ": "
                    + str(record.get("error") or "numerical gate not reached")
                )
            backend.verify(output / name)
            return record

        backend.prepare("cavity", 1, 3000, output / "source-input")
        solve("source", output / "source-input")
        preparation_start = time.monotonic()
        mapping.prepare(
            output / "source",
            2,
            5000,
            output / "mapped-input",
            foam_root,
            timeout_s=timeout_s,
            stop=stop,
        )
        report["preparation_wall_s"] = time.monotonic() - preparation_start
        mapped = solve("mapped", output / "mapped-input")
        backend.prepare("cavity", 2, 5000, output / "control-input")
        control = solve("control", output / "control-input")
        _, metadata = same_recipe(
            output / "mapped", output / "control", mapped, control
        )
        differences = field_differences(
            output / "mapped",
            output / "control",
            mapped,
            control,
            "cavity",
            metadata["cells"],
        )
        report["field_differences"] = differences
        report["audits"] = {n: audit(output / n) for n in ["mapped", "control"]}
        report["ghia"] = {
            n: ghia(output / n, r)
            for n, r in [("mapped", mapped), ("control", control)]
        }
        report["passed"] = (
            all(d["maximum_absolute"] <= 1e-4 for d in differences.values())
            and all(a["passed"] for a in report["audits"].values())
            and all(g["passed"] for g in report["ghia"].values())
        )
        report["meaning"] = (
            "converged same-fine-grid cavity agreement after explicit nearest-cell initialization; source/preparation work is additional, not fine-grid iterations"
        )
    except UnacceptedRun as exc:
        report["stop_reason"] = str(exc)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        report["error"] = backend.diagnostic(exc, "mapping_experiment")
    finally:
        for s, handler in old.items():
            signal.signal(s, handler)
        report["total_wall_s"] = time.monotonic() - start
        backend.write_json(output / "report.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--foam-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--timeout-s", type=float, default=120)
    args = ap.parse_args()
    try:
        report = experiment(args.foam_root, args.output, args.timeout_s)
    except (ValueError, OSError) as exc:
        print(
            json.dumps(
                {
                    "passed": False,
                    "error": backend.diagnostic(exc, "mapping_experiment"),
                }
            )
        )
        return 1
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in ["passed", "error", "field_differences", "ghia"]
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1 if report.get("error") else 2


if __name__ == "__main__":
    raise SystemExit(main())
