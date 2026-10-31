"""Accepted cavity cost versus error; misses and incomplete runs stay in the report."""

import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import time

import compare_backends as cmp
from check_fields import check as audit
from process_measure import measure

METHODS = ["native-steady", "openfoam-steady"]
SCHEMA = "cfd-craft.accuracy-sweep/0.1"


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-B004 sweep.{field}: {message}")


def number(value, field, lower=0, upper=float("inf"), integer=False):
    valid_type = type(value) is int if integer else type(value) in (int, float)
    require(
        valid_type and math.isfinite(value) and lower <= value <= upper,
        field,
        "invalid finite numeric value",
    )


def run_method(method, grid, destination, binary, foam_root, limits):
    destination.mkdir()
    began = time.monotonic()
    row = dict(
        method=method,
        grid=grid,
        numerical_accepted=False,
        independent_passed=False,
        reference_screen_passed=False,
        reference_error=None,
        predicted_u=None,
        solver_s=None,
        process_wall_s=None,
        workflow_s=None,
        error=None,
    )
    archive = destination / "run"
    if method == "native-steady":
        case = cmp.native_case(method)
        case["grid"]["cells"] = [grid, 2, grid]
        case["run"]["wall_time_limit_s"] = limits["native_wall_s"]
        case["run"]["max_steps"] = limits["native_max_steps"]
        input_file = destination / "input.json"
        cmp.backend.write_json(input_file, case)
        usage = measure(
            [
                str(binary),
                "run",
                str(input_file.resolve()),
                "--output",
                str(archive.resolve()),
            ],
            destination / "process",
            limits["native_wall_s"] + 20,
        )
        require(
            usage["returncode"] in (0, 2) and not usage["outer_timeout"],
            "native.execution",
            f"child failed: {usage}",
        )
        summary = json.loads((archive / "summary.json").read_text())
        consumed = json.loads((archive / "case.json").read_text())
        manifest = json.loads((archive / "manifest.json").read_text())
        require(consumed == case, "native.case", "consumed case differs from plan")
        require(
            manifest["input_case_sha256"] == cmp.digest(input_file),
            "native.input",
            "input identity differs",
        )
        require(
            manifest["executable_sha256"] == cmp.digest(binary),
            "native.binary",
            "archive producer differs",
        )
        require(
            manifest["source_sha256"] == summary["source_sha256"],
            "native.source",
            "archive source differs",
        )
        checked = audit(archive)
        field = json.loads((archive / "fields.json").read_text())
        predicted, error = cmp.at_ghia_stations(*cmp.native_centerline(case, field))
        row.update(
            numerical_accepted=usage["returncode"] == 0
            and summary["assessment"] == "steady_discrete_solution",
            independent_passed=checked["passed"],
            solver_s=summary["elapsed_s"],
            solver_timer="native elapsed_s; excludes process startup and output",
            steps=summary["steps"],
            pressure_iterations=summary["pressure_iterations"],
            physical_time_s=summary["physical_time_s"],
            assessment=summary["assessment"],
            termination=summary["termination"],
            source_sha256=summary["source_sha256"],
            cells=summary["fluid_cells"],
            case_sha256=summary["case_sha256"],
            input_sha256=cmp.digest(input_file),
            initial_state_sha256=summary["initial_state_sha256"],
            momentum_residual=summary["momentum_residual"],
            numerical_error=summary.get("error"),
            independent_check=dict(assessed=True, **checked),
        )
        row.update(reference_error=error, predicted_u=[float(v) for v in predicted])
    else:
        prepared = destination / "input"
        require(grid in (24, 48, 72), "openfoam.grid", "unsupported recipe grid")
        cmp.backend.prepare("cavity", grid // 24, limits["foam_iterations"], prepared)
        command = [
            sys.executable,
            str(cmp.ROOT / "integrations/openfoam_backend.py"),
            "run",
            "--case",
            str(prepared.resolve()),
            "--foam-root",
            str(foam_root),
            "--timeout-s",
            str(limits["foam_wall_s"]),
            "--memory-mib",
            "2048",
            "--output-mib",
            "128",
            "--output",
            str(archive.resolve()),
        ]
        usage = measure(command, destination / "process", limits["foam_wall_s"] + 30)
        require(
            usage["returncode"] in (0, 2) and not usage["outer_timeout"],
            "openfoam.execution",
            f"child failed: {usage}",
        )
        r = cmp.backend.verify(archive)
        require(
            r["case_sha256"] == cmp.digest(prepared / "case.json"),
            "openfoam.case",
            "consumed input differs",
        )
        numerical = r.get("numerical") or {}
        solver = [c["wall_s"] for c in r["commands"] if c["program"] == "foamRun"]
        require(len(solver) <= 1, "openfoam.commands", "ambiguous solver process")
        row.update(
            numerical_accepted=usage["returncode"] == 0 and r["passed"],
            independent_passed=bool(numerical)
            and numerical["relative_boundary_imbalance"] <= 1e-6,
            independent_check=dict(
                assessed=bool(numerical),
                relative_boundary_imbalance=numerical.get(
                    "relative_boundary_imbalance"
                ),
                threshold=1e-6,
                meaning="independently summed stored boundary phi and finite final fields, checked by backend.verify; not a full local-flux audit",
            ),
            solver_s=solver[0] if solver else None,
            solver_timer="foamRun process; includes startup, case reading and solver output",
            steps=numerical.get("iterations", 0),
            cells=r["case_metadata"]["cells"],
            assessment="accepted" if r["passed"] else "incomplete",
            termination=r["execution_status"],
            numerical_error=r.get("error"),
            case_sha256=r["case_sha256"],
            runtime_identity=hashlib.sha256(
                json.dumps(r.get("runtime"), sort_keys=True).encode()
            ).hexdigest(),
        )
        if r["passed"]:
            predicted, error = cmp.at_ghia_stations(
                *cmp.openfoam_centerline(archive, r)
            )
            row.update(reference_error=error, predicted_u=[float(v) for v in predicted])
        else:
            row["reference_unavailable"] = (
                "no accepted final sampled profile; no saved pre-failure snapshot substituted"
            )
    row.update(
        workflow_s=time.monotonic() - began,
        process_wall_s=usage["process_wall_s"],
        peak_rss_kib_linux=usage["peak_rss_kib_linux"],
        rss_scope=usage["rss_scope"],
        measurement_timer_sha256=usage["timer_sha256"],
        stray_processes_stopped=usage["stray_processes_stopped"],
        returncode=usage["returncode"],
        archive_manifest_sha256=cmp.digest(archive / "manifest.json"),
        run_directory=destination.name,
    )
    if row["reference_error"] is not None:
        number(row["reference_error"], "reference_error")
        row["reference_screen_passed"] = row["reference_error"] <= cmp.REFERENCE_TARGET
    row["accepted"] = (
        row["numerical_accepted"]
        and row["independent_passed"]
        and row["reference_screen_passed"]
    )
    cmp.backend.write_json(destination / "measurement.json", row)
    return row


def validate_row(row):
    for field in [
        "accepted",
        "numerical_accepted",
        "independent_passed",
        "reference_screen_passed",
    ]:
        require(type(row[field]) is bool, f"row.{field}", "boolean required")
    number(row["workflow_s"], "row.workflow_s", lower=1e-30)
    number(row["steps"], "row.steps", integer=True)
    number(row["cells"], "row.cells", lower=1, integer=True)
    if row["solver_s"] is not None:
        number(row["solver_s"], "row.solver_s", lower=1e-30)
    if row["reference_error"] is not None:
        number(row["reference_error"], "row.reference_error")
    require(
        row["accepted"]
        == (
            row["numerical_accepted"]
            and row["independent_passed"]
            and row["reference_screen_passed"]
        ),
        "row.accepted",
        "verdict differs",
    )
    if row["reference_error"] is not None:
        require(
            row["reference_screen_passed"]
            == (row["reference_error"] <= cmp.REFERENCE_TARGET),
            "row.reference_screen_passed",
            "verdict differs",
        )
    else:
        require(
            not row["reference_screen_passed"],
            "row.reference_screen_passed",
            "missing reference",
        )
    if row["accepted"]:
        require(
            row["solver_s"] is not None
            and isinstance(row["predicted_u"], list)
            and bool(row["predicted_u"]),
            "row.accepted",
            "missing timing or profile",
        )
        for v in row["predicted_u"]:
            require(
                type(v) in (int, float) and math.isfinite(v),
                "row.predicted_u",
                "nonfinite profile",
            )


def summarize(rows, configurations, rounds, target):
    groups = []
    for config in configurations:
        selected = [
            r
            for r in rows
            if not r["warmup"]
            and (r["method"], r["grid"]) == (config["method"], config["grid"])
        ]
        require(len(selected) == rounds, "rows", "missing or duplicate timed row")
        complete = all(not r.get("error") for r in selected)
        all_accepted = complete and all(r.get("accepted") for r in selected)
        group = dict(
            **config,
            timed_rows=len(selected),
            accepted_rows=sum(bool(r.get("accepted")) for r in selected),
            all_accepted=all_accepted,
            qualifies=False,
            reference_error=None,
            workflow_median_s=None,
            solver_median_s=None,
        )
        if complete:
            for r in selected:
                number(r["workflow_s"], "workflow_s", lower=1e-30)
                if r["solver_s"] is not None:
                    number(r["solver_s"], "solver_s", lower=1e-30)
                if r["reference_error"] is not None:
                    number(r["reference_error"], "reference_error")
                if r.get("accepted"):
                    require(
                        r["reference_error"] is not None
                        and r["reference_error"] <= cmp.REFERENCE_TARGET
                        and r["solver_s"] is not None,
                        "accepted",
                        "inconsistent accepted row",
                    )
            group.update(
                workflow_median_s=statistics.median(r["workflow_s"] for r in selected),
                workflow_min_s=min(r["workflow_s"] for r in selected),
                workflow_max_s=max(r["workflow_s"] for r in selected),
            )
            solver = [r["solver_s"] for r in selected if r["solver_s"] is not None]
            rss = [
                r["peak_rss_kib_linux"]
                for r in selected
                if r.get("peak_rss_kib_linux") is not None
            ]
            group.update(
                solver_median_s=statistics.median(solver)
                if len(solver) == rounds
                else None,
                peak_rss_median_kib_linux=statistics.median(rss)
                if len(rss) == rounds
                else None,
            )
        if all_accepted:
            for key in ["steps", "cells", "predicted_u", "case_sha256"]:
                require(
                    all(r[key] == selected[0][key] for r in selected),
                    f"repeat.{key}",
                    "accepted result/work differs",
                )
            identity = (
                "source_sha256"
                if config["method"] == "native-steady"
                else "runtime_identity"
            )
            require(
                len({r[identity] for r in selected}) == 1,
                f"repeat.{identity}",
                "producer differs",
            )
            if config["method"] == "native-steady":
                for key in ["pressure_iterations", "initial_state_sha256"]:
                    require(
                        all(r[key] == selected[0][key] for r in selected),
                        f"repeat.{key}",
                        "work/initial state differs",
                    )
            require(
                all(
                    r["reference_error"] == selected[0]["reference_error"]
                    for r in selected
                ),
                "repeat.reference_error",
                "error differs",
            )
            group.update(
                reference_error=selected[0]["reference_error"],
                steps=selected[0]["steps"],
                cells=selected[0]["cells"],
                qualifies=selected[0]["reference_error"] <= target,
            )
        else:
            group["status"] = (
                "unaccepted_or_failed; timings are work consumed, not cost to accepted accuracy"
            )
        groups.append(group)
    cost = {}
    for method in METHODS:
        eligible = [g for g in groups if g["method"] == method and g["qualifies"]]
        cost[method] = dict(
            target_reached=bool(eligible),
            status="reached_on_tested_configurations"
            if eligible
            else "target_not_reached_within_tested_grids_and_budgets",
            workflow_best=min(eligible, key=lambda g: g["workflow_median_s"])
            if eligible
            else None,
            solver_best=min(eligible, key=lambda g: g["solver_median_s"])
            if eligible
            else None,
        )
    ratios = None
    if all(c["target_reached"] for c in cost.values()):
        ratios = {
            timer: cost["native-steady"][timer + "_best"][timer + "_median_s"]
            / cost["openfoam-steady"][timer + "_best"][timer + "_median_s"]
            for timer in ["workflow", "solver"]
        }
    return groups, cost, ratios


def sweep(
    binary,
    foam_root,
    output,
    levels=(1, 2),
    rounds=3,
    target=0.01,
    native_wall_s=180,
    foam_wall_s=180,
    native_max_steps=20000,
    foam_iterations=3000,
    native_diagnostic=True,
    runner=run_method,
):
    require(
        isinstance(levels, (list, tuple))
        and bool(levels)
        and all(type(n) is int and n in (1, 2, 3) for n in levels)
        and len(set(levels)) == len(levels),
        "levels",
        "distinct levels 1..3 required",
    )
    number(rounds, "rounds", 1, 5, integer=True)
    number(target, "target", 1e-12, cmp.REFERENCE_TARGET)
    number(native_wall_s, "native_wall_s", 1e-6, 600)
    number(foam_wall_s, "foam_wall_s", 1e-6, 600)
    number(native_max_steps, "native_max_steps", 1, 20000, integer=True)
    number(foam_iterations, "foam_iterations", 50, 20000, integer=True)
    cmp.backend.snapshot_interval(foam_iterations)
    require(type(native_diagnostic) is bool, "native_diagnostic", "boolean required")
    binary, foam_root = Path(binary).resolve(), Path(foam_root).resolve()
    require(binary.is_file(), "binary", "file required")
    require(foam_root.is_dir(), "foam_root", "directory required")
    configurations = [
        dict(method=m, grid=24 * level) for level in levels for m in METHODS
    ]
    if native_diagnostic:
        configurations.insert(0, dict(method="native-steady", grid=12))
    inputs = [
        binary,
        *cmp.PRODUCERS,
        Path(__file__),
        cmp.ROOT / "validation/process_measure.py",
        cmp.ROOT / "validation/backstep_data.py",
    ]
    identities = {cmp.name(p): cmp.digest(p) for p in inputs}
    limits = dict(
        native_wall_s=native_wall_s,
        foam_wall_s=foam_wall_s,
        native_max_steps=native_max_steps,
        foam_iterations=foam_iterations,
    )
    output = Path(output)
    cmp.backend.claim_directory(output)
    report = dict(
        schema_version=SCHEMA,
        completed=False,
        workflow_valid=False,
        passed=False,
        plan=dict(
            configurations=configurations,
            rounds=rounds,
            warmups_per_configuration=1,
            target=target,
            reference_screen=cmp.REFERENCE_TARGET,
            limits=limits,
            input_sha256=identities,
            threads=1,
            environment=dict(
                platform=platform.platform(),
                processor=platform.processor(),
                cpu_count=os.cpu_count(),
                python=platform.python_version(),
            ),
            meaning="same physical cavity and sampled observable; different spatial schemes, span cells, stopping rules and timer scopes; no GCI or extrapolated crossing",
        ),
        rows=[],
        physical_qualification=False,
    )
    path = output / "report.json"
    cmp.backend.write_json(path, report)

    def identity_check():
        for p in inputs:
            require(
                cmp.digest(p) == identities[cmp.name(p)],
                "inputs",
                f"{cmp.name(p)} changed",
            )

    try:
        # Each grid is its own paired block. Native 12 is a diagnostic block.
        for grid in dict.fromkeys(c["grid"] for c in configurations):
            block = [c for c in configurations if c["grid"] == grid]
            for index in range(-1, rounds):
                order = block if index % 2 == 0 else list(reversed(block))
                for config in order:
                    identity_check()
                    label = f"{'warmup' if index < 0 else f'round-{index:02d}'}-n{grid}-{config['method']}"
                    row = dict(
                        **config,
                        warmup=index < 0,
                        round=index,
                        order=[c["method"] for c in order],
                        run_directory=label,
                        accepted=False,
                        error=None,
                    )
                    report["rows"].append(row)
                    cmp.backend.write_json(path, report)
                    try:
                        measured = runner(
                            config["method"],
                            grid,
                            output / label,
                            binary,
                            foam_root,
                            limits,
                        )
                        # A rejected measurement stays in the report beside its error.
                        row["rejected_measurement"] = measured
                        require(
                            measured["method"] == config["method"]
                            and measured["grid"] == grid,
                            "row.configuration",
                            "returned configuration differs",
                        )
                        validate_row(measured)
                        del row["rejected_measurement"]
                        row.update(measured)
                    except (
                        ValueError,
                        OSError,
                        KeyError,
                        TypeError,
                        IndexError,
                        AttributeError,
                    ) as exc:
                        row["error"] = (
                            str(exc)
                            if str(exc).startswith("CFD-")
                            else f"CFD-B004 sweep.row: {exc}"
                        )
                    identity_check()
                    cmp.backend.write_json(path, report)
        report["completed"] = True
        (
            report["groups"],
            report["cost_at_target"],
            report["native_over_openfoam_at_target"],
        ) = summarize(report["rows"], configurations, rounds, target)
        report["workflow_valid"] = not any(r["error"] for r in report["rows"])
        report["passed"] = report["workflow_valid"] and all(
            r["accepted"] for r in report["rows"]
        )
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        report["error"] = (
            str(exc)
            if str(exc).startswith("CFD-")
            else f"CFD-B004 sweep.campaign: {exc}"
        )
    cmp.backend.write_json(path, report)
    return report
