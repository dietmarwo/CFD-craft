#!/usr/bin/env python3
"""Trusted-command launcher: retain a complete urban worker archive on failure."""

import json
from pathlib import Path
import subprocess
import sys
import zipfile

completed = subprocess.run(
    [
        sys.executable,
        "validation/urban_campaign.py",
        "worker",
        "job.json",
        "--binary",
        "./solver",
    ],
    check=False,
)
row = Path("result.json")
if not row.exists():
    row.write_text(
        json.dumps(
            {
                "accepted": False,
                "error": "urban_worker_did_not_return",
                "exit_code": completed.returncode,
            }
        )
        + "\n"
    )
Path("urban-result.json").write_bytes(row.read_bytes())
with zipfile.ZipFile(
    "urban-archive.zip", "w", compression=zipfile.ZIP_DEFLATED
) as archive:
    for filename in [
        "case.json",
        "job.json",
        "result.json",
        "independent-check.json",
        "independent-check.stderr",
        "stdout.txt",
        "stderr.txt",
    ]:
        path = Path(filename)
        if path.is_file():
            archive.write(path, filename)
    for path in sorted(Path("profile").rglob("*")):
        if path.is_file() and not path.is_symlink():
            archive.write(path, path.as_posix())
result = json.loads(row.read_text())
sys.exit(0 if completed.returncode == 0 and result.get("accepted") else 2)
