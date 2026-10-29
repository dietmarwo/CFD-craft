#!/usr/bin/env python3
"""Profile one subprocess using Unix child resource accounting (KiB on Linux)."""

import argparse
import json
from pathlib import Path
import resource
import subprocess
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--case", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir()
    command = [
        str(args.binary.resolve()),
        "run",
        str(args.case.resolve()),
        "--output",
        str((args.output / "run").resolve()),
    ]
    start = time.monotonic()
    with (
        (args.output / "stdout.log").open("w") as out,
        (args.output / "stderr.log").open("w") as err,
    ):
        p = subprocess.run(command, stdout=out, stderr=err, timeout=180)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    summary = args.output / "run/summary.json"
    result = json.loads(summary.read_text()) if summary.exists() else None
    report = dict(
        returncode=p.returncode,
        wall_s=time.monotonic() - start,
        child_cpu_s=usage.ru_utime + usage.ru_stime,
        peak_rss_kib_linux=usage.ru_maxrss,
        summary=result,
        passed=p.returncode == 0 and result is not None,
        scope="this exact case and process; no extrapolated RANS throughput claim",
    )
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
