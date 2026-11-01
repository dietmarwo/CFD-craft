#!/usr/bin/env python3
"""Stage V: native self-convergence and default byte-identity controls.

Consume a real shared-grid accuracy sweep, run a separately budgeted native
96² reference, and compare canonical artifacts with an unmodified-main build.
The reference is descriptive evidence, never a cost-at-target timed sample.
"""

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess

import numpy as np

import accuracy_sweep as sweep
import compare_backends as cmp
from momentum_accuracy import require

ARTIFACTS = [
    "fields.json",
    "checkpoint.json",
    "probes.csv",
    "geometry.json",
    "case.json",
]


def compare_defaults(baseline, candidate):
    results = {}
    for name in ARTIFACTS:
        before, after = (
            Path(baseline, name).read_bytes(),
            Path(candidate, name).read_bytes(),
        )
        require(before == after, "defaults." + name, "canonical artifacts differ")
        results[name] = hashlib.sha256(after).hexdigest()
    a = json.loads(Path(baseline, "summary.json").read_text())
    b = json.loads(Path(candidate, "summary.json").read_text())
    for field in ["steps", "pressure_iterations", "assessment", "termination"]:
        require(a[field] == b[field], "defaults." + field, "work or assessment differs")
    return dict(
        passed=True,
        sha256=results,
        steps=b["steps"],
        pressure_iterations=b["pressure_iterations"],
        assessment=b["assessment"],
    )


def default_controls(binary, baseline_binary, output):
    rows = []
    for label, filename in [
        ("cavity", "cases/verification/lid-cavity.json"),
        ("transient", "cases/verification/poiseuille.json"),
        ("masked-canyon", "cases/canyon/wh1-wind270.json"),
    ]:
        case = json.loads((cmp.ROOT / filename).read_text())
        case["run"]["threads"] = 1
        if label == "cavity":
            case["run"]["mode"] = "steady"
            case["run"]["wall_time_limit_s"] = 180.0
        elif label == "transient":
            case["run"]["end_time_s"] = 0.01
        else:
            case["run"]["max_steps"] = 3
        for producer, executable in [
            ("baseline", baseline_binary),
            ("candidate", binary),
        ]:
            run = cmp.run_case(
                executable, copy.deepcopy(case), output / f"{label}-{producer}"
            )
            require(
                run["returncode"] in (0, 2) and run["independent"]["passed"],
                "defaults." + label,
                "control execution or audit failed",
            )
        row = compare_defaults(
            output / f"{label}-baseline", output / f"{label}-candidate"
        )
        rows.append(dict(case=label, **row))
    return rows


def reference(binary, output, native_numerics=None):
    limits = dict(
        native_wall_s=1800,
        native_max_steps=80000,
        native_pressure_preconditioner="multigrid",
    )
    # The self-convergence reference uses the same scheme as the sweep it serves.
    if native_numerics:
        limits["native_numerics"] = sweep.native_numerics_selection(native_numerics)
    row = sweep.run_method(
        "native-steady", 96, output / "native-96", binary, None, limits
    )
    cmp.backend.write_json(output / "reference.json", dict(plan=limits, row=row))
    return row


def self_convergence(sweep_directory, reference_directory):
    campaign = json.loads(Path(sweep_directory, "report.json").read_text())
    ref = json.loads(Path(reference_directory, "reference.json").read_text())["row"]
    if not ref["accepted"]:
        return dict(
            available=False,
            reason="96² reference did not reach unchanged gates",
            reference=ref,
        )
    ref_run = Path(reference_directory, ref["run_directory"], "run")
    # Recheck the actual final fields; do not substitute a cached sampled array.
    require(
        sweep.audit(ref_run)["passed"],
        "self.reference",
        "reference archive/fields audit failed",
    )
    ref_case = json.loads((ref_run / "case.json").read_text())
    ref_fields = json.loads((ref_run / "fields.json").read_text())
    # A same-scheme reference: the sweep and the reference select the same numerics.
    planned = campaign["plan"]["limits"].get("native_numerics", {})
    require(
        all(ref_case["numerics"].get(k) == v for k, v in planned.items())
        and all(
            ref_case["numerics"].get(k) is None
            for k in sweep.NATIVE_NUMERICS
            if k not in planned
        ),
        "self.scheme",
        "reference numerics differ from the sweep's",
    )
    stations = np.linspace(0.0, 1.0, 257)
    ref_profile = np.interp(stations, *cmp.native_centerline(ref_case, ref_fields))
    rows = []
    for grid in campaign["plan"]["shared_grids"]:
        selected = [
            r
            for r in campaign["rows"]
            if r["method"] == "native-steady" and r["grid"] == grid and not r["warmup"]
        ]
        if not selected or not all(r["accepted"] for r in selected):
            rows.append(dict(grid=grid, accepted=False))
            continue
        run = Path(sweep_directory, selected[0]["run_directory"], "run")
        require(
            sweep.audit(run)["passed"], "self.grid", "grid archive/fields audit failed"
        )
        case = json.loads((run / "case.json").read_text())
        fields = json.loads((run / "fields.json").read_text())
        profile = np.interp(stations, *cmp.native_centerline(case, fields))
        error = profile - ref_profile
        rows.append(
            dict(
                grid=grid,
                accepted=True,
                l1=float(np.mean(abs(error))),
                l2=float(np.sqrt(np.mean(error**2))),
                linf=float(np.max(abs(error))),
            )
        )
    accepted_rows = [r for r in rows if r["accepted"]]
    slopes = {}
    if len(accepted_rows) >= 2:
        for key in ["l1", "l2", "linf"]:
            require(
                all(r[key] > 0 and math.isfinite(r[key]) for r in accepted_rows),
                "self.errors",
                "positive finite errors required",
            )
            slopes[key] = float(
                np.polyfit(
                    np.log([1 / r["grid"] for r in accepted_rows]),
                    np.log([r[key] for r in accepted_rows]),
                    1,
                )[0]
            )
    return dict(
        available=len(accepted_rows) >= 2,
        rows=rows,
        orders=slopes,
        reference_grid=96,
        station_count=257,
        meaning="descriptive centerline difference to a finite same-scheme reference; not exact error or GCI",
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--binary", type=Path, default=cmp.ROOT / "target/release/cfd-craft"
    )
    ap.add_argument("--baseline-binary", type=Path)
    ap.add_argument("--sweep", type=Path)
    ap.add_argument(
        "--reference", type=Path, help="Reuse an already completed reference campaign"
    )
    ap.add_argument("--reference-only", action="store_true")
    ap.add_argument(
        "--native-numerics",
        type=json.loads,
        default={},
        help="Opt-in numerics of the 96² reference, as JSON; match the sweep's",
    )
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    report = dict(schema_version="cfd-craft.momentum-baseline/0.1", passed=False)
    claimed = False
    try:
        args.output.mkdir()
        claimed = True
        if args.reference is None:
            report["reference"] = reference(
                args.binary.resolve(), args.output, args.native_numerics
            )
        if not args.reference_only:
            require(
                args.sweep is not None and args.baseline_binary is not None,
                "arguments",
                "sweep and baseline binary required",
            )
            report["self_convergence"] = self_convergence(
                args.sweep, args.reference or args.output
            )
            report["default_controls"] = default_controls(
                args.binary.resolve(), args.baseline_binary.resolve(), args.output
            )
        report["passed"] = report.get("reference", {}).get(
            "accepted", True
        ) and report.get("self_convergence", {}).get("available", True)
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        IndexError,
        subprocess.SubprocessError,
    ) as exc:
        report["error"] = (
            str(exc)
            if str(exc).startswith("CFD-")
            else f"CFD-B007 momentum.campaign: {exc}"
        )
    if claimed:
        cmp.backend.write_json(args.output / "report.json", report)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 1 if report.get("error") else (0 if report["passed"] else 2)


if __name__ == "__main__":
    raise SystemExit(main())
