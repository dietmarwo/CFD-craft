#!/usr/bin/env python3
"""Run one unittest file and publish each failure as a GitHub Actions error.

The checks view and the check-run annotations API then show which test failed
and its traceback without opening the job log. The exit code is the test run's.

    python validation/unittest_notices.py validation/test_mapping.py [-O]
"""

import re
import subprocess
import sys

from external_notices import escape


def failures(text):
    """(title, body) for each FAIL/ERROR block of a unittest report."""
    blocks = re.split(r"^=+\n", text, flags=re.M)
    for block in blocks:
        match = re.match(r"(FAIL|ERROR): (\S+) \(([^)]+)\)", block)
        if match:
            body = block.split("\n" + "-" * 70 + "\n", 1)[-1]
            yield f"{match[1]} {match[3]}", body.strip()[-3000:]


def main():
    script, *options = sys.argv[1:]
    command = [sys.executable, *options, script, "-v"]
    result = subprocess.run(command, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    for title, body in failures(result.stderr):
        print(f"::error title={escape(title, True)}::{escape(body)}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
