"""Stage urban workers as the existing execution.command/0.1 job protocol."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare_spec(folder, binary, threads, budget):
    case = json.loads((folder / "case.json").read_text())
    staged = [
        ("case.json", folder / "case.json", False),
        ("job.json", folder / "job.json", False),
        ("launch.py", ROOT / "integrations/launch_urban_command.py", False),
        ("validation/urban_campaign.py", ROOT / "validation/urban_campaign.py", False),
        ("validation/check_fields.py", ROOT / "validation/check_fields.py", False),
        ("solver", binary, True),
    ]
    inputs = []
    for i, (target, source, executable) in enumerate(staged):
        # Physical names are flat, relative to the spec; staged paths retain modules.
        physical = folder / f"staged-input-{i}"
        if source.resolve() != physical.resolve():
            shutil.copyfile(source, physical)
        inputs.append(
            dict(
                path=target,
                file=physical.name,
                bytes=physical.stat().st_size,
                sha256=hashlib.sha256(physical.read_bytes()).hexdigest(),
                executable=executable,
            )
        )
    spec = dict(
        schema_version="execution.command/0.1",
        request_key=f"urban-{folder.name}",
        argv=[sys.executable, "launch.py"],
        env={},
        resources=dict(cpu_slots=threads),
        limits=dict(wall_seconds=budget + 120, grace_seconds=3),
        replay="never",
        inputs=inputs,
        outputs=[
            dict(
                name="urban_result",
                path="urban-result.json",
                required=True,
                max_bytes=2 * 1048576,
            ),
            dict(
                name="urban_archive",
                path="urban-archive.zip",
                required=True,
                max_bytes=min(case["output"]["max_total_mib"] + 2, 64) * 1048576,
            ),
        ],
    )
    path = folder / "command.json"
    path.write_text(json.dumps(spec, indent=2) + "\n")
    return path


def initialize(runner, node, capacity):
    result = subprocess.run(
        [
            str(runner),
            "--root",
            str(node),
            "node",
            "init",
            "--capacity",
            str(capacity),
            "--allow-commands",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"Cannot initialize runner node: {result.stderr}")


def execute(runner, node, folder, binary, threads, budget, timeout):
    path = prepare_spec(folder, binary, threads, budget)
    done = subprocess.run(
        [str(runner), "--root", str(node), "run", "--spec", str(path.resolve())],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    (folder / "runner.stdout").write_text(done.stdout)
    (folder / "runner.stderr").write_text(done.stderr)
    try:
        execution = json.loads(done.stdout)
    except ValueError:
        return dict(
            id=folder.name,
            accepted=False,
            error="runner_did_not_return_json",
            exit_code=done.returncode,
        )
    (folder / "runner-execution.json").write_text(
        json.dumps(execution, indent=2) + "\n"
    )
    if "directory" not in execution:
        return dict(
            id=folder.name,
            accepted=False,
            error=execution.get("error", "runner_missing_directory"),
            exit_code=done.returncode,
        )
    directory = Path(execution["directory"])
    manifest = subprocess.run(
        [str(runner), "--root", str(node), "result", str(directory)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    (folder / "runner-manifest.json").write_text(manifest.stdout)
    candidates = list(directory.rglob("urban-result.json"))
    if not candidates:
        return dict(
            id=folder.name,
            accepted=False,
            error="runner_missing_worker_result",
            runner_state=execution.get("state"),
        )
    row = json.loads(candidates[0].read_text())
    row["runner_state"] = execution.get("state")
    row["runner_manifest_passed"] = manifest.returncode == 0
    row["native_accepted"] = row.get("accepted", False)
    row["accepted"] = (
        row["native_accepted"]
        and execution.get("state") == "completed"
        and manifest.returncode == 0
    )
    # Expose the sealed result archive, never mutate the runner's result directory.
    for candidate in directory.rglob("urban-archive.zip"):
        shutil.copyfile(candidate, folder / "urban-archive.zip")
        break
    (folder / "result.json").write_text(json.dumps(row, indent=2) + "\n")
    return row
