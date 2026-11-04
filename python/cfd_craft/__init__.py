"""In-process, bounded CFD summaries; native CLI for fields and archives."""

import importlib.metadata
import json
import os
from . import _native

try:
    __version__ = importlib.metadata.version("cfd-craft")
except importlib.metadata.PackageNotFoundError:  # not installed as a distribution
    __version__ = _native.__version__


class CfdError(ValueError):
    """Rejected input, including the shared native diagnostic report when present."""

    def __init__(self, message):
        try:
            self.report = json.loads(message)
        except ValueError:
            self.report = None
        self.diagnostics = (self.report or {}).get("diagnostics", [])
        super().__init__(message)


def _rejected(path, message):
    """A CfdError carrying a coded report like the native diagnostics."""
    report = {
        "valid": False,
        "diagnostics": [
            {
                "code": "CFD-P001",
                "severity": "error",
                "path": path,
                "message": message,
            }
        ],
    }
    return CfdError(json.dumps(report))


def case_bytes(case):
    """Preserve raw JSON bytes for native duplicate/unknown-field validation."""
    if isinstance(case, bytes):
        return case
    if isinstance(case, str):
        return case.encode("utf-8")
    try:
        text = json.dumps(case, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        # NaN/infinity or a value JSON cannot represent.
        raise _rejected("python.case", str(error)) from None
    return text.encode("utf-8")


def describe():
    """Return native schemas, supported interface operations and build identity."""
    return json.loads(_native.describe_json())


def check(case):
    """Return the native preflight report: validity and coded diagnostics.

    The checks are the CLI's (strict parsing, geometry, sources, receptors and
    the host-memory estimate); the report omits the CLI's geometry evidence and
    its {"check": ...} wrapper.
    """
    return json.loads(_native.check_json(case_bytes(case)))


def simulate(case, *, cancel_file=None):
    """Run in-process without the GIL and return a native summary dictionary.

    Inspect termination, assessment, checks and experimental_validation before
    using receptor values. Incomplete runs remain results, not successes.
    Creating cancel_file stops cooperatively. Ctrl-C raises KeyboardInterrupt
    after the worker has stopped. Each call has its own bounded Rayon pool.
    """
    try:
        return json.loads(
            _native.simulate_json(
                case_bytes(case),
                None if cancel_file is None else os.fsdecode(cancel_file),
            )
        )
    except _native.NativeError as error:
        raise CfdError(str(error)) from None
