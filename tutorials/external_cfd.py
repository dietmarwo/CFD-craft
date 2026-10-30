#!/usr/bin/env python3
"""Run both CFD backends and a measurement comparison, retaining failed rows."""

import argparse
import json
import signal
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
sys.path.insert(0, str(ROOT / "validation"))
import openfoam_backend as backend
from backstep_data import fetch, load, sha256
from compare_backstep import assess, samples, save
from common import accepted, run_case

require = backend.require


def cavity_comparison(binary, external, output):
    result = {
        "passed": False,
        "kind": "numerical_comparison",
        "experimental_validation": False,
        "native_run": None,
    }
    try:
        external_report = backend.verify(external)
        result["external_run_manifest_sha256"] = sha256(
            Path(external) / "manifest.json"
        )
        c = json.loads((ROOT / "cases/verification/lid-cavity.json").read_text())
        r = run_case(binary, c, Path(output) / "native-cavity")
        result["native_run"] = r
        require(
            accepted(r),
            "cavity.native_run",
            "not an accepted native solution",
            "CFD-X006",
        )
        numerical = backend.numerical_assessment(
            Path(external) / "case",
            (Path(external) / "solve.log").read_text(),
            "cavity",
        )
        require(
            numerical == external_report["numerical"],
            "cavity.external_run.numerical",
            "summary differs from the returned log and fields",
            "CFD-X006",
        )
        require(
            numerical["passed"],
            "cavity.external_run.numerical",
            "convergence/continuity gate not reached",
            "CFD-X007",
        )
        field = json.loads((Path(output) / "native-cavity/fields.json").read_text())
        nx, ny, nz = c["grid"]["cells"]
        native_u = (
            np.array(field["velocity"][: (nx + 1) * ny * nz])
            .reshape(nz, ny, nx + 1)[:, :, nx // 2]
            .mean(axis=1)
        )
        native_y = np.r_[0, (np.arange(nz) + 0.5) / nz, 1]
        native_u = np.r_[0, native_u, 1]
        external_values = samples(
            external, "centerline", ["y", "U_x", "U_y", "U_z"], external_report
        )
        external_y = np.r_[0, external_values[:, 0], 1]
        external_u = np.r_[0, external_values[:, 1], 1]
        reference = np.loadtxt(
            ROOT / "validation/ghia-re100-u.csv", delimiter=",", skiprows=1
        )
        native_predicted = np.interp(reference[:, 0], native_y, native_u)
        external_predicted = np.interp(reference[:, 0], external_y, external_u)
        errors = {
            "native_vs_ghia": float(max(abs(native_predicted - reference[:, 1]))),
            "openfoam_vs_ghia": float(max(abs(external_predicted - reference[:, 1]))),
            "native_vs_openfoam_at_reference_stations": float(
                max(abs(native_predicted - external_predicted))
            ),
        }
        result.update(
            maximum_absolute_errors_lid_speed=errors,
            target_max=0.06,
            native_vertical_axis="z",
            openfoam_vertical_axis="y",
            reynolds=100,
            reference="Ghia numerical benchmark, not a physical experiment",
            native_final_time_s=field["time_s"],
            external_steady_iterations=numerical["iterations"],
            native_case_sha256=r["summary"]["case_sha256"]
            if "case_sha256" in r["summary"]
            else sha256(Path(output) / "native-cavity.case.json"),
        )
        require(
            all(error <= 0.06 for error in errors.values()),
            "cavity.maximum_absolute_errors_lid_speed",
            "exceeds the frozen target of 0.06",
            "CFD-X009",
        )
        result["passed"] = True
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result["error"] = backend.diagnostic(exc, "cavity")
    backend.write_json(Path(output) / "cavity-comparison.json", result)
    return result


def mesh_sensitivity(rows):
    usable = [
        row for row in rows if (row.get("comparison") or {}).get("numerical_passed")
    ]
    result = {
        "available_converged_levels": [r["level"] for r in usable],
        "assessed": False,
        "meaning": "mesh sensitivity of this external RANS setup; no extrapolated physical error or GCI",
    }
    if len(usable) < 2:
        return result
    a, b = usable[-2:]
    ra = a["comparison"]["paired_velocity_samples"]
    rb = b["comparison"]["paired_velocity_samples"]
    require(
        [(r["station_x_over_h"], r["sample_id"], r["y_over_h"]) for r in ra]
        == [(r["station_x_over_h"], r["sample_id"], r["y_over_h"]) for r in rb],
        "mesh_sensitivity.paired_velocity_samples",
        "sample identities differ between levels",
        "CFD-D001",
    )
    difference = max(
        abs(x["predicted_u_over_u_ref"] - y["predicted_u_over_u_ref"])
        for x, y in zip(ra, rb, strict=True)
    )
    xa = a["comparison"]["reattachment"]["predicted_x_over_h"]
    xb = b["comparison"]["reattachment"]["predicted_x_over_h"]
    result.update(
        assessed=True,
        levels=[a["level"], b["level"]],
        maximum_velocity_change_u_ref=difference,
        reattachment_change_h=abs(xa - xb)
        if xa is not None and xb is not None
        else None,
        velocity_change_target_max=0.05,
        velocity_stability_passed=difference <= 0.05,
    )
    return result


def workflow(foam_root, binary, output, preset="smoke", data=None, timeout_s=600):
    output = Path(output)
    backend.claim_directory(output)
    report = {
        "schema_version": "cfd-craft.external-tutorial/0.1",
        "preset": preset,
        "passed": False,
        "workflow_completed": False,
        "cavity": None,
        "backstep": [],
        "physical_qualification": {"passed": False, "status": "not_qualified"},
        "workflow_implementation_sha256": sha256(__file__),
    }
    stop = backend.Stop()
    previous = {
        s: signal.signal(s, stop.signal) for s in [signal.SIGINT, signal.SIGTERM]
    }
    try:
        backend.prepare("cavity", 1, 3000, output / "cavity-input")
        cavity = backend.run(
            output / "cavity-input",
            output / "openfoam-cavity",
            foam_root,
            timeout_s=timeout_s,
            stop=stop,
        )
        report["cavity"] = (
            cavity_comparison(binary, output / "openfoam-cavity", output)
            if cavity["passed"]
            else {"passed": False, "external": cavity}
        )
        if preset != "cavity" and not stop.cancelled:
            if data is None:
                data = output / "measurements"
                fetch(data)
            reference = load(data)
            report["reference_sha256"] = reference["raw_sha256"]
            for level in [1] if preset == "smoke" else [1, 2, 3]:
                if stop.cancelled:
                    break
                row = {"level": level, "comparison": None}
                report["backstep"].append(row)
                name = f"backstep-level{level}"
                backend.prepare(
                    "backstep", level, 6000, output / (name + "-input"), data
                )
                row["execution"] = backend.run(
                    output / (name + "-input"),
                    output / name,
                    foam_root,
                    timeout_s=timeout_s,
                    output_mib=512,
                    stop=stop,
                )
                try:
                    row["comparison"] = assess(output / name, data)
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    row["comparison"] = {
                        "passed": False,
                        "status": "invalid",
                        "error": backend.diagnostic(exc, "comparison"),
                    }
                save(output / (name + "-comparison"), row["comparison"])
                backend.write_json(output / "report.json", report)
            report["mesh_sensitivity"] = mesh_sensitivity(report["backstep"])
        report["workflow_completed"] = not stop.cancelled
        report["passed"] = (
            report["workflow_completed"]
            and report["cavity"]["passed"]
            and all(row["comparison"]["passed"] for row in report["backstep"])
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        report["error"] = backend.diagnostic(exc, "workflow")
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        backend.write_json(output / "report.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--foam-root", type=Path, required=True)
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/cfd-craft")
    ap.add_argument("--data", type=Path)
    ap.add_argument("--preset", choices=["cavity", "smoke", "study"], default="smoke")
    ap.add_argument("--timeout-s", type=float, default=600)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        report = workflow(
            args.foam_root,
            args.binary,
            args.output,
            args.preset,
            args.data,
            args.timeout_s,
        )
    except (ValueError, OSError) as exc:
        print(json.dumps({"passed": False, "error": backend.diagnostic(exc, "output")}))
        return 1
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "workflow_completed": report["workflow_completed"],
                "physical_qualification": report["physical_qualification"],
                "error": report.get("error"),
            },
            indent=2,
        )
    )
    if report["passed"]:
        return 0
    # Exit 2: the workflow recorded failed, unaccepted or cancelled evidence.
    # Exit 1: the workflow itself stopped with an error (runtime, data, I/O).
    return 1 if report.get("error") else 2


if __name__ == "__main__":
    raise SystemExit(main())
