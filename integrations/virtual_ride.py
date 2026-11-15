#!/usr/bin/env python3
"""Idealized constant-speed sampling of an accepted steady native path receptor."""

import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path

MAX_RIDE_SAMPLES = 200000


def require(condition, message):
    if not condition:
        raise ValueError(f"CFD-M004 virtual_ride: {message}")


def finite(values):
    return all(type(value) in (int, float) and math.isfinite(value) for value in values)


def first_order_response(knot_times, targets, sample_times, response_time_s, initial):
    """Exact tau*y' = x-y for piecewise-linear x, evaluated at requested times.

    The initial value applies at knot_times[0]. This includes the analytic step
    response when x is constant and the initial sensor differs from that input.
    """
    require(len(knot_times) == len(targets) >= 2, "sensor input dimensions")
    require(
        finite(knot_times) and finite(targets) and finite(sample_times),
        "nonfinite sensor series",
    )
    require(
        all(b > a for a, b in zip(knot_times[:-1], knot_times[1:], strict=True)),
        "sensor knots must increase",
    )
    require(
        len(sample_times) > 0
        and all(
            b > a for a, b in zip(sample_times[:-1], sample_times[1:], strict=True)
        ),
        "sample times must increase",
    )
    require(
        knot_times[0] <= sample_times[0] <= sample_times[-1] <= knot_times[-1],
        "samples outside input interval",
    )
    require(
        finite([response_time_s, initial]) and response_time_s >= 0,
        "invalid sensor response/initial value",
    )
    if response_time_s == 0:
        return [interpolate(knot_times, targets, time) for time in sample_times]
    result = []
    current_time, sensor, segment = knot_times[0], initial, 0
    for output_time in sample_times:
        while current_time < output_time:
            while (
                segment + 2 < len(knot_times)
                and current_time >= knot_times[segment + 1]
            ):
                segment += 1
            stop = min(output_time, knot_times[segment + 1])
            duration = stop - current_time
            slope = (targets[segment + 1] - targets[segment]) / (
                knot_times[segment + 1] - knot_times[segment]
            )
            value = targets[segment] + slope * (current_time - knot_times[segment])
            # expm1 prevents loss of significance when dt << tau.
            loss = -math.expm1(-duration / response_time_s)
            z = duration / response_time_s
            if z < 1e-4:
                ramp = duration * z * (0.5 - z / 6 + z * z / 24 - z**3 / 120)
            else:
                ramp = duration - response_time_s * loss
            sensor += (value - sensor) * loss + slope * ramp
            current_time = stop
        result.append(sensor)
    require(finite(result), "nonfinite integrated sensor response")
    return result


def interpolate(knots, values, position):
    if position == knots[0]:
        return values[0]
    if position == knots[-1]:
        return values[-1]
    segment = min(max(bisect.bisect_right(knots, position) - 1, 0), len(knots) - 2)
    slope = (values[segment + 1] - values[segment]) / (
        knots[segment + 1] - knots[segment]
    )
    return values[segment] + (position - knots[segment]) * slope


def ride(path, *, speed_m_s, sampling_interval_s, response_time_s, initial_kg_m3=None):
    """Generate a bounded idealized ride from one native PathEvidence record."""
    require(
        finite([speed_m_s, sampling_interval_s, response_time_s]),
        "nonfinite ride parameters",
    )
    require(
        speed_m_s > 0 and sampling_interval_s > 0 and response_time_s >= 0,
        "speed/interval must be positive, response time nonnegative",
    )
    distance, concentration, points = (
        path["distance_m"],
        path["concentrations_kg_m3"],
        path["points_m"],
    )
    require(
        2 <= len(distance) <= 20001
        and len(distance) == len(concentration) == len(points),
        "path sample dimensions",
    )
    require(
        finite(distance)
        and finite(concentration)
        and all(len(p) == 3 and finite(p) for p in points),
        "nonfinite path data",
    )
    require(
        distance[0] == 0
        and all(b > a for a, b in zip(distance[:-1], distance[1:], strict=True)),
        "path arc length must strictly increase from zero",
    )
    knot_times = [value / speed_m_s for value in distance]
    duration = knot_times[-1]
    ratio = duration / sampling_interval_s
    require(
        math.isfinite(ratio) and ratio <= MAX_RIDE_SAMPLES - 1,
        "ride sample budget exceeded (200000)",
    )
    samples = max(1, math.ceil(ratio))
    # A rounded ratio can ceil to an extra interval while the corresponding
    # grid time rounds exactly to the final endpoint. Keep that endpoint once.
    times = [
        time
        for sample in range(samples)
        if (time := sample * sampling_interval_s) < duration
    ] + [duration]
    initial = concentration[0] if initial_kg_m3 is None else initial_kg_m3
    require(finite([initial]), "nonfinite initial sensor concentration")
    true = [interpolate(knot_times, concentration, time) for time in times]
    measured = first_order_response(
        knot_times, concentration, times, response_time_s, initial
    )
    # Archived cases retain all geometric corners even when a coarse sampling
    # interval straddles one. Use those original vertices for position only;
    # the concentration signal remains interpolation of the recorded samples.
    if "polyline_m" in path:
        vertices = [[*p, path["height_m"]] for p in path["polyline_m"]]
        geometry_distance = [0.0]
        for start, end in zip(vertices[:-1], vertices[1:], strict=True):
            geometry_distance.append(geometry_distance[-1] + math.dist(start, end))
        require(
            abs(geometry_distance[-1] - distance[-1]) <= 1e-12 * max(distance[-1], 1),
            "path geometry length mismatch",
        )
        position_geometry = "declared_polyline"
    else:
        vertices, geometry_distance = points, distance
        position_geometry = "sampled_path_chords"
    travelled = [time * speed_m_s for time in times[:-1]] + [distance[-1]]
    coordinate_arrays = [[point[axis] for point in vertices] for axis in range(3)]
    positions = [
        [
            interpolate(geometry_distance, coordinates, position)
            for coordinates in coordinate_arrays
        ]
        for position in travelled
    ]
    positions[0] = list(vertices[0])
    positions[-1] = list(vertices[-1])
    return {
        "schema_version": "cfd-craft.virtual-ride/0.1",
        "scope": "idealized pass through a steady mean local concentration increment; not a time-resolved atmospheric prediction or experimental validation",
        "sensor_model": "first_order_ODE_exact_for_piecewise_linear_path_signal",
        "position_geometry": position_geometry,
        "parameters": {
            "speed_m_s": speed_m_s,
            "sampling_interval_s": sampling_interval_s,
            "response_time_s": response_time_s,
            "initial_kg_m3": initial,
        },
        "time_s": times,
        "distance_m": travelled,
        "points_m": positions,
        "steady_field_kg_m3": true,
        "sensor_kg_m3": measured,
    }


def read_path(run_directory, constituent_id, path_id):
    """Verify the manifest and consumed case/summary before taking a path."""
    root = Path(run_directory)
    marker = json.loads((root / "complete.json").read_text())
    manifest_bytes = (root / "manifest.json").read_bytes()
    require(
        hashlib.sha256(manifest_bytes).hexdigest() == marker["manifest_sha256"],
        "manifest checksum mismatch",
    )
    manifest = json.loads(manifest_bytes)
    records = {}
    for name in ["case.json", "summary.json"]:
        source = root / name
        require(
            not source.is_symlink() and source.stat().st_size <= 64 * 1024**2,
            "invalid or oversized consumed artifact",
        )
        data = source.read_bytes()
        require(
            hashlib.sha256(data).hexdigest() == manifest["files"][name],
            f"artifact checksum mismatch: {name}",
        )
        records[name] = json.loads(data)
    case, summary = records["case.json"], records["summary.json"]
    require(
        case["run"]["mode"] == "steady"
        and summary["termination"] == "completed"
        and summary["assessment"] == "steady_discrete_solution"
        and all(item["passed"] for item in summary["checks"]),
        "an accepted completed steady field is required",
    )
    require(
        any(r["kind"] == "path" and r["id"] == path_id for r in case["receptors"]),
        "path ID absent from consumed case",
    )
    constituent = next(
        (item for item in summary["constituents"] if item["id"] == constituent_id), None
    )
    require(
        constituent is not None and path_id in constituent.get("paths", {}),
        "constituent/path result missing",
    )
    provenance = {
        "case_sha256": summary["case_sha256"],
        "physics_sha256": summary["physics_sha256"],
        "source_sha256": summary["source_sha256"],
        "summary_file_sha256": manifest["files"]["summary.json"],
        "experimental_validation": summary["experimental_validation"],
        "constituent": constituent_id,
        "path": path_id,
        "checked_artifacts": ["manifest.json", "case.json", "summary.json"],
    }
    path = dict(constituent["paths"][path_id])
    receptor = next(r for r in case["receptors"] if r["id"] == path_id)
    path["polyline_m"] = receptor["polyline_m"]
    path["height_m"] = receptor["height_m"]
    return path, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--constituent", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--speed-m-s", type=float, required=True)
    parser.add_argument("--sampling-interval-s", type=float, required=True)
    parser.add_argument("--response-time-s", type=float, default=0.0)
    parser.add_argument("--initial-kg-m3", type=float)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        require(not args.output.exists(), "output already exists")
        path, provenance = read_path(args.run_directory, args.constituent, args.path)
        result = ride(
            path,
            speed_m_s=args.speed_m_s,
            sampling_interval_s=args.sampling_interval_s,
            response_time_s=args.response_time_s,
            initial_kg_m3=args.initial_kg_m3,
        )
        result["provenance"] = provenance
        serialized = json.dumps(result, indent=2, allow_nan=False) + "\n"
        with args.output.open("x") as stream:
            stream.write(serialized)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "samples": len(result["time_s"]),
                    "scope": result["scope"],
                }
            )
        )
    except (ValueError, TypeError, KeyError, OSError, StopIteration) as error:
        message = str(error)
        if not message.startswith("CFD-M004"):
            message = f"CFD-M004 virtual_ride: {message}"
        parser.exit(1, f"{message}\n")


if __name__ == "__main__":
    main()
