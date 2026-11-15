#!/usr/bin/env python3
"""Convert projected-metric GeoJSON/CityJSON buildings to native polygon prisms.

Requires Shapely only in this integration, never in the Rust solver. Geographic
GeoJSON must be reprojected before conversion; units and assumptions are explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

from shapely import affinity
from shapely.geometry import Polygon, box, shape
from shapely.ops import unary_union


def _polygons(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [p for item in geometry.geoms for p in _polygons(item)]
    return []


def _number(value):
    try:
        x = float(str(value).removesuffix(" m"))
    except (ValueError, TypeError):
        return None
    return x if math.isfinite(x) else None


def _nonfinite_supplied(value):
    """True for a supplied number or numeric text that is NaN or infinite."""
    try:
        return not math.isfinite(float(str(value).removesuffix(" m")))
    except (ValueError, TypeError, OverflowError):
        return False


GEOGRAPHIC = ("4326", "4979", "crs84", "wgs84", "wgs 84", "longlat", "latlon")


def _records(data):
    if not isinstance(data, dict):
        raise ValueError("Expected a FeatureCollection or CityJSON object")
    if data.get("type") == "FeatureCollection":
        declared = json.dumps(data.get("crs", "")).lower()
        if any(v in declared for v in GEOGRAPHIC):
            raise ValueError(
                "GeoJSON crs member declares geographic coordinates; reproject first"
            )
        for i, feature in enumerate(data["features"]):
            if not isinstance(feature, dict) or not isinstance(
                feature.get("geometry"), dict
            ):
                raise ValueError(f"GeoJSON feature {i} needs a geometry object")
            properties = feature.get("properties") or {}
            geom = shape(feature["geometry"])
            if geom.geom_type not in ("Polygon", "MultiPolygon"):
                raise ValueError("GeoJSON buildings must be Polygon or MultiPolygon")
            # 3D GeoJSON coordinates, when present, describe ground elevations.
            z = [v[2] for p in _polygons(geom) for v in p.exterior.coords if len(v) > 2]
            yield str(feature.get("id", properties.get("id", i))), geom, properties, z
    elif data.get("type") == "CityJSON":
        transform = data.get("transform", {})
        scale, translate = (
            transform.get("scale", [1, 1, 1]),
            transform.get("translate", [0, 0, 0]),
        )
        if any(
            not isinstance(v, (list, tuple))
            or len(v) != 3
            or any(type(x) not in (float, int) or not math.isfinite(x) for x in v)
            for v in (scale, translate)
        ):
            raise ValueError(
                "CityJSON transform must have finite three-axis scale/translate"
            )
        if any(x <= 0 for x in scale):
            raise ValueError("CityJSON scale must be positive")
        if any(
            not isinstance(v, list)
            or len(v) != 3
            or any(type(x) not in (float, int) or not math.isfinite(x) for x in v)
            for v in data["vertices"]
        ):
            raise ValueError("CityJSON vertices must be finite 3D points")
        vertices = [
            [v[a] * scale[a] + translate[a] for a in range(3)] for v in data["vertices"]
        ]

        def indices(value):
            for item in value:
                if isinstance(item, list):
                    yield from indices(item)
                else:
                    if type(item) is not int or not 0 <= item < len(vertices):
                        raise ValueError(
                            "CityJSON vertex index must be a nonnegative in-range integer"
                        )
                    yield item

        for identifier, obj in data["CityObjects"].items():
            if obj["type"] not in ("Building", "BuildingPart"):
                continue
            # 3DBAG and other CityJSON datasets store parent metadata/LoD0
            # plus child solids; do not count both the parent and its parts.
            if obj.get("children"):
                continue
            properties = {}
            for parent in obj.get("parents", []):
                properties.update(data["CityObjects"][parent].get("attributes", {}))
            properties.update(obj.get("attributes", {}))
            geometries = obj.get("geometry", [])
            positive_lods = [
                g
                for g in geometries
                if _number(g.get("lod")) is not None and float(g["lod"]) > 0
            ]
            if positive_lods:
                geometries = [min(positive_lods, key=lambda g: float(g["lod"]))]
            used = set()
            candidates = []
            projected_rings = []
            for geometry in geometries:
                if geometry.get("type") not in (
                    "MultiSurface",
                    "CompositeSurface",
                    "Solid",
                    "MultiSolid",
                    "CompositeSolid",
                ):
                    raise ValueError(
                        f"Unsupported CityJSON geometry: {geometry.get('type')}"
                    )
                for i in indices(geometry.get("boundaries", [])):
                    used.add(i)

                # Project every surface ring; horizontal roofs/grounds cover the footprint.
                def rings(value):
                    if value and all(isinstance(i, int) for i in value):
                        yield value
                    else:
                        for item in value:
                            if isinstance(item, list):
                                yield from rings(item)

                for ring in rings(geometry.get("boundaries", [])):
                    if len(ring) >= 3:
                        p = Polygon([vertices[i][:2] for i in ring])
                        if p.area > 1e-10 and p.is_valid:
                            candidates.append(p)
                            projected_rings.append([vertices[i][2] for i in ring])
            if not candidates:
                raise ValueError(
                    f"CityJSON building {identifier} has no planar footprint"
                )
            z = [vertices[i][2] for i in used]
            props = properties
            props.setdefault("height", max(z) - min(z))
            # Conservative base-envelope screen: projected lower-half surfaces
            # include all elevations of a sloping base, not just its minimum.
            middle = (min(z) + max(z)) * 0.5
            base = [
                v
                for ring in projected_rings
                if sum(ring) / len(ring) <= middle
                for v in ring
            ]
            if not base:
                raise ValueError(
                    f"CityJSON building {identifier}: ground envelope is unavailable"
                )
            yield identifier, unary_union(candidates), props, base
    else:
        raise ValueError("Expected FeatureCollection or CityJSON")


def dominant_angle(polygons):
    """Length-weighted dominant edge orientation modulo 90 degrees."""
    bins = [0.0] * 90
    for p in polygons:
        points = list(p.exterior.coords)
        for a, b in zip(points, points[1:], strict=False):
            dx, dy = b[0] - a[0], b[1] - a[1]
            bins[round(math.degrees(math.atan2(dy, dx))) % 90] += math.hypot(dx, dy)
    return float(max(range(90), key=bins.__getitem__))


def convert(
    source: Path,
    template: dict,
    *,
    crop,
    cell_m,
    source_license,
    attribution,
    coordinate_system,
    rotation_deg=None,
    height_attribute="height",
    levels_attribute="building:levels",
    level_height_m=3.0,
    default_height_m=8.0,
    max_ground_range_m=0.5,
    ensemble_clearance=False,
):
    if (
        not source_license.strip()
        or not attribution.strip()
        or not coordinate_system.strip()
    ):
        raise ValueError(
            "License, attribution and projected metric coordinate-system declaration are required"
        )
    if any(v in coordinate_system.lower() for v in GEOGRAPHIC):
        raise ValueError(
            "Use a projected metric coordinate system; reproject geographic data first"
        )
    if not math.isfinite(cell_m) or cell_m <= 0:
        raise ValueError("cell_m must be finite and positive")
    if (
        len(crop) != 4
        or not all(math.isfinite(v) for v in crop)
        or crop[0] >= crop[2]
        or crop[1] >= crop[3]
    ):
        raise ValueError("crop is [xmin,ymin,xmax,ymax] in declared projected meters")
    if not (
        all(
            math.isfinite(v)
            for v in (max_ground_range_m, level_height_m, default_height_m)
        )
        and 0 <= max_ground_range_m
        and 0 < level_height_m
        and 0 < default_height_m
    ):
        raise ValueError("Ground range and height fallback parameters are invalid")
    data = json.loads(source.read_bytes())
    records = []
    assumptions = []
    ground = []
    clip = box(*crop)
    for identifier, geom, props, elevations in _records(data):
        if geom.is_empty or not box(*geom.bounds).intersects(clip):
            continue
        if not geom.is_valid:
            raise ValueError(
                f"Invalid footprint {identifier}; repair in source before conversion"
            )
        geom = geom.intersection(clip)
        if geom.is_empty:
            continue
        for key in (height_attribute, levels_attribute):
            if _nonfinite_supplied(props.get(key)):
                raise ValueError(f"Building {identifier}: {key} must be finite")
        height = _number(props.get(height_attribute))
        method = "attribute"
        if height is None:
            levels = _number(props.get(levels_attribute))
            height = levels * level_height_m if levels is not None else default_height_m
            method = "levels" if levels is not None else "default"
        if height <= 0:
            raise ValueError(f"Building {identifier}: height must be positive")
        if (
            "ground_elevation_m" in props
            and _number(props["ground_elevation_m"]) is None
        ):
            raise ValueError(
                f"Building {identifier}: ground_elevation_m must be finite"
            )
        samples = elevations or [_number(props.get("ground_elevation_m")) or 0.0]
        if any(not math.isfinite(v) for v in samples):
            raise ValueError(f"Building {identifier}: ground elevations must be finite")
        ground.extend(samples)
        assumptions.append(
            {
                "id": identifier,
                "height_m": height,
                "height_method": method,
                "ground_method": "supplied"
                if elevations or "ground_elevation_m" in props
                else "assumed_flat_zero",
            }
        )
        records.extend((identifier, p, height) for p in _polygons(geom))
    if not records:
        raise ValueError("No building footprints intersect the crop")
    ground_range = max(ground) - min(ground)
    if ground_range > max_ground_range_m:
        raise ValueError(
            f"Terrain elevation range {ground_range:g} m exceeds {max_ground_range_m:g} m; flat-ground solver refuses this crop"
        )
    angle = (
        dominant_angle([p for _, p, _ in records])
        if rotation_deg is None
        else rotation_deg
    )
    if not math.isfinite(angle):
        raise ValueError("Rotation must be finite")
    origin = ((crop[0] + crop[2]) * 0.5, (crop[1] + crop[3]) * 0.5)
    grouped = {}
    for identifier, polygon, height in records:
        polygon = affinity.rotate(polygon, -angle, origin=origin)
        # Touching footprints are merged only at identical height.
        grouped.setdefault(height, []).append(polygon)
    buildings = []
    dropped = []
    for height, polys in sorted(grouped.items()):
        for polygon in _polygons(unary_union(polys)):
            polygon = polygon.simplify(cell_m * 0.05, preserve_topology=True)
            if polygon.interiors:
                raise ValueError(
                    "Footprint holes need decomposition into simple polygons before import"
                )
            corners = list(polygon.minimum_rotated_rectangle.exterior.coords)
            width = min(
                math.dist(a, b) for a, b in zip(corners[:-1], corners[1:], strict=True)
            )
            if min(width, height) < 2 * cell_m:
                dropped.append(
                    {
                        "bounds_m": list(polygon.bounds),
                        "height_m": height,
                        "reason": "below_two_cells",
                    }
                )
                continue
            buildings.append((polygon, height))
    if not buildings:
        raise ValueError("Every building was below two cells; refine the grid")
    h = max(height for _, height in buildings)
    bounds = unary_union([p for p, _ in buildings]).bounds
    up, down, side = (
        (15 * h, 15 * h, 15 * h) if ensemble_clearance else (5 * h, 15 * h, 5 * h)
    )
    offset = [up - bounds[0], side - bounds[1]]
    extent = [
        bounds[2] - bounds[0] + up + down,
        bounds[3] - bounds[1] + 2 * side,
        6 * h,
    ]
    if not all(math.isfinite(v / cell_m) for v in extent):
        raise ValueError("Converted domain extent overflows; check heights and units")
    case = json.loads(json.dumps(template))
    case["name"] = "converted-urban-district"
    case["grid"]["cells"] = [max(2, math.ceil(v / cell_m)) for v in extent]
    # Round domain sizes up to retain the requested isotropic cell width.
    case["domain"]["size_m"] = [n * cell_m for n in case["grid"]["cells"]]
    case["geometry"] = []
    for i, (p, height) in enumerate(buildings):
        p = affinity.translate(p, *offset)
        xmin, ymin, xmax, ymax = p.bounds
        case["geometry"].append(
            {
                "id": f"building-{i}",
                "min_m": [xmin, ymin, 0.0],
                "max_m": [xmax, ymax, height],
                "footprint_m": [list(v[:2]) for v in list(p.exterior.coords)[:-1]],
            }
        )
    case["sources"], case["receptors"], case["initial_conditions"] = [], [], []
    case["building_roughness_m"] = 0.01
    case["geometry_min_passage_cells"] = 3
    if case["flow"]["kind"] != "neutral_rans":
        raise ValueError("Urban map conversion requires a neutral_rans template")
    source_wind = case["flow"]["direction_deg_from"]
    case["flow"]["direction_deg_from"] = (source_wind + angle) % 360
    case["flow"]["reference_height_m"] = min(10.0, case["domain"]["size_m"][2])
    provenance = {
        "schema_version": "cfd-craft.map-provenance/1",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "license": source_license,
        "attribution": attribution,
        "coordinate_system": coordinate_system,
        "source_wind_direction_deg_from": source_wind,
        "local_wind_direction_deg_from": case["flow"]["direction_deg_from"],
        "crop_m": list(crop),
        "rotation_deg": angle,
        "rotation_origin_m": list(origin),
        "translation_m": offset,
        "cell_m": cell_m,
        "ground_range_m": ground_range,
        "max_ground_range_m": max_ground_range_m,
        "assumptions": assumptions,
        "dropped": dropped,
        "merge_policy": "touching footprints at equal height",
        "flat_ground_only": True,
        "clearances_H": {
            "upstream": up / h,
            "downstream": down / h,
            "lateral": side / h,
            "above_roof": 5.0,
        },
    }
    return case, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--template", type=Path, default=Path("cases/canyon/wh1-wind270.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--crop", type=float, nargs=4, required=True)
    parser.add_argument("--cell-m", type=float, required=True)
    parser.add_argument("--license", dest="source_license", required=True)
    parser.add_argument("--attribution", required=True)
    parser.add_argument(
        "--coordinate-system",
        required=True,
        help="Explicit projected CRS in meters, not longitude/latitude",
    )
    parser.add_argument("--rotation-deg", type=float)
    parser.add_argument("--height-attribute", default="height")
    parser.add_argument("--max-ground-range-m", type=float, default=0.5)
    parser.add_argument("--ensemble-clearance", action="store_true")
    parser.add_argument("--binary", type=Path, default=Path("target/release/cfd-craft"))
    args = parser.parse_args()
    kwargs = vars(args).copy()
    source, template, output, binary = [
        kwargs.pop(k) for k in ("source", "template", "output", "binary")
    ]
    try:
        case, evidence = convert(source, json.loads(template.read_text()), **kwargs)
        output.mkdir(parents=True, exist_ok=False)
        target = output / "case.json"
        target.write_text(json.dumps(case, indent=2) + "\n")
        process = subprocess.run(
            [str(binary.resolve()), "check", str(target)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        (output / "check.json").write_text(process.stdout)
        evidence["check_exit_code"] = process.returncode
        (output / "map-provenance.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
        if process.returncode:
            raise ValueError(
                "Converted case failed native check; retained output/check.json"
            )
    except (
        ValueError,
        OSError,
        KeyError,
        IndexError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as exc:
        parser.exit(1, f"CFD-M001 map: {exc}\n")


if __name__ == "__main__":
    main()
