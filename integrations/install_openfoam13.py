#!/usr/bin/env python3
"""Stage the tested public Foundation-13 Ubuntu package without root privileges.

OpenFOAM is separately licensed GPL software; no OpenFOAM executable or source
is part of this repository. This utility supports Ubuntu 24.04 x86_64.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path

URL = "https://dl.openfoam.org/ubuntu/dists/noble/main/binary-amd64/openfoam13_20260407_amd64.deb"
SHA256 = "9a491909372dd3de79d6fa8980d7fe6c9c1624da49cd14d61675ecacf4fdbcc2"
SIZE = 118586852


def validate(package):
    package = Path(package)
    if (
        package.stat().st_size != SIZE
        or hashlib.sha256(package.read_bytes()).hexdigest() != SHA256
    ):
        raise ValueError("CFD-X002 runtime.package: package size/SHA-256 mismatch")


def install(output, package_file=None):
    if not shutil.which("dpkg-deb"):
        raise ValueError("CFD-X002 runtime.dpkg-deb: Ubuntu dpkg-deb is required")
    output = Path(output).resolve()
    try:
        output.mkdir()
    except FileExistsError as exc:
        raise ValueError(
            f"CFD-E062 output: directory already exists: {output}"
        ) from exc
    package = (
        Path(package_file).resolve() if package_file else output / "openfoam13.deb"
    )
    if not package_file:
        total = 0
        with (
            urllib.request.urlopen(URL, timeout=45) as source,
            package.open("wb") as target,
        ):
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > SIZE:
                    raise ValueError("CFD-X002 runtime.package: oversized download")
                target.write(chunk)
    validate(package)
    subprocess.run(
        ["dpkg-deb", "-x", str(package), str(output / "runtime")],
        check=True,
        timeout=120,
    )
    root = output / "runtime/opt/openfoam13"
    record = {
        "source": URL,
        "package_sha256": SHA256,
        "package_bytes": SIZE,
        "foam_root": str(root),
        "version": "13",
        "package_version": "20260407",
        "license": "GPL, separately distributed by the OpenFOAM Foundation",
        "source_and_license": "https://openfoam.org/download/13-ubuntu/",
    }
    (output / "package.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument(
        "--package-file", type=Path, help="optional local copy of the exact pinned .deb"
    )
    args = ap.parse_args()
    try:
        print(json.dumps(install(args.output, args.package_file), indent=2))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        message = str(exc)
        if not message.startswith("CFD-"):
            message = f"CFD-X002 runtime.install: {message}"
        print(json.dumps({"passed": False, "error": message}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
