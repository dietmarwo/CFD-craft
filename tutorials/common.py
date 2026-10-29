"""Canonical execution helpers; preserve a report even when a case fails."""

import json
import subprocess
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validation"))
from check_fields import check, require  # noqa: F401 (re-exported to the scripts)


def receptor_values(record, case):
    """Receptor values of the first constituent, in the case's receptor order.

    The summary stores receptors by ID in sorted order (R10 before R2), so values
    must be looked up by ID rather than taken in stored order.
    """
    stored = record["summary"]["constituents"][0]["receptors_kg_m3"]
    return [stored[r["id"]] for r in case["receptors"]]


def sidecar(destination, suffix):
    """The file next to a run directory named after the whole run name."""
    return destination.with_name(destination.name + suffix)


def run_case(binary, case, destination, restart=None):
    destination = Path(destination)
    # Sidecars append to the run name, so "schmidt-0.5" and "schmidt-0.9" stay distinct.
    p = sidecar(destination, ".case.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(case, indent=2) + "\n")
    start = time.monotonic()
    command = [str(Path(binary).resolve()), "run", str(p), "--output", str(destination)]
    if restart is not None:
        command.extend(["--restart", str(restart)])
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=case["run"]["wall_time_limit_s"] + 20,
    )
    sidecar(destination, ".stdout.log").write_text(completed.stdout)
    sidecar(destination, ".stderr.log").write_text(completed.stderr)
    summary_path = destination / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.is_file() else None
    audit = None
    if (destination / "fields.json").exists():
        try:
            audit = check(destination)
        except (ValueError, OSError, KeyError, IndexError, TypeError) as exc:
            audit = dict(passed=False, error=str(exc))
    return dict(
        case=case["name"],
        returncode=completed.returncode,
        wall_s=time.monotonic() - start,
        summary=summary,
        independent=audit,
        path=str(destination.name),
    )


def accepted(record):
    return (
        record["returncode"] == 0
        and record["summary"] is not None
        and record["summary"]["assessment"]
        in ["steady_discrete_solution", "transient_interval_completed"]
        and record["independent"] is not None
        and record["independent"]["passed"]
    )


def write_report(output, report):
    Path(output, "report.json").write_text(json.dumps(report, indent=2) + "\n")
