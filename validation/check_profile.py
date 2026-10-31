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
        math.isfinite(value) and value >= 0, field, "finite nonnegative value required"
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
        require(p[field] == summary[field], field, "differs from retained summary")
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
    linear = phases.get("pressure_solve", {})
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
    if summary["termination"] == "completed":
        require(
            delta_steps == steps and delta_pressure == pressure,
            "work.completed",
            "completed work differs",
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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directory", type=Path)
    args = ap.parse_args()
    try:
        print(json.dumps(check(args.directory), indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(
            str(exc)
            if str(exc).startswith("CFD-")
            else f"CFD-B003 profile.archive: {exc}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
