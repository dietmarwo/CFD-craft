#!/usr/bin/env python3
"""Zip a run tree with its directory entries and check the extracted copy.

File-only copies, such as artifact uploads or file indexes, drop empty
directories. An OpenFOAM archive's progress record can name a time directory
that holds no files, and the verifier then rejects such a copy although the
original verifies. This zip keeps every directory entry and rejects symlinks.
Every sealed archive in the extracted copy must verify exactly as the original
does; an original that fails stays failed in the copy.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
import openfoam_backend as backend

SCHEMA = "cfd-craft.evidence-archive/0.1"


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-B004 sweep.archive.{field}: {message}")


def pack(root, destination):
    """Write every file and directory below root; return the number of entries."""
    root, destination = Path(root), Path(destination)
    require(root.is_dir() and not root.is_symlink(), "source", "directory required")
    # Member names start at the resolved root's own name, never with "..".
    root = root.resolve()
    require(
        not destination.exists() and not destination.is_symlink(),
        "output",
        "new file required",
    )
    paths = sorted(root.rglob("*"))
    for path in paths:
        require(not path.is_symlink(), str(path.relative_to(root)), "symlink rejected")
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in [root, *paths]:
            archive.write(path, str(path.relative_to(root.parent)))
    return len(paths) + 1


def tree(root):
    """Every entry below root: relative path, kind and file digest."""
    root = Path(root)
    return [
        [
            str(path.relative_to(root)),
            "directory" if path.is_dir() else "file",
            None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest(),
        ]
        for path in sorted(root.rglob("*"))
    ]


def verify_tree(root, binary):
    """Integrity of every sealed archive below root, native or OpenFOAM.

    Error texts name paths relative to root, so an original and its copy that
    fail in the same way compare equal."""
    root = Path(root)
    prefixes = sorted({str(root.resolve()), str(root)}, key=len, reverse=True)
    rows = []
    for marker in sorted(root.rglob("complete.json")):
        directory = marker.parent
        row = dict(archive=str(directory.relative_to(root)), verified=False)
        try:
            manifest = json.loads((directory / "manifest.json").read_text())
            row["schema"] = manifest.get("schema_version")
            if row["schema"] == "cfd-craft.external-archive/0.1":
                backend.verify(directory)
            elif row["schema"] == "cfd-craft.manifest/0.1":
                # The native reporter checks the manifest, hashes and summary.
                done = subprocess.run(
                    [str(binary), "report", str(directory)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                row["report_returncode"] = done.returncode
                require(
                    done.returncode in (0, 2),
                    row["archive"],
                    done.stderr.strip()[-300:] or "native report failed",
                )
            else:
                raise ValueError(f"CFD-B004 sweep.archive.schema: {row['schema']}")
            row["verified"] = True
        except (ValueError, OSError, KeyError, TypeError) as exc:
            text = str(exc)
            for prefix in prefixes:
                text = text.replace(prefix, "<tree>")
            row["error"] = text
        rows.append(row)
    return rows


def round_trip(root, destination, binary):
    root, destination = Path(root), Path(destination)
    # A missing reporter would fail original and copy alike and pass the check.
    binary = Path(binary).resolve()
    require(binary.is_file(), "binary", f"native reporter not found: {binary}")
    entries = pack(root, destination)
    root = root.resolve()
    original = verify_tree(root, binary)
    require(bool(original), "archives", "no sealed archive found")
    listing = tree(root)
    with tempfile.TemporaryDirectory(prefix="cfd-evidence-") as temp:
        with zipfile.ZipFile(destination) as archive:
            for info in archive.infolist():
                name = Path(info.filename)
                require(
                    not name.is_absolute() and ".." not in name.parts,
                    "member",
                    f"unsafe member {info.filename}",
                )
            archive.extractall(temp)
        copy = verify_tree(Path(temp) / root.name, binary)
        copied = tree(Path(temp) / root.name)
    return dict(
        schema_version=SCHEMA,
        zip=destination.name,
        entries=entries,
        archives=len(original),
        verified=sum(r["verified"] for r in original),
        failed=[r for r in original if not r["verified"]],
        tree_identical=copied == listing,
        missing_in_copy=sorted({e[0] for e in listing} - {e[0] for e in copied})[:20],
        round_trip_identical=copy == original and copied == listing,
        differences=[dict(archives=[len(original), len(copy)])]
        if len(copy) != len(original)
        else [
            dict(original=a, copy=b)
            for a, b in zip(original, copy, strict=True)
            if a != b
        ],
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("zip", type=Path)
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/cfd-craft")
    args = ap.parse_args()
    try:
        report = round_trip(args.root, args.zip, args.binary)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        report = dict(
            schema_version=SCHEMA,
            round_trip_identical=False,
            error=str(exc)
            if str(exc).startswith("CFD-")
            else f"CFD-B004 sweep.archive.execution: {exc}",
        )
    print(json.dumps(report, indent=2))
    return 0 if report["round_trip_identical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
