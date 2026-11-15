#!/usr/bin/env python3
"""Bounded cold-start district wind-rose campaign with durable failed rows.

The worker subcommand is also a trusted-command entry point for optimization-jobs.
It always keeps the consumed case, native archive, profile, stdout and stderr.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def prepare(
    case,
    output,
    *,
    run_budget_s,
    campaign_budget_s,
    threads,
    workers,
    map_rotation_deg=0.0,
):
    if min(run_budget_s, campaign_budget_s, threads, workers) <= 0 or not all(
        math.isfinite(v) for v in (run_budget_s, campaign_budget_s)
    ):
        raise ValueError("Budgets and worker counts must be finite and positive")
    if case["flow"]["kind"] != "neutral_rans":
        raise ValueError("Wind rose requires neutral_rans")
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema_version": "cfd-craft.urban-campaign/1",
        "directions_deg_from": list(range(0, 360, 30)),
        "run_budget_s": run_budget_s,
        "campaign_budget_s": campaign_budget_s,
        "threads_per_worker": threads,
        "workers": workers,
        "initialization": "cold per direction; no cross-case restart",
        "direction_frame": "model_local_meteorological_from",
        "map_rotation_deg": map_rotation_deg,
        "meaning": "local-source increments in neutral flow; not total ambient PM or experimental validation",
        "jobs": [],
    }
    for angle in plan["directions_deg_from"]:
        folder = output / f"wind-{angle:03d}"
        folder.mkdir()
        c = json.loads(json.dumps(case))
        c["name"] = f"district-wind-{angle:03d}"
        c["flow"]["direction_deg_from"] = float(angle)
        c["run"].update(threads=threads, wall_time_limit_s=run_budget_s)
        c["output"].update(fields=True, checkpoint=False)
        write_json(folder / "case.json", c)
        job = {
            "schema_version": "cfd-craft.urban-job/1",
            "id": folder.name,
            "case": "case.json",
            "wall_time_limit_s": run_budget_s,
            "memory_limit_mib": c["run"]["memory_limit_mib"],
            "initialization": "cold",
            "direction_deg_from": angle,
            "geographic_direction_deg_from": (angle - map_rotation_deg) % 360,
        }
        write_json(folder / "job.json", job)
        plan["jobs"].append(f"{folder.name}/job.json")
    write_json(output / "campaign-plan.json", plan)
    return plan


def execute_job(job_path, binary):
    start = time.monotonic()
    folder = job_path.parent
    job = json.loads(job_path.read_text())
    case = json.loads((folder / job["case"]).read_text())
    row = {
        "id": job["id"],
        "direction_deg_from": job["direction_deg_from"],
        "geographic_direction_deg_from": job.get(
            "geographic_direction_deg_from", job["direction_deg_from"]
        ),
        "accepted": False,
        "initialization": "cold",
        "case_file_sha256": hashlib.sha256(
            (folder / job["case"]).read_bytes()
        ).hexdigest(),
        "run_budget_s": job["wall_time_limit_s"],
        "observed_peak_rss_kib": 0,
    }
    row["worker_status"] = "running"
    write_json(folder / "result.json", row)
    # Solver preflight plus an inherited hard address-space limit in this worker.
    # Keep 512 MiB for runtime/serializer overhead above the declared estimate.
    hard = (job["memory_limit_mib"] + 512) * 1024**2
    resource.setrlimit(resource.RLIMIT_AS, (hard, hard))
    try:
        command = [
            str(binary.resolve()),
            "profile",
            str((folder / job["case"]).resolve()),
            "--output",
            str((folder / "profile").resolve()),
        ]
        row["command"] = ["cfd-craft", "profile", "case.json", "--output", "profile"]
        with (
            (folder / "stdout.txt").open("w") as stdout,
            (folder / "stderr.txt").open("w") as stderr,
        ):
            process = subprocess.Popen(
                command, stdout=stdout, stderr=stderr, start_new_session=False
            )
            deadline = time.monotonic() + job["wall_time_limit_s"] + 15
            while process.poll() is None:
                try:
                    text = Path(f"/proc/{process.pid}/status").read_text()
                    for line in text.splitlines():
                        if line.startswith("VmHWM:"):
                            row["observed_peak_rss_kib"] = max(
                                row["observed_peak_rss_kib"], int(line.split()[1])
                            )
                except FileNotFoundError:
                    pass
                if time.monotonic() > deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    row["error"] = "worker_watchdog_timeout"
                    break
                time.sleep(0.1)
            row["exit_code"] = process.wait()
        archive = folder / "profile/run"
        if (archive / "summary.json").exists():
            summary = json.loads((archive / "summary.json").read_text())
            row.update(
                termination=summary["termination"],
                assessment=summary["assessment"],
                steps=summary["steps"],
                solver_elapsed_s=summary["elapsed_s"],
                cells=math.prod(case["grid"]["cells"]),
                source_sha256=summary["source_sha256"],
                physics_sha256=summary["physics_sha256"],
                constituents=summary["constituents"],
                experimental_validation=summary["experimental_validation"],
            )
            audit = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "validation/check_fields.py"),
                    str(archive),
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            (folder / "independent-check.json").write_text(audit.stdout)
            (folder / "independent-check.stderr").write_text(audit.stderr)
            row["independent_check_passed"] = audit.returncode == 0
            row["accepted"] = (
                process.returncode == 0
                and summary["assessment"] == "steady_discrete_solution"
                and all(c["passed"] for c in summary["checks"])
                and audit.returncode == 0
            )
            profile = json.loads((folder / "profile/profile.json").read_text())
            phases = profile["timing"]["phases"]
            row["phase_exclusive_s"] = {
                name: v["exclusive_s"] for name, v in phases.items()
            }
        else:
            row.setdefault("error", "no_native_archive")
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        row["error"] = str(exc)
    row["worker_status"] = "finished"
    row["worker_elapsed_s"] = time.monotonic() - start
    write_json(folder / "result.json", row)
    return row


def run(plan, output, binary, runner=None):
    start = time.monotonic()
    deadline = start + plan["campaign_budget_s"]

    integration = None
    if runner is not None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "urban_job", ROOT / "integrations/urban_job.py"
        )
        integration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(integration)
        integration.initialize(
            runner, output / "node", plan["workers"] * plan["threads_per_worker"]
        )

    def child(relative):
        folder = (output / relative).parent
        if time.monotonic() + plan["run_budget_s"] + 20 > deadline:
            row = {
                "id": folder.name,
                "accepted": False,
                "error": "campaign_budget_exhausted",
                "initialization": "cold",
            }
            write_json(folder / "result.json", row)
            return row
        if integration is not None:
            try:
                return integration.execute(
                    runner,
                    output / "node",
                    folder,
                    binary,
                    plan["threads_per_worker"],
                    plan["run_budget_s"],
                    min(deadline - time.monotonic(), plan["run_budget_s"] + 150),
                )
            except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
                row = {
                    "id": folder.name,
                    "accepted": False,
                    "error": str(exc),
                    "initialization": "cold",
                }
                write_json(folder / "result.json", row)
                return row
        try:
            with (folder / "worker.stderr").open("w") as stderr:
                worker = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "worker",
                        str((output / relative).resolve()),
                        "--binary",
                        str(binary.resolve()),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=stderr,
                    start_new_session=True,
                )
                try:
                    worker.wait(
                        timeout=min(
                            deadline - time.monotonic(), plan["run_budget_s"] + 120
                        )
                    )
                except subprocess.TimeoutExpired:
                    os.killpg(worker.pid, signal.SIGTERM)
                    try:
                        worker.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(worker.pid, signal.SIGKILL)
                        worker.wait()
            if (folder / "result.json").exists():
                return json.loads((folder / "result.json").read_text())
        except subprocess.TimeoutExpired:
            pass
        row = {
            "id": folder.name,
            "accepted": False,
            "error": "worker_failed",
            "initialization": "cold",
        }
        write_json(folder / "result.json", row)
        return row

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=plan["workers"]) as pool:
        for row in pool.map(child, plan["jobs"]):
            rows.append(row)
            write_json(output / "results.json", rows)
    report = {
        "schema_version": "cfd-craft.urban-report/1",
        "rows": rows,
        "elapsed_s": time.monotonic() - start,
        "accepted": sum(r["accepted"] for r in rows),
        "failed": sum(not r["accepted"] for r in rows),
        "all_directions_retained": len(rows) == 12,
        "within_budget": time.monotonic() <= deadline,
        "experimental_validation": "not_validated",
        "gpu_experiment": "not_requested_without_measured_million_cell_pressure_bottleneck",
    }
    write_json(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    worker = sub.add_parser("worker")
    worker.add_argument("job", type=Path)
    worker.add_argument(
        "--binary", type=Path, default=ROOT / "target/release/cfd-craft"
    )
    campaign = sub.add_parser("run")
    campaign.add_argument("case", type=Path)
    campaign.add_argument("--output", type=Path, required=True)
    campaign.add_argument(
        "--binary", type=Path, default=ROOT / "target/release/cfd-craft"
    )
    campaign.add_argument("--run-budget-s", type=float, default=120.0)
    campaign.add_argument("--campaign-budget-s", type=float, default=1200.0)
    campaign.add_argument("--threads", type=int, default=1)
    campaign.add_argument("--workers", type=int, default=2)
    campaign.add_argument("--map-provenance", type=Path)
    campaign.add_argument(
        "--runner",
        type=Path,
        help="Use the existing optimization-run trusted-command worker",
    )
    args = parser.parse_args()
    if args.command == "worker":
        execute_job(args.job, args.binary)
    else:
        plan = prepare(
            json.loads(args.case.read_text()),
            args.output,
            run_budget_s=args.run_budget_s,
            campaign_budget_s=args.campaign_budget_s,
            threads=args.threads,
            workers=args.workers,
            map_rotation_deg=(
                json.loads(args.map_provenance.read_text())["rotation_deg"]
                if args.map_provenance
                else 0.0
            ),
        )
        if args.map_provenance:
            (args.output / "map-provenance.json").write_bytes(
                args.map_provenance.read_bytes()
            )
        report = run(
            plan,
            args.output,
            args.binary,
            args.runner.resolve() if args.runner else None,
        )
        print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
        return 0 if report["accepted"] == 12 and report["within_budget"] else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
