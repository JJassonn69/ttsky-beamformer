#!/usr/bin/env python3
"""Audit V2 control-power connectivity, ownership, coverage, and keepouts."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


CONDUCTORS = ("locali", "metal1", "metal2", "metal3", "metal4")
VIA_LAYERS = {
    "viali": ("locali", "metal1"),
    "via1": ("metal1", "metal2"),
    "via2": ("metal2", "metal3"),
    "via3": ("metal3", "metal4"),
}


def intersects(a: list[float], b: list[float], touch: bool = True) -> bool:
    epsilon = 1e-9 if touch else -1e-9
    return not (
        a[2] < b[0] - epsilon or b[2] < a[0] - epsilon
        or a[3] < b[1] - epsilon or b[3] < a[1] - epsilon
    )


def rectangle_distance(a: list[float], b: list[float]) -> float:
    dx = max(float(a[0]) - float(b[2]), float(b[0]) - float(a[2]), 0.0)
    dy = max(float(a[1]) - float(b[3]), float(b[1]) - float(a[3]), 0.0)
    return math.hypot(dx, dy)


def conductor_components(
    shapes: list[dict[str, Any]], net: str, errors: list[str]
) -> tuple[int, int]:
    conductors = [item for item in shapes if item["net"] == net and item["layer"] in CONDUCTORS]
    vias = [item for item in shapes if item["net"] == net and item["layer"] in VIA_LAYERS]
    edges: dict[int, set[int]] = defaultdict(set)
    for first_index, first in enumerate(conductors):
        for second_index in range(first_index + 1, len(conductors)):
            second = conductors[second_index]
            if first["layer"] == second["layer"] and intersects(first["bbox_um"], second["bbox_um"]):
                edges[first_index].add(second_index)
                edges[second_index].add(first_index)
    for via in vias:
        lower, upper = VIA_LAYERS[via["layer"]]
        lower_nodes = [
            index for index, item in enumerate(conductors)
            if item["layer"] == lower and intersects(item["bbox_um"], via["bbox_um"])
        ]
        upper_nodes = [
            index for index, item in enumerate(conductors)
            if item["layer"] == upper and intersects(item["bbox_um"], via["bbox_um"])
        ]
        if not lower_nodes or not upper_nodes:
            errors.append(
                f"{via['id']} {net}/{via['layer']} lacks "
                f"{'lower' if not lower_nodes else ''}{' and ' if not lower_nodes and not upper_nodes else ''}"
                f"{'upper' if not upper_nodes else ''} conductor ownership"
            )
        for first in lower_nodes:
            for second in upper_nodes:
                edges[first].add(second)
                edges[second].add(first)
    unseen = set(range(len(conductors)))
    components = 0
    while unseen:
        components += 1
        start = unseen.pop()
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for neighbour in edges[node]:
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    queue.append(neighbour)
    return components, len(vias)


def validate(
    plan: dict[str, Any], geometry: dict[str, Any], placement: dict[str, Any]
) -> dict[str, Any]:
    errors: list[str] = []
    shapes = geometry["shapes"]
    rails = geometry["row_rails"]
    contacts = geometry["upper_contacts"]
    helper_rails = geometry.get("fixed_helper_rails", [])
    helper_contacts = geometry.get("fixed_helper_contacts", [])
    helper_nwell_bridges = geometry.get("fixed_helper_nwell_bridges", [])
    minimum_contacts = int(plan["rules"]["minimum_upper_contacts_per_rail"])
    expected_rail_count = sum(
        int(region["row_count"]) + 1 for region in placement["regions"].values()
    )
    if len(rails) != expected_rail_count:
        errors.append(f"row rail count {len(rails)} != {expected_rail_count}")

    rail_keys = {(item["region"], int(item["boundary"])): item for item in rails}
    connection_counts: Counter[tuple[str, int]] = Counter(
        (item["region"], int(item["boundary"])) for item in contacts
    )
    for region_name, region in placement["regions"].items():
        for boundary in range(int(region["row_count"]) + 1):
            record = rail_keys.get((region_name, boundary))
            if not record:
                errors.append(f"missing {region_name} boundary rail {boundary}")
                continue
            expected_net = "VGND" if boundary % 2 == 0 else "VDPWR"
            if record["net"] != expected_net:
                errors.append(f"{region_name} boundary {boundary} is {record['net']}, expected {expected_net}")
            if connection_counts[(region_name, boundary)] < minimum_contacts:
                errors.append(
                    f"{region_name} boundary {boundary} has only "
                    f"{connection_counts[(region_name, boundary)]} upper contacts"
                )

    expected_helper_rails: dict[tuple[str, str, int], dict[str, Any]] = {}
    for group in plan["fixed_helper_standard_cell_power"]["groups"]:
        for segment in group["segments"]:
            for rail_index, rail in enumerate(group["rails"]):
                expected_helper_rails[(
                    group["name"], segment["name"], rail_index,
                )] = {
                    "net": rail["net"],
                    "y_um": float(rail["y"]),
                    "x_span_um": list(map(float, segment["rail_x_span"])),
                    "contacts": [
                        [float(x), float(rail["y"])]
                        for x in segment["contact_x_by_net"][rail["net"]]
                    ],
                }
    actual_helper_rails = {
        (item["group"], item["segment"], int(item["rail"])): item
        for item in helper_rails
    }
    if len(actual_helper_rails) != len(helper_rails):
        errors.append("duplicate fixed-helper rail records")
    if set(actual_helper_rails) != set(expected_helper_rails):
        errors.append("generated fixed-helper rail set differs from frozen plan")
    helper_contact_points: dict[tuple[str, str, int], list[list[float]]] = defaultdict(list)
    for item in helper_contacts:
        helper_contact_points[(
            item["group"], item["segment"], int(item["rail"]),
        )].append(list(map(float, item["point_um"])))
    for key, expected in expected_helper_rails.items():
        actual = actual_helper_rails.get(key)
        if actual is None:
            continue
        if (actual["net"] != expected["net"]
                or any(abs(float(a) - float(b)) > 1e-9
                       for a, b in zip(actual["x_span_um"], expected["x_span_um"]))
                or abs(float(actual["y_um"]) - expected["y_um"]) > 1e-9):
            errors.append(f"fixed-helper rail {key} differs from frozen plan")
        actual_points = sorted(helper_contact_points.get(key, []))
        expected_points = sorted(expected["contacts"])
        if actual_points != expected_points:
            errors.append(
                f"fixed-helper rail {key} contacts {actual_points} != {expected_points}"
            )
        if len(actual_points) < minimum_contacts:
            errors.append(
                f"fixed-helper rail {key} has only {len(actual_points)} upper contacts"
            )

    expected_nwell_bridges = {
        item["name"]: list(map(float, item["bbox"]))
        for item in plan["fixed_helper_standard_cell_power"]["nwell_bridges"]
    }
    actual_nwell_bridges = {
        item["name"]: list(map(float, item["bbox_um"]))
        for item in helper_nwell_bridges
    }
    if actual_nwell_bridges != expected_nwell_bridges:
        errors.append("generated fixed-helper nwell bridges differ from frozen plan")

    # Every placed macro overlaps the complete lower and upper row rail.  The
    # alternating R0/MX (or MY/R180) row convention makes the bottom rail
    # VGND on even rows and VDPWR on odd rows without inspecting hidden PCell
    # geometry.
    covered_power_pins = 0
    powered_instances = (
        placement["placements"]
        + placement["well_taps"]
        + placement.get("fillers", [])
    )
    for item in powered_instances:
        region = item["region"]
        row = int(item["row"])
        box = list(map(float, item["bbox_um"]))
        for boundary in (row, row + 1):
            rail = rail_keys[(region, boundary)]
            y = float(rail["y_um"])
            x0, x1 = map(float, rail["x_span_um"])
            if box[0] < x0 - 1e-9 or box[2] > x1 + 1e-9:
                errors.append(f"{item['instance']} leaves its {rail['net']} rail span")
            if not (box[1] - 0.25 <= y <= box[3] + 0.25):
                errors.append(f"{item['instance']} does not touch boundary rail {boundary}")
            covered_power_pins += 1

    component_report: dict[str, int] = {}
    via_report: dict[str, int] = {}
    for net in ("VDPWR", "VGND"):
        components, via_count = conductor_components(shapes, net, errors)
        component_report[net] = components
        via_report[net] = via_count
        if components != 1:
            errors.append(f"{net} has {components} disconnected conductor components")

    # Same-layer power nets may neither overlap nor use the routing checker as
    # a substitute for minimum clearance.
    spacing = float(plan["rules"]["minimum_same_layer_spacing"])
    cross_net_spacing_count = 0
    for index, first in enumerate(shapes):
        if first["net"] not in ("VDPWR", "VGND"):
            continue
        for second in shapes[index + 1:]:
            if second["net"] == first["net"] or second["layer"] != first["layer"]:
                continue
            distance = rectangle_distance(first["bbox_um"], second["bbox_um"])
            if distance < spacing - 1e-9:
                cross_net_spacing_count += 1
                errors.append(
                    f"{first['id']} and {second['id']} have only {distance:.3f} um "
                    f"{first['layer']} clearance"
                )

    keepout_hits: list[str] = []
    for keepout in plan["reserved_keepouts"]:
        if "bbox" in keepout:
            box = list(map(float, keepout["bbox"]))
        else:
            box = list(map(float, [
                keepout["x_span"][0], keepout["y_span"][0],
                keepout["x_span"][1], keepout["y_span"][1],
            ]))
        layer = keepout.get("layer")
        for shape in shapes:
            if layer and shape["layer"] != layer:
                continue
            if shape["net"] in keepout.get("allowed_power", []):
                continue
            if intersects(shape["bbox_um"], box, touch=False):
                keepout_hits.append(f"{keepout['name']}:{shape['id']}")
    if keepout_hits:
        errors.extend(f"power shape enters keepout {item}" for item in keepout_hits)

    via_ownership = Counter(item["layer"] for item in shapes if item["layer"] in VIA_LAYERS)
    expected_labels = {(item["net"], item["layer"]) for item in geometry["labels"]}
    if expected_labels != {("VDPWR", "metal4"), ("VGND", "metal4")}:
        errors.append(f"unexpected power labels {sorted(expected_labels)}")

    analog_endpoints = {
        (item["component"], item["terminal"]) for item in geometry["analog_endpoints"]
    }
    planned_endpoints = {
        (item["component"], item["terminal"]) for item in plan["analog_vdpwr_endpoints"]
    }
    if analog_endpoints != planned_endpoints:
        errors.append("generated analog VDPWR endpoints differ from frozen plan")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "row_rail_count": len(rails),
        "upper_contact_count": len(contacts),
        "fixed_helper_rail_count": len(helper_rails),
        "fixed_helper_upper_contact_count": len(helper_contacts),
        "fixed_helper_nwell_bridge_count": len(helper_nwell_bridges),
        "covered_standard_cell_tap_and_filler_power_edges": covered_power_pins,
        "net_component_count": component_report,
        "via_count_by_net": via_report,
        "via_count_by_layer": dict(sorted(via_ownership.items())),
        "cross_net_spacing_violation_count": cross_net_spacing_count,
        "keepout_intersection_count": len(keepout_hits),
        "analog_vdpwr_endpoint_count": len(analog_endpoints),
        "metal5_shape_count": sum(item["layer"] == "metal5" for item in shapes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_power_plan.json"))
    parser.add_argument("--geometry", type=Path,
                        default=Path("build/v2/control_power/control_power_geometry.json"))
    parser.add_argument("--placement", type=Path,
                        default=Path("build/v2/control_placement/control_placement.json"))
    parser.add_argument("--report", type=Path,
                        default=Path("build/v2/control_power/control_power_audit.json"))
    args = parser.parse_args()
    report = validate(
        json.loads(args.plan.read_text(encoding="utf-8")),
        json.loads(args.geometry.read_text(encoding="utf-8")),
        json.loads(args.placement.read_text(encoding="utf-8")),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
