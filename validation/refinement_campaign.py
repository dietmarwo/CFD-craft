#!/usr/bin/env python3
"""Bounded coarse-to-fine steady campaigns with separate acceptance verdicts.

The source is an accepted cold archive. Mapping happens once; subsequent stages
use the unchanged same-mesh eligibility gate. Two accepted grids permit a
descriptive observable comparison, not a GCI or physical qualification.
"""

import argparse
import hashlib
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
import openfoam_restart as restart
from audit_openfoam_mesh import audit
from backstep_data import load
from compare_backstep import assess, interpolate, samples

SCHEMA = "cfd-craft.refinement-campaign/0.1"


def require(ok, field, message):
    backend.require(ok, "refinement." + field, message, "CFD-X015")


def definition(run):
    return json.loads((Path(run) / "case/case.json").read_text())


def limits(iterations, max_stages, timeout_s, preparation_s, output_mib, memory_mib):
    for name, value, low, high in [
        ("iterations", iterations, 50, 20000),
        ("max_stages", max_stages, 1, 8),
        ("output_mib", output_mib, 1, 2048),
        ("memory_mib", memory_mib, 256, 8192),
    ]:
        require(
            type(value) is int and low <= value <= high, name, f"expected {low}..{high}"
        )
    for name, value in [("timeout_s", timeout_s), ("preparation_s", preparation_s)]:
        require(mapping.finite(value) and 0 < value <= 3600, name, "expected (0,3600]")
    try:
        backend.snapshot_interval(iterations)
    except ValueError as exc:
        require(False, "iterations", str(exc))
    return {
        "iterations_per_stage": iterations,
        "max_stages": max_stages,
        "wall_s_per_stage": timeout_s,
        "preparation_wall_s": preparation_s,
        "output_mib_per_stage": output_mib,
        "child_address_space_mib": memory_mib,
    }


def copy_archive(source, target, budget_bytes):
    """Copy the bytes of one stable, verified archive, including its seals."""
    before = backend.inventory(source)
    require(
        sum(e["bytes"] for e in before.values()) <= budget_bytes,
        "source.bytes",
        "source exceeds the declared copy budget",
    )
    target = Path(target)
    target.mkdir()
    for name, entry in before.items():
        blob = (Path(source) / name).read_bytes()
        require(
            len(blob) == entry["bytes"]
            and hashlib.sha256(blob).hexdigest() == entry["sha256"],
            "source.copy." + name,
            "source changed while copying",
        )
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    require(
        backend.inventory(source) == before,
        "source.inventory",
        "source changed during the snapshot",
    )
    require(
        backend.inventory(target) == before, "source.copy", "snapshot inventory differs"
    )
    return backend.verify(target)


def cavity_observation(run, record):
    values = samples(run, "centerline", ["y", "U_x", "U_y", "U_z"], record)
    reference = np.loadtxt(
        ROOT / "validation/ghia-re100-u.csv", delimiter=",", skiprows=1
    )
    predicted = np.interp(
        reference[:, 0], np.r_[0, values[:, 0], 1], np.r_[0, values[:, 1], 1]
    )
    error = float(np.max(abs(predicted - reference[:, 1])))
    return {
        "reference": "Ghia numerical reference, not an experiment",
        "reference_sha256": backend.sha256(ROOT / "validation/ghia-re100-u.csv"),
        "sample_positions": reference[:, 0].tolist(),
        "predicted_u_over_u_ref": predicted.tolist(),
        "maximum_error": error,
        "target_max": 0.06,
        "passed": error <= 0.06,
    }


def observation(run, data):
    record = backend.verify(run)
    found = {
        "execution_status": record["execution_status"],
        "numerically_accepted": record["passed"],
        "independent": None,
        "comparison": None,
        "accepted": False,
        "passed": False,
    }
    if record["numerical"] is None:
        return found
    independent = audit(run)
    comparison = (
        assess(run, data, independent=independent)
        if record["case"] == "backstep"
        else cavity_observation(run, record)
    )
    found.update(
        independent=independent,
        comparison=comparison,
        accepted=record["passed"] and independent["passed"],
        passed=record["passed"] and independent["passed"] and comparison["passed"],
    )
    return found


def paired_metrics(coarse, fine):
    """Compare accepted observations at identical physical sampling identities."""
    a, b = coarse["comparison"], fine["comparison"]
    if "paired_velocity_samples" not in a:
        require(
            a["sample_positions"] == b["sample_positions"],
            "pair.samples",
            "cavity positions differ",
        )
        delta = np.asarray(b["predicted_u_over_u_ref"]) - a["predicted_u_over_u_ref"]
        require(
            np.isfinite(delta).all(), "pair.samples", "nonfinite velocity differences"
        )
        return {"maximum_velocity_change_u_ref": float(np.max(abs(delta)))}
    first, second = a["paired_velocity_samples"], b["paired_velocity_samples"]
    keys = ("station_x_over_h", "sample_id", "y_over_h")
    identity = lambda row: tuple(row[k] for k in keys)
    require(
        len(first) > 0
        and len(first) == len(second)
        and len({identity(row) for row in first}) == len(first)
        and [identity(row) for row in first] == [identity(row) for row in second],
        "pair.samples",
        "missing, duplicate or different velocity sample identities",
    )
    delta = np.array(
        [
            y["predicted_u_over_u_ref"] - x["predicted_u_over_u_ref"]
            for x, y in zip(first, second, strict=True)
        ]
    )
    require(np.isfinite(delta).all(), "pair.samples", "nonfinite velocity differences")
    reattachment = [r["reattachment"]["predicted_x_over_h"] for r in [a, b]]
    return {
        "maximum_velocity_change_u_ref": float(np.max(abs(delta))),
        "rms_velocity_change_u_ref": float(np.sqrt(np.mean(delta**2))),
        "reattachment_change_h": abs(reattachment[1] - reattachment[0])
        if None not in reattachment
        else None,
        "coarse_reattachment_x_over_h": reattachment[0],
        "fine_reattachment_x_over_h": reattachment[1],
    }


def mesh_pair(source, fine, data):
    """A descriptive two-grid comparison, conditional on numerical/audit gates."""
    a, b = backend.verify(source), backend.verify(fine)
    da, db = definition(source), definition(fine)
    require(
        a["case"] == b["case"] and db["level"] == da["level"] + 1,
        "pair.level",
        "expected the next level of the same case",
    )
    for key in [
        "mesh_family",
        "solver_profile",
        "reynolds",
        "height_m",
        "reference_speed_m_s",
    ]:
        require(
            da["metadata"].get(key) == db["metadata"].get(key),
            "pair.metadata." + key,
            "physics or recipe differs",
        )
    for name in sorted(
        set(restart.fixed_names(a["case"]))
        - {"system/blockMeshDict", "system/sampleProfiles"}
    ):
        require(
            da["inputs"].get(name) == db["inputs"].get(name),
            "pair.inputs." + name,
            "physics or solver controls differ",
        )
    require(
        restart.identity(a["runtime"]) == restart.identity(b["runtime"]),
        "pair.runtime",
        "runtimes differ",
    )
    coarse, finer = observation(source, data), observation(fine, data)
    eligible = coarse["accepted"] and finer["accepted"]
    result = {
        "status": "evaluated" if eligible else "not_assessed",
        "assessed": eligible,
        "passed": False,
        "levels": [da["level"], db["level"]],
        "coarse": coarse,
        "fine": finer,
        "meaning": "two-grid observable sensitivity; passed means both original numerical/audit/reference gates, not mesh independence or a GCI",
        "physical_qualification": False,
        "grid_convergence_estimate": "not_assessed: two grids only",
    }
    if not eligible:
        result["reason"] = (
            "both final numerical assessments and independent audits must pass"
        )
        return result
    result.update(paired_metrics(coarse, finer))
    result["passed"] = coarse["passed"] and finer["passed"]
    if a["case"] == "backstep":
        positions = np.array([r[0] for r in load(data)["cf"] if r[0] > 0])
        curves = []
        for label, found in [("coarse", coarse), ("fine", finer)]:
            curve = found["comparison"]["friction_curve"]
            curves.append(
                interpolate(
                    np.array([r["x_over_h"] for r in curve]),
                    np.array([r["cf"] for r in curve]),
                    positions,
                    "refinement.pair." + label + ".cf",
                )
            )
        result["maximum_cf_change_at_measured_positions"] = float(
            np.max(abs(curves[1] - curves[0]))
        )
        result["cf_comparison_x_over_h"] = positions.tolist()
    return result


def lineage(source, runs):
    """Bind every checked receipt to its retained, verified parent archive."""
    parent = backend.verify(source)
    previous = Path(source)
    coarse = definition(source)
    total = 0
    for number, run in enumerate(runs, 1):
        record = backend.verify(run)
        job = definition(run)
        field = f"stages[{number}].parent"
        require(
            record["case"] == parent["case"] and job["level"] == coarse["level"] + 1,
            field,
            "wrong case or fine level",
        )
        if number == 1:
            state = job.get("mesh_initialization") or {}
            require(
                state.get("source_manifest_sha256")
                == backend.sha256(previous / "manifest.json")
                and state.get("source_case_sha256") == parent["case_sha256"]
                and state.get("source_iterations") == parent["numerical"]["iterations"],
                field,
                "mapping does not bind the retained coarse parent",
            )
        else:
            state = job.get("initial_state") or {}
            require(
                state.get("source_manifest_sha256")
                == backend.sha256(previous / "manifest.json")
                and state.get("source_case_sha256") == parent["case_sha256"]
                and state.get("source_completed_iterations") == total
                and state.get("source_time")
                == parent["numerical"]["final_time_directory"]
                and state.get("source_numerical_passed") == parent["passed"]
                and state.get("source_runtime_sha256")
                == restart.identity(parent["runtime"]),
                field,
                "continuation parent identity, time, runtime or fine work differs",
            )
            entries = json.loads((previous / "manifest.json").read_text())["files"]
            for name, entry in state["source_fields"].items():
                require(
                    entry == entries[f"case/{state['source_time']}/{name}"],
                    field + "." + name,
                    "parent field identity differs",
                )
            for name, entry in state["source_mesh"].items():
                require(
                    entry == entries["case/constant/polyMesh/" + name],
                    field + ".mesh." + name,
                    "parent mesh identity differs",
                )
        total += (record["numerical"] or {}).get("iterations", 0)
        previous, parent = Path(run), record
    return total


def checkpoint(output, report, label):
    runs = [
        output / r["run_directory"]
        for r in report["stages"]
        if r.get("execution") is not None
    ]
    try:
        total = lineage(output / "source", runs)
        checked = [
            {
                "directory": str(p.relative_to(output)),
                "manifest_sha256": backend.sha256(p / "manifest.json"),
            }
            for p in [output / "source", *runs]
        ]
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        require(False, "archives." + label, backend.diagnostic(exc, "archive"))
    report["completed_fine_iterations"] = total
    report["archive_checkpoints"].append(
        {"label": label, "archives": checked, "passed": True}
    )
    backend.write_json(output / "report.json", report)


def exit_code(report):
    return 1 if report.get("error") else 0 if report.get("passed") else 2


def campaign(
    source,
    foam_root,
    output,
    data=None,
    iterations=3000,
    max_stages=4,
    timeout_s=3500,
    preparation_s=900,
    output_mib=1024,
    memory_mib=4096,
):
    declared = limits(
        iterations, max_stages, timeout_s, preparation_s, output_mib, memory_mib
    )
    source, output = Path(source), Path(output)
    parent = backend.verify(source)
    original = definition(source)
    require(
        parent["passed"] and parent["execution_status"] == "completed",
        "source.acceptance",
        "accepted completed coarse source required",
    )
    require(
        not (original.get("initial_state") or original.get("mesh_initialization")),
        "source.initialization",
        "cold-generated coarse source required",
    )
    require(original["level"] in [1, 2], "source.level", "source level must be 1 or 2")
    require(
        parent["case"] != "backstep" or data is not None,
        "data",
        "verified measurements required for the backstep",
    )
    if parent["case"] == "backstep":
        require(
            original["metadata"].get("mesh_family") == "wall-resolved"
            and original["metadata"].get("solver_profile") == "simplec",
            "source.recipe",
            "wall-resolved/simplec reference source required",
        )
        load(data)
    require(
        audit(source)["passed"], "source.audit", "coarse independent audit must pass"
    )
    plan = {
        "source_manifest_sha256": backend.sha256(source / "manifest.json"),
        "source_case_sha256": parent["case_sha256"],
        "case": parent["case"],
        "source_level": original["level"],
        "target_level": original["level"] + 1,
        "limits": declared,
        "implementation_sha256": {
            p.name: backend.sha256(p)
            for p in [
                Path(__file__),
                ROOT / "integrations/openfoam_backend.py",
                ROOT / "integrations/openfoam_cases.py",
                ROOT / "integrations/openfoam_mapping.py",
                ROOT / "integrations/openfoam_restart.py",
                ROOT / "validation/audit_openfoam_mesh.py",
                ROOT / "validation/compare_backstep.py",
                ROOT / "validation/backstep_data.py",
            ]
        },
    }
    backend.claim_directory(output)
    began = time.monotonic()
    report = {
        "schema_version": SCHEMA,
        "plan": plan,
        "plan_sha256": restart.identity(plan),
        "phase": "snapshotting_source",
        "passed": False,
        "workflow_completed": False,
        "physical_qualification": False,
        "stages": [],
        "archive_checkpoints": [],
        "completed_fine_iterations": 0,
        "source_iterations": parent["numerical"]["iterations"],
        "source_recorded_wall_s": parent.get("wall_s"),
        "source_work_meaning": "recorded coarse work, additional to fine work; reused source wall time is not new campaign wall time",
    }
    backend.write_json(output / "report.json", report)
    stop = backend.Stop()
    previous = {
        s: signal.signal(s, stop.signal) for s in [signal.SIGINT, signal.SIGTERM]
    }
    try:
        copy_archive(source, output / "source", output_mib * 1024**2)
        report["coarse_observation"] = observation(output / "source", data)
        checkpoint(output, report, "source_snapshot")
        backend.require(not stop.cancelled, "execution.cancel", "cancelled", "CFD-X008")
        report["phase"] = "preparing_mapping"
        backend.write_json(output / "report.json", report)
        started = time.monotonic()
        prepared = mapping.prepare(
            output / "source",
            plan["target_level"],
            iterations,
            output / "mapped-input",
            foam_root,
            data,
            timeout_s=preparation_s,
            output_mib=output_mib,
            memory_mib=memory_mib,
            stop=stop,
        )
        report["preparation_wall_s"] = time.monotonic() - started
        report["mesh_initialization"] = prepared["mesh_initialization"]
        run = None
        reason = "stage_limit"
        for number in range(1, max_stages + 1):
            if stop.cancelled:
                reason = "cancelled"
                break
            if number == 1:
                input_case = output / "mapped-input"
            else:
                input_case = output / f"stage-{number:02d}-input"
                try:
                    restart.prepare(run, iterations, input_case)
                except restart.IneligibleSource as exc:
                    report["source_rejection"] = str(exc)
                    reason = "source_ineligible"
                    break
            name = f"stage-{number:02d}"
            run = output / name
            row = {"stage": number, "run_directory": name, "execution": None}
            report["stages"].append(row)
            report["phase"] = "solving"
            backend.write_json(output / "report.json", report)
            row["execution"] = backend.run(
                input_case,
                run,
                foam_root,
                timeout_s=timeout_s,
                output_mib=output_mib,
                memory_mib=memory_mib,
                stop=stop,
            )
            backend.write_json(output / "report.json", report)
            checkpoint(output, report, f"stage_{number}_returned")
            row["observation"] = observation(run, data)
            backend.write_json(output / "report.json", report)
            record = row["execution"]
            numerical = record["numerical"]
            if record["execution_status"] != "completed":
                reason = "execution_" + record["execution_status"]
                break
            if numerical is None:
                reason = "no_final_field"
                break
            if numerical["solver_reported_convergence"]:
                if row["observation"]["passed"]:
                    reason = "accepted"
                elif not record["passed"]:
                    reason = "converged_without_numerical_acceptance"
                elif not row["observation"]["accepted"]:
                    reason = "converged_without_independent_acceptance"
                else:
                    reason = "measurement_screen_failed"
                break
        report["stop_reason"] = reason
        if run is not None:
            report["mesh_sensitivity"] = mesh_pair(output / "source", run, data)
            report["passed"] = report["mesh_sensitivity"]["passed"]
        report["workflow_completed"] = not stop.cancelled
        checkpoint(output, report, "final_collection")
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        if stop.cancelled:
            report["stop_reason"] = "cancelled"
            report["cancellation_diagnostic"] = backend.diagnostic(exc, "refinement")
        else:
            report["error"] = backend.diagnostic(exc, "refinement")
            report["stop_reason"] = "workflow_error"
        report["passed"] = False
        report["workflow_completed"] = False
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)
        if stop.cancelled:
            report["passed"] = False
            report["workflow_completed"] = False
            report["stop_reason"] = "cancelled"
        report["phase"] = "finished"
        report["total_wall_s"] = time.monotonic() - began
        backend.write_json(output / "report.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--foam-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--data", type=Path)
    ap.add_argument("--iterations", type=int, default=3000)
    ap.add_argument("--max-stages", type=int, default=4)
    ap.add_argument("--timeout-s", type=float, default=3500)
    ap.add_argument("--preparation-s", type=float, default=900)
    ap.add_argument("--output-mib", type=int, default=1024)
    ap.add_argument("--memory-mib", type=int, default=4096)
    args = ap.parse_args()
    try:
        report = campaign(
            args.source,
            args.foam_root,
            args.output,
            args.data,
            args.iterations,
            args.max_stages,
            args.timeout_s,
            args.preparation_s,
            args.output_mib,
            args.memory_mib,
        )
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        report = {"passed": False, "error": backend.diagnostic(exc, "refinement")}
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in [
                    "passed",
                    "workflow_completed",
                    "stop_reason",
                    "completed_fine_iterations",
                    "error",
                ]
            },
            indent=2,
        )
    )
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
