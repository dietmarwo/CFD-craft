#!/usr/bin/env python3
"""Summarize a retained urban campaign, including failures and field equivalence."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from check_fields import check


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accepted_summary(summary, audit_passed):
    return (
        summary["termination"] == "completed"
        and summary["assessment"] == "steady_discrete_solution"
        and bool(summary["checks"])
        and all(item["passed"] for item in summary["checks"])
        and audit_passed
    )


def paired_case_fidelity(first, second):
    left = json.loads(json.dumps(first))
    right = json.loads(json.dumps(second))
    old = left["numerics"].pop("pressure_preconditioner", "ic0")
    new = right["numerics"].pop("pressure_preconditioner", "ic0")
    return old == "ic0" and new == "multigrid" and left == right


def summarize(root):
    records = []
    names = [
        "block-4m-ic0",
        "block-4m-multigrid",
        "block-2m-ic0",
        "block-2m-multigrid",
        "canyon-27k-ic0",
        "canyon-27k-multigrid",
        "canyon-93k-replay-ic0",
        "canyon-93k-replay-multigrid",
        "rotated-canyon-0-0",
        "rotated-canyon-0-45",
        "rotated-canyon-1-0",
        "rotated-canyon-1-45",
    ]
    for name in names:
        directory = root / name
        archive = (
            directory / "profile/run"
            if (directory / "profile/run").exists()
            else directory / "run"
        )
        row = dict(id=name, accepted=False)
        path = archive / "summary.json"
        if path.exists():
            s = json.loads(path.read_text())
            p = archive.parent / "profile.json"
            phases = json.loads(p.read_text())["timing"]["phases"] if p.exists() else {}
            try:
                audit = check(archive)
                passed = audit["passed"]
            except (ValueError, OSError, KeyError) as exc:
                audit = dict(passed=False, error=str(exc))
                passed = False
            (directory / "final-independent-check.json").write_text(
                json.dumps(audit, indent=2) + "\n"
            )
            row.update(
                termination=s["termination"],
                assessment=s["assessment"],
                steps=s["steps"],
                elapsed_s=s["elapsed_s"],
                source_sha256=s["source_sha256"],
                case_sha256=s["case_sha256"],
                physics_sha256=s["physics_sha256"],
                fields_sha256=digest(archive / "fields.json"),
                pressure_iterations=s["pressure_iterations"],
                phase_exclusive_s={k: v["exclusive_s"] for k, v in phases.items()},
                independent_check=audit,
                accepted=accepted_summary(s, passed),
            )
            if phases and "pressure_multigrid_setup" in phases:
                row["multigrid_setup_s"] = phases["pressure_multigrid_setup"][
                    "exclusive_s"
                ]
                row["multigrid_work"] = phases["pressure_solve"].get("multigrid")
        else:
            row["error"] = (
                "no completed native archive; rejected or interrupted row retained"
            )
            stdout = root / (name + ".stdout")
            if stdout.exists():
                try:
                    row["native_check"] = json.loads(stdout.read_text())
                except ValueError:
                    pass
        records.append(row)
    pairs = []
    for a, b in [
        ("block-4m-ic0", "block-4m-multigrid"),
        ("canyon-27k-ic0", "canyon-27k-multigrid"),
        ("canyon-93k-replay-ic0", "canyon-93k-replay-multigrid"),
    ]:
        ra, rb = [next(r for r in records if r["id"] == name) for name in (a, b)]

        def archive(name):
            d = root / name
            return d / "profile/run" if (d / "profile/run").exists() else d / "run"

        pair = dict(
            ic0=a,
            multigrid=b,
            equivalence_tolerances=dict(
                velocity_max_absolute=1e-4,
                pressure_max_absolute=1e-3,
                receptor_relative=0.01,
            ),
            both_accepted=ra["accepted"] and rb["accepted"],
        )
        cases = [json.loads((archive(n) / "case.json").read_text()) for n in (a, b)]
        pair["case_fidelity_passed"] = paired_case_fidelity(*cases)
        if not pair["case_fidelity_passed"]:
            pair["error"] = (
                "consumed cases differ beyond the declared pressure preconditioner; no ratio"
            )
            pairs.append(pair)
            continue
        if all((archive(n) / "fields.json").exists() for n in (a, b)):
            fields = [
                json.loads((archive(n) / "fields.json").read_text()) for n in (a, b)
            ]
            summaries = [
                json.loads((archive(n) / "summary.json").read_text()) for n in (a, b)
            ]
            pair["velocity_max_absolute_difference"] = float(
                np.max(
                    np.abs(
                        np.array(fields[0]["velocity"])
                        - np.array(fields[1]["velocity"])
                    )
                )
            )
            pair["pressure_max_absolute_difference"] = float(
                np.max(
                    np.abs(
                        np.array(fields[0]["pressure"])
                        - np.array(fields[1]["pressure"])
                    )
                )
            )
            differences = []
            for x, y in zip(
                summaries[0]["constituents"], summaries[1]["constituents"], strict=True
            ):
                for sensor in x["receptors_kg_m3"]:
                    v, w = x["receptors_kg_m3"][sensor], y["receptors_kg_m3"][sensor]
                    differences.append(abs(v - w) / max(abs(v), abs(w), 1e-300))
            pair["receptor_max_relative_difference"] = max(differences, default=0.0)
            pair["fields_equivalent"] = (
                pair["velocity_max_absolute_difference"] <= 1e-4
                and pair["pressure_max_absolute_difference"] <= 1e-3
                and pair["receptor_max_relative_difference"] <= 0.01
            )
            if pair["both_accepted"] and pair["fields_equivalent"]:
                pair["ic0_over_multigrid_elapsed_ratio"] = (
                    ra["elapsed_s"] / rb["elapsed_s"]
                )
                pair["coupled_gain_observed"] = rb["elapsed_s"] < ra["elapsed_s"]
        pairs.append(pair)
    ensembles = {}
    for name in ["district-ensemble", "runner-ensemble", "runner-ensemble-v2"]:
        path = root / name / "report.json"
        if path.exists():
            ensembles[name] = json.loads(path.read_text())
    fine = root / "district-fine-sensitivity/result.json"
    fine_row = json.loads(fine.read_text()) if fine.exists() else None
    provenance = root / "district-provenance.json"
    if fine_row is not None and provenance.exists():
        angle = json.loads(provenance.read_text())["rotation_deg"]
        original = fine_row.get("geographic_direction_deg_from")
        corrected = (fine_row["direction_deg_from"] - angle) % 360
        fine_row["geographic_direction_deg_from"] = corrected
        if original != corrected:
            fine_row["metadata_correction"] = {
                "recorded_geographic_direction_deg_from": original,
                "corrected_geographic_direction_deg_from": corrected,
                "reason": "fine job omitted the maprotation metadata; consumed case is model-local270, same as coarse270; native inputs/fields and raw worker result retained unchanged",
            }
    return dict(
        schema_version="cfd-craft.urban-evidence/1",
        base_commit="7d8d70a864383e92f431d8afdacd15864e6c1c54",
        records=records,
        pairs=pairs,
        ensembles=ensembles,
        fine_sensitivity=fine_row,
        timing_scope="one cold run per method on a shared host; setup and exclusive phases recorded; not a repeated speed ranking",
        experimental_validation="not_validated",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.evidence)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            dict(records=len(report["records"]), pairs=report["pairs"]), indent=2
        )
    )


if __name__ == "__main__":
    sys.exit(main())
