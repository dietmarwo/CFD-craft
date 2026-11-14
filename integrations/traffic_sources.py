#!/usr/bin/env python3
"""Convert supplied street emissions to bounded-domain native line sources.

Street GeoJSON must already share the map converter's projected metric frame.
Only explicitly supplied CSV rates are used; no traffic or emission factors are
inferred. Requires the optional integrations/requirements-urban.txt dependency.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys

from shapely import affinity
from shapely.geometry import LineString, Polygon, box

ROOT = Path(__file__).resolve().parents[1]
RATE_COLUMNS = {"street_id", "constituent", "rate_kg_s_m", "units"}
GEOGRAPHIC_NAMES = ("4326", "4979", "crs84", "wgs84", "wgs 84", "longlat", "latlon")


class TrafficSourceError(ValueError):
    """A coded traffic conversion rejection with a precise input path."""

    def __init__(self, path, message, **details):
        self.diagnostic = {
            "code": "CFD-M002",
            "path": path,
            "message": message,
            "details": details,
        }
        super().__init__(f"CFD-M002 {path}: {message}")


def _require(condition, path, message, **details):
    if not condition:
        raise TrafficSourceError(path, message, **details)


def _finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def _identifier(value, path):
    _require(type(value) in (str, int), path, "Use a nonempty text or integer ID")
    text = str(value).strip()
    _require(bool(text), path, "Use a nonempty ID")
    return text


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _json_digest(value):
    return _digest(json.dumps(value, sort_keys=True, allow_nan=False).encode())


def _load_json(raw, path):
    def invalid_constant(value):
        raise TrafficSourceError(path, f"Nonfinite JSON value {value}")

    try:
        return json.loads(raw, parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise TrafficSourceError(path, f"Expected UTF-8 JSON: {exc}") from exc


def _rates(raw, constituents):
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        names = reader.fieldnames or []
        _require(
            RATE_COLUMNS.issubset(names) and len(set(names)) == len(names),
            "rates.columns",
            "CSV requires unique street_id,constituent,rate_kg_s_m,units columns",
        )
        rows = []
        seen = set()
        for line, row in enumerate(reader, 2):
            path = f"rates.rows[{line}]"
            _require(None not in row, path, "Too many CSV values")
            street = _identifier(row.get("street_id"), path + ".street_id")
            constituent = _identifier(row.get("constituent"), path + ".constituent")
            _require(
                constituent in constituents,
                path + ".constituent",
                f"Unknown case constituent {constituent!r}",
            )
            units = (row.get("units") or "").strip()
            _require(units == "kg/s/m", path + ".units", "Rate units must be kg/s/m")
            try:
                rate = float(row.get("rate_kg_s_m", ""))
            except (TypeError, ValueError) as exc:
                raise TrafficSourceError(
                    path + ".rate_kg_s_m", "Rate must be numeric"
                ) from exc
            _require(
                math.isfinite(rate) and rate >= 0,
                path + ".rate_kg_s_m",
                "Rate must be finite and nonnegative",
            )
            key = street, constituent
            _require(key not in seen, path, f"duplicate street/constituent row {key!r}")
            seen.add(key)
            rows.append(
                {
                    "street_id": street,
                    "constituent": constituent,
                    "rate_kg_s_m": rate,
                    "units": units,
                    "csv_line": line,
                }
            )
        _require(bool(rows), "rates", "Supply at least one explicit rate row")
        return rows, sorted(set(names) - RATE_COLUMNS)
    except UnicodeError as exc:
        raise TrafficSourceError("rates", "Rate CSV must be UTF-8") from exc


def _street_lines(data, id_property):
    _require(
        isinstance(data, dict) and data.get("type") == "FeatureCollection",
        "streets.type",
        "Street input must be a GeoJSON FeatureCollection",
    )
    _require(
        not any(v in json.dumps(data.get("crs", "")).lower() for v in GEOGRAPHIC_NAMES),
        "streets.crs",
        "GeoJSON crs member declares geographic coordinates; reproject first",
    )
    _require(
        isinstance(data.get("features"), list), "streets.features", "Expected a list"
    )
    streets = {}
    for index, feature in enumerate(data["features"]):
        path = f"streets.features[{index}]"
        _require(
            isinstance(feature, dict) and feature.get("type") == "Feature",
            path,
            "Expected a GeoJSON Feature",
        )
        properties = feature.get("properties")
        if properties is None:
            properties = {}
        _require(
            isinstance(properties, dict), path + ".properties", "Expected an object"
        )
        given = feature.get("id", properties.get(id_property))
        identifier = _identifier(given, path + ".id")
        if "id" in feature and id_property in properties:
            _require(
                identifier
                == _identifier(
                    properties[id_property], path + ".properties." + id_property
                ),
                path + ".id",
                "Feature and property street IDs disagree",
            )
        _require(
            identifier not in streets,
            path + ".id",
            f"duplicate street ID {identifier!r}",
        )
        geometry = feature.get("geometry")
        _require(
            isinstance(geometry, dict), path + ".geometry", "Expected a line geometry"
        )
        kind = geometry.get("type")
        _require(
            kind in ("LineString", "MultiLineString"),
            path + ".geometry.type",
            "Only LineString and MultiLineString streets are supported",
        )
        coordinates = geometry.get("coordinates")
        parts = [coordinates] if kind == "LineString" else coordinates
        _require(
            isinstance(parts, list) and bool(parts),
            path + ".geometry.coordinates",
            "Expected nonempty line coordinates",
        )
        lines, elevations, duplicate_vertices = [], [], 0
        for part, points in enumerate(parts):
            location = path + f".geometry.coordinates[{part}]"
            _require(
                isinstance(points, list) and len(points) >= 2,
                location,
                "Each line needs at least two coordinate positions",
            )
            xy = []
            for vertex, point in enumerate(points):
                _require(
                    isinstance(point, (list, tuple))
                    and len(point) in (2, 3)
                    and all(_finite(v) for v in point),
                    location + f"[{vertex}]",
                    "Street coordinates must be finite 2D or 3D positions in projected meters",
                )
                xy.append((float(point[0]), float(point[1])))
                if len(point) == 3:
                    elevations.append(float(point[2]))
            length = math.fsum(
                math.dist(a, b) for a, b in zip(xy, xy[1:], strict=False)
            )
            _require(
                length > 0 and math.isfinite(length),
                location,
                "Street line must have finite positive length",
            )
            duplicate_vertices += sum(a == b for a, b in zip(xy, xy[1:], strict=False))
            lines.append(xy)
        streets[identifier] = {
            "lines": lines,
            "geometry_kind": kind,
            "input_z_range_m": [min(elevations), max(elevations)]
            if elevations
            else None,
            "duplicate_consecutive_vertices": duplicate_vertices,
        }
    return streets


def _parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry] if geometry.length > 0 else []
    if geometry.geom_type in ("MultiLineString", "GeometryCollection"):
        return [part for item in geometry.geoms for part in _parts(item)]
    return []  # Point contacts carry zero emitted mass.


def _settings(case, provenance, height):
    _require(isinstance(case, dict), "case", "Case must be a JSON object")
    _require(
        isinstance(case.get("domain"), dict), "case.domain", "Domain must be an object"
    )
    _require(
        isinstance(provenance, dict),
        "map_provenance",
        "Map provenance must be a JSON object",
    )
    _require(
        provenance.get("flat_ground_only") is True,
        "map_provenance.flat_ground_only",
        "Only the flat-ground map converter frame is supported",
    )
    size = case["domain"].get("size_m")
    _require(
        isinstance(size, list)
        and len(size) == 3
        and all(_finite(v) and v > 0 for v in size),
        "case.domain.size_m",
        "Domain must have three finite positive lengths",
    )
    _require(
        _finite(height) and 0 <= height < size[2],
        "height_m",
        "Declared height must be finite and inside [0,Lz)",
    )
    _require(
        provenance.get("schema_version") == "cfd-craft.map-provenance/1",
        "map_provenance.schema_version",
        "Use the urban map converter's provenance schema",
    )
    crs = provenance.get("coordinate_system", "")
    _require(
        isinstance(crs, str)
        and bool(crs.strip())
        and not any(v in crs.lower() for v in GEOGRAPHIC_NAMES),
        "map_provenance.coordinate_system",
        "Street and map data must share the declared projected metric frame",
    )
    crop = provenance.get("crop_m")
    origin = provenance.get("rotation_origin_m")
    translation = provenance.get("translation_m")
    angle = provenance.get("rotation_deg")
    _require(
        isinstance(crop, list)
        and len(crop) == 4
        and all(_finite(v) for v in crop)
        and crop[0] < crop[2]
        and crop[1] < crop[3],
        "map_provenance.crop_m",
        "Crop must be finite [xmin,ymin,xmax,ymax]",
    )
    for name, value in [("rotation_origin_m", origin), ("translation_m", translation)]:
        _require(
            isinstance(value, list)
            and len(value) == 2
            and all(_finite(v) for v in value),
            "map_provenance." + name,
            "Expected two finite projected-meter values",
        )
    _require(
        _finite(angle), "map_provenance.rotation_deg", "Map rotation must be finite"
    )
    upper = [math.nextafter(float(v), -math.inf) for v in size[:2]]
    source_crop = box(
        crop[0],
        crop[1],
        math.nextafter(crop[2], -math.inf),
        math.nextafter(crop[3], -math.inf),
    )
    return size, source_crop, box(0, 0, *upper), origin, translation, angle


def _buildings(case, height):
    shapes = []
    geometry = case.get("geometry", [])
    _require(isinstance(geometry, list), "case.geometry", "Geometry must be a list")
    for i, building in enumerate(geometry):
        path = f"case.geometry[{i}]"
        _require(isinstance(building, dict), path, "Each building must be an object")
        lo, hi = building.get("min_m"), building.get("max_m")
        _require(
            isinstance(lo, list)
            and isinstance(hi, list)
            and len(lo) == len(hi) == 3
            and all(
                _finite(a) and _finite(b) and a < b for a, b in zip(lo, hi, strict=True)
            ),
            path,
            "Building needs finite increasing bounds",
        )
        if not lo[2] <= height < hi[2]:
            continue
        vertices = building.get("footprint_m")
        if vertices is not None:
            _require(
                isinstance(vertices, list)
                and len(vertices) >= 3
                and all(
                    isinstance(p, (list, tuple))
                    and len(p) == 2
                    and all(_finite(v) for v in p)
                    for p in vertices
                ),
                path + ".footprint_m",
                "Footprint requires at least three finite x/y vertices",
            )
        polygon = (
            Polygon(vertices)
            if vertices is not None
            else box(lo[0], lo[1], hi[0], hi[1])
        )
        _require(
            not polygon.is_empty and polygon.is_valid and polygon.area > 0,
            path + ".footprint_m",
            "Building footprint must be a valid nonzero-area polygon",
        )
        shapes.append((building.get("id", str(i)), polygon))
    return shapes


def _convert(
    case,
    map_provenance,
    street_raw,
    rates_raw,
    *,
    height_m,
    street_id_property="id",
    street_license="not_declared",
    street_attribution="not_declared",
    rates_description="explicit_user_supplied_csv; no emission factors inferred",
):
    """Return a copied case plus a full traffic conversion/provenance record.

    Paths use projected source-frame XY, cropped like the buildings before
    rotation/translation and then clipped to [0,Lx)x[0,Ly). Every original
    vertex is retained as a segment break: bends are never shortcut by chords.
    Native preflight is performed by the CLI on the complete returned case.
    """
    size, crop, domain, origin, translation, angle = _settings(
        case, map_provenance, height_m
    )
    constituents_data = case.get("constituents", [])
    _require(
        isinstance(constituents_data, list),
        "case.constituents",
        "Constituents must be a list",
    )
    constituents = set()
    for i, sp in enumerate(constituents_data):
        _require(
            isinstance(sp, dict) and isinstance(sp.get("id"), str) and bool(sp["id"]),
            f"case.constituents[{i}].id",
            "Each constituent needs a nonempty text ID",
        )
        _require(
            sp["id"] not in constituents,
            f"case.constituents[{i}].id",
            "Duplicate case constituent ID",
        )
        constituents.add(sp["id"])
    sources = case.get("sources", [])
    _require(isinstance(sources, list), "case.sources", "Sources must be a list")
    source_ids = set()
    for i, source in enumerate(sources):
        _require(
            isinstance(source, dict)
            and isinstance(source.get("id"), str)
            and bool(source["id"]),
            f"case.sources[{i}].id",
            "Each source needs a nonempty text ID",
        )
        _require(
            source["id"] not in source_ids,
            f"case.sources[{i}].id",
            "Duplicate case source ID",
        )
        source_ids.add(source["id"])
    rows, unused_columns = _rates(rates_raw, constituents)
    streets = _street_lines(_load_json(street_raw, "streets"), street_id_property)
    shapes = _buildings(case, height_m)
    report = {
        "schema_version": "cfd-craft.traffic-provenance/1",
        "streets_file_sha256": _digest(street_raw),
        "rates_file_sha256": _digest(rates_raw),
        "input_case_json_sha256": _json_digest(case),
        "map_provenance_json_sha256": _json_digest(map_provenance),
        "coordinate_system": map_provenance["coordinate_system"],
        "street_license": street_license,
        "street_attribution": street_attribution,
        "rates_description": rates_description,
        "height_m": height_m,
        "crop_m": map_provenance["crop_m"],
        "rotation_deg": angle,
        "rotation_origin_m": origin,
        "translation_m": translation,
        "streets": {},
        "rate_rows": [],
        "unmatched_zero_rate_rows": [],
        "unused_csv_columns": unused_columns,
        "added_sources": [],
        "total_added_rate_kg_s": 0.0,
        "experimental_validation": "not_validated",
        "assumptions": [
            "Street coordinates already share the building map's projected metric frame; no CRS reprojection is performed.",
            "Street paths are clipped to the original building crop, transformed by its stored -rotation/origin/translation, then clipped to the native upper-exclusive domain.",
            "All sources use the explicitly declared height above flattened ground; any input coordinate Z is ignored and its range recorded per street.",
            "Rates are used exactly as supplied in kg/s/m; no traffic counts, emission factors, background or rates for unlisted streets are invented.",
            "Duplicate coordinate vertices emit no extra length; distinct street IDs and overlapping parts retain their supplied multiplicity.",
            "A continuous source segment touching or crossing a building footprint at the declared height is rejected; nothing is relocated or redistributed.",
        ],
    }
    supplied = {row["street_id"] for row in rows}
    for identifier, street in streets.items():
        segments = []
        original_length = 0.0
        for points in street["lines"]:
            for a, b in zip(points, points[1:], strict=False):
                original_length += math.dist(a, b)
                if a == b:
                    continue
                for clipped in _parts(LineString([a, b]).intersection(crop)):
                    local = affinity.rotate(clipped, -angle, origin=origin)
                    local = affinity.translate(local, *translation)
                    for part in _parts(local.intersection(domain)):
                        positions = list(part.coords)
                        for start, end in zip(positions, positions[1:], strict=False):
                            # GEOS keeps straight segments, but preserving every
                            # returned vertex also handles multi-part degeneracy.
                            if start != end:
                                segments.append(
                                    (
                                        [float(v) for v in start[:2]]
                                        + [float(height_m)],
                                        [float(v) for v in end[:2]] + [float(height_m)],
                                    )
                                )
        retained = math.fsum(math.dist(a, b) for a, b in segments)
        report["streets"][identifier] = {
            "geometry_kind": street["geometry_kind"],
            "original_length_m": original_length,
            "retained_length_m": retained,
            "removed_length_m": max(0.0, original_length - retained),
            "segments": len(segments),
            "input_z_range_m": street["input_z_range_m"],
            "duplicate_consecutive_vertices": street["duplicate_consecutive_vertices"],
            "status": "no_supplied_rate"
            if identifier not in supplied
            else ("inside_crop_and_domain" if segments else "outside_crop_or_domain"),
        }
        street["segments"] = segments
    result = copy.deepcopy(case)
    result.setdefault("sources", [])
    source_ids = {source["id"] for source in result["sources"]}
    for row_index, supplied_row in enumerate(
        sorted(rows, key=lambda r: (r["street_id"], r["constituent"]))
    ):
        row = dict(supplied_row)
        street_id = row["street_id"]
        if street_id not in streets:
            _require(
                row["rate_kg_s_m"] == 0,
                f"rates.rows[{row['csv_line']}].street_id",
                f"Positive-rate street {street_id!r} is unknown to the supplied GeoJSON",
            )
            row.update(
                status="unknown_street_zero_rate",
                source_ids=[],
                retained_length_m=0.0,
                emission_rate_kg_s=0.0,
            )
            report["unmatched_zero_rate_rows"].append(row)
            report["rate_rows"].append(row)
            continue
        street = streets[street_id]
        row.update(
            retained_length_m=report["streets"][street_id]["retained_length_m"],
            source_ids=[],
        )
        emission = row["rate_kg_s_m"] * row["retained_length_m"]
        _require(
            math.isfinite(emission),
            f"rates.rows[{row['csv_line']}].rate_kg_s_m",
            "Integrated emission rate overflows",
        )
        row["emission_rate_kg_s"] = emission
        row["status"] = (
            "zero_supplied_rate"
            if row["rate_kg_s_m"] == 0
            else report["streets"][street_id]["status"]
        )
        if row["rate_kg_s_m"] > 0:
            for segment_index, (start, end) in enumerate(street["segments"]):
                segment = LineString([start[:2], end[:2]])
                for building_id, footprint in shapes:
                    _require(
                        not segment.intersects(footprint),
                        f"streets[{street_id!r}].segments[{segment_index}]",
                        f"Street {street_id!r} intersects/touches building {building_id!r}; source rejected without relocation",
                        street_id=street_id,
                        constituent=row["constituent"],
                        building_id=building_id,
                        segment_from_m=start,
                        segment_to_m=end,
                    )
                identifier = f"traffic-{row_index:04d}-{segment_index:05d}"
                _require(
                    identifier not in source_ids,
                    "case.sources",
                    f"Generated source ID {identifier!r} conflicts with an existing source",
                )
                source_ids.add(identifier)
                source = {
                    "kind": "line",
                    "id": identifier,
                    "constituent": row["constituent"],
                    "from_m": start,
                    "to_m": end,
                    "rate_kg_s_m": row["rate_kg_s_m"],
                }
                result["sources"].append(source)
                row["source_ids"].append(identifier)
                report["added_sources"].append(
                    {
                        "source_id": identifier,
                        "street_id": street_id,
                        "constituent": row["constituent"],
                        "length_m": math.dist(start, end),
                        "emission_rate_kg_s": row["rate_kg_s_m"]
                        * math.dist(start, end),
                    }
                )
        report["rate_rows"].append(row)
    report["total_added_rate_kg_s"] = math.fsum(
        row["emission_rate_kg_s"] for row in report["rate_rows"]
    )
    _require(
        math.isfinite(report["total_added_rate_kg_s"]),
        "rates",
        "Total integrated emission rate overflows",
    )
    report["output_case_json_sha256"] = _json_digest(result)
    return result, report


def convert(
    case,
    map_provenance,
    streets_path: Path,
    rates_path: Path,
    *,
    height_m,
    street_id_property="id",
    street_license="not_declared",
    street_attribution="not_declared",
    rates_description="explicit_user_supplied_csv; no emission factors inferred",
):
    """Convert exact consumed file bytes; reject with coded/hashable evidence.

    Existing constituents and sources are preserved. Source XY must share the
    projected metric map frame; input coordinate Z is replaced by height_m and
    recorded explicitly. The CLI runs native check on the complete copied case.
    """
    street_raw, rates_raw = (
        Path(streets_path).read_bytes(),
        Path(rates_path).read_bytes(),
    )
    try:
        return _convert(
            case,
            map_provenance,
            street_raw,
            rates_raw,
            height_m=height_m,
            street_id_property=street_id_property,
            street_license=street_license,
            street_attribution=street_attribution,
            rates_description=rates_description,
        )
    except TrafficSourceError as exc:
        exc.diagnostic["input_sha256"] = {
            "streets": _digest(street_raw),
            "rates": _digest(rates_raw),
        }
        raise


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--map-provenance", type=Path, required=True)
    parser.add_argument("--streets", type=Path, required=True)
    parser.add_argument("--rates", type=Path, required=True)
    parser.add_argument("--height-m", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--binary", type=Path, default=ROOT / "target/release/cfd-craft"
    )
    parser.add_argument("--street-id-property", default="id")
    parser.add_argument("--street-license", default="not_declared")
    parser.add_argument("--street-attribution", default="not_declared")
    parser.add_argument(
        "--rates-description",
        default="explicit_user_supplied_csv; no emission factors inferred",
    )
    args = parser.parse_args()
    created = False
    try:
        _require(not args.output.exists(), "output", "Choose a new output directory")
        args.output.mkdir(parents=True)
        created = True
        case_raw, map_raw = args.case.read_bytes(), args.map_provenance.read_bytes()
        case, report = convert(
            _load_json(case_raw, "case"),
            _load_json(map_raw, "map_provenance"),
            args.streets,
            args.rates,
            height_m=args.height_m,
            street_id_property=args.street_id_property,
            street_license=args.street_license,
            street_attribution=args.street_attribution,
            rates_description=args.rates_description,
        )
        report["input_case_file_sha256"] = _digest(case_raw)
        report["map_provenance_file_sha256"] = _digest(map_raw)
        target = args.output / "case.json"
        _write(target, case)
        _write(args.output / "traffic-provenance.json", report)
        process = subprocess.run(
            [str(args.binary.resolve()), "check", str(target.resolve())],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        (args.output / "check.json").write_text(process.stdout)
        (args.output / "check.stderr").write_text(process.stderr)
        report["native_check_exit_code"] = process.returncode
        _write(args.output / "traffic-provenance.json", report)
        _require(
            process.returncode == 0,
            "native_check",
            "Complete converted case failed native check; case/provenance/check output retained",
        )
        print(
            json.dumps(
                {
                    "added_sources": len(report["added_sources"]),
                    "total_added_rate_kg_s": report["total_added_rate_kg_s"],
                    "native_check_passed": True,
                }
            )
        )
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        if isinstance(exc, TrafficSourceError):
            diagnostic = exc.diagnostic
        else:
            diagnostic = {"code": "CFD-M002", "path": "traffic", "message": str(exc)}
        if created:
            _write(args.output / "diagnostic.json", diagnostic)
        print(
            f"{diagnostic['code']} {diagnostic['path']}: {diagnostic['message']}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
