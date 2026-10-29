#!/usr/bin/env python3
"""Independent archived-field checks. Essential checks survive python -O."""

import hashlib
import json
from pathlib import Path
import sys
import math


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def finite(values, name):
    require(all(math.isfinite(v) for v in values), f"nonfinite values in {name}")


def receptor_weights(receptor, dx, cells, fluid, index):
    """Cell weights of a receptor, computed as the solver documents them."""
    nx, ny, nz = cells
    weights = {}
    if receptor["kind"] == "point":
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
                    for b in c["geometry"]
                )
    require(
        hashlib.sha256(bytes(int(f) for f in fluid)).hexdigest()
        == geometry["mask_sha256"],
        "geometry mask differs from the case boxes",
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
        mass = math.fsum(values) * volume
        scale = max(
            budget["initial_kg"]
            + budget["emitted_kg"]
            + budget["inflow_kg"]
            + budget["outflow_kg"],
            1e-30,
        )
        defect = (
            mass
            - budget["initial_kg"]
            - budget["emitted_kg"]
            - budget["inflow_kg"]
            + budget["outflow_kg"]
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
        require(
            abs(budget["emitted_kg"] - rate * s["time_s"]) < 1e-9 * scale,
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
