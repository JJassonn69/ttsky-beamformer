#!/usr/bin/env python3
"""Check routing interactions on the flattened release GDS.

Magic's source-cell DRC can miss spacing and connectivity interactions between
top-level paint and hierarchical PCells.  This dependency-free checker reads
the exact GDS that will be submitted, flattens its hierarchy, and mirrors the
small set of independent SKY130 rules that previously escaped local signoff:

* met3 and met4 minimum spacing: 0.30 um;
* met4 connected-area minimum: 0.24 um^2;
* capm spacing to an unrelated met3 component: 1.34 um.

It intentionally accepts only axis-aligned rectangles on the checked layers.
Unexpected geometry is a hard failure rather than a silent false pass.
"""

from __future__ import annotations

import argparse
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

Layer = tuple[int, int]
Point = tuple[float, float]
Rect = tuple[float, float, float, float]
Matrix = tuple[float, float, float, float, float, float]

MET3 = (70, 20)
CAPM = (89, 44)
MET4 = (71, 20)


@dataclass
class Reference:
    name: str
    origin: tuple[int, int]
    reflected: bool = False
    magnification: float = 1.0
    angle: float = 0.0


@dataclass
class Structure:
    polygons: list[tuple[Layer, list[tuple[int, int]]]] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)


def real8(data: bytes) -> float:
    if data == b"\0" * 8:
        return 0.0
    sign = -1.0 if data[0] & 0x80 else 1.0
    exponent = (data[0] & 0x7F) - 64
    mantissa = int.from_bytes(data[1:], "big") / float(1 << 56)
    return sign * mantissa * (16.0**exponent)


def parse_gds(path: Path) -> tuple[dict[str, Structure], float]:
    structures: dict[str, Structure] = {}
    current: Structure | None = None
    current_name = ""
    element: dict[str, object] | None = None
    meters_per_database_unit = 1e-9
    raw = path.read_bytes()
    offset = 0
    while offset < len(raw):
        if offset + 4 > len(raw):
            raise ValueError(f"truncated GDS record at byte {offset}")
        length, record_type, _data_type = struct.unpack(">HBB", raw[offset : offset + 4])
        if length < 4 or offset + length > len(raw):
            raise ValueError(f"invalid GDS record at byte {offset}")
        data = raw[offset + 4 : offset + length]
        offset += length

        if record_type == 0x03 and len(data) >= 16:  # UNITS
            meters_per_database_unit = real8(data[8:16])
        elif record_type == 0x05:  # BGNSTR
            current = Structure()
            current_name = ""
        elif record_type == 0x06:  # STRNAME
            current_name = data.rstrip(b"\0").decode("ascii")
        elif record_type in (0x08, 0x0A):  # BOUNDARY or SREF
            element = {"type": record_type, "layer": 0, "datatype": 0}
        elif record_type == 0x0D and element is not None:  # LAYER
            element["layer"] = struct.unpack(">h", data)[0]
        elif record_type == 0x0E and element is not None:  # DATATYPE
            element["datatype"] = struct.unpack(">h", data)[0]
        elif record_type == 0x10 and element is not None:  # XY
            values = struct.unpack(f">{len(data) // 4}i", data)
            element["xy"] = list(zip(values[0::2], values[1::2]))
        elif record_type == 0x12 and element is not None:  # SNAME
            element["name"] = data.rstrip(b"\0").decode("ascii")
        elif record_type == 0x1A and element is not None:  # STRANS
            element["reflected"] = bool(struct.unpack(">H", data)[0] & 0x8000)
        elif record_type == 0x1B and element is not None:  # MAG
            element["magnification"] = real8(data)
        elif record_type == 0x1C and element is not None:  # ANGLE
            element["angle"] = real8(data)
        elif record_type == 0x11 and element is not None and current is not None:
            xy = element.get("xy", [])
            if element["type"] == 0x08 and len(xy) >= 4:
                current.polygons.append(
                    ((int(element["layer"]), int(element["datatype"])), list(xy))
                )
            elif element["type"] == 0x0A and xy:
                current.references.append(
                    Reference(
                        name=str(element["name"]),
                        origin=xy[0],
                        reflected=bool(element.get("reflected", False)),
                        magnification=float(element.get("magnification", 1.0)),
                        angle=float(element.get("angle", 0.0)),
                    )
                )
            element = None
        elif record_type == 0x07 and current is not None:  # ENDSTR
            structures[current_name] = current
            current = None
    return structures, meters_per_database_unit * 1e6


def compose(parent: Matrix, child: Matrix) -> Matrix:
    a, b, c, d, tx, ty = parent
    e, f, g, h, ux, uy = child
    return (
        a * e + b * g,
        a * f + b * h,
        c * e + d * g,
        c * f + d * h,
        a * ux + b * uy + tx,
        c * ux + d * uy + ty,
    )


def reference_matrix(reference: Reference) -> Matrix:
    theta = math.radians(reference.angle)
    cosine, sine = math.cos(theta), math.sin(theta)
    scale_y = -reference.magnification if reference.reflected else reference.magnification
    scale_x = reference.magnification
    return (
        cosine * scale_x,
        -sine * scale_y,
        sine * scale_x,
        cosine * scale_y,
        reference.origin[0],
        reference.origin[1],
    )


def transform(matrix: Matrix, point: tuple[int, int]) -> Point:
    a, b, c, d, tx, ty = matrix
    x, y = point
    return a * x + b * y + tx, c * x + d * y + ty


def flatten_rectangles(
    structures: dict[str, Structure], top: str, database_um: float
) -> dict[Layer, list[Rect]]:
    wanted = {MET3, MET4, CAPM}
    output: dict[Layer, list[Rect]] = {layer: [] for layer in wanted}

    def visit(name: str, matrix: Matrix, ancestry: tuple[str, ...]) -> None:
        if name in ancestry:
            raise ValueError(f"recursive GDS hierarchy: {' -> '.join(ancestry + (name,))}")
        if name not in structures:
            raise ValueError(f"GDS references missing structure {name}")
        structure = structures[name]
        for layer, polygon in structure.polygons:
            if layer not in wanted:
                continue
            points = [transform(matrix, point) for point in polygon]
            if points[0] != points[-1]:
                points.append(points[0])
            if any(
                first[0] != second[0] and first[1] != second[1]
                for first, second in zip(points, points[1:])
            ):
                raise ValueError(f"non-orthogonal polygon on checked layer {layer}")
            xs = [point[0] * database_um for point in points]
            ys = [point[1] * database_um for point in points]
            rectangle = (min(xs), min(ys), max(xs), max(ys))
            polygon_area = abs(
                sum(
                    points[index][0] * points[index + 1][1]
                    - points[index + 1][0] * points[index][1]
                    for index in range(len(points) - 1)
                )
            ) * 0.5 * database_um * database_um
            rectangle_area = (rectangle[2] - rectangle[0]) * (rectangle[3] - rectangle[1])
            if not math.isclose(polygon_area, rectangle_area, abs_tol=1e-9):
                raise ValueError(f"non-rectangular polygon on checked layer {layer}")
            output[layer].append(rectangle)
        for reference in structure.references:
            visit(
                reference.name,
                compose(matrix, reference_matrix(reference)),
                ancestry + (name,),
            )

    visit(top, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), ())
    return output


def rectangle_gap(first: Rect, second: Rect) -> float:
    dx = max(0.0, first[0] - second[2], second[0] - first[2])
    dy = max(0.0, first[1] - second[3], second[1] - first[3])
    return math.hypot(dx, dy)


def connected_components(rectangles: list[Rect]) -> list[list[Rect]]:
    parent = list(range(len(rectangles)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = root(first), root(second)
        if first_root != second_root:
            parent[second_root] = first_root

    for first_index, first in enumerate(rectangles):
        for second_index, second in enumerate(rectangles[:first_index]):
            if rectangle_gap(first, second) == 0.0:
                union(first_index, second_index)
    grouped: dict[int, list[Rect]] = {}
    for index, rectangle in enumerate(rectangles):
        grouped.setdefault(root(index), []).append(rectangle)
    return list(grouped.values())


def component_gap(first: list[Rect], second: list[Rect]) -> float:
    return min(rectangle_gap(a, b) for a in first for b in second)


def union_area(rectangles: list[Rect]) -> float:
    x_edges = sorted({rectangle[0] for rectangle in rectangles} | {rectangle[2] for rectangle in rectangles})
    area = 0.0
    for left, right in zip(x_edges, x_edges[1:]):
        intervals = sorted(
            (rectangle[1], rectangle[3])
            for rectangle in rectangles
            if rectangle[0] < right and rectangle[2] > left
        )
        if not intervals:
            continue
        bottom, top = intervals[0]
        height = 0.0
        for next_bottom, next_top in intervals[1:]:
            if next_bottom > top:
                height += top - bottom
                bottom, top = next_bottom, next_top
            else:
                top = max(top, next_top)
        height += top - bottom
        area += (right - left) * height
    return area


def spacing_violations(components: list[list[Rect]], minimum: float) -> list[float]:
    violations: list[float] = []
    for first_index, first in enumerate(components):
        for second in components[:first_index]:
            gap = component_gap(first, second)
            if gap < minimum - 1e-9:
                violations.append(gap)
    return violations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("gds", type=Path)
    parser.add_argument("--top", help="top GDS structure; defaults to the GDS filename stem")
    args = parser.parse_args()
    top = args.top or args.gds.stem
    structures, database_um = parse_gds(args.gds)
    rectangles = flatten_rectangles(structures, top, database_um)
    met3 = connected_components(rectangles[MET3])
    met4 = connected_components(rectangles[MET4])
    capm = connected_components(rectangles[CAPM])

    met3_spacing = spacing_violations(met3, 0.30)
    met4_spacing = spacing_violations(met4, 0.30)
    met4_area = [union_area(component) for component in met4 if union_area(component) < 0.24 - 1e-9]
    capm_spacing = []
    for plate in capm:
        for metal in met3:
            gap = component_gap(plate, metal)
            if 0.0 < gap < 1.34 - 1e-9:
                capm_spacing.append(gap)

    checks = {
        "met3 spacing": met3_spacing,
        "met4 spacing": met4_spacing,
        "met4 minimum area": met4_area,
        "capm-to-unrelated-met3 spacing": capm_spacing,
    }
    failures = {name: values for name, values in checks.items() if values}
    print(
        "Flattened GDS audit: "
        f"{len(rectangles[MET3])} M3 rectangles/{len(met3)} components, "
        f"{len(rectangles[MET4])} M4 rectangles/{len(met4)} components, "
        f"{len(capm)} capm component(s)"
    )
    for name, values in failures.items():
        sample = ", ".join(f"{value:.3f}" for value in sorted(values)[:8])
        unit = "um^2" if name == "met4 minimum area" else "um"
        print(f"FAIL {name}: {len(values)} marker(s); smallest {sample} {unit}")
    if failures:
        raise SystemExit(1)
    print("Flattened GDS routing rules passed: M3/M4 spacing, M4 area, and capm clearance")


if __name__ == "__main__":
    main()
