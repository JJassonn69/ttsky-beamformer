#!/usr/bin/env python3
"""Check routing interactions on the flattened release GDS.

Magic's source-cell DRC can miss spacing and connectivity interactions between
top-level paint and hierarchical PCells.  This dependency-free checker reads
the exact GDS that will be submitted, flattens its hierarchy, and mirrors the
small set of independent SKY130 rules that previously escaped local signoff:

* met3 and met4 minimum spacing: 0.30 um;
* met4 minimum width: 0.30 um;
* met4 connected-area minimum: 0.24 um^2;
* every via3 cut is fully enclosed by the union of met3 below and met4 above;
* no met4-to-met3 transition terminates on a via-only met3 island;
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

LI1 = (67, 20)
MCON = (67, 44)
MET1 = (68, 20)
VIA1 = (68, 44)
MET2 = (69, 20)
VIA2 = (69, 44)
MET3 = (70, 20)
VIA3 = (70, 44)
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
    # Keep lower-cut layers as well as the escaped upper-metal rule subset.
    # They are inexpensive to flatten and let release tests prove that an
    # extresist contact-meshing warning is not hiding malformed GDS cuts.
    wanted = {MCON, VIA1, MET2, VIA2, MET3, VIA3, MET4, CAPM}
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


def orthogonal_polygon_rectangles(
    points: list[Point], database_um: float,
) -> list[Rect]:
    """Decompose one closed orthogonal polygon into exact horizontal slabs.

    Lower-metal standard-cell shapes are commonly L-shaped, so their bounding
    boxes are too pessimistic for pin-access checks.  The existing release
    checker intentionally rejects such polygons on upper routing layers; this
    helper is separate and is used only where exact lower-metal obstacles are
    required.
    """

    if points[0] != points[-1]:
        points = points + [points[0]]
    if any(
        first[0] != second[0] and first[1] != second[1]
        for first, second in zip(points, points[1:])
    ):
        raise ValueError("non-orthogonal polygon in lower-metal obstacle map")
    y_edges = sorted({point[1] for point in points})
    result: list[Rect] = []
    for bottom, top in zip(y_edges, y_edges[1:]):
        if bottom == top:
            continue
        middle = (bottom + top) / 2.0
        crossings: list[float] = []
        for first, second in zip(points, points[1:]):
            if first[0] != second[0]:
                continue
            lo, hi = sorted((first[1], second[1]))
            if lo <= middle < hi:
                crossings.append(first[0])
        crossings.sort()
        if len(crossings) % 2:
            raise ValueError("invalid orthogonal polygon has odd scanline crossings")
        for left, right in zip(crossings[0::2], crossings[1::2]):
            if left == right:
                continue
            result.append((
                left * database_um, bottom * database_um,
                right * database_um, top * database_um,
            ))
    return result


def flatten_orthogonal_rectangles(
    structures: dict[str, Structure], top: str, database_um: float,
    wanted: set[Layer],
) -> dict[Layer, list[Rect]]:
    """Flatten arbitrary orthogonal polygons on explicitly requested layers."""

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
            transformed = [transform(matrix, point) for point in polygon]
            output[layer].extend(
                orthogonal_polygon_rectangles(transformed, database_um)
            )
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


def clipped_rectangle(rectangle: Rect, boundary: Rect) -> Rect | None:
    clipped = (
        max(rectangle[0], boundary[0]),
        max(rectangle[1], boundary[1]),
        min(rectangle[2], boundary[2]),
        min(rectangle[3], boundary[3]),
    )
    if clipped[0] >= clipped[2] or clipped[1] >= clipped[3]:
        return None
    return clipped


def enclosure_deficit(cut: Rect, conductors: list[Rect]) -> float:
    """Return uncovered cut area, allowing legal split-rectangle junctions."""
    intersections = [
        clipped
        for conductor in conductors
        if (clipped := clipped_rectangle(conductor, cut)) is not None
    ]
    cut_area = (cut[2] - cut[0]) * (cut[3] - cut[1])
    return max(0.0, cut_area - union_area(intersections))


def minimum_width_violations(
    rectangles: list[Rect], minimum: float,
) -> list[float]:
    """Return real narrow features after reconstructing fractured GDS paint.

    Magic may serialize one legal wire as a full-width center rectangle plus
    50 nm edge strips at via and branch junctions.  Testing each serialization
    rectangle independently creates false violations.  A thin fragment is
    legal only when the union covers a full minimum-width band along its
    complete long dimension; a true narrow wire or attached stub still fails.
    """
    violations: list[float] = []
    for rectangle in rectangles:
        x1, y1, x2, y2 = rectangle
        width, height = x2 - x1, y2 - y1
        narrow = min(width, height)
        if narrow >= minimum - 1e-9:
            continue
        candidates: list[Rect] = []
        if height < minimum - 1e-9:
            candidates.extend((
                (x1, y2 - minimum, x2, y2),
                (x1, y1, x2, y1 + minimum),
            ))
        if width < minimum - 1e-9:
            candidates.extend((
                (x2 - minimum, y1, x2, y2),
                (x1, y1, x1 + minimum, y2),
            ))
        if not any(enclosure_deficit(target, rectangles) <= 1e-9 for target in candidates):
            violations.append(narrow)
    return violations


def spacing_violations(components: list[list[Rect]], minimum: float) -> list[float]:
    violations: list[float] = []
    for first_index, first in enumerate(components):
        for second in components[:first_index]:
            gap = component_gap(first, second)
            if gap < minimum - 1e-9:
                violations.append(gap)
    return violations


def via_only_met3_islands(
    rectangles: dict[Layer, list[Rect]],
    components: dict[Layer, list[list[Rect]]],
) -> list[float]:
    """Return areas of M3 components that only hang from one M4 component.

    This is deliberately a connectivity test, not an enclosure test.  A stale
    via3 plus its legal M3 landing can pass DRC while doing no useful work.  A
    useful M3 component below via3 must continue down through via2, bridge two
    otherwise separate M4 components, or form part of the intentional MIM
    capacitor plate geometry.
    """
    dangling: list[float] = []
    for met3_component in components[MET3]:
        attached_via3 = [
            cut for cut in rectangles[VIA3]
            if any(rectangle_gap(cut, metal) == 0.0 for metal in met3_component)
        ]
        if not attached_via3:
            continue
        descends_through_via2 = any(
            any(rectangle_gap(cut, metal) == 0.0 for metal in met3_component)
            for cut in rectangles[VIA2]
        )
        if descends_through_via2:
            continue
        mim_plate_geometry = any(
            component_gap(met3_component, capm_component) == 0.0
            for capm_component in components[CAPM]
        )
        if mim_plate_geometry:
            continue
        attached_met4_components = {
            index
            for cut in attached_via3
            for index, met4_component in enumerate(components[MET4])
            if any(rectangle_gap(cut, metal) == 0.0 for metal in met4_component)
        }
        if len(attached_met4_components) <= 1:
            dangling.append(union_area(met3_component))
    return dangling


def audit_rectangles(
    rectangles: dict[Layer, list[Rect]],
) -> tuple[dict[Layer, list[list[Rect]]], dict[str, list[float]]]:
    """Return flattened components and markers for the escaped rule subset."""
    components = {
        layer: connected_components(rectangles[layer])
        for layer in (MET3, MET4, CAPM)
    }
    met4_width = minimum_width_violations(rectangles[MET4], 0.30)
    met4_area = [
        union_area(component)
        for component in components[MET4]
        if union_area(component) < 0.24 - 1e-9
    ]
    capm_spacing = []
    for plate in components[CAPM]:
        for metal in components[MET3]:
            gap = component_gap(plate, metal)
            if 0.0 < gap < 1.34 - 1e-9:
                capm_spacing.append(gap)
    via3_enclosure = [
        max(
            enclosure_deficit(cut, rectangles[MET3]),
            enclosure_deficit(cut, rectangles[MET4]),
        )
        for cut in rectangles[VIA3]
    ]
    via3_enclosure = [deficit for deficit in via3_enclosure if deficit > 1e-9]
    checks = {
        "met3 spacing": spacing_violations(components[MET3], 0.30),
        "met4 spacing": spacing_violations(components[MET4], 0.30),
        "met4 minimum width": met4_width,
        "met4 minimum area": met4_area,
        "via3 enclosure": via3_enclosure,
        "via-only met3 island": via_only_met3_islands(rectangles, components),
        "capm-to-unrelated-met3 spacing": capm_spacing,
    }
    return components, checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("gds", type=Path)
    parser.add_argument("--top", help="top GDS structure; defaults to the GDS filename stem")
    args = parser.parse_args()
    top = args.top or args.gds.stem
    structures, database_um = parse_gds(args.gds)
    rectangles = flatten_rectangles(structures, top, database_um)
    components, checks = audit_rectangles(rectangles)
    failures = {name: values for name, values in checks.items() if values}
    print(
        "Flattened GDS audit: "
        f"{len(rectangles[MET3])} M3 rectangles/{len(components[MET3])} components, "
        f"{len(rectangles[VIA3])} via3 cuts, "
        f"{len(rectangles[MET4])} M4 rectangles/{len(components[MET4])} components, "
        f"{len(components[CAPM])} capm component(s)"
    )
    for name, values in failures.items():
        sample = ", ".join(f"{value:.3f}" for value in sorted(values)[:8])
        unit = "um^2" if name in {
            "met4 minimum area", "via3 enclosure", "via-only met3 island"
        } else "um"
        print(f"FAIL {name}: {len(values)} marker(s); smallest {sample} {unit}")
    if failures:
        raise SystemExit(1)
    print(
        "Flattened GDS routing rules passed: M3/M4 spacing, M4 width/area, "
        "via3 two-sided enclosure/dead-end connectivity, and capm clearance"
    )


if __name__ == "__main__":
    main()
