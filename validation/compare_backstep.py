#!/usr/bin/env python3
"""Compare an actual external archive with frozen physical measurements.

Even a passed development screen does not remove the declared qualification
blockers. Reattachment and each velocity station are evaluated separately.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
import openfoam_backend as backend
from backstep_data import FILES, load, require, sha256

PROTOCOL = ROOT / "validation/protocols/backstep-v1.json"
PROTOCOL_SHA256 = "5ba3204425ff0ee1b717a9d3a61a876d4d0420b5e98480658937b0dcfba0ba93"


def samples(run, name, columns, report=None):
    report = report if report is not None else backend.verify(run)
    require(
        report["numerical"] is not None, "archive.numerical", "missing final solution"
    )
    latest = report["numerical"]["final_time_directory"]
    path = Path(run) / "case/postProcessing/sampleProfiles" / latest / (name + ".xy")
    header = path.read_text().splitlines()[0].lstrip("#").split()
    require(header == columns, f"samples.{name}.columns", "wrong field order")
    values = np.loadtxt(path, ndmin=2)
    require(values.shape[1] == len(columns), f"samples.{name}", "wrong column count")
    require(np.isfinite(values).all(), f"samples.{name}", "nonfinite result")
    require(
        np.all(np.diff(values[:, 0]) > 0), f"samples.{name}", "positions must increase"
    )
    return values


def interpolate(x, y, target, field):
    require(len(x) == len(y) and len(x) >= 2, field, "wrong shape")
    require(np.isfinite(x).all() and np.isfinite(y).all(), field, "nonfinite values")
    require(np.all(np.diff(x) > 0), field, "positions must increase")
    require(
        np.min(target) >= x[0] and np.max(target) <= x[-1],
        field,
        "extrapolation forbidden",
    )
    return np.interp(target, x, y)


def rmse(error):
    return float(np.sqrt(np.mean(error**2))) if len(error) else None


def no_step_baseline(inlet, y):
    """A predictor that ignores the step: the measured x/H=-4 profile above the
    step height and zero below it, held constant beyond the measured range."""
    inlet = np.array(inlet)
    return np.where(y < 1.0, 0.0, np.interp(y, inlet[:, 1], inlet[:, 2]))


def first_cell_y_plus(metadata, x, stress):
    """y+ of the first lower-wall cell centre, from the sampled wall shear stress."""
    height = metadata.get("lower_wall_first_cell_height_h")
    if height is None:
        return None
    nu = metadata["reference_speed_m_s"] * metadata["height_m"] / metadata["reynolds"]
    y_plus = np.sqrt(np.hypot(stress[:, 0], stress[:, 1])) * 0.5 * height / nu
    regions = {"scored_1_to_12": (1, 12), "recovery_12_to_40": (12, 40)}
    result = {
        "first_cell_centre_height_h": 0.5 * height,
        "wall_treatment": metadata.get("turbulence_package"),
        "meaning": "wall-resolved candidate: compare the actual first-cell y+ with one; all-wall distances are checked independently"
        if metadata.get("mesh_family") == "wall-resolved"
        else "k-based wall functions switch near y+ 11; a first cell in the buffer layer (about 5 < y+ < 30) makes Cf and reattachment depend on the wall treatment",
    }
    for name, (lo, hi) in regions.items():
        selected = y_plus[(x > lo) & (x < hi)]
        result[name] = {
            "median": float(np.median(selected)),
            "minimum": float(selected.min()),
            "maximum": float(selected.max()),
        }
    return result


def measurement_screen(numerical_passed, agreement):
    """Metrics of a solve that missed its numerical gate describe one iterate, not a
    solution: they are reported, but they do not make a measurement screen."""
    return {
        "numerical_passed": numerical_passed,
        "measurement_screen": "evaluated"
        if numerical_passed
        else "not_assessed: the numerical gate failed; the metrics describe the final iterate only",
        "measurement_screen_passed": agreement if numerical_passed else None,
        "passed": numerical_passed and agreement,
    }


def crossing(x, cf):
    crossings = []
    for i in range(len(x) - 1):
        if 1 < x[i] < 12 and cf[i] < 0 <= cf[i + 1]:
            crossings.append(
                float(x[i] - cf[i] * (x[i + 1] - x[i]) / (cf[i + 1] - cf[i]))
            )
    return crossings[-1] if crossings else None, crossings


def assess(run, data, protocol=PROTOCOL, independent=None):
    """`independent` is this archive's audit when the caller has already run it."""
    protocol = Path(protocol)
    require(
        sha256(protocol) == PROTOCOL_SHA256,
        "protocol.sha256",
        "frozen protocol changed",
    )
    p = json.loads(protocol.read_text())
    require(
        p == json.loads(PROTOCOL.read_text()),
        "protocol",
        "does not match the frozen project protocol",
    )
    require(p["raw_sha256"] == FILES, "protocol.raw_sha256", "wrong reference")
    reference = load(data)
    result = backend.verify(run)
    require(result["case"] == "backstep", "archive.case", "wrong physical case")
    require(
        result["case_metadata"]["reference_sha256"] == FILES,
        "archive.reference",
        "wrong input data",
    )
    # Recompute numerical checks from returned phi and the actual solver log.
    numerical = backend.numerical_assessment(
        Path(run) / "case", (Path(run) / "solve.log").read_text(), "backstep"
    )
    require(
        numerical == result["numerical"],
        "archive.numerical",
        "summary does not match fields/log",
    )
    metrics = {}
    paired = []
    for station in p["evaluation_stations_x_over_h"]:
        values = samples(
            run,
            f"station{station}",
            [
                "y",
                "U_x",
                "U_y",
                "U_z",
                "wallShearStress_x",
                "wallShearStress_y",
                "wallShearStress_z",
            ],
            result,
        )
        observed = np.array(reference["profiles"][station])
        require(
            len(values) == len(observed),
            f"station[{station}].samples",
            "missing or extra positions",
        )
        require(
            np.allclose(values[:, 0], observed[:, 1], atol=1e-12, rtol=0),
            f"station[{station}].y_over_h",
            "sample identity mismatch",
        )
        error = values[:, 1] - observed[:, 2]
        y = observed[:, 1]
        station_rmse = rmse(error)
        metrics[str(station)] = {
            "samples": len(values),
            "rmse_u_ref": station_rmse,
            "maximum_absolute_error_u_ref": float(max(abs(error))),
            "target_rmse_max": p["profile_rmse_max_u_ref"],
            "within_target": station_rmse <= p["profile_rmse_max_u_ref"],
            # The outer flow is easy to match; the shear layer is not.
            "rmse_u_ref_below_y2": rmse(error[y < 2]),
            "rmse_u_ref_from_y2": rmse(error[y >= 2]),
            "baseline_no_step_rmse_u_ref": rmse(
                no_step_baseline(reference["profiles"][-4], y) - observed[:, 2]
            ),
        }
        for observed_row, predicted_row in zip(observed, values, strict=True):
            paired.append(
                {
                    "station_x_over_h": station,
                    "sample_id": int(observed_row[0]),
                    "y_over_h": float(observed_row[1]),
                    "observed_u_over_u_ref": float(observed_row[2]),
                    "predicted_u_over_u_ref": float(predicted_row[1]),
                }
            )
    values = samples(
        run,
        "friction",
        [
            "x",
            "U_x",
            "U_y",
            "U_z",
            "wallShearStress_x",
            "wallShearStress_y",
            "wallShearStress_z",
        ],
        result,
    )
    # OpenFOAM stores kinematic traction into the fluid. For an attached positive
    # streamwise boundary layer the wall's traction is negative, while Cf is positive.
    cf = -2 * values[:, 4]
    observed = np.array([row for row in reference["cf"] if row[0] > 0])
    predicted = interpolate(values[:, 0], cf, observed[:, 0], "cf.x_over_h")
    cf_rmse = rmse(predicted - observed[:, 1])
    reattach, crossings = crossing(values[:, 0], cf)
    reattach_error = (
        abs(reattach - p["reattachment_x_over_h"]) if reattach is not None else None
    )
    friction = {
        "samples": len(observed),
        "excluded_upstream_rows": len(reference["cf"]) - len(observed),
        "rmse": cf_rmse,
        "target_rmse_max": p["lower_wall_cf_rmse_max"],
        "within_target": cf_rmse <= p["lower_wall_cf_rmse_max"],
        "baseline_zero_cf_rmse": rmse(observed[:, 1]),
        "reported_measurement_error_not_used_as_a_95pct_interval": observed[
            :, 2
        ].tolist(),
    }
    reattachment = {
        "predicted_x_over_h": reattach,
        "all_negative_to_positive_crossings": crossings,
        "observed_x_over_h": p["reattachment_x_over_h"],
        "reported_experimental_uncertainty_h": p["reattachment_reported_uncertainty_h"],
        "absolute_error_h": reattach_error,
        "target_absolute_error_max_h": p["reattachment_absolute_error_max_h"],
        "within_target": reattach_error is not None
        and reattach_error <= p["reattachment_absolute_error_max_h"],
    }
    agreement = (
        all(m["within_target"] for m in metrics.values())
        and friction["within_target"]
        and reattachment["within_target"]
    )

    if result["case_metadata"].get("mesh_family") != "wall-resolved":
        independent = None
    elif independent is None:
        from audit_openfoam_mesh import audit

        independent = audit(run)
    require(
        independent is None
        or independent.get("run_manifest_sha256")
        == sha256(Path(run) / "manifest.json"),
        "independent_mesh_audit.run_manifest_sha256",
        "the audit belongs to another archive",
    )
    prerequisites = numerical["passed"] and (
        independent is None or independent["passed"]
    )
    screen = measurement_screen(prerequisites, agreement)
    screen["numerical_passed"] = numerical["passed"]
    screen["measurement_prerequisites_passed"] = prerequisites
    if numerical["passed"] and not prerequisites:
        screen["measurement_screen"] = (
            "not_assessed: independent local-continuity/wall-resolution audit failed"
        )

    return {
        "schema_version": "cfd-craft.backstep-comparison/0.1",
        "status": "evaluated",
        "reference": reference["reference"],
        "protocol_sha256": sha256(protocol),
        "reference_sha256": reference["raw_sha256"],
        "implementation_sha256": {
            path.name: sha256(path)
            for path in [
                Path(__file__),
                ROOT / "validation/backstep_data.py",
                ROOT / "integrations/openfoam_backend.py",
                ROOT / "validation/audit_openfoam_mesh.py",
            ]
        },
        "run_manifest_sha256": sha256(Path(run) / "manifest.json"),
        **screen,
        "independent_mesh_audit": independent,
        "residual_trend": numerical["residual_trend"],
        "near_wall_resolution": first_cell_y_plus(
            result["case_metadata"], values[:, 0], values[:, 4:6]
        ),
        "profiles": metrics,
        "skin_friction": friction,
        "reattachment": reattachment,
        "paired_velocity_samples": paired,
        "friction_curve": [
            {"x_over_h": float(x), "cf": float(y)}
            for x, y in zip(values[:, 0], cf, strict=True)
        ],
        "physical_qualification": {
            "passed": False,
            "status": "preliminary_comparison",
            "blockers": p["qualification_blockers"],
        },
        "interpretation": p["interpretation"],
    }


def save(output, result):
    output = Path(output)
    backend.claim_directory(output)
    backend.write_json(output / "report.json", result)
    rows = result.get("paired_velocity_samples", [])
    if rows:
        with (output / "paired-velocity.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    if result.get("status") != "evaluated":
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 4, figsize=(10, 4), sharey=True)
        for ax, station in zip(axes, [1, 4, 6, 10], strict=True):
            selected = [r for r in rows if r["station_x_over_h"] == station]
            ax.plot(
                [r["predicted_u_over_u_ref"] for r in selected],
                [r["y_over_h"] for r in selected],
                label="OpenFOAM",
            )
            ax.plot(
                [r["observed_u_over_u_ref"] for r in selected],
                [r["y_over_h"] for r in selected],
                "x",
                label="experiment",
            )
            ax.set(xlabel="U/Uref", title=f"x/H={station}")
        axes[0].set_ylabel("y/H")
        axes[-1].legend()
        fig.suptitle("Driver--Seegmiller: preliminary comparison; qualification open")
        fig.tight_layout()
        fig.savefig(output / "profiles.png", dpi=140)
        plt.close(fig)
    except Exception as exc:
        result["figure_error"] = str(exc)
        backend.write_json(output / "report.json", result)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--protocol", type=Path, default=PROTOCOL)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        result = assess(args.run, args.data, args.protocol)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result = {
            "status": "invalid",
            "passed": False,
            "error": backend.diagnostic(exc, "comparison"),
        }
    try:
        save(args.output, result)
    except (ValueError, OSError) as exc:
        print(json.dumps({"passed": False, "error": backend.diagnostic(exc, "output")}))
        return 1
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ["paired_velocity_samples", "friction_curve"]
            },
            indent=2,
        )
    )
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
