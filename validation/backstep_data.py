#!/usr/bin/env python3
"""Fetch and parse the unchanged TMR Driver--Seegmiller measurements.

Raw measurements are downloaded explicitly, never replaced by a test fixture.
The x/H=-4 profile is an input; the four downstream profiles are evaluation data.
"""

import argparse
import hashlib
import json
import math
import re
import urllib.request
from pathlib import Path

BASE = "https://tmbwg.github.io/turbmodels/Backstep_validation/"
FILES = {
    "cp.expnew.dat": "2b3ec9f8d8025b958d6ddcf6767daaf3c93083d45ef350a8cf9c4b46f93a882a",
    "cf.exp.dat": "cd9b6434b7956bc58e859de6af654cd7f891e25303babf1dd8633d6c58f74276",
    "profiles.exp.dat": "23e8b44db52bfc36c66af6b743a4080c34f0165eb213a3db29c0914e12cf598d",
}


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-D001 {field}: {message}")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def profiles(text):
    result = {}
    station = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "variables")):
            continue
        if line.startswith("zone"):
            match = re.fullmatch(r'zone,t="exp, x/H=(-?\d+)"', line)
            require(match is not None, "profiles.zone", "unrecognized station")
            station = int(match[1])
            require(station not in result, "profiles.zone", "duplicate station")
            result[station] = []
            continue
        require(station is not None, "profiles", "data before station")
        try:
            row = [float(x) for x in line.split()]
        except ValueError as exc:
            raise ValueError("CFD-D001 profiles.row: nonnumeric value") from exc
        require(len(row) == 11, "profiles.row", "expected 11 columns")
        require(all(math.isfinite(x) for x in row), "profiles.row", "nonfinite value")
        require(row[0].is_integer(), "profiles.sample_id", "noninteger identity")
        result[station].append(row)
    require(
        set(result) == {-4, 1, 4, 6, 10}, "profiles.stations", "unexpected stations"
    )
    for station, rows in result.items():
        require(len(rows) >= 10, f"profiles[{station}]", "too few measurements")
        require(
            len({r[0] for r in rows}) == len(rows), "profiles.sample_id", "duplicate"
        )
        require(
            all(a[1] < b[1] for a, b in zip(rows, rows[1:], strict=False)),
            "profiles.y_over_h",
            "positions must increase strictly",
        )
    return result


def skin_friction(text):
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "variables")):
            continue
        try:
            row = [float(x) for x in line.split()]
        except ValueError as exc:
            raise ValueError("CFD-D001 cf.row: nonnumeric value") from exc
        require(len(row) == 3, "cf.row", "expected x/H, Cf and reported error")
        require(all(math.isfinite(x) for x in row), "cf.row", "nonfinite value")
        require(row[2] > 0, "cf.reported_error", "must be positive")
        rows.append(row)
    require(len(rows) >= 10, "cf", "too few measurements")
    require(
        all(a[0] < b[0] for a, b in zip(rows, rows[1:], strict=False)),
        "cf.x_over_h",
        "positions must increase strictly",
    )
    return rows


def load(directory):
    directory = Path(directory)
    for name, digest in FILES.items():
        require(not (directory / name).is_symlink(), name, "symlinks are not data")
        try:
            actual = sha256(directory / name)
        except OSError as exc:
            raise ValueError(f"CFD-D001 {name}: measurement file unavailable") from exc
        require(actual == digest, name, "raw SHA-256 mismatch")
    return {
        "profiles": profiles((directory / "profiles.exp.dat").read_text()),
        "cf": skin_friction((directory / "cf.exp.dat").read_text()),
        "raw_sha256": FILES.copy(),
        "reference": "Driver and Seegmiller (1985), doi:10.2514/3.8890; TMR 2DBFS",
        "reattachment_x_over_h": 6.26,
        "reattachment_reported_uncertainty_h": 0.10,
    }


def fetch(directory):
    directory = Path(directory)
    directory.mkdir()
    record = {"schema_version": "cfd-craft.reference-download/0.1", "files": []}
    try:
        for name, digest in FILES.items():
            request = urllib.request.Request(
                BASE + name, headers={"User-Agent": "CFD-craft/0.1"}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(1024 * 1024 + 1)
            require(len(data) <= 1024 * 1024, name, "unexpectedly large download")
            require(
                hashlib.sha256(data).hexdigest() == digest, name, "download changed"
            )
            (directory / name).write_bytes(data)
            record["files"].append({"name": name, "url": BASE + name, "sha256": digest})
        load(directory)
        record["status"] = "verified_raw_measurements"
    except Exception as exc:
        record.update(status="failed", error=str(exc))
        raise
    finally:
        (directory / "download.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        print(json.dumps(fetch(args.output), indent=2))
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
