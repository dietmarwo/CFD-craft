#!/usr/bin/env python3
"""Check a native phase-profile envelope against its returned CFD archive."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from check_fields import check as audit


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-B003 profile.{field}: {message}")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def regular(path):
    path = Path(path)
    require(
        path.is_file() and not path.is_symlink(), path.name, "regular file required"
    )
    return json.loads(path.read_text())


def number(value, field, integer=False):
    require(
        type(value) is int if integer else type(value) in (int, float),
        field,
        "invalid numeric type",
    )
    require(
        (type(value) is int or math.isfinite(value)) and value >= 0,
        field,
        "finite nonnegative value required",
    )
    return value


def check(root):
    root = Path(root)
    require(
        root.is_dir() and not root.is_symlink(), "output", "regular directory required"
    )
    p = regular(root / "profile.json")
    require(
        p["schema_version"] == "cfd-craft.native-profile/0.1",
        "schema_version",
        "unsupported",
    )
    require(p["archive_directory"] == "run", "archive_directory", "expected run")
    archive = root / "run"
    require(
        archive.is_dir() and not archive.is_symlink(),
        "run",
        "regular directory required",
    )
    marker = regular(archive / "complete.json")
    manifest = regular(archive / "manifest.json")
    summary = regular(archive / "summary.json")
    require(
        p["archive_manifest_sha256"]
        == sha(archive / "manifest.json")
        == marker["manifest_sha256"],
        "manifest",
        "identity differs",
    )
    require(
        manifest["schema_version"] == "cfd-craft.manifest/0.1",
        "manifest.schema_version",
        "unsupported",
    )
    for name, digest in manifest["files"].items():
        require(
            Path(name).name == name and not (archive / name).is_symlink(),
            "manifest.files",
            "invalid artifact",
        )
        require(
            sha(archive / name) == digest, "manifest.files." + name, "checksum differs"
        )
    require(
        {f.name for f in archive.iterdir()}
        == set(manifest["files"]) | {"manifest.json", "complete.json"},
        "manifest.files",
        "unlisted or missing file",
    )
    require(p["summary"] == summary, "summary", "differs from retained archive")
    for field in ["source_sha256", "case_sha256", "threads"]:
        require(
            type(p[field]) is type(summary[field]) and p[field] == summary[field],
            field,
            "differs from retained summary",
        )
    omitted = manifest.get("omitted", {})
    require(isinstance(omitted, dict), "manifest.omitted", "object required")
    require(
        type(p["omitted"]) is list and p["omitted"] == sorted(omitted),
        "omitted",
        "differs from the manifest's omitted artifacts",
    )
    require(type(p["passed"]) is bool, "passed", "boolean required")
    # A sealed archive means the solve returned and its archive was written.
    require(p["error"] is None, "error", "a sealed archive reports no error")
    require(
        p["input_sha256"] == manifest["input_case_sha256"],
        "input_sha256",
        "differs from manifest",
    )
    require(
        p["source_sha256"] == manifest["source_sha256"],
        "source_sha256",
        "differs from manifest",
    )
    independent = None
    if "fields.json" in manifest["files"]:
        require(
            p["state_sha256"] == sha(archive / "fields.json"),
            "state_sha256",
            "differs from returned fields",
        )
        independent = audit(archive)
    timing = p["timing"]
    require(
        timing["schema_version"] == "cfd-craft.phase-profile/0.1",
        "timing.schema_version",
        "unsupported",
    )
    elapsed = number(timing["elapsed_s"], "timing.elapsed_s")
    phases = timing["phases"]
    require(
        isinstance(phases, dict) and "solver_run" in phases,
        "timing.phases",
        "missing solver span",
    )
    for name, row in phases.items():
        for field in [
            "calls",
            "work_units",
            "operator_applications",
            "preconditioner_applications",
            "true_residual_checks",
        ]:
            number(row[field], f"timing.phases.{name}.{field}", integer=True)
        for field in ["inclusive_s", "exclusive_s"]:
            number(row[field], f"timing.phases.{name}.{field}")
        require(
            row["exclusive_s"] <= row["inclusive_s"],
            f"timing.phases.{name}",
            "exclusive exceeds inclusive",
        )
    epsilon = max(1e-9, elapsed * 1e-9)
    total = sum(row["exclusive_s"] for row in phases.values())
    roots = phases["solver_run"]["inclusive_s"] + phases.get("archive_write", {}).get(
        "inclusive_s", 0
    )
    require(
        abs(total - roots) <= epsilon,
        "timing.accounting",
        "nested time is counted twice or missing",
    )
    require(
        abs(total - timing["accounted_exclusive_s"]) <= epsilon,
        "timing.accounted_exclusive_s",
        "sum differs",
    )
    require(
        number(timing["unattributed_s"], "timing.unattributed_s") + total
        <= elapsed + epsilon,
        "timing.elapsed_s",
        "accounting exceeds elapsed",
    )
    require(
        abs(total + timing["unattributed_s"] - elapsed) <= epsilon,
        "timing.unattributed_s",
        "remainder differs",
    )
    initial_steps = number(p["initial_steps"], "initial_steps", integer=True)
    initial_pressure = number(
        p["initial_pressure_iterations"], "initial_pressure_iterations", integer=True
    )
    delta_steps = summary["steps"] - initial_steps
    delta_pressure = summary["pressure_iterations"] - initial_pressure
    steps = phases.get("step", {}).get("calls", 0)
    calls = {name: phases.get(name, {}).get("calls", 0) for name in phases}
    # Every committed step is monitored once; an error ends the loop after at
    # most one uncommitted step, whose time-step phase precedes it.
    require(
        calls.get("monitor", 0) == delta_steps,
        "work.monitor",
        "monitor calls differ from newly retained steps",
    )
    require(
        steps - delta_steps in (0, 1),
        "work.steps",
        "more than one attempted step was not retained",
    )
    require(
        calls.get("timestep", 0) - steps in (0, 1),
        "work.timestep",
        "time-step and step calls differ by more than one",
    )
    stopped = summary["termination"] in ["cancelled", "wall_time_limit", "diverged"]
    require(
        stopped or (steps == delta_steps and calls.get("timestep", 0) == steps),
        "work.steps",
        "a run that ended without an error retains every attempted step",
    )
    linear = phases.get("pressure_solve", {})
    multigrid = linear.get("multigrid")
    selected = regular(archive / "case.json")["numerics"].get(
        "pressure_preconditioner", "ic0"
    )
    if multigrid is not None:
        require(
            selected == "multigrid",
            "work.multigrid",
            "case selects another preconditioner",
        )
        fields = [
            "hierarchy_builds",
            "hierarchy_levels",
            "hierarchy_cells",
            "hierarchy_nonzeros",
            "hierarchy_bytes",
            "cycles",
            "smoothing_cell_updates",
            "residual_cell_updates",
            "restriction_cell_updates",
            "prolongation_cell_updates",
            "coarse_solves",
        ]
        require(isinstance(multigrid, dict), "work.multigrid", "expected object")
        require(
            set(fields).issubset(multigrid)
            and set(multigrid).issubset(
                set(fields)
                | {
                    "block_smoothing_cell_updates",
                    "block_solves",
                    "block_level_cell_visits",
                }
            ),
            "work.multigrid",
            "unexpected or missing fields",
        )
        for field in fields:
            number(multigrid[field], f"work.multigrid.{field}", integer=True)
        line_fields = [
            "block_smoothing_cell_updates",
            "block_solves",
            "block_level_cell_visits",
        ]
        require(
            all(f in multigrid for f in line_fields)
            or all(f not in multigrid for f in line_fields),
            "work.multigrid.block",
            "block counters must occur together",
        )
        for field in line_fields:
            number(multigrid.get(field, 0), f"work.multigrid.{field}", integer=True)
        line_updates = multigrid.get("block_smoothing_cell_updates", 0)
        line_solves = multigrid.get("block_solves", 0)
        block_visits = multigrid.get("block_level_cell_visits", 0)
        require(
            (line_updates == line_solves == 0)
            or (
                0
                < 2 * line_solves
                <= line_updates
                <= multigrid["smoothing_cell_updates"]
            ),
            "work.multigrid.block",
            "block work exceeds total smoothing or has no solves",
        )

        require(
            line_updates == 2 * block_visits
            and block_visits <= multigrid["residual_cell_updates"],
            "work.multigrid.block",
            "block passes differ from fixed two-sweep work",
        )
        require(
            multigrid["cycles"]
            == linear.get("preconditioner_applications", 0)
            == multigrid["coarse_solves"],
            "work.multigrid.cycles",
            "cycle/application/coarse-solve counts differ",
        )
        require(
            multigrid["hierarchy_builds"] == calls.get("pressure_multigrid_setup", 0)
            and not calls.get("pressure_factor_setup", 0),
            "work.multigrid.hierarchy_builds",
            "setup counts differ or IC(0) fallback occurred",
        )
        require(
            multigrid["residual_cell_updates"]
            == multigrid["restriction_cell_updates"]
            == multigrid["prolongation_cell_updates"]
            and multigrid["smoothing_cell_updates"]
            == 4 * multigrid["residual_cell_updates"] - 2 * block_visits,
            "work.multigrid.updates",
            "fixed-cycle work differs",
        )
        require(
            (
                multigrid["hierarchy_levels"] > 0
                and multigrid["hierarchy_nonzeros"] >= multigrid["hierarchy_cells"] > 0
                and multigrid["hierarchy_bytes"] > 0
            )
            or (stopped and multigrid["cycles"] == 0),
            "work.multigrid.hierarchy",
            "missing hierarchy dimensions/storage",
        )
    else:
        require(
            selected != "multigrid" or not calls.get("pressure_solve", 0),
            "work.multigrid",
            "missing selected preconditioner work",
        )
    algorithm = regular(archive / "case.json")["numerics"].get(
        "steady_algorithm", "explicit"
    )
    momentum = phases.get("momentum_solve", {})
    inner = momentum.get("work_units", 0)
    if algorithm == "explicit":
        require(
            not momentum.get("calls", 0)
            and "momentum_solver_iterations" not in summary
            and "initial_momentum_solver_iterations" not in p,
            "work.momentum_solve",
            "explicit pseudo-time did implicit momentum work",
        )
    else:
        require(
            "initial_momentum_solver_iterations" in p
            and "momentum_solver_iterations" in summary,
            "initial_momentum_solver_iterations",
            "implicit pseudo-time must record its inner work",
        )
        initial_inner = number(
            p["initial_momentum_solver_iterations"],
            "initial_momentum_solver_iterations",
            integer=True,
        )
        delta_inner = (
            number(
                summary["momentum_solver_iterations"],
                "summary.momentum_solver_iterations",
                integer=True,
            )
            - initial_inner
        )
        require(
            momentum.get("operator_applications", 0)
            == MOMENTUM_APPLICATIONS_PER_ITERATION[algorithm] * inner
            and momentum.get("preconditioner_applications", 0) <= inner
            and inner <= MOMENTUM_ITERATION_CAP[algorithm] * momentum.get("calls", 0),
            "work.momentum_solve",
            "inner work differs from its operator applications or exceeds the cap",
        )
        require(
            0 <= delta_inner <= inner and (stopped or delta_inner == inner),
            "work.momentum_solver_iterations",
            "retained inner work differs from attempted work",
        )
    pressure = linear.get("work_units", 0)
    require(
        linear.get("operator_applications", 0)
        == pressure + linear.get("true_residual_checks", 0),
        "work.operator_applications",
        "operator applications differ from iterations plus true-residual checks",
    )
    require(
        0 <= delta_steps <= steps, "work.steps", "retained work exceeds attempted work"
    )
    require(
        0 <= delta_pressure <= pressure,
        "work.pressure_iterations",
        "retained work exceeds attempted work",
    )
    if not stopped:
        require(
            delta_steps == steps and delta_pressure == pressure,
            "work.completed",
            "completed or iteration-limited work differs",
        )
    accepted = summary["assessment"] in [
        "steady_discrete_solution",
        "transient_interval_completed",
    ]
    require(
        p["passed"] == (accepted and not p["omitted"] and p["error"] is None),
        "passed",
        "verdict differs",
    )
    return dict(
        integrity_passed=True,
        numerical_accepted=accepted,
        independent=independent,
        attempted_steps=steps,
        retained_new_steps=delta_steps,
        attempted_pressure_iterations=pressure,
        retained_new_pressure_iterations=delta_pressure,
        physical_qualification=False,
    )


# Predeclared inner caps per solve (crates/cfd-craft/src/momentum_solve.rs).
MOMENTUM_ITERATION_CAP = dict(implicit_viscous=50, implicit_projection=50)
# CG applies its operator once per iteration, BiCGStab twice.
MOMENTUM_APPLICATIONS_PER_ITERATION = dict(implicit_viscous=1, implicit_projection=2)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directory", type=Path)
    args = ap.parse_args()
    try:
        print(json.dumps(check(args.directory), indent=2))
    except KeyError as exc:
        print(f"CFD-B003 profile.{exc.args[0]}: missing field")
        return 1
    except (ValueError, OSError, TypeError, AttributeError, ArithmeticError) as exc:
        print(
            str(exc)
            if str(exc).startswith("CFD-")
            else f"CFD-B003 profile.archive: {exc}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
