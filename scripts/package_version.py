"""Print the release version; fail if the version sources disagree.

The version lives in `[workspace.package]` of Cargo.toml, in `[package]` of
bindings/python/Cargo.toml (the extension reports it as
`cfd_craft._native.__version__`) and in `[project]` of pyproject.toml. Cargo
writes pre-releases as `0.3.0-dev.1`, Python as `0.3.0.dev1`; both are
compared in Python's spelling. A release tag must equal `v` plus the printed
version. Runs on every supported Python (3.10+) and platform.
"""

import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: no tomllib
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]
PRE = {"dev": ".dev", "alpha": "a", "beta": "b", "rc": "rc"}


def read(name):
    # UTF-8 explicitly: the locale encoding (cp1252 on Windows) cannot
    # decode every file.
    return (ROOT / name).read_text(encoding="utf-8")


def table_version(name, table):
    """`version` of the TOML table `table` (dotted) in file `name`."""
    text = read(name)
    if tomllib is not None:
        data = tomllib.loads(text)
        for key in table.split("."):
            data = data[key]
        return data["version"]
    # Without tomllib: the `version = "..."` line of that table's section.
    section = re.search(
        rf"^\[{re.escape(table)}\][ \t]*$(.*?)(?=^\[|\Z)", text, re.M | re.S
    )
    found = section and re.search(r'^version\s*=\s*"([^"]+)"', section.group(1), re.M)
    if not found:
        sys.exit(f"CFD-R001 release.version: no version in [{table}] of {name}")
    return found.group(1)


def python_spelling(cargo):
    """`0.3.0-dev.1` -> `0.3.0.dev1`; a plain release is unchanged."""
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:-(dev|alpha|beta|rc)\.(\d+))?", cargo)
    if not match:
        sys.exit(f"CFD-R001 release.version: unsupported Cargo version {cargo!r}")
    release, kind, number = match.groups()
    return release if kind is None else f"{release}{PRE[kind]}{number}"


def versions():
    """The three version sources in Python's spelling; exits if they disagree."""
    found = {
        "Cargo.toml": python_spelling(table_version("Cargo.toml", "workspace.package")),
        "bindings/python/Cargo.toml": python_spelling(
            table_version("bindings/python/Cargo.toml", "package")
        ),
        "pyproject.toml": table_version("pyproject.toml", "project"),
    }
    if len(set(found.values())) != 1:
        sys.exit(f"CFD-R001 release.version: version sources disagree: {found}")
    return found["pyproject.toml"]


if __name__ == "__main__":
    print(versions())
