#!/usr/bin/env python3
"""Summarize complete smoke and study runs into results/verified.json.

Each directory holds F1/, F2/ and F3/ with the summary.json that run.py
writes. Only complete, passed runs are recorded; the record keeps the numbers
that docs/evidence/optimization-lessons.md cites, not host paths or timings.
"""

import argparse
import json
from pathlib import Path

CHAPTERS = ["F1", "F2", "F3"]


def fail(field, message):
    raise ValueError(f"CFD-T001 optimization.record.{field}: {message}")


def f1(s):
    rows = []
    for arm in s["arms"]:
        row = dict(
            method=arm["method"],
            q=arm["q"],
            replay_objective=arm["replay_objective"],
            superposition_max_error=arm["superposition_max_error"],
            heldout_wind_objective=arm["heldout_wind_objective"],
        )
        if arm["method"] == "LP":
            row.update(
                objective=arm["objective"],
                reference_objective=arm["reference_objective"],
            )
        else:
            row.update(
                search_objective=arm["objective"],
                seed=arm["seed"],
                requested_evaluations=arm["requested_evaluations"],
            )
        if arm["method"] == "BiteOpt":
            row["actual_evaluations"] = arm["actual_evaluations"]
        if arm["method"] == "GP":
            row["native_work"] = arm["work"]
        rows.append(row)
    return dict(arms=rows)


def f2(s):
    rows = []
    for arm in s["arms"]:
        rows.append(
            dict(
                method=arm["method"],
                sensors=arm["sensors"],
                coverage=arm["coverage"],
                inversion=[
                    dict(
                        wind=i["wind"],
                        rank=i["noiseless"]["rank"],
                        condition_number=i["noiseless"]["condition_number"],
                        noiseless_relative_rate_error=i["noiseless"][
                            "relative_rate_error"
                        ],
                        noisy_relative_rate_error=i["noisy"]["relative_rate_error"],
                    )
                    for i in arm["inversion"]
                ],
            )
        )
    return dict(arms=rows, coverage_optimal_subsets=s["coverage_optimal_subsets"])


def f3(s):
    return dict(
        arms=[
            dict(
                method=a["method"],
                speed=a["training"]["speed"],
                coarse_objective=a["training"]["objective"],
                fine_objective=a["fine"]["objective"],
                relative_energy_grid_change=a["relative_energy_grid_change"],
                holdout_accepted=a["holdout"]["accepted"],
                supported_at_requested_fidelity=a["supported_at_requested_fidelity"],
            )
            for a in s["arms"]
        ],
        supported_designs=s["supported_designs"],
        distinct_designs=s["distinct_designs"],
        ranking_changed=s["ranking_changed"],
        search=s["search"],
    )


def chapter(folder, name):
    path = folder / name / "summary.json"
    if not path.is_file():
        fail(f"{name}.summary", f"{path.name} missing for {name}")
    s = json.loads(path.read_text())
    if s.get("state") != "complete" or s.get("passed") is not True:
        fail(f"{name}.state", f"{name} did not complete with passed checks")
    return s, dict(
        passed=True,
        checks=[c["name"] for c in s["checks"]],
        budgets=s["budgets"],
        work=s["work"],
        results={"F1": f1, "F2": f2, "F3": f3}[name](s),
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--smoke", type=Path, required=True)
    p.add_argument("--study", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    record = dict(
        schema_version="cfd-craft.optimization-record/0.1",
        scope="Executed teaching workflows, not optimizer-performance or physical-validation claims.",
        presets={},
    )
    versions = None
    for preset, folder in [("smoke", args.smoke), ("study", args.study)]:
        record["presets"][preset] = {}
        for name in CHAPTERS:
            summary, row = chapter(folder, name)
            if summary["preset"] != preset:
                fail(f"{name}.preset", f"{folder.name}/{name} is not a {preset} run")
            if versions is None:
                versions = summary["versions"]
            elif summary["versions"] != versions:
                fail(f"{name}.versions", "runs used different package versions")
            record["presets"][preset][name] = row
    record["versions"] = versions
    args.output.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
