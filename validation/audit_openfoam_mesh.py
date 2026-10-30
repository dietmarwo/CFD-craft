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


def read(path, field):
    try:
        return Path(path).read_text()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"CFD-X011 {field}: cannot read {Path(path).name}") from exc


def floats(tokens, field):
    try:
        values = np.array(tokens, dtype=float)
    except ValueError as exc:
        raise ValueError(f"CFD-X011 {field}: nonnumeric value") from exc
    require(np.isfinite(values).all(), field, "nonfinite value")
    return values


def section(text, key, field):
    """The body of `key { ... }`; this auditor's own reader, not the adapter's."""
    match = re.search(r"(?<![\w.])" + re.escape(key) + r"\s*\{", text)
    require(match is not None, field, "missing block")
    depth = 1
    for i in range(match.end(), len(text)):
        depth += (text[i] == "{") - (text[i] == "}")
        if depth == 0:
            return text[match.end() : i]
    require(False, field, "unterminated block")


def scalars(text, key, count, field):
    uniform = re.search(r"\b" + key + r"\s+uniform\s+([^\s;]+)\s*;", text)
    if uniform:
        return np.full(count, floats([uniform[1]], field)[0])
    match = re.search(
        r"\b" + key + r"\s+nonuniform\s+List<scalar>\s+(\d+)\s*\((.*?)\)\s*;",
        text,
        re.S,
    )
    require(match is not None, field, "expected an ASCII scalar list")
    tokens = match[2].split()
    require(int(match[1]) == count == len(tokens), field, "wrong value count")
    return floats(tokens, field)


def strip_comments(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


def payload(path):
    field = "mesh." + Path(path).name
    text = strip_comments(read(path, field))
    header = re.search(r"\bFoamFile\s*\{([^{}]*)\}", text)
    require(
        header is not None and re.search(r"\bformat\s+ascii\s*;", header[1]),
        field,
        "ASCII required",
    )
    body = text[header.end() :]
    match = re.search(r"^\s*(\d+)\s*\(", body, re.M)
    require(match is not None, field, "missing counted list")
    rest = body[match.end() :].strip()
    require(rest.endswith(")"), field, "unterminated list")
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
    group = r"\(\s*([^\s()]+)\s+([^\s()]+)\s+([^\s()]+)\s*\)"
    rows = re.findall(group, text)
    require(
        0 < count <= 3000000
        and len(rows) == count
        and not re.sub(group, "", text).strip(),
        "mesh.points",
        "expected the counted number of (x y z) groups within the supported scope",
    )
    points = floats(rows, "mesh.points")
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
        or (neighbour.max() < cells and np.all(owner[: len(neighbour)] < neighbour)),
        "mesh.neighbour",
        "invalid cell labels or owner not below neighbour",
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
    centres = (minimum + maximum) / 2
    face_centres = (low + high) / 2
    # Area vectors from the stored vertex order point out of the owner cell.
    area = 0.5 * np.sum(np.cross(vertices, np.roll(vertices, -1, axis=1)), axis=1)
    toward = face_centres - centres[owner]
    toward[: len(neighbour)] = centres[neighbour] - centres[owner[: len(neighbour)]]
    require(
        np.all(np.sum(area * toward, axis=1) > 0),
        "mesh.faces",
        "face orientation does not point from owner to neighbour or out of the domain",
    )
    return {
        "cells": cells,
        "owner": owner,
        "neighbour": neighbour,
        "volumes": volumes,
        "lengths": lengths,
        "face_centres": face_centres,
        "cell_centres": centres,
        "boundary": strip_comments(read(directory / "boundary", "mesh.boundary")),
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
        field = "mesh.boundary." + name
        definition = section(mesh["boundary"], name, field)
        count = re.search(r"\bnFaces\s+(\d+)\s*;", definition)
        start = re.search(r"\bstartFace\s+(\d+)\s*;", definition)
        require(count is not None and start is not None, field, "missing face range")
        count, start = int(count[1]), int(start[1])
        require(
            len(mesh["neighbour"]) <= start <= start + count <= len(mesh["owner"]),
            field,
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
        rows = floats(uniform[1].split(), field)
        require(rows.shape == (3,), field, "wrong vector width")
        return np.tile(rows, (count, 1))
    match = re.search(
        r"\bvalue\s+nonuniform\s+List<vector>\s+(\d+)\s*\((.*?)\)\s*;", text, re.S
    )
    require(match is not None and int(match[1]) == count, field, "wrong vector count")
    group = r"\(\s*([^\s()]+)\s+([^\s()]+)\s+([^\s()]+)\s*\)"
    rows = re.findall(group, match[2])
    require(
        len(rows) == count and not re.sub(group, "", match[2]).strip(),
        field,
        "wrong vector width",
    )
    return floats(rows, field)


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


def relative_cell_imbalance(mesh, flux):
    """abs(sum of face fluxes) over half the summed absolute face fluxes, per cell."""
    flux = np.asarray(flux, dtype=float)
    net = cell_divergence(mesh, flux) * mesh["volumes"]
    gross = np.zeros(mesh["cells"])
    np.add.at(gross, mesh["owner"], abs(flux))
    np.add.at(gross, mesh["neighbour"], abs(flux[: len(mesh["neighbour"])]))
    moving = gross > 0
    return float(max(abs(net[moving]) / (gross[moving] / 2), default=0.0))


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


def represented_domain(mesh, kind):
    # Cavity: 1 x 1 x 0.1 m. Backstep: (4*8 + 50*9) H^2 times a 0.1 H span.
    expected = 0.1 if kind == "cavity" else 48.2
    require(
        abs(sum(mesh["volumes"]) - expected) <= 1e-8,
        "mesh.volume",
        "wrong represented domain",
    )


def face_fluxes(mesh, parts, text):
    """Every face's stored flux; the empty span faces carry none."""
    internal = len(mesh["neighbour"])
    flux = np.zeros(len(mesh["owner"]))
    flux[:internal] = scalars(
        text, "internalField", internal, "fields.phi.internalField"
    )
    boundary = section(text, "boundaryField", "fields.phi.boundaryField")
    for name, (start, count) in parts.items():
        if name != "span":
            field = "fields.phi." + name
            flux[start : start + count] = scalars(
                section(boundary, name, field), "value", count, field
            )
    return flux


def local_continuity(mesh, flux, height, speed):
    divergence = cell_divergence(mesh, flux) * height / speed
    largest = float(max(abs(divergence)))
    return {
        "maximum_abs_divergence_h_over_u": largest,
        "volume_weighted_rms_divergence_h_over_u": float(
            np.sqrt(np.sum(divergence**2 * mesh["volumes"]) / sum(mesh["volumes"]))
        ),
        # Reported, not gated: unlike the gated measure it does not grow as cells shrink.
        "maximum_relative_cell_imbalance": relative_cell_imbalance(mesh, flux),
        "target_max": 1e-4,
        "passed": bool(largest <= 1e-4),
    }


def wall_resolution(mesh, parts, metadata, text):
    """max(y+) <=1 on every solid wall from the stored tangential wall traction."""
    traction = section(text, "boundaryField", "wallShearStress.boundaryField")
    height = metadata["height_m"]
    nu = metadata["reference_speed_m_s"] * height / metadata["reynolds"]
    wall = {"target_y_plus_max": 1.0, "patches": {}, "passed": True}
    for name, distance in checked_wall_distances(mesh, parts, metadata).items():
        start, count = parts[name]
        axis = 0 if name == "stepWall" else 1
        field = "wallShearStress." + name
        stress = vector_values(section(traction, name, field), count, field)
        stress[:, axis] = 0
        magnitude = np.linalg.norm(stress, axis=1)
        # An unsampled wall is written as zero traction and would pass trivially.
        require(magnitude.max() > 0, field, "zero tangential traction on every face")
        yplus = np.sqrt(magnitude) * distance / nu
        worst = int(np.argmax(yplus))
        passed = bool(yplus[worst] <= 1)
        wall["patches"][name] = {
            "faces": count,
            "first_cell_centre_distance_h": float(np.median(distance) / height),
            "maximum_y_plus": float(yplus[worst]),
            "maximum_y_plus_at_xy_over_h": [
                float(v) for v in mesh["face_centres"][start + worst, :2] / height
            ],
            "median_y_plus": float(np.median(yplus)),
            "passed": passed,
        }
        wall["passed"] &= passed
    return wall


def audit(run):
    run = Path(run)
    try:
        record = backend.verify(run)
    except OSError as exc:
        name = Path(exc.filename).name if exc.filename else "archive"
        raise ValueError(f"CFD-X006 archive: cannot read {name}") from exc
    if record["numerical"] is None:
        return {
            "schema_version": "cfd-craft.cartesian-audit/0.1",
            "status": "not_assessed",
            "passed": False,
            "reason": "CFD-X011 run.numerical: no final iteration field to audit",
            "run_manifest_sha256": sha256(run / "manifest.json"),
            "implementation_sha256": sha256(__file__),
        }
    case = run / "case"
    latest = record["numerical"]["final_time_directory"]
    mesh = cartesian_mesh(case)
    parts = patches(mesh, record["case"])
    metadata = record["case_metadata"]
    require(mesh["cells"] == metadata["cells"], "mesh.cells", "metadata mismatch")
    represented_domain(mesh, record["case"])
    flux = face_fluxes(mesh, parts, read(case / latest / "phi", "fields.phi"))
    continuity = local_continuity(
        mesh,
        flux,
        metadata.get("height_m", 1.0),
        metadata.get("reference_speed_m_s", 1.0),
    )
    wall = None
    if metadata.get("mesh_family") == "wall-resolved":
        path = case / latest / "wallShearStress"
        wall = wall_resolution(
            mesh, parts, metadata, read(path, "wallShearStress.boundaryField")
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
        "meaning": "independent mesh, face-flux and wall-traction readers; the archive seal is checked by the adapter's verifier. No momentum/turbulence residual reconstruction or physical-validation claim",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists() or not args.output.parent.is_dir():
        code = (
            "CFD-E062 output: file exists"
            if args.output.exists()
            else ("CFD-E063 output: parent directory does not exist")
        )
        print(json.dumps({"passed": False, "error": code}))
        return 1
    try:
        result = audit(args.run)
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        result = {
            "status": "invalid",
            "passed": False,
            "error": backend.diagnostic(exc, "audit"),
        }
    backend.write_json(args.output, result)
    print(json.dumps(result, indent=2))
    # Invalid input or archive is an error (1); an evaluated failure is evidence (2).
    return 1 if result["status"] == "invalid" else 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
