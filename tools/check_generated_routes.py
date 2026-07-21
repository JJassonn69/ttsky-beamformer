#!/usr/bin/env python3
"""Audit generated routing for shorts and matched-pair geometry.

The router deliberately emits overlapping landing pads and repeated branches
on the same logical net.  Metrics therefore union collinear wire intervals and
exclude the known via-landing rectangles before comparing matched nets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

LAYERS = r"metal[1-4]|locali|via[1-3]|viali"
WIRE_LAYERS = ("metal1", "metal2", "metal3", "metal4")
VIA_LAYERS = ("via1", "via2", "via3")
EPSILON = 1e-6
VIA_ADJACENT_LAYERS = {
    "viali": ("locali", "metal1"),
    "via1": ("metal1", "metal2"),
    "via2": ("metal2", "metal3"),
    "via3": ("metal3", "metal4"),
}
TOP_PIN_BOTTOM = 224.76
TOP_PIN_TOP = 225.76
TOP_PIN_HALF_WIDTH = 0.15
TOP_PIN_MINIMUM_SPACING = 0.30
ROUTING_MINIMUM_SPACING = {
    "metal3": 0.30,
    "metal4": 0.30,
}
ROUTING_MINIMUM_WIDTH = {
    "metal3": 0.30,
    "metal4": 0.30,
}

# Exact M4 pin centers from the TinyTapeout SKY130 analog template LEF.  These
# shapes exist in the base cell but not in generated route.tcl, so the route
# audit must add them explicitly.  Only clk and ui_in[0] are used by this
# design; all other top-edge pins remain obstacles even when logically unused.
TOP_M4_PINS: tuple[tuple[str, float, frozenset[str]], ...] = (
    ("clk", 143.98, frozenset({"clk"})),
    ("ena", 146.74, frozenset()),
    ("rst_n", 141.22, frozenset()),
    ("ui_in[0]", 138.46, frozenset({"select", "ui_in[0]"})),
    ("ui_in[1]", 135.70, frozenset()),
    ("ui_in[2]", 132.94, frozenset()),
    ("ui_in[3]", 130.18, frozenset()),
    ("ui_in[4]", 127.42, frozenset()),
    ("ui_in[5]", 124.66, frozenset()),
    ("ui_in[6]", 121.90, frozenset()),
    ("ui_in[7]", 119.14, frozenset()),
    *((f"uio_in[{index}]", center, frozenset()) for index, center in enumerate(
        (116.38, 113.62, 110.86, 108.10, 105.34, 102.58, 99.82, 97.06)
    )),
    *((f"uo_out[{index}]", center, frozenset()) for index, center in enumerate(
        (94.30, 91.54, 88.78, 86.02, 83.26, 80.50, 77.74, 74.98)
    )),
    *((f"uio_out[{index}]", center, frozenset()) for index, center in enumerate(
        (72.22, 69.46, 66.70, 63.94, 61.18, 58.42, 55.66, 52.90)
    )),
    *((f"uio_oe[{index}]", center, frozenset()) for index, center in enumerate(
        (50.14, 47.38, 44.62, 41.86, 39.10, 36.34, 33.58, 30.82)
    )),
)


@dataclass(frozen=True)
class Shape:
    layer: str
    x1: float
    y1: float
    x2: float
    y2: float
    net: str
    route: str
    line: int

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[float, float]:
        return (round((self.x1 + self.x2) / 2.0, 4),
                round((self.y1 + self.y2) / 2.0, 4))


@dataclass(frozen=True)
class NetLabel:
    net: str
    x: float
    y: float
    line: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("route", nargs="?", default="build/layout/route.tcl")
    parser.add_argument("--manifest", default="layout/circuit.json")
    parser.add_argument("--report")
    return parser.parse_args()


def parse_route(path: Path) -> dict[str, list[Shape]]:
    shapes: dict[str, list[Shape]] = defaultdict(list)
    net: str | None = None
    route = ""
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        route_comment = None
        for pattern in (r"# horizontal net track: (.+)", r"# .* -> (.+)"):
            match = re.match(pattern, line)
            if match:
                route_comment = match.group(1)
                break
        if route_comment is not None:
            net = route_comment
            route = line[2:].strip()
        match = re.match(
            rf"paint_rect ({LAYERS}) ([\d.-]+) ([\d.-]+) ([\d.-]+) ([\d.-]+)",
            line,
        )
        if match and net is not None:
            layer = match.group(1)
            x1, y1, x2, y2 = map(float, match.groups()[1:])
            shapes[layer].append(
                Shape(layer, min(x1, x2), min(y1, y2), max(x1, x2),
                      max(y1, y2), net, route, line_number)
            )
    return shapes


def parse_net_labels(path: Path) -> list[NetLabel]:
    labels: list[NetLabel] = []
    net: str | None = None
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        match = re.match(r"# net label: (.+)", line)
        if match:
            net = match.group(1)
            continue
        if net is None:
            continue
        match = re.match(
            r"box ([\d.-]+)um ([\d.-]+)um ([\d.-]+)um ([\d.-]+)um", line
        )
        if match:
            x1, y1, x2, y2 = map(float, match.groups())
            if abs(x2 - x1) > EPSILON or abs(y2 - y1) > EPSILON:
                raise ValueError(f"net label box at line {line_number} is not a point")
            labels.append(NetLabel(net, x1, y1, line_number))
            net = None
    if net is not None:
        raise ValueError(f"net label {net} has no following box")
    return labels


def label_connection_errors(
    shapes: dict[str, list[Shape]], labels: list[NetLabel],
) -> list[str]:
    """Reject labels at open space or ambiguous cross-net layer crossings."""
    conductors = [
        shape for layer in ("metal3", "via3", "metal4")
        for shape in shapes.get(layer, [])
    ]
    errors: list[str] = []
    for label in labels:
        covering = [
            shape for shape in conductors
            if shape.x1 - EPSILON <= label.x <= shape.x2 + EPSILON
            and shape.y1 - EPSILON <= label.y <= shape.y2 + EPSILON
        ]
        if not any(shape.net == label.net for shape in covering):
            errors.append(
                f"label {label.net} line {label.line} is not on its own conductor"
            )
        foreign = sorted({shape.net for shape in covering if shape.net != label.net})
        if foreign:
            errors.append(
                f"label {label.net} line {label.line} also overlaps foreign "
                f"conductor(s): {', '.join(foreign)}"
            )
    return errors


def overlaps(a: Shape, b: Shape) -> bool:
    return (min(a.x2, b.x2) >= max(a.x1, b.x1)
            and min(a.y2, b.y2) >= max(a.y1, b.y1))


def same_layer_components(layer_shapes: list[Shape]) -> list[list[Shape]]:
    """Group touching/overlapping rectangles on one conductor layer."""
    parents = list(range(len(layer_shapes)))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = root(first), root(second)
        if first_root != second_root:
            parents[second_root] = first_root

    for first_index, first in enumerate(layer_shapes):
        for second_index, second in enumerate(layer_shapes[:first_index]):
            if first.net == second.net and overlaps(first, second):
                union(first_index, second_index)
    grouped: dict[int, list[Shape]] = defaultdict(list)
    for index, shape in enumerate(layer_shapes):
        grouped[root(index)].append(shape)
    return list(grouped.values())


def overlap_errors(shapes: dict[str, list[Shape]]) -> list[str]:
    errors: list[str] = []
    for layer, layer_shapes in shapes.items():
        for index, first in enumerate(layer_shapes):
            for second in layer_shapes[index + 1:]:
                if first.net != second.net and overlaps(first, second):
                    errors.append(
                        f"{layer}: {first.net} line {first.line} overlaps "
                        f"{second.net} line {second.line}"
                    )
    return errors


def rectangle_union_covers(
    target: tuple[float, float, float, float], candidates: list[Shape],
) -> bool:
    """Return true when candidate rectangles completely cover target."""
    left, bottom, right, top = target
    clipped: list[tuple[float, float, float, float]] = []
    for shape in candidates:
        rectangle = (
            max(left, shape.x1),
            max(bottom, shape.y1),
            min(right, shape.x2),
            min(top, shape.y2),
        )
        if rectangle[0] < rectangle[2] - EPSILON and rectangle[1] < rectangle[3] - EPSILON:
            clipped.append(rectangle)
    x_edges = sorted({left, right, *(value for item in clipped for value in (item[0], item[2]))})
    y_edges = sorted({bottom, top, *(value for item in clipped for value in (item[1], item[3]))})
    for x1, x2 in zip(x_edges, x_edges[1:]):
        for y1, y2 in zip(y_edges, y_edges[1:]):
            if x2 - x1 <= EPSILON or y2 - y1 <= EPSILON:
                continue
            x, y = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            if not any(
                shape.x1 - EPSILON <= x <= shape.x2 + EPSILON
                and shape.y1 - EPSILON <= y <= shape.y2 + EPSILON
                for shape in candidates
            ):
                return False
    return True


def orthogonal_neck_errors(shapes: dict[str, list[Shape]]) -> list[str]:
    """Reject half-width metal necks at Manhattan bends before GDS export.

    Two nominal-width rectangles that both stop on the same centerline form
    only a half-width corner overlap.  Magic exposes that re-entrant overlap
    as a minimum-width marker after GDS booleanization.  A legal T/crossing or
    an explicit full-width corner fill covers the complete minimum-width
    square around the centerline intersection and passes this check.
    """
    errors: list[str] = []
    reported: set[tuple[str, str, float, float]] = set()
    for layer, minimum in ROUTING_MINIMUM_WIDTH.items():
        layer_shapes = shapes.get(layer, [])
        for net in sorted({shape.net for shape in layer_shapes}):
            candidates = [shape for shape in layer_shapes if shape.net == net]
            horizontal = [shape for shape in candidates if shape.width > shape.height + EPSILON]
            vertical = [shape for shape in candidates if shape.height > shape.width + EPSILON]
            for first in horizontal:
                for second in vertical:
                    x, y = second.center[0], first.center[1]
                    if not (
                        first.x1 - EPSILON <= x <= first.x2 + EPSILON
                        and second.y1 - EPSILON <= y <= second.y2 + EPSILON
                    ):
                        continue
                    key = (layer, net, round(x, 4), round(y, 4))
                    if key in reported:
                        continue
                    half = minimum / 2.0
                    target = (x - half, y - half, x + half, y + half)
                    if rectangle_union_covers(target, candidates):
                        continue
                    reported.add(key)
                    errors.append(
                        f"{layer}: {net} has a sub-{minimum:.2f} um orthogonal "
                        f"neck at ({x:.4f}, {y:.4f}) near lines "
                        f"{first.line}/{second.line}"
                    )
    return errors


def via_connection_errors(shapes: dict[str, list[Shape]]) -> list[str]:
    """Reject a via cut overlapping adjacent metal attributed to another net."""
    errors: list[str] = []
    for via_layer, adjacent_layers in VIA_ADJACENT_LAYERS.items():
        for via in shapes.get(via_layer, []):
            for metal_layer in adjacent_layers:
                for metal in shapes.get(metal_layer, []):
                    if via.net != metal.net and overlaps(via, metal):
                        errors.append(
                            f"{via_layer}: {via.net} line {via.line} overlaps "
                            f"{metal_layer} for {metal.net} line {metal.line}"
                        )
    return errors


def disconnected_route_errors(shapes: dict[str, list[Shape]]) -> list[str]:
    """Reject floating same-net metal/via islands in generated geometry."""
    by_net: dict[str, list[Shape]] = defaultdict(list)
    for layer_shapes in shapes.values():
        for shape in layer_shapes:
            # Degenerate paint boxes produce no mask geometry and therefore
            # are not electrical components.
            if shape.width > EPSILON and shape.height > EPSILON:
                by_net[shape.net].append(shape)

    errors: list[str] = []
    for net, net_shapes in sorted(by_net.items()):
        parents = list(range(len(net_shapes)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(first: int, second: int) -> None:
            first_root = find(first)
            second_root = find(second)
            if first_root != second_root:
                parents[second_root] = first_root

        for first_index, first in enumerate(net_shapes):
            for second_index in range(first_index + 1, len(net_shapes)):
                second = net_shapes[second_index]
                connected = first.layer == second.layer and overlaps(first, second)
                if not connected and first.layer in VIA_ADJACENT_LAYERS:
                    connected = (
                        second.layer in VIA_ADJACENT_LAYERS[first.layer]
                        and overlaps(first, second)
                    )
                if not connected and second.layer in VIA_ADJACENT_LAYERS:
                    connected = (
                        first.layer in VIA_ADJACENT_LAYERS[second.layer]
                        and overlaps(first, second)
                    )
                if connected:
                    union(first_index, second_index)

        components: dict[int, list[Shape]] = defaultdict(list)
        for index, shape in enumerate(net_shapes):
            components[find(index)].append(shape)
        ordered = sorted(components.values(), key=len, reverse=True)
        for component in ordered[1:]:
            sample = min(component, key=lambda shape: shape.line)
            errors.append(
                f"{net}: disconnected generated component with "
                f"{len(component)} shape(s), starting at {sample.layer} "
                f"line {sample.line}"
            )
    return errors


def rectangle_gap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    dx = max(0.0, first[0] - second[2], second[0] - first[2])
    dy = max(0.0, first[1] - second[3], second[1] - first[3])
    return (dx * dx + dy * dy) ** 0.5


def same_layer_spacing_errors(shapes: dict[str, list[Shape]]) -> list[str]:
    """Reject sub-rule spacing between generated shapes on different nets."""
    errors: list[str] = []
    for layer, minimum in ROUTING_MINIMUM_SPACING.items():
        layer_shapes = shapes.get(layer, [])
        for index, first in enumerate(layer_shapes):
            first_rect = (first.x1, first.y1, first.x2, first.y2)
            for second in layer_shapes[index + 1:]:
                if first.net == second.net:
                    continue
                gap = rectangle_gap(
                    first_rect, (second.x1, second.y1, second.x2, second.y2)
                )
                # Overlaps are reported separately with more direct wording.
                if EPSILON < gap < minimum - EPSILON:
                    errors.append(
                        f"{layer}: {first.net} line {first.line} is {gap:.3f} um "
                        f"from {second.net} line {second.line}; minimum is "
                        f"{minimum:.2f} um"
                    )
    return errors


def top_boundary_clearance_errors(shapes: dict[str, list[Shape]]) -> list[str]:
    """Reject M4 routes too close to any standard top-edge boundary pin."""
    errors: list[str] = []
    for shape in shapes.get("metal4", []):
        route_rect = (shape.x1, shape.y1, shape.x2, shape.y2)
        for pin_name, center_x, allowed_nets in TOP_M4_PINS:
            if shape.net in allowed_nets:
                continue
            pin_rect = (
                center_x - TOP_PIN_HALF_WIDTH,
                TOP_PIN_BOTTOM,
                center_x + TOP_PIN_HALF_WIDTH,
                TOP_PIN_TOP,
            )
            gap = rectangle_gap(route_rect, pin_rect)
            if gap < TOP_PIN_MINIMUM_SPACING - EPSILON:
                errors.append(
                    f"metal4: {shape.net} line {shape.line} is {gap:.3f} um "
                    f"from top pin {pin_name}; minimum is "
                    f"{TOP_PIN_MINIMUM_SPACING:.2f} um"
                )
    return errors


def boundary_route_results(
    shapes: dict[str, list[Shape]], constraints: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[str]]:
    """Check that top-pin control routes fan out monotonically downward."""
    results: list[dict[str, object]] = []
    failures: list[str] = []
    for constraint in constraints:
        name = str(constraint["name"])
        net = str(constraint["net"])
        track_route = f"horizontal net track: {net}"
        boundary_route = f"TinyTapeout boundary pin -> {net}"
        track_shapes = [
            shape for shape in shapes.get("metal3", [])
            if shape.net == net and shape.route == track_route
            and shape.width > shape.height
        ]
        boundary_shapes = [
            shape for shape in shapes.get("metal4", [])
            if shape.net == net and shape.route == boundary_route
            and shape.height > shape.width
        ]
        endpoint_shapes = [
            shape for shape in shapes.get("metal4", [])
            if shape.net == net and shape.route not in {track_route, boundary_route}
        ]
        item_failures: list[str] = []
        if len(track_shapes) != 1:
            item_failures.append(
                f"{name}: expected one horizontal M3 track for {net}, "
                f"found {len(track_shapes)}"
            )
            track_y = 0.0
        else:
            track_y = track_shapes[0].center[1]
        if not boundary_shapes:
            item_failures.append(f"{name}: missing top-pin M4 leg for {net}")
            source_leg = float("inf")
        else:
            source_leg = max(shape.height for shape in boundary_shapes)
        if not endpoint_shapes:
            item_failures.append(f"{name}: missing endpoint M4 routes for {net}")
            reversal = float("inf")
        else:
            # The 0.20 um allowance is the intended M4 landing half-width at
            # the M3 track.  Any conductor above that landing means the track
            # sits below a load and creates a down-then-up U-shaped detour.
            reversal = max(
                0.0,
                max(shape.y2 for shape in endpoint_shapes) - (track_y + 0.20),
            )
        source_limit = float(constraint["max_source_leg_um"])
        reversal_limit = float(constraint["max_endpoint_reversal_um"])
        if source_leg > source_limit + EPSILON:
            item_failures.append(
                f"{name}: source-to-track leg {source_leg:.3f} um exceeds "
                f"{source_limit:.3f} um"
            )
        if reversal > reversal_limit + EPSILON:
            item_failures.append(
                f"{name}: endpoint route reverses {reversal:.3f} um above "
                f"the distribution track; limit is {reversal_limit:.3f} um"
            )
        failures.extend(item_failures)
        results.append({
            "name": name,
            "net": net,
            "track_y_um": track_y,
            "source_leg_um": round(source_leg, 6),
            "endpoint_reversal_um": round(reversal, 6),
            "passed": not item_failures,
            "failures": item_failures,
        })
    return results, failures


def close(value: float, target: float) -> bool:
    return abs(value - target) <= EPSILON


def landing_shape(shape: Shape, via_centers: dict[str, set[tuple[float, float]]]) -> bool:
    """Return true for metal rectangles emitted only to enclose a via cut."""
    dimensions = tuple(sorted((round(shape.width, 4), round(shape.height, 4))))
    center = shape.center
    if shape.layer == "metal1":
        return dimensions in {(0.32, 0.32), (0.40, 0.40)} and center in via_centers["via1"]
    if shape.layer == "metal2":
        return ((dimensions == (0.32, 0.32) and center in via_centers["via1"])
                or (dimensions == (0.40, 0.40) and center in via_centers["via2"]))
    if shape.layer == "metal3":
        return dimensions == (0.40, 0.62) and (
            center in via_centers["via2"] or center in via_centers["via3"]
        )
    if shape.layer == "metal4":
        return dimensions == (0.40, 0.40) and center in via_centers["via3"]
    return False


def dead_end_via3_errors(shapes: dict[str, list[Shape]]) -> list[str]:
    """Reject via3 landings that do not continue on both sides of the cut.

    A lower M3 landing may continue laterally on M3 or immediately descend
    through via2 to a device terminal.  Merely belonging to the overall net
    through M4 is not enough: that would leave an unnecessary dead-end M3 pad.
    The upper M4 side must likewise extend beyond its via enclosure.
    """
    via_centers = {
        layer: {shape.center for shape in shapes.get(layer, [])}
        for layer in VIA_LAYERS
    }
    unique_sites = {
        (via.net, *via.center): via for via in shapes.get("via3", [])
    }
    errors: list[str] = []
    for (net, x, y), via in sorted(unique_sites.items()):
        lower = [
            metal for metal in shapes.get("metal3", [])
            if metal.net == net and overlaps(metal, via)
        ]
        upper = [
            metal for metal in shapes.get("metal4", [])
            if metal.net == net and overlaps(metal, via)
        ]
        lateral_m3 = any(
            not landing_shape(metal, via_centers) for metal in lower
        )
        downward_via2 = any(
            cut.net == net and any(overlaps(cut, metal) for metal in lower)
            for cut in shapes.get("via2", [])
        )
        extending_m4 = any(
            not landing_shape(metal, via_centers) for metal in upper
        )
        if not lower or (not lateral_m3 and not downward_via2):
            errors.append(
                f"via3: {net} at ({x:.4f}, {y:.4f}) has a dead-end M3 landing"
            )
        if not upper or not extending_m4:
            errors.append(
                f"via3: {net} at ({x:.4f}, {y:.4f}) has a dead-end M4 landing"
            )

    # A wider stale track rectangle is not geometrically a via landing, so the
    # local test above intentionally regards it as lateral M3.  Catch the more
    # subtle case by examining the complete same-net connectivity graph: an M3
    # component that has no via2 and only hangs from one M4 component performs
    # no routing function even if it is wider than the nominal landing pad.
    m4_component_ids: dict[Shape, int] = {}
    for component_index, component in enumerate(
        same_layer_components(shapes.get("metal4", []))
    ):
        for metal in component:
            m4_component_ids[metal] = component_index
    for component in same_layer_components(shapes.get("metal3", [])):
        net = component[0].net
        attached_via3 = [
            via for via in unique_sites.values()
            if via.net == net and any(overlaps(via, metal) for metal in component)
        ]
        if not attached_via3:
            continue
        has_lateral_m3 = any(
            not landing_shape(metal, via_centers) for metal in component
        )
        if not has_lateral_m3:
            continue
        descends_through_via2 = any(
            cut.net == net and any(overlaps(cut, metal) for metal in component)
            for cut in shapes.get("via2", [])
        )
        if descends_through_via2:
            continue
        attached_m4_components = {
            m4_component_ids[metal]
            for via in attached_via3
            for metal in shapes.get("metal4", [])
            if metal.net == net and overlaps(via, metal)
        }
        if len(attached_m4_components) <= 1:
            left = min(metal.x1 for metal in component)
            bottom = min(metal.y1 for metal in component)
            right = max(metal.x2 for metal in component)
            top = max(metal.y2 for metal in component)
            errors.append(
                f"via3: {net} has a via-only M3 island "
                f"({left:.4f}, {bottom:.4f})-({right:.4f}, {top:.4f})"
            )
    return errors


def merged_length(intervals: list[tuple[float, float]]) -> float:
    merged: list[tuple[float, float]] = []
    for start, stop in sorted(intervals):
        if merged and start <= merged[-1][1] + EPSILON:
            merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        else:
            merged.append((start, stop))
    return sum(stop - start for start, stop in merged)


def shape_metrics(net_shapes: dict[str, list[Shape]], net: str) -> dict[str, object]:
    shapes = net_shapes
    via_centers = {
        layer: {shape.center for shape in shapes.get(layer, []) if shape.net == net}
        for layer in VIA_LAYERS
    }
    intervals: dict[tuple[str, str, float], list[tuple[float, float]]] = defaultdict(list)
    for layer in WIRE_LAYERS:
        for shape in shapes.get(layer, []):
            if shape.net != net or landing_shape(shape, via_centers):
                continue
            if shape.width <= EPSILON or shape.height <= EPSILON:
                continue
            horizontal = shape.width >= shape.height
            orientation = "h" if horizontal else "v"
            centerline = round(
                (shape.y1 + shape.y2) / 2.0 if horizontal
                else (shape.x1 + shape.x2) / 2.0,
                4,
            )
            interval = (shape.x1, shape.x2) if horizontal else (shape.y1, shape.y2)
            if interval[1] - interval[0] > EPSILON:
                intervals[(layer, orientation, centerline)].append(interval)
    wire_lengths = {layer: 0.0 for layer in WIRE_LAYERS}
    for (layer, _orientation, _centerline), layer_intervals in intervals.items():
        wire_lengths[layer] += merged_length(layer_intervals)
    wire_lengths = {layer: round(length, 6) for layer, length in wire_lengths.items()}
    return {
        "wire_length_um": wire_lengths,
        "total_wire_length_um": round(sum(wire_lengths.values()), 6),
        "via_sites": {layer: len(via_centers[layer]) for layer in VIA_LAYERS},
    }


def route_metrics(shapes: dict[str, list[Shape]]) -> dict[str, dict[str, object]]:
    nets = sorted({shape.net for layer_shapes in shapes.values() for shape in layer_shapes})
    return {net: shape_metrics(shapes, net) for net in nets}


def endpoint_path_metrics(
    shapes: dict[str, list[Shape]], endpoint: str, net: str,
    include_global_track: bool = True,
) -> dict[str, object]:
    route_names = {f"{endpoint} -> {net}"}
    if include_global_track:
        route_names.update({
            f"horizontal net track: {net}",
            f"TinyTapeout boundary pin -> {net}",
        })
    selected: dict[str, list[Shape]] = defaultdict(list)
    for layer, layer_shapes in shapes.items():
        selected[layer] = [
            shape for shape in layer_shapes
            if shape.net == net and shape.route in route_names
        ]
    endpoint_route = f"{endpoint} -> {net}"
    if not any(shape.route == endpoint_route for layer in selected.values() for shape in layer):
        raise ValueError(f"missing generated endpoint route {endpoint_route}")
    return shape_metrics(selected, net)


def functional_path_metrics(
    shapes: dict[str, list[Shape]], endpoints: list[str], net: str,
) -> dict[str, object]:
    """Measure the connected source-to-load tree, not one arbitrary branch."""
    route_names = {f"{endpoint} -> {net}" for endpoint in endpoints}
    route_names.add(f"horizontal net track: {net}")
    selected: dict[str, list[Shape]] = defaultdict(list)
    for layer, layer_shapes in shapes.items():
        selected[layer] = [
            shape for shape in layer_shapes
            if shape.net == net and shape.route in route_names
        ]
    for endpoint in endpoints:
        endpoint_route = f"{endpoint} -> {net}"
        if not any(
            shape.route == endpoint_route
            for layer_shapes in selected.values()
            for shape in layer_shapes
        ):
            raise ValueError(f"missing generated endpoint route {endpoint_route}")
    return shape_metrics(selected, net)


def mismatch_percent(first: float, second: float) -> float:
    average = (abs(first) + abs(second)) / 2.0
    if average <= EPSILON:
        return 0.0
    return 100.0 * abs(first - second) / average


def matching_results(
    metrics: dict[str, dict[str, object]], constraints: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[str]]:
    results: list[dict[str, object]] = []
    failures: list[str] = []
    for constraint in constraints:
        name = str(constraint["name"])
        required = bool(constraint.get("required", True))
        first_net, second_net = map(str, constraint["nets"])
        if first_net not in metrics or second_net not in metrics:
            failure = f"{name}: missing route metrics for {first_net} or {second_net}"
            failures.append(failure)
            results.append({"name": name, "passed": False, "failures": [failure]})
            continue
        first = metrics[first_net]
        second = metrics[second_net]
        layers = [str(layer) for layer in constraint.get("layers", WIRE_LAYERS)]
        layer_limit = float(constraint["max_layer_length_mismatch_percent"])
        total_limit = float(constraint["max_total_length_mismatch_percent"])
        pair_failures: list[str] = []
        layer_mismatch: dict[str, float] = {}
        for layer in layers:
            first_length = float(first["wire_length_um"][layer])
            second_length = float(second["wire_length_um"][layer])
            mismatch = mismatch_percent(first_length, second_length)
            layer_mismatch[layer] = mismatch
            if mismatch > layer_limit + EPSILON:
                pair_failures.append(
                    f"{name}: {layer} length mismatch {mismatch:.3f}% > {layer_limit:.3f}% "
                    f"({first_net}={first_length:.3f}um, {second_net}={second_length:.3f}um)"
                )
        first_total = sum(float(first["wire_length_um"][layer]) for layer in layers)
        second_total = sum(float(second["wire_length_um"][layer]) for layer in layers)
        total_mismatch = mismatch_percent(first_total, second_total)
        if total_mismatch > total_limit + EPSILON:
            pair_failures.append(
                f"{name}: selected-layer total mismatch {total_mismatch:.3f}% > "
                f"{total_limit:.3f}% ({first_net}={first_total:.3f}um, "
                f"{second_net}={second_total:.3f}um)"
            )
        via_comparison: dict[str, list[int]] = {}
        for layer in map(str, constraint.get("equal_vias", [])):
            first_count = int(first["via_sites"][layer])
            second_count = int(second["via_sites"][layer])
            via_comparison[layer] = [first_count, second_count]
            if first_count != second_count:
                pair_failures.append(
                    f"{name}: {layer} site count differs "
                    f"({first_net}={first_count}, {second_net}={second_count})"
                )
        for layer, allowed_delta in constraint.get("max_via_site_delta", {}).items():
            layer = str(layer)
            first_count = int(first["via_sites"][layer])
            second_count = int(second["via_sites"][layer])
            via_comparison[layer] = [first_count, second_count]
            if abs(first_count - second_count) > int(allowed_delta):
                pair_failures.append(
                    f"{name}: {layer} site-count delta exceeds {int(allowed_delta)} "
                    f"({first_net}={first_count}, {second_net}={second_count})"
                )
        if required:
            failures.extend(pair_failures)
        results.append({
            "name": name,
            "nets": [first_net, second_net],
            "layers": layers,
            "layer_length_mismatch_percent": layer_mismatch,
            "selected_layer_total_um": [round(first_total, 6), round(second_total, 6)],
            "total_length_mismatch_percent": total_mismatch,
            "via_sites": via_comparison,
            "required": required,
            "geometry_passed": not pair_failures,
            "passed": not pair_failures or not required,
            "failures": pair_failures,
        })
    return results, failures


def endpoint_matching_results(
    shapes: dict[str, list[Shape]], constraints: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[str]]:
    results: list[dict[str, object]] = []
    failures: list[str] = []
    for constraint in expand_endpoint_constraints(constraints):
        name = str(constraint["name"])
        first_endpoint, second_endpoint = map(str, constraint["endpoints"])
        first_net, second_net = map(str, constraint["nets"])
        include_global_track = str(constraint.get("path_scope", "pin")) != "branch"
        first = endpoint_path_metrics(
            shapes, first_endpoint, first_net, include_global_track
        )
        second = endpoint_path_metrics(
            shapes, second_endpoint, second_net, include_global_track
        )
        pair_constraint = dict(constraint)
        pair_constraint["nets"] = [first_net, second_net]
        pair_results, pair_failures = matching_results(
            {first_net: first, second_net: second}, [pair_constraint]
        )
        result = pair_results[0]
        result["endpoints"] = [first_endpoint, second_endpoint]
        # Replace generic net-only prefixes with the physical endpoint names
        # in the human-readable failure output.
        raw_failures = list(result["failures"])
        renamed = [
            failure.replace(
                f"({first_net}=", f"({first_endpoint}=",
            ).replace(
                f", {second_net}=", f", {second_endpoint}=",
            )
            for failure in raw_failures
        ]
        result["failures"] = renamed
        results.append(result)
        if bool(constraint.get("required", True)):
            failures.extend(renamed)
    return results, failures


def expand_endpoint_constraints(
    constraints: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Expand a matched-net endpoint group into independently checked paths."""
    expanded: list[dict[str, object]] = []
    for constraint in constraints:
        if "endpoints" in constraint:
            expanded.append(constraint)
            continue
        pairs = constraint.get("endpoint_pairs")
        if not isinstance(pairs, list) or not pairs:
            raise ValueError(
                f"{constraint.get('name', '<unnamed>')}: endpoint constraint "
                "requires endpoints or a non-empty endpoint_pairs list"
            )
        branch_clusters = constraint.get("branch_clusters")
        if branch_clusters is not None and (
            not isinstance(branch_clusters, list)
            or len(branch_clusters) != len(pairs)
        ):
            raise ValueError(
                f"{constraint.get('name', '<unnamed>')}: branch_clusters "
                "must have one entry per endpoint pair"
            )
        for index, pair in enumerate(pairs, 1):
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError(
                    f"{constraint.get('name', '<unnamed>')}: endpoint pair "
                    f"{index} must contain exactly two endpoints"
                )
            item = dict(constraint)
            item.pop("endpoint_pairs")
            item["name"] = f"{constraint['name']}_{index:02d}"
            item["endpoints"] = pair
            item.pop("branch_clusters", None)
            if branch_clusters is not None:
                cluster = branch_clusters[index - 1]
                if cluster is None:
                    item["local_branch_columns"] = False
                else:
                    item["branch_cluster"] = f"{constraint['name']}:{cluster}"
            expanded.append(item)
    return expanded


def expand_path_constraints(
    constraints: list[dict[str, object]],
) -> list[dict[str, object]]:
    expanded: list[dict[str, object]] = []
    for constraint in constraints:
        path_pairs = constraint.get("path_pairs")
        if not isinstance(path_pairs, list) or not path_pairs:
            raise ValueError(
                f"{constraint.get('name', '<unnamed>')}: path constraint "
                "requires a non-empty path_pairs list"
            )
        for index, pair in enumerate(path_pairs, 1):
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or any(not isinstance(path, list) or len(path) < 2 for path in pair)
            ):
                raise ValueError(
                    f"{constraint.get('name', '<unnamed>')}: path pair {index} "
                    "must contain two endpoint lists"
                )
            item = dict(constraint)
            item.pop("path_pairs")
            item["name"] = f"{constraint['name']}_{index:02d}"
            item["paths"] = pair
            expanded.append(item)
    return expanded


def path_matching_results(
    shapes: dict[str, list[Shape]], constraints: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[str]]:
    results: list[dict[str, object]] = []
    failures: list[str] = []
    for constraint in expand_path_constraints(constraints):
        name = str(constraint["name"])
        first_net, second_net = map(str, constraint["nets"])
        first_path, second_path = constraint["paths"]
        first = functional_path_metrics(shapes, list(map(str, first_path)), first_net)
        second = functional_path_metrics(shapes, list(map(str, second_path)), second_net)
        pair_constraint = dict(constraint)
        pair_constraint["nets"] = [first_net, second_net]
        pair_results, pair_failures = matching_results(
            {first_net: first, second_net: second}, [pair_constraint]
        )
        result = pair_results[0]
        result["paths"] = [first_path, second_path]
        first_label = " -> ".join(map(str, first_path))
        second_label = " -> ".join(map(str, second_path))
        raw_failures = list(result["failures"])
        renamed = [
            failure.replace(f"({first_net}=", f"({first_label}=").replace(
                f", {second_net}=", f", {second_label}="
            )
            for failure in raw_failures
        ]
        result["failures"] = renamed
        results.append(result)
        if bool(constraint.get("required", True)):
            failures.extend(renamed)
    return results, failures


def main() -> None:
    args = parse_args()
    path = Path(args.route)
    manifest = json.loads(Path(args.manifest).read_text())
    shapes = parse_route(path)
    labels = parse_net_labels(path)
    label_errors = label_connection_errors(shapes, labels)
    errors = overlap_errors(shapes)
    via_errors = via_connection_errors(shapes)
    spacing_errors = same_layer_spacing_errors(shapes)
    neck_errors = orthogonal_neck_errors(shapes)
    dead_end_via3 = dead_end_via3_errors(shapes)
    disconnected_errors = disconnected_route_errors(shapes)
    top_boundary_errors = top_boundary_clearance_errors(shapes)
    metrics = route_metrics(shapes)
    results, matching_failures = matching_results(
        metrics, list(manifest.get("route_match_constraints", []))
    )
    endpoint_results, endpoint_failures = endpoint_matching_results(
        shapes, list(manifest.get("route_endpoint_constraints", []))
    )
    path_results, path_failures = path_matching_results(
        shapes, list(manifest.get("route_path_constraints", []))
    )
    boundary_results, boundary_failures = boundary_route_results(
        shapes, list(manifest.get("boundary_route_constraints", []))
    )
    report = {
        "route": str(path),
        "route_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "shape_count": sum(
            shape.width > EPSILON and shape.height > EPSILON
            for layer_shapes in shapes.values()
            for shape in layer_shapes
        ),
        "net_label_count": len(labels),
        "net_label_connection_error_count": len(label_errors),
        "cross_net_overlap_count": len(errors),
        "cross_net_via_overlap_count": len(via_errors),
        "cross_net_spacing_count": len(spacing_errors),
        "orthogonal_neck_count": len(neck_errors),
        "dead_end_via3_site_count": len(dead_end_via3),
        "disconnected_route_component_count": len(disconnected_errors),
        "top_boundary_m4_clearance_count": len(top_boundary_errors),
        "metrics": metrics,
        "matching": results,
        "endpoint_matching": endpoint_results,
        "path_matching": path_results,
        "boundary_routing": boundary_results,
        "passed": (
            not errors and not via_errors and not spacing_errors and not neck_errors
            and not dead_end_via3
            and not disconnected_errors
            and not top_boundary_errors
            and not label_errors
            and not matching_failures
            and not endpoint_failures and not path_failures
            and not boundary_failures
        ),
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"route-matching report={report_path}")
    if errors:
        print("Generated route contains cross-net overlaps:")
        print("\n".join(errors[:50]))
    if via_errors:
        print("Generated route contains cross-net via/metal overlaps:")
        print("\n".join(via_errors[:50]))
    if spacing_errors:
        print("Generated route violates same-layer routing spacing:")
        print("\n".join(spacing_errors[:50]))
    if neck_errors:
        print("Generated route contains sub-width Manhattan necks:")
        print("\n".join(neck_errors[:50]))
    if dead_end_via3:
        print("Generated route contains dead-end via3 landings:")
        print("\n".join(dead_end_via3[:50]))
    if disconnected_errors:
        print("Generated route contains disconnected same-net components:")
        print("\n".join(disconnected_errors[:50]))
    if top_boundary_errors:
        print("Generated route violates top-boundary M4 clearance:")
        print("\n".join(top_boundary_errors[:50]))
    if label_errors:
        print("Generated route contains ambiguous or disconnected net labels:")
        print("\n".join(label_errors[:50]))
    if matching_failures:
        print("Generated route violates matched-pair constraints:")
        print("\n".join(matching_failures))
    if endpoint_failures:
        print("Generated route violates endpoint-path constraints:")
        print("\n".join(endpoint_failures))
    if path_failures:
        print("Generated route violates functional source-to-load constraints:")
        print("\n".join(path_failures))
    if boundary_failures:
        print("Generated route violates boundary-control routing constraints:")
        print("\n".join(boundary_failures))
    if (
        errors or via_errors or spacing_errors or neck_errors or dead_end_via3
        or disconnected_errors
        or top_boundary_errors
        or label_errors
        or matching_failures
        or endpoint_failures or path_failures or boundary_failures
    ):
        raise SystemExit(1)
    print(
        f"Generated-route audit passed ({report['shape_count']} shapes, "
        f"{report['net_label_count']} net labels, "
        f"{len(results)} net pairs, {len(endpoint_results)} endpoint pairs, "
        f"{len(path_results)} functional paths)"
    )


if __name__ == "__main__":
    main()
