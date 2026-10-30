#!/usr/bin/env python3
"""Compare a continued run's final fields, work and metrics with a control run.

Both archives must verify and come from the same recipe, mesh and runtime.

- `fixed-work`: the continued chain and the control did the same number of
  iterations; their fields must agree to the equivalence bounds. Neither needs
  to be converged.
- `converged`: both reached the nonlinear gate; the chain's cumulative work,
  its fields and (for the backstep) its audit and measurement metrics must
  agree with the control to the bounds below.

The report states every measured difference and decides nothing beyond them.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
sys.path.insert(0, str(ROOT / "validation"))
import openfoam_backend as backend
import openfoam_restart as restart

FIELDS = {"cavity": ("U", "p"), "backstep": ("U", "p", "k", "omega", "nut")}
# Absolute U (U_ref) and p (U_ref^2) bounds; k/omega/nut use the largest
# difference over the control's largest magnitude.
BOUNDS = {
    "fixed-work": {
        "cavity": {"U": 1e-6, "p": 1e-6},
        "backstep": {"U": 1e-5, "p": 1e-5, "turbulence": 1e-5},
    },
    "converged": {
        "cavity": {"U": 1e-3, "p": 1e-3, "work_fraction": 0.05},
        "backstep": {
            "U": 1e-3,
            "p": 1e-3,
            "turbulence": 1e-3,
            "work_fraction": 0.05,
            "reattachment_h": 0.01,
            "cf_rmse": 1e-5,
            "profile_rmse": 1e-4,
            "y_plus": 0.01,
        },
    },
}


def require(ok, field, message):
    backend.require(ok, "comparison." + field, message, "CFD-X013")


def cumulative(record):
    state = record.get("initial_state") or {}
    return (
        state.get("source_completed_iterations", 0) + record["numerical"]["iterations"]
    )


def cell_values(path, cells, vector):
    values = np.array(backend.internal_values(path, cells, vector))
    width = 3 if vector else 1
    if len(values) == width:
        values = np.tile(values, cells)
    return values.reshape(cells, 3) if vector else values


def same_recipe(run, control, a, b):
    require(a["case"] == b["case"], "case", "different cases")
    for record, label in [(a, "run"), (b, "control")]:
        require(record["numerical"] is not None, label, "no final field")
    kind = a["case"]
    first = json.loads((Path(run) / "case/case.json").read_text())
    second = json.loads((Path(control) / "case/case.json").read_text())
    for name in sorted(restart.fixed_names(kind)):
        require(
            first["inputs"].get(name) == second["inputs"].get(name),
            "inputs." + name,
            "the recipes differ",
        )
    require(first["metadata"] == second["metadata"], "metadata", "the recipes differ")
    manifests = [
        json.loads((Path(p) / "manifest.json").read_text())["files"]
        for p in [run, control]
    ]
    for name in restart.MESH_FILES:
        key = "case/constant/polyMesh/" + name
        require(
            manifests[0].get(key) == manifests[1].get(key),
            "mesh." + name,
            "the meshes differ",
        )
    require(
        restart.identity(a["runtime"]) == restart.identity(b["runtime"]),
        "runtime",
        "the runtimes differ",
    )
    return kind, first["metadata"]


def field_differences(run, control, a, b, kind, cells):
    result = {}
    for name in FIELDS[kind]:
        vector = name == "U"
        x = cell_values(
            Path(run) / "case" / a["numerical"]["final_time_directory"] / name,
            cells,
            vector,
        )
        y = cell_values(
            Path(control) / "case" / b["numerical"]["final_time_directory"] / name,
            cells,
            vector,
        )
        difference = abs(x - y)
        largest = float(np.max(abs(y)))
        scale = np.maximum(abs(y), 1e-12 * max(largest, 1e-300))
        entry = {
            "maximum_absolute": float(np.max(difference)),
            "control_maximum_magnitude": largest,
            "maximum_over_control_maximum": float(np.max(difference))
            / max(largest, 1e-300),
            # Reported, not gated: a local view that the max-normalized value hides.
            "maximum_cell_relative": float(np.max(difference / scale)),
        }
        if name == "p":
            offset = float(np.mean(x - y))
            entry["maximum_absolute_offset_removed"] = float(
                np.max(abs(x - y - offset))
            )
            entry["offset"] = offset
        result[name] = entry
    return result


def metrics(run, data):
    from audit_openfoam_mesh import audit
    from compare_backstep import assess

    independent = audit(run)
    comparison = assess(run, data, independent=independent)
    return {
        "audit_passed": independent["passed"],
        "screen_passed": comparison.get("measurement_screen_passed"),
        "reattachment_x_over_h": comparison["reattachment"]["predicted_x_over_h"],
        "cf_rmse": comparison["skin_friction"]["rmse"],
        "profile_rmse": {k: v["rmse_u_ref"] for k, v in comparison["profiles"].items()},
        "maximum_y_plus": {
            k: v["maximum_y_plus"]
            for k, v in (
                (independent.get("wall_resolution") or {}).get("patches") or {}
            ).items()
        },
    }


def compare(run, control, mode, data=None):
    require(mode in BOUNDS, "mode", "use fixed-work or converged")
    a, b = backend.verify(run), backend.verify(control)
    kind, metadata = same_recipe(run, control, a, b)
    require(
        mode == "fixed-work" or kind == "cavity" or data is not None,
        "data",
        "converged backstep comparisons need the verified measurements",
    )
    bounds = BOUNDS[mode][kind]
    work = {"run": cumulative(a), "control": cumulative(b)}
    fields = field_differences(run, control, a, b, kind, metadata["cells"])
    checks = {
        "U": fields["U"]["maximum_absolute"] <= bounds["U"],
        "p": fields["p"]["maximum_absolute"] <= bounds["p"],
    }
    if "turbulence" in bounds:
        checks["turbulence"] = all(
            fields[n]["maximum_over_control_maximum"] <= bounds["turbulence"]
            for n in ["k", "omega", "nut"]
        )
    result = {
        "schema_version": "cfd-craft.restart-comparison/0.1",
        "mode": mode,
        "case": kind,
        "bounds": bounds,
        "work": work,
        "numerical_passed": {"run": a["passed"], "control": b["passed"]},
        "fields": fields,
        "run_manifest_sha256": backend.sha256(Path(run) / "manifest.json"),
        "control_manifest_sha256": backend.sha256(Path(control) / "manifest.json"),
        "implementation_sha256": backend.sha256(__file__),
    }
    if mode == "fixed-work":
        checks["work"] = work["run"] == work["control"]
    else:
        checks["numerical"] = a["passed"] and b["passed"]
        checks["work"] = (
            abs(work["run"] - work["control"])
            <= bounds["work_fraction"] * work["control"]
        )
        if kind == "backstep":
            found = {"run": metrics(run, data), "control": metrics(control, data)}
            result["metrics"] = found
            x, y = found["run"], found["control"]
            checks["audit_and_screen"] = all(
                m["audit_passed"] and m["screen_passed"] is True for m in found.values()
            )
            checks["reattachment"] = (
                None not in (x["reattachment_x_over_h"], y["reattachment_x_over_h"])
                and abs(x["reattachment_x_over_h"] - y["reattachment_x_over_h"])
                <= bounds["reattachment_h"]
            )
            checks["cf_rmse"] = abs(x["cf_rmse"] - y["cf_rmse"]) <= bounds["cf_rmse"]
            checks["profile_rmse"] = all(
                abs(x["profile_rmse"][k] - y["profile_rmse"][k])
                <= bounds["profile_rmse"]
                for k in y["profile_rmse"]
            )
            checks["y_plus"] = set(x["maximum_y_plus"]) == set(
                y["maximum_y_plus"]
            ) and all(
                abs(x["maximum_y_plus"][k] - y["maximum_y_plus"][k]) <= bounds["y_plus"]
                for k in y["maximum_y_plus"]
            )
    result["checks"] = checks
    result["passed"] = all(checks.values())
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--run", type=Path, required=True, help="final archive of the chain"
    )
    ap.add_argument("--control", type=Path, required=True)
    ap.add_argument("--mode", choices=sorted(BOUNDS), required=True)
    ap.add_argument("--data", type=Path, help="verified backstep measurements")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists() or not args.output.parent.is_dir():
        error = (
            "CFD-E062 output: file exists"
            if args.output.exists()
            else "CFD-E063 output: parent directory does not exist"
        )
        print(json.dumps({"passed": False, "error": error}))
        return 1
    try:
        result = compare(args.run, args.control, args.mode, args.data)
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        result = {
            "status": "invalid",
            "passed": False,
            "error": backend.diagnostic(exc, "comparison"),
        }
    backend.write_json(args.output, result)
    print(json.dumps(result, indent=2))
    return 1 if result.get("status") == "invalid" else 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
