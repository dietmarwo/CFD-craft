#!/usr/bin/env python3
"""Export a verified JSON field archive to a ParaView rectilinear VTK XML file."""

import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from check_fields import check, require


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--max-mib", type=int, default=64)
    args = ap.parse_args()
    check(args.run)
    c = json.loads((args.run / "case.json").read_text())
    s = json.loads((args.run / "fields.json").read_text())
    n = c["grid"]["cells"]
    count = math.prod(n)
    require(
        count * (180 + 26 * len(c["constituents"])) < args.max_mib * 1048576,
        "estimated VTK output exceeds budget",
    )
    dx = [L / N for L, N in zip(c["domain"]["size_m"], n, strict=True)]
    face = []
    offset = 0
    for a in range(3):
        dims = n.copy()
        if c["boundaries"]["xyz"[a]] != "periodic":
            dims[a] += 1
        size = math.prod(dims)
        face.append((dims, s["velocity"][offset : offset + size]))
        offset += size
    velocity = []
    mask = []
    for k in range(n[2]):
        for j in range(n[1]):
            for i in range(n[0]):
                q = [i, j, k]
                p = [(v + 0.5) * h for v, h in zip(q, dx, strict=True)]
                mask.append(
                    int(
                        not any(
                            all(
                                lo <= v < hi
                                for lo, v, hi in zip(
                                    b["min_m"], p, b["max_m"], strict=True
                                )
                            )
                            for b in c["geometry"]
                        )
                    )
                )
                for a, (dims, values) in enumerate(face):

                    def ix(v):
                        return (v[2] * dims[1] + v[1]) * dims[0] + v[0]

                    hi = q.copy()
                    hi[a] += 1
                    if c["boundaries"]["xyz"[a]] == "periodic":
                        hi[a] %= n[a]
                    velocity.append(0.5 * (values[ix(q)] + values[ix(hi)]))
    extent = f"0 {n[0]} 0 {n[1]} 0 {n[2]}"
    vtk = ET.Element(
        "VTKFile", type="RectilinearGrid", version="0.1", byte_order="LittleEndian"
    )
    grid = ET.SubElement(vtk, "RectilinearGrid", WholeExtent=extent)
    piece = ET.SubElement(grid, "Piece", Extent=extent)
    data = ET.SubElement(piece, "CellData", Vectors="velocity_m_s")

    def add(parent, name, values, components=1, kind="Float64"):
        node = ET.SubElement(
            parent,
            "DataArray",
            type=kind,
            Name=name,
            NumberOfComponents=str(components),
            format="ascii",
        )
        node.text = " ".join(format(v, ".17g") for v in values)

    add(data, "fluid_mask", mask, kind="UInt8")
    add(data, "velocity_m_s", velocity, 3)
    add(data, "pressure_kinematic_m2_s2", s["pressure"])
    add(data, "k_m2_s2", s["k"])
    add(data, "epsilon_m2_s3", s["epsilon"])
    for constituent, values in zip(c["constituents"], s["concentrations"], strict=True):
        add(data, constituent["id"] + "_kg_m3", values)
    coordinates = ET.SubElement(piece, "Coordinates")
    for a in range(3):
        add(coordinates, "xyz"[a] + "_m", [i * dx[a] for i in range(n[a] + 1)])
    payload = ET.tostring(vtk, encoding="utf-8", xml_declaration=True)
    require(len(payload) <= args.max_mib * 1048576, "actual VTK output exceeds budget")
    with args.output.open("xb") as f:
        f.write(payload)
    print(json.dumps(dict(output=str(args.output), cells=count, bytes=len(payload))))


if __name__ == "__main__":
    main()
