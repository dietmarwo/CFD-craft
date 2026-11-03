"""Summary-only Python CLI; the native CLI owns field/restart archives."""

import argparse
import json
from pathlib import Path
import sys
from . import CfdError, __version__, check, describe, simulate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("describe")
    commands.add_parser("check").add_argument("case", type=Path)
    run = commands.add_parser("simulate")
    run.add_argument("case", type=Path)
    run.add_argument("--cancel-file", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "describe":
            result, status = describe(), 0
        elif args.command == "check":
            result = check(args.case.read_bytes())
            status = 0 if result["valid"] else 1
        else:
            result = simulate(args.case.read_bytes(), cancel_file=args.cancel_file)
            status = (
                0
                if result["assessment"]
                in {"steady_discrete_solution", "transient_interval_completed"}
                else 2
            )
    except (OSError, ValueError) as error:
        result = (
            error.report
            if isinstance(error, CfdError) and error.report
            else {"error": f"CFD-P001 python.{args.command}: {error}"}
        )
        status = 1
    print(json.dumps(result, indent=2, allow_nan=False))
    sys.exit(status)


if __name__ == "__main__":
    main()
