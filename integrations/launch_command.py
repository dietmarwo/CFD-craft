#!/usr/bin/env python3
"""Run in a fresh child directory, then expose a flat, sealed command output.

The runner prepares declared output parent directories before launch. The CFD
CLI deliberately requires a new run directory, so output collection uses this
small explicit adapter rather than relaxing the CLI's overwrite rule.

On SIGTERM or SIGINT (a runner deadline or cancellation) the launcher forwards
the signal to the solver, waits for it to write its cancelled summary, and still
copies that summary, so a stopped run keeps its evidence.
"""

from pathlib import Path
import shutil
import signal
import subprocess
import sys

solver = Path(sys.argv[1]).resolve()
child = None
pending = []


def forward(signum, _frame):
    # A signal that arrives before the solver exists is delivered once it starts.
    if child is None:
        pending.append(signum)
    else:
        child.send_signal(signum)


for signum in (signal.SIGTERM, signal.SIGINT):
    signal.signal(signum, forward)
child = subprocess.Popen([str(solver), "run", "case.json", "--output", "simulation"])
for signum in pending:
    child.send_signal(signum)
returncode = child.wait()
summary = Path("simulation/summary.json")
if summary.is_file():
    with summary.open("rb") as source, Path("summary.json").open("xb") as destination:
        shutil.copyfileobj(source, destination)
raise SystemExit(returncode)
