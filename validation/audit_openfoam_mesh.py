#!/usr/bin/env python3
"""Independent geometry/phi/wall-distance audit of generated Cartesian cases.

Only axis-aligned, conforming hexahedra with quadrilateral faces are supported.
This is deliberately not an arbitrary OpenFOAM mesh reader.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
import openfoam_backend as backend
from backstep_data import sha256


def require(ok, field, message):
    backend.require(ok, field, message, "CFD-X011")


def payload(path):
    text = Path(path).read_text()
    require(
        re.search(r"\bformat\s+ascii\s*;", text),
        "mesh." + Path(path).name,
        "ASCII required",
    )
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    match = re.search(r"^\s*(\d+)\s*\(", text, re.M)
    require(match is not None, "mesh." + Path(path).name, "missing counted list")
    rest = text[match.end() :].strip()
    require(rest.endswith(")"), "mesh." + Path(path).name, "unterminated list")
    return int(match[1]), rest[:-1]


def labels(path):
    count, text = payload(path)
    tokens = text.split()
    require(
        len(tokens) == count and all(re.fullmatch(r"\d+", x) for x in tokens),
        "mesh." + Path(path).name,
        "invalid label count/value",
    )
    return np.array(tokens, dtype=np.int64)


def cartesian_mesh(case):
    directory = Path(case) / "constant/polyMesh"
    count, text = payload(directory / "points")
    tokens = text.replace("(", " ").replace(")", " ").split()
    require(
        0 < count <= 3000000 and len(tokens) == count * 3,
        "mesh.points",
        "wrong count or size outside supported scope",
    )
    points = np.array(tokens, dtype=float).reshape(count, 3)
    require(np.isfinite(points).all(), "mesh.points", "nonfinite coordinate")
    count, text = payload(directory / "faces")
    pattern = r"4\s*\((\s*\d+(?:\s+\d+){3}\s*)\)"
    rows = re.findall(pattern, text)
    require(
        0 < count <= 5000000
        and len(rows) == count
        and not re.sub(pattern, "", text).strip(),
        "mesh.faces",
        "only complete quadrilateral lists are supported",
    )
    faces = np.array([r.split() for r in rows], dtype=np.int64)
    require(
        faces.min() >= 0 and faces.max() < len(points),
        "mesh.faces",
        "invalid point label",
    )
    owner = labels(directory / "owner")
    neighbour = labels(directory / "neighbour")
    require(
        len(owner) == len(faces) and len(neighbour) <= len(owner),
        "mesh.owner",
        "face count mismatch",
    )
    cells = int(owner.max()) + 1
    require(0 < cells <= 1000000, "mesh.cells", "outside supported scope")
    require(
        not len(neighbour)
        or (neighbour.max() < cells and np.all(owner[: len(neighbour)] != neighbour)),
        "mesh.neighbour",
        "invalid cell labels",
    )
    vertices = points[faces]
    low = vertices.min(axis=1)
    high = vertices.max(axis=1)
    widths = high - low
    require(
        np.all(np.sum(widths <= 1e-12, axis=1) == 1),
        "mesh.faces",
        "faces must be aligned with coordinate axes",
    )
    corners = np.isclose(vertices, high[:, None, :], atol=1e-12, rtol=0)
    require(
        np.all(corners | np.isclose(vertices, low[:, None, :], atol=1e-12, rtol=0)),
        "mesh.faces",
        "nonrectangular face",
    )
    codes = np.sum(corners * np.array([1, 2, 4]), axis=2)
    require(
        np.all(np.diff(np.sort(codes, axis=1), axis=1) > 0),
        "mesh.faces",
        "duplicated or nonrectangular corners",
    )
    minimum = np.full((cells, 3), np.inf)
    maximum = np.full((cells, 3), -np.inf)
    np.minimum.at(minimum, owner, low)
    np.maximum.at(maximum, owner, high)
    np.minimum.at(minimum, neighbour, low[: len(neighbour)])
    np.maximum.at(maximum, neighbour, high[: len(neighbour)])
    lengths = maximum - minimum
    require(
        np.isfinite(lengths).all() and np.all(lengths > 0),
        "mesh.cells",
        "empty or nonfinite cell bounds",
    )
    require(
        np.all(
            np.bincount(owner, minlength=cells)
            + np.bincount(neighbour, minlength=cells)
            == 6
        ),
        "mesh.cells",
        "every supported hexahedron must have six faces",
    )
    volumes = np.prod(lengths, axis=1)
    return {
        "cells": cells,
        "owner": owner,
        "neighbour": neighbour,
        "volumes": volumes,
        "lengths": lengths,
        "face_centres": (low + high) / 2,
        "cell_centres": (minimum + maximum) / 2,
        "boundary": (directory / "boundary").read_text(),
    }


def patches(mesh, kind):
    names = (
        ["lid", "walls", "span"]
        if kind == "cavity"
        else [
            "inlet",
            "outlet",
            "lowerWall",
            "stepWall",
            "upperWall",
            "upstreamWall",
            "span",
        ]
    )
    result = {}
    for name in names:
        definition = backend.block(mesh["boundary"], name)
        count = int(re.search(r"\bnFaces\s+(\d+)", definition)[1])
        start = int(re.search(r"\bstartFace\s+(\d+)", definition)[1])
        require(
            len(mesh["neighbour"]) <= start <= start + count <= len(mesh["owner"]),
            "mesh.boundary." + name,
            "invalid patch range",
        )
        result[name] = (start, count)
    all_faces = [
        i for start, count in result.values() for i in range(start, start + count)
    ]
    require(
        sorted(all_faces) == list(range(len(mesh["neighbour"]), len(mesh["owner"]))),
        "mesh.boundary",
        "patches overlap or omit faces",
    )
    return result


def vector_values(text, count, field):
    uniform = re.search(r"\bvalue\s+uniform\s*\(([^()]*)\)\s*;", text)
    if uniform:
        rows = np.array([float(v) for v in uniform[1].split()])
        require(rows.shape == (3,), field, "wrong vector width")
        values = np.tile(rows, (count, 1))
    else:
        match = re.search(
            r"\bvalue\s+nonuniform\s+List<vector>\s+(\d+)\s*\((.*?)\)\s*;", text, re.S
        )
        require(
            match is not None and int(match[1]) == count, field, "wrong vector count"
        )
        tokens = match[2].replace("(", " ").replace(")", " ").split()
        require(len(tokens) == count * 3, field, "wrong vector width")
        values = np.array(tokens, dtype=float).reshape(count, 3)
    require(np.isfinite(values).all(), field, "nonfinite wall traction")
    return values


def cell_divergence(mesh, flux):
    flux = np.asarray(flux, dtype=float)
    require(
        flux.shape == (len(mesh["owner"]),) and np.isfinite(flux).all(),
        "fields.phi",
        "invalid face flux",
    )
    total = np.zeros(mesh["cells"])
    np.add.at(total, mesh["owner"], flux)
    np.add.at(total, mesh["neighbour"], -flux[: len(mesh["neighbour"])])
    return total / mesh["volumes"]


def checked_wall_distances(mesh, parts, metadata):
    claimed = metadata["wall_first_cell_height_h"]
    require(
        set(claimed) == {"lowerWall", "stepWall", "upperWall", "upstreamWall"},
        "mesh.wall_first_cell_height_h",
        "all four solid walls are required",
    )
    distances = {}
    for name, full_height in claimed.items():
        start, count = parts[name]
        faces = slice(start, start + count)
        axis = 0 if name == "stepWall" else 1
        distance = abs(
            mesh["cell_centres"][mesh["owner"][faces], axis]
            - mesh["face_centres"][faces, axis]
        )
        require(
            count > 0
            and np.isfinite(full_height)
            and full_height > 0
            and np.allclose(
                2 * distance, full_height * metadata["height_m"], rtol=1e-9, atol=1e-12
            ),
            "mesh.wall_first_cell_height_h." + name,
            "generated height differs from the actual mesh",
        )
        distances[name] = distance
    return distances


def audit(run):
    run = Path(run)
    record = backend.verify(run)
    require(
        record["numerical"] is not None,
        "run.numerical",
        "no final iteration field to audit",
    )
    case = run / "case"
    latest = record["numerical"]["final_time_directory"]
    mesh = cartesian_mesh(case)
    parts = patches(mesh, record["case"])
    metadata = record["case_metadata"]
    require(mesh["cells"] == metadata["cells"], "mesh.cells", "metadata mismatch")
    text = (case / latest / "phi").read_text()
    count = len(mesh["neighbour"])
    internal = np.array(backend.scalar_value(text, "internalField", count))
    all_flux = np.zeros(len(mesh["owner"]))
    all_flux[:count] = internal
    boundary = backend.block(text, "boundaryField")
    for name, (start, count) in parts.items():
        if name == "span":
            continue
        flux = backend.scalar_value(backend.block(boundary, name), "value", count)
        all_flux[start : start + count] = flux
    height = metadata.get("height_m", 1.0)
    speed = metadata.get("reference_speed_m_s", 1.0)
    divergence = cell_divergence(mesh, all_flux) * height / speed
    continuity = {
        "maximum_abs_divergence_h_over_u": float(max(abs(divergence))),
        "volume_weighted_rms_divergence_h_over_u": float(
            np.sqrt(np.sum(divergence**2 * mesh["volumes"]) / sum(mesh["volumes"]))
        ),
        "target_max": 1e-4,
        "passed": bool(max(abs(divergence)) <= 1e-4),
    }
    wall = None
    if metadata.get("mesh_family") == "wall-resolved":
        traction = backend.block(
            (case / latest / "wallShearStress").read_text(), "boundaryField"
        )
        wall = {"target_y_plus_max": 1.0, "patches": {}, "passed": True}
        nu = speed * height / metadata["reynolds"]
        for name, distance in checked_wall_distances(mesh, parts, metadata).items():
            start, count = parts[name]
            axis = 0 if name == "stepWall" else 1
            stress = vector_values(
                backend.block(traction, name), count, "wallShearStress." + name
            )
            stress[:, axis] = 0
            yplus = np.sqrt(np.linalg.norm(stress, axis=1)) * distance / nu
            passed = bool(max(yplus) <= 1)
            wall["patches"][name] = {
                "faces": count,
                "first_cell_centre_distance_h": float(np.median(distance) / height),
                "maximum_y_plus": float(max(yplus)),
                "median_y_plus": float(np.median(yplus)),
                "passed": passed,
            }
            wall["passed"] &= passed
    expected_volume = 0.1 if record["case"] == "cavity" else 48.2
    require(
        abs(sum(mesh["volumes"]) - expected_volume) <= 1e-8,
        "mesh.volume",
        "wrong represented domain",
    )
    return {
        "schema_version": "cfd-craft.cartesian-audit/0.1",
        "status": "evaluated",
        "passed": continuity["passed"] and (wall is None or wall["passed"]),
        "numerical_passed": record["passed"],
        "cells": mesh["cells"],
        "represented_volume_m3": float(sum(mesh["volumes"])),
        "local_continuity": continuity,
        "wall_resolution": wall,
        "run_manifest_sha256": sha256(run / "manifest.json"),
        "implementation_sha256": sha256(__file__),
        "meaning": "independent mesh/face-flux and wall-distance checks; no momentum/turbulence residual reconstruction or physical-validation claim",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        result = audit(args.run)
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        result = {
            "status": "invalid",
            "passed": False,
            "error": backend.diagnostic(exc, "audit"),
        }
    if args.output.exists():
        print(json.dumps({"passed": False, "error": "CFD-E062 output: file exists"}))
        return 1
    backend.write_json(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
