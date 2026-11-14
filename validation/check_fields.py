#!/usr/bin/env python3
"""Independent archived-field checks. Essential checks survive python -O."""

import hashlib
import json
from pathlib import Path
import struct
import sys
import math


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def finite(values, name):
    require(all(math.isfinite(v) for v in values), f"nonfinite values in {name}")


def flow_state_fingerprint(fields):
    """SHA-256 of the stored flow arrays: per array a little-endian u64 length,
    then its little-endian f64 values (velocity, pressure, k, epsilon)."""
    fingerprint = hashlib.sha256()
    for name in ("velocity", "pressure", "k", "epsilon"):
        values = fields[name]
        fingerprint.update(struct.pack("<Q", len(values)))
        for value in values:
            fingerprint.update(struct.pack("<d", value))
    return fingerprint.hexdigest()


def path_samples(receptor):
    """Independent equal-arc-length path positions and trapezoidal coefficients."""
    vertices = receptor["polyline_m"]
    spacing = receptor["sample_spacing_m"]
    height = receptor["height_m"]
    require(2 <= len(vertices) <= 4097, "path vertex count")
    require(
        math.isfinite(spacing) and spacing > 0 and math.isfinite(height),
        "path spacing/height",
    )
    lengths = [
        math.dist(a, b) for a, b in zip(vertices[:-1], vertices[1:], strict=True)
    ]
    require(
        all(math.isfinite(value) and value > 0 for value in lengths),
        "path segment lengths",
    )
    length = sum(lengths)
    require(math.isfinite(length / spacing), "path sample count overflow")
    intervals = max(1, math.ceil(length / spacing))
    require(intervals < 20001, "path sample budget")
    cumulative = [0.0]
    for value in lengths:
        cumulative.append(cumulative[-1] + value)
    points, distances, quadrature = [], [], []
    segment = 0
    for sample in range(intervals + 1):
        distance = length if sample == intervals else length * sample / intervals
        while segment + 2 < len(cumulative) and cumulative[segment + 1] < distance:
            segment += 1
        fraction = min(max((distance - cumulative[segment]) / lengths[segment], 0), 1)
        if sample == intervals:
            point = [*vertices[-1], height]
        else:
            point = [
                vertices[segment][a]
                + fraction * (vertices[segment + 1][a] - vertices[segment][a])
                for a in range(2)
            ] + [height]
        points.append(point)
        distances.append(distance)
        quadrature.append((0.5 if sample in {0, intervals} else 1.0) / intervals)
    return points, distances, quadrature


def path_weights(receptor, dx, cells, fluid, index):
    """Check complete segment supports before forming ordinary point weights."""
    points, distances, quadrature = path_samples(receptor)
    require(
        all(
            all(math.isfinite(p[a]) and 0 <= p[a] < cells[a] * dx[a] for a in range(3))
            for p in points
        ),
        "path outside domain",
    )
    height = receptor["height_m"]
    vertices = receptor["polyline_m"]
    for start, end in zip(vertices[:-1], vertices[1:], strict=True):
        cuts = [0.0, 1.0]
        for axis in range(2):
            delta = end[axis] - start[axis]
            if delta:
                cuts.extend(
                    t
                    for k in range(1, cells[axis])
                    if 0 < (t := (k * dx[axis] - start[axis]) / delta) < 1
                )
        cuts.sort()
        for low, high in zip(cuts[:-1], cuts[1:], strict=True):
            if low == high:
                continue
            t = (low + high) / 2
            p = [start[a] + t * (end[a] - start[a]) for a in range(2)] + [height]
            q = [min(math.floor(p[a] / dx[a]), cells[a] - 1) for a in range(3)]
            require(fluid[index(*q)], "path segment crosses a represented solid")
    weights = [
        receptor_weights(
            {"kind": "point", "id": receptor["id"], "point_m": p},
            dx,
            cells,
            fluid,
            index,
        )
        for p in points
    ]
    return points, distances, quadrature, weights


def receptor_weights(receptor, dx, cells, fluid, index):
    """Cell weights of a receptor, computed as the solver documents them."""
    nx, ny, nz = cells
    weights = {}
    if receptor["kind"] == "path":
        _, _, quadrature, samples = path_weights(receptor, dx, cells, fluid, index)
        for coefficient, sample_weights in zip(quadrature, samples, strict=True):
            for cell, weight in sample_weights.items():
                weights[cell] = weights.get(cell, 0) + coefficient * weight
    elif receptor["kind"] == "point":
        point = receptor["point_m"]
        base = [math.floor(point[a] / dx[a] - 0.5) for a in range(3)]
        frac = [point[a] / dx[a] - 0.5 - base[a] for a in range(3)]
        for k in range(2):
            for j in range(2):
                for i in range(2):
                    corner = [i, j, k]
                    q = [
                        min(max(base[a] + corner[a], 0), cells[a] - 1) for a in range(3)
                    ]
                    w = math.prod(
                        frac[a] if corner[a] else 1.0 - frac[a] for a in range(3)
                    )
                    if w > 1e-14:
                        cell = index(*q)
                        weights[cell] = weights.get(cell, 0.0) + w
    else:
        lo, hi = receptor["min_m"], receptor["max_m"]
        for k in range(nz):
            for j in range(ny):
                for i in range(nx):
                    center = [(i + 0.5) * dx[0], (j + 0.5) * dx[1], (k + 0.5) * dx[2]]
                    w = math.prod(
                        max(
                            min(hi[a], center[a] + 0.5 * dx[a])
                            - max(lo[a], center[a] - 0.5 * dx[a]),
                            0.0,
                        )
                        for a in range(3)
                    )
                    if w > 1e-14:
                        weights[index(i, j, k)] = w
    require(weights, f"receptor {receptor['id']} has no support")
    require(
        all(fluid[cell] for cell in weights),
        f"receptor {receptor['id']} samples a solid cell",
    )
    total = math.fsum(weights.values())
    return {cell: w / total for cell, w in weights.items()}


def inside_polygon(vertices, point):
    """Independent half-open horizontal ray crossings, local metric x/y."""
    x, y = point[:2]
    count = 0
    for a, b in zip(vertices, vertices[1:] + vertices[:1], strict=True):
        if (a[1] > y) != (b[1] > y):
            cross_x = (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            count += x < cross_x
    return count % 2 == 1


def particle_parameters(particle):
    """Independent spherical aerosol formulas in SI units at 293.15 K/101325 Pa."""
    diameter = particle["diameter_m"]
    density = particle["density_kg_m3"]

    def slip(d):
        kn = 2 * 6.6e-8 / d
        return 1 + kn * (1.257 + 0.4 * math.exp(-1.1 / kn))

    settling = particle.get("settling_velocity_m_s")
    if settling is None:
        settling = (
            (density - 1.204) * 9.80665 * diameter**2 * slip(diameter) / (18 * 1.81e-5)
        )
    target = (density - 1.204) / (1000 - 1.204) * diameter**2 * slip(diameter)
    lo, hi = 0.0, diameter * max(math.sqrt(density), 1)
    for _ in range(80):
        mid = (lo + hi) / 2
        if mid**2 * slip(mid) < target:
            lo = mid
        else:
            hi = mid
    return settling, diameter if density == 1000 else (lo + hi) / 2


def canopy_evidence(case, components, fluid, cells, dx, index):
    """Independent work of the staggered canopy sink in its face inner product."""
    nx, ny, nz = cells
    volume = math.prod(dx)
    cell_drag = [0.0] * len(fluid)
    coverage = {v["id"]: 0 for v in case["vegetation"]}
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                cell = index(i, j, k)
                if not fluid[cell]:
                    continue
                p = [(i + 0.5) * dx[0], (j + 0.5) * dx[1], (k + 0.5) * dx[2]]
                coefficient = 0.0
                for v in case["vegetation"]:
                    if all(v["min_m"][a] <= p[a] < v["max_m"][a] for a in range(3)):
                        coverage[v["id"]] += 1
                        coefficient += (
                            v["drag_coefficient"] * v["leaf_area_density_m2_m3"]
                        )
                velocity = []
                for a, (dims, face_values) in enumerate(components):
                    q = [i, j, k]
                    low = (q[2] * dims[1] + q[1]) * dims[0] + q[0]
                    q[a] += 1
                    if case["boundaries"]["xyz"[a]] == "periodic":
                        q[a] %= cells[a]
                    high = (q[2] * dims[1] + q[1]) * dims[0] + q[0]
                    velocity.append(0.5 * (face_values[low] + face_values[high]))
                cell_drag[cell] = coefficient * math.sqrt(
                    math.fsum(u * u for u in velocity)
                )
    power = 0.0
    force = [0.0, 0.0, 0.0]
    flow = case["flow"]
    if flow["kind"] == "neutral_rans":
        angle = math.radians(flow["direction_deg_from"])
        nominal = [-math.sin(angle), -math.cos(angle), 0.0]
    else:
        nominal = flow.get("velocity_m_s", flow.get("initial_velocity_m_s"))
    for a, (dims, face_values) in enumerate(components):
        periodic = case["boundaries"]["xyz"[a]] == "periodic"
        for k in range(dims[2]):
            for j in range(dims[1]):
                for i in range(dims[0]):
                    q = [i, j, k]
                    lo = q.copy()
                    lo[a] -= 1
                    hi = q.copy()
                    if periodic:
                        lo[a] %= cells[a]
                        hi[a] %= cells[a]
                    low = index(*lo) if 0 <= lo[a] < cells[a] else None
                    high = index(*hi) if 0 <= hi[a] < cells[a] else None
                    low = low if low is not None and fluid[low] else None
                    high = high if high is not None and fluid[high] else None
                    if low is not None and high is not None:
                        coefficient = 0.5 * (cell_drag[low] + cell_drag[high])
                        dual_volume = volume
                    elif (
                        not periodic
                        and case["boundaries"]["xyz"[a]] == "open"
                        and (
                            (q[a] == 0 and high is not None and nominal[a] < -1e-12)
                            or (
                                q[a] == cells[a]
                                and low is not None
                                and nominal[a] > 1e-12
                            )
                        )
                    ):
                        coefficient = cell_drag[low if low is not None else high]
                        dual_volume = volume * 0.5
                    else:
                        continue
                    fi = (k * dims[1] + j) * dims[0] + i
                    velocity = face_values[fi]
                    power += coefficient * velocity * velocity * dual_volume
                    force[a] -= coefficient * velocity * dual_volume
    return power, force, coverage


def check(path):
    path = Path(path)
    marker = json.loads((path / "complete.json").read_text())
    require(sha(path / "manifest.json") == marker["manifest_sha256"], "manifest hash")
    manifest = json.loads((path / "manifest.json").read_text())
    require(
        manifest.get("schema_version") == "cfd-craft.manifest/0.1",
        "manifest schema_version",
    )
    for name, digest in manifest["files"].items():
        require(Path(name).name == name, "artifact path")
        require(not (path / name).is_symlink(), "symlink artifact")
        require(sha(path / name) == digest, f"artifact hash: {name}")
    unlisted = (
        {entry.name for entry in path.iterdir()}
        - set(manifest["files"])
        - {"manifest.json", "complete.json"}
    )
    require(not unlisted, f"unlisted entries in the run directory: {sorted(unlisted)}")
    c = json.loads((path / "case.json").read_text())
    summary = json.loads((path / "summary.json").read_text())
    geometry = json.loads((path / "geometry.json").read_text())
    require(
        "fields.json" in manifest["files"],
        "full fields unavailable; cannot independently check",
    )
    s = json.loads((path / "fields.json").read_text())
    nx, ny, nz = c["grid"]["cells"]
    n = nx * ny * nz
    dx = [L / N for L, N in zip(c["domain"]["size_m"], [nx, ny, nz], strict=True)]
    volume = math.prod(dx)
    index = lambda i, j, k: (k * ny + j) * nx + i
    fluid = [True] * n
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                p = [(i + 0.5) * dx[0], (j + 0.5) * dx[1], (k + 0.5) * dx[2]]
                fluid[index(i, j, k)] = not any(
                    all(
                        lo <= x < hi
                        for lo, x, hi in zip(b["min_m"], p, b["max_m"], strict=True)
                    )
                    and ("footprint_m" not in b or inside_polygon(b["footprint_m"], p))
                    for b in c["geometry"]
                )
    require(
        hashlib.sha256(bytes(int(f) for f in fluid)).hexdigest()
        == geometry["mask_sha256"],
        "geometry mask differs from the case shapes",
    )
    shape_records = geometry.get("shapes")
    # Archives predating per-shape evidence hold boxes only; a polygon prism
    # always has evidence, and present evidence must cover exactly the case.
    require(
        shape_records is not None
        or not any("footprint_m" in shape for shape in c["geometry"]),
        "per-shape evidence missing for polygon prisms",
    )
    require(
        shape_records is None
        or set(shape_records) == {shape["id"] for shape in c["geometry"]},
        "per-shape evidence ID set differs from the case",
    )
    for shape in c["geometry"] if shape_records is not None else []:
        record = shape_records[shape["id"]]
        vertices = shape.get("footprint_m")
        area = (
            abs(
                math.fsum(
                    a[0] * b[1] - b[0] * a[1]
                    for a, b in zip(vertices, vertices[1:] + vertices[:1], strict=True)
                )
            )
            * 0.5
            if vertices
            else math.prod(shape["max_m"][a] - shape["min_m"][a] for a in (0, 1))
        )
        exact = area * (shape["max_m"][2] - shape["min_m"][2])
        count = 0
        members = []
        for k in range(nz):
            for j in range(ny):
                for i in range(nx):
                    p = [(v + 0.5) * d for v, d in zip((i, j, k), dx, strict=True)]
                    included = all(
                        lo <= x < hi
                        for lo, x, hi in zip(
                            shape["min_m"], p, shape["max_m"], strict=True
                        )
                    ) and (not vertices or inside_polygon(vertices, p))
                    if included:
                        count += 1
                        members.append((i, j, k))
        minimum_passage = None
        for q in members:
            for a in (0, 1):
                for sign in (-1, 1):
                    next_cell = list(q)
                    next_cell[a] += sign
                    width = 0
                    while 0 <= next_cell[a] < (nx, ny, nz)[a]:
                        if not fluid[index(*next_cell)]:
                            if width > 0:
                                minimum_passage = (
                                    width
                                    if minimum_passage is None
                                    else min(minimum_passage, width)
                                )
                            break
                        width += 1
                        next_cell[a] += sign
        require(
            record["narrowest_fluid_passage_cells"] == minimum_passage,
            "per-shape passage resolution",
        )
        require(record["solid_cells"] == count, "per-shape solid cells")
        require(
            abs(record["exact_volume_m3"] - exact) <= 1e-10 * max(exact, 1.0),
            "per-shape exact volume",
        )
        require(
            abs(record["represented_volume_m3"] - count * volume)
            <= 1e-10 * max(exact, 1.0),
            "per-shape represented volume",
        )
        require(
            abs(record["volume_error_m3"] - (count * volume - exact))
            <= 1e-10 * max(exact, 1.0),
            "per-shape volume error",
        )
    if summary.get("frozen_flow") is not None:
        evidence = summary["frozen_flow"]
        require(
            evidence["assessment"] == "steady_discrete_solution"
            and evidence["response_flow_updates"] == 0,
            "frozen flow preparation/update evidence",
        )
        require(
            flow_state_fingerprint(s) == evidence["flow_state_sha256"],
            "frozen flow state fingerprint",
        )
    finite(s["velocity"], "velocity")
    for name in ["pressure", "k", "epsilon"]:
        require(len(s[name]) == n, f"{name} has {len(s[name])} values for {n} cells")
        finite(s[name], name)
    if c["flow"]["kind"] == "neutral_rans":
        require(
            all(v > 0 for v, f in zip(s["k"], fluid, strict=True) if f),
            "k must be positive in fluid cells",
        )
        require(
            all(v > 0 for v, f in zip(s["epsilon"], fluid, strict=True) if f),
            "epsilon must be positive in fluid cells",
        )
    components = []
    offset = 0
    for a in range(3):
        dims = [nx, ny, nz]
        periodic = c["boundaries"]["xyz"[a]] == "periodic"
        if not periodic:
            dims[a] += 1
        count = math.prod(dims)
        values = s["velocity"][offset : offset + count]
        offset += count
        components.append((dims, values))
    require(offset == len(s["velocity"]), "face count")
    if c["flow"]["kind"] == "prescribed_uniform":
        for a, (dims, values) in enumerate(components):
            expected = c["flow"]["velocity_m_s"][a]
            require(
                all(
                    abs(v - expected) <= 1e-12 * max(1.0, abs(expected)) for v in values
                ),
                "face velocities differ from the prescribed velocity",
            )
    if any(v["leaf_area_density_m2_m3"] > 0 for v in c.get("vegetation", [])):
        drag_power, integrated_drag, coverage = canopy_evidence(
            c, components, fluid, [nx, ny, nz], dx, index
        )
        canopy = summary["vegetation"]
        require(
            canopy["drag_quadrature"] == "staggered_active_faces_dual_volumes",
            "unknown drag work convention",
        )
        require(
            canopy["volume_fluid_cells"] == coverage,
            "canopy coverage differs from case mask",
        )
        require(
            abs(canopy["drag_power_per_density_m5_s3"] - drag_power)
            <= 1e-11 * max(drag_power, 1e-300),
            "canopy drag power differs from fields",
        )
        for a in range(3):
            require(
                abs(
                    canopy["integrated_drag_acceleration_m4_s2"][a] - integrated_drag[a]
                )
                <= 1e-11 * max(abs(integrated_drag[a]), 1e-300),
                "canopy integrated drag differs from fields",
            )
    max_div = 0.0
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                if not fluid[index(i, j, k)]:
                    continue
                div = 0.0
                for a, (dims, v) in enumerate(components):
                    p = [i, j, k]
                    lo = (p[2] * dims[1] + p[1]) * dims[0] + p[0]
                    p[a] += 1
                    if c["boundaries"]["xyz"[a]] == "periodic":
                        p[a] %= [nx, ny, nz][a]
                    hi = (p[2] * dims[1] + p[1]) * dims[0] + p[0]
                    div += (v[hi] - v[lo]) / dx[a]
                max_div = max(max_div, abs(div))
    # The scale comes from the archived fields, not from the solver's own summary.
    speed = max((abs(v) for v in s["velocity"]), default=0.0)
    require(max_div <= 1e-7 * max(1.0, speed) / min(dx), "independent local continuity")
    scalar_results = []
    require(
        len(c["constituents"])
        == len(s["concentrations"])
        == len(s["budgets"])
        == len(summary["constituents"]),
        "constituent, concentration, budget and summary counts differ",
    )
    weights = {
        r["id"]: receptor_weights(r, dx, [nx, ny, nz], fluid, index)
        for r in c["receptors"]
    }
    for sp, values, budget, record in zip(
        c["constituents"],
        s["concentrations"],
        s["budgets"],
        summary["constituents"],
        strict=True,
    ):
        require(record["id"] == sp["id"], "summary constituent order")
        require(
            len(values) == n and all(math.isfinite(v) for v in values),
            "scalar dimensions/finiteness",
        )
        # Transport never changes a solid cell, so mass there cannot come from the solver.
        require(
            all(v == 0.0 for v, f in zip(values, fluid, strict=True) if not f),
            f"{sp['id']} has nonzero concentration in a solid cell",
        )
        require(
            set(record["receptors_kg_m3"]) == set(weights),
            f"receptor set of {sp['id']} differs from the case",
        )
        for rid, w in weights.items():
            value = math.fsum(values[cell] * wi for cell, wi in w.items())
            reported = record["receptors_kg_m3"][rid]
            require(
                abs(reported - value) <= 1e-12 * max(abs(value), 1e-300) + 1e-300,
                f"receptor {rid} of {sp['id']} differs from its field value",
            )
        path_receptors = [r for r in c["receptors"] if r["kind"] == "path"]
        require(
            set(record.get("paths", {})) == {r["id"] for r in path_receptors},
            "path result ID set differs from case",
        )
        require(
            sum(len(path_samples(r)[0]) for r in path_receptors) <= 50000,
            "total path sample budget",
        )
        for receptor in path_receptors:
            points, distances, quadrature, sample_weights = path_weights(
                receptor, dx, [nx, ny, nz], fluid, index
            )
            path_record = record["paths"][receptor["id"]]
            require(
                len(path_record["points_m"])
                == len(path_record["distance_m"])
                == len(path_record["concentrations_kg_m3"])
                == len(points),
                "path result sample count",
            )
            for expected, reported in zip(points, path_record["points_m"], strict=True):
                require(
                    len(reported) == 3
                    and all(
                        abs(a - b) <= 2e-12 * max(1.0, abs(a))
                        for a, b in zip(expected, reported, strict=True)
                    ),
                    "path sample position mismatch",
                )
            for expected, reported in zip(
                distances, path_record["distance_m"], strict=True
            ):
                require(
                    abs(expected - reported) <= 2e-12 * max(1.0, abs(expected)),
                    "path arc length mismatch",
                )
            recomputed = [
                math.fsum(values[cell] * weight for cell, weight in sample.items())
                for sample in sample_weights
            ]
            for expected, reported in zip(
                recomputed, path_record["concentrations_kg_m3"], strict=True
            ):
                require(
                    math.isfinite(reported)
                    and abs(expected - reported)
                    <= 1e-12 * max(abs(expected), 1e-300) + 1e-300,
                    "path sample concentration mismatch",
                )
            mean = math.fsum(
                value * coefficient
                for value, coefficient in zip(recomputed, quadrature, strict=True)
            )
            require(
                abs(mean - path_record["mean_kg_m3"])
                <= 2e-12 * max(abs(mean), 1e-300) + 1e-300,
                "path mean mismatch",
            )
            require(
                path_record["mean_kg_m3"] == record["receptors_kg_m3"][receptor["id"]],
                "path mean differs from receptor map",
            )
        mass = math.fsum(v for v, f in zip(values, fluid, strict=True) if f) * volume
        deposited = budget.get("deposited_kg", {})
        require(
            all(
                surface in {"ground", "roof", "vegetation"}
                and math.isfinite(value)
                and value >= 0
                for surface, value in deposited.items()
            ),
            "invalid cumulative deposition",
        )
        require(
            record.get("deposited_kg", {}) == deposited,
            "reported cumulative deposition mismatch",
        )
        deposited_mass = math.fsum(deposited.values())
        scale = max(
            budget["initial_kg"]
            + budget["emitted_kg"]
            + budget["inflow_kg"]
            + budget["outflow_kg"]
            + deposited_mass,
            1e-30,
        )
        defect = (
            mass
            - budget["initial_kg"]
            - budget["emitted_kg"]
            - budget["inflow_kg"]
            + budget["outflow_kg"]
            + deposited_mass
        )
        require(abs(mass - record["mass_kg"]) < 1e-11 * scale, "reported mass mismatch")
        require(abs(defect) < 1e-9 * scale, "independent mass accounting")
        require(
            min(values) >= -1e-10 * max(max(values), 1e-30), "negative concentration"
        )
        rate = 0.0
        for source in c["sources"]:
            if source["constituent"] != sp["id"]:
                continue
            if source["kind"] == "point":
                rate += source["rate_kg_s"]
            elif source["kind"] == "line":
                rate += source["rate_kg_s_m"] * math.dist(
                    source["from_m"], source["to_m"]
                )
            else:
                rate += source["rate_kg_s_m3"] * math.prod(
                    b - a for a, b in zip(source["min_m"], source["max_m"], strict=True)
                )
        # An implicit steady algorithm advances the constituents in capped
        # explicit sub-steps and archives the pseudo-time they covered.
        scalar_time = s.get("scalar_time_s", s["time_s"])
        require(
            type(scalar_time) in (int, float)
            and math.isfinite(scalar_time)
            and 0.0 <= scalar_time <= s["time_s"] * (1 + 1e-12),
            "scalar pseudo-time outside 0..time_s",
        )
        require(
            abs(budget["emitted_kg"] - rate * scalar_time) < 1e-9 * scale,
            "emission normalization/time accounting",
        )
        # Reconstruct current open-boundary scalar removal from archived face velocities.
        incoming = 0.0
        outgoing = 0.0
        for a, (dims, face_values) in enumerate(components):
            if c["boundaries"]["xyz"[a]] != "open":
                continue
            for k in range(nz):
                for j in range(ny):
                    for i in range(nx):
                        q = [i, j, k]
                        for side in [-1, 1]:
                            if q[a] != (0 if side < 0 else [nx, ny, nz][a] - 1):
                                continue
                            cell = index(i, j, k)
                            if not fluid[cell]:
                                continue
                            face = q.copy()
                            if side > 0:
                                face[a] += 1
                            fi = (face[2] * dims[1] + face[1]) * dims[0] + face[0]
                            normal_u = side * face_values[fi]
                            f = c["flow"]
                            if f["kind"] == "neutral_rans":
                                angle = math.radians(f["direction_deg_from"])
                                nominal = [-math.sin(angle), -math.cos(angle), 0.0][
                                    a
                                ] * side
                                nu_t = (
                                    0.09 * s["k"][cell] ** 2 / s["epsilon"][cell]
                                    if s["epsilon"][cell] > 0
                                    else 0.0
                                )
                                D = (
                                    sp["diffusivity_m2_s"]
                                    + nu_t / f["turbulent_schmidt"]
                                )
                            else:
                                nominal = (
                                    side
                                    * f.get(
                                        "velocity_m_s", f.get("initial_velocity_m_s")
                                    )[a]
                                )
                                D = sp["diffusivity_m2_s"]
                            flux = max(normal_u, 0.0) * values[cell] * volume / dx[a]
                            if nominal < -1e-12:
                                flux += (
                                    D * values[cell] / (0.5 * dx[a]) * volume / dx[a]
                                )
                            outgoing += max(flux, 0.0)
                            incoming += max(-flux, 0.0)
        particle = sp.get("particle")
        deposition_rates = {}
        if particle is not None:
            settling, aerodynamic = particle_parameters(particle)
            require(
                abs(record["settling_velocity_m_s"] - settling)
                <= 1e-13 * max(settling, 1e-300),
                "settling formula mismatch",
            )
            require(
                abs(record["aerodynamic_diameter_m"] - aerodynamic)
                <= 1e-13 * max(aerodynamic, 1e-300),
                "aerodynamic size mismatch",
            )
            ground_extra = particle.get("ground_deposition_velocity_m_s", 0)
            roof_extra = particle.get("roof_deposition_velocity_m_s", 0)
            for k in range(nz):
                for j in range(ny):
                    for i in range(nx):
                        cell = index(i, j, k)
                        if not fluid[cell]:
                            continue
                        if k == 0:
                            if c["boundaries"]["z"] == "open":
                                outgoing += settling * values[cell] * volume / dx[2]
                            elif c["boundaries"]["z"] in {"wall", "ground_open_top"}:
                                flux = (
                                    (settling + ground_extra)
                                    * values[cell]
                                    * volume
                                    / dx[2]
                                )
                                deposition_rates["ground"] = (
                                    deposition_rates.get("ground", 0) + flux
                                )
                            elif (
                                c["boundaries"]["z"] == "periodic"
                                and not fluid[index(i, j, nz - 1)]
                            ):
                                flux = (
                                    (settling + roof_extra)
                                    * values[cell]
                                    * volume
                                    / dx[2]
                                )
                                deposition_rates["roof"] = (
                                    deposition_rates.get("roof", 0) + flux
                                )
                        elif not fluid[index(i, j, k - 1)]:
                            flux = (
                                (settling + roof_extra) * values[cell] * volume / dx[2]
                            )
                            deposition_rates["roof"] = (
                                deposition_rates.get("roof", 0) + flux
                            )
            leaf_rate = 0.0
            for cell in range(n):
                if not fluid[cell]:
                    continue
                p = [
                    ((cell % nx) + 0.5) * dx[0],
                    ((cell // nx % ny) + 0.5) * dx[1],
                    ((cell // (nx * ny)) + 0.5) * dx[2],
                ]
                loss = math.fsum(
                    v["leaf_area_density_m2_m3"]
                    * v.get("leaf_deposition_velocity_m_s", 0)
                    for v in c.get("vegetation", [])
                    if all(v["min_m"][a] <= p[a] < v["max_m"][a] for a in range(3))
                )
                leaf_rate += loss * values[cell] * volume
            if leaf_rate:
                deposition_rates["vegetation"] = leaf_rate
            reported = record.get("deposition_rate_kg_s", {})
            require(
                set(reported) <= {"ground", "roof", "vegetation"},
                "unknown deposition surface",
            )
            for surface in {"ground", "roof", "vegetation"}:
                expected = deposition_rates.get(surface, 0)
                require(
                    abs(reported.get(surface, 0) - expected)
                    <= 1e-12 * max(expected, 1e-300),
                    f"{surface} deposition rate differs from field flux",
                )
        else:
            require(
                not deposited and not record.get("deposition_rate_kg_s"),
                "passive gas has particle deposition",
            )
        flux_scale = max(rate + outgoing + incoming, 1e-30)
        require(
            abs(record["source_rate_kg_s"] - rate) < 1e-9 * flux_scale,
            "current source rate",
        )
        require(
            abs(record["boundary_outflow_rate_kg_s"] - outgoing) < 1e-9 * flux_scale,
            "current scalar outflow",
        )
        require(
            abs(record["boundary_inflow_rate_kg_s"] - incoming) < 1e-9 * flux_scale,
            "current scalar inflow",
        )
        scalar_results.append(
            dict(id=sp["id"], mass_kg=mass, relative_defect=abs(defect) / scale)
        )
    if any(sp.get("particle") is not None for sp in c["constituents"]):
        pm = summary["particulate_matter"]
        require(set(pm) == {"PM2.5", "PM10"}, "particulate cutoff set")
        for name, cutoff in [("PM2.5", 2.5e-6), ("PM10", 10e-6)]:
            selected = [
                record
                for sp, record in zip(
                    c["constituents"], summary["constituents"], strict=True
                )
                if sp.get("particle") is not None
                and particle_parameters(sp["particle"])[1] <= cutoff
            ]
            expected_mass = math.fsum(record["mass_kg"] for record in selected)
            require(
                abs(pm[name]["mass_kg"] - expected_mass)
                <= 1e-12 * max(expected_mass, 1e-300),
                "PM bin mass sum",
            )
            for rid in weights:
                expected = math.fsum(
                    record["receptors_kg_m3"][rid] for record in selected
                )
                require(
                    abs(pm[name]["receptors_kg_m3"][rid] - expected)
                    <= 1e-12 * max(expected, 1e-300),
                    "PM receptor bin sum",
                )
    return dict(
        schema_version="cfd-craft.independent-check/0.1",
        passed=True,
        max_divergence_s_inv=max_div,
        scalars=scalar_results,
        scope="archived mass, recorded cumulative budget, emission rate/time, current local continuity, receptor values, geometry mask and field finiteness; not independent turbulent-model validation",
    )


if __name__ == "__main__":
    try:
        print(json.dumps(check(sys.argv[1]), indent=2))
    except (ValueError, KeyError, OSError, IndexError, TypeError) as e:
        print(json.dumps(dict(passed=False, error=str(e))))
        sys.exit(1)
