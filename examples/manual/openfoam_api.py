#!/usr/bin/env python3
"""Source-checkout Python adapter API; a real bounded Foundation-13 cavity."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integrations"))
import openfoam_backend as backend


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--foam-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    report = dict(passed=False, physical_qualification=False)
    claimed = False
    try:
        backend.claim_directory(args.output)
        claimed = True
        backend.prepare("cavity", 1, 3000, args.output / "input")
        executed = backend.run(
            args.output / "input",
            args.output / "run",
            args.foam_root,
            timeout_s=180,
            output_mib=64,
            memory_mib=2048,
        )
        report["execution"] = executed
        checked = backend.verify(args.output / "run")
        report["archive_consistent"] = True
        report["passed"] = executed["passed"] and checked["numerical"]["passed"]
    except (ValueError, OSError, KeyError, TypeError) as exc:
        report["error"] = backend.diagnostic(exc, "manual.openfoam")
    if claimed:
        backend.write_json(args.output / "report.json", report)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
