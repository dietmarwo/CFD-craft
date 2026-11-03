#!/usr/bin/env python3
"""Run one simulator-owned CFD optimization tutorial."""

import sys
from support import main
from allocation import run as f1
from sensors import run as f2
from coupled import run as f3

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in {"F1", "F2", "F3"}:
        raise SystemExit(
            "usage: run.py {F1,F2,F3} --output NEW_DIRECTORY [--preset smoke|study]"
        )
    chapter = sys.argv.pop(1)
    raise SystemExit(main(chapter, {"F1": f1, "F2": f2, "F3": f3}[chapter]))
