#!/usr/bin/env python3
"""Run in a fresh child directory, then expose a flat, sealed command output.

The runner prepares declared output parent directories before launch. The CFD
CLI deliberately requires a new run directory, so output collection uses this
small explicit adapter rather than relaxing the CLI's overwrite rule.
"""

from pathlib import Path
import shutil
import subprocess
import sys

solver = Path(sys.argv[1]).resolve()
completed = subprocess.run([str(solver), "run", "case.json", "--output", "simulation"])
summary = Path("simulation/summary.json")
if summary.is_file():
    with summary.open("rb") as source, Path("summary.json").open("xb") as destination:
        shutil.copyfileobj(source, destination)
raise SystemExit(completed.returncode)
