#!/usr/bin/env python3
"""Audit phase handoff geometry, ownership, monotonicity, and cross-stage spacing."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_gds_flat_rules import (  # noqa: E402
    MET2, MET3, MET4, flatten_rectangles, parse_gds, rectangle_gap,
)
from check_route_cut_geometry import cut_geometry_errors  # noqa: E402


CONDUCTORS = ("locali", "metal1", "metal2", "metal3", "metal4")
VIAS = {"viali": ("locali", "metal1"), "via1": ("metal1", "metal2"),
        "via2": ("metal2", "metal3"), "via3": ("metal3", "metal4")}


def intersects(a: list[float], b: list[float]) -> bool:
    return not (a[2] < b[0] - 1e-9 or b[2] < a[0] - 1e-9
                or a[3] < b[1] - 1e-9 or b[3] < a[1] - 1e-9)


def distance(a: list[float], b: list[float]) -> float:
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def validate(geometry: dict[str, Any], plan: dict[str, Any],
             power: dict[str, Any], trim: dict[str, Any],
             source_rectangles: dict[tuple[int, int], list[tuple[float, float, float, float]]] | None = None,
             ) -> dict[str, Any]:
    errors: list[str] = []
    routes, shapes = geometry["routes"], geometry["shapes"]
    expected = {f"phase_{signal}[{channel}]" for signal in ("select0", "select1", "enable") for channel in range(4)}
    if {item["net"] for item in routes} != expected:
        errors.append("phase route net set differs from the 12-net contract")
    if len(geometry["labels"]) != 12:
        errors.append("phase route label count is not 12")
    if any(item["layer"] == "metal5" for item in shapes):
        errors.append("phase handoff uses forbidden metal5")
    if any(item["direction_reversals"] != 0 for item in routes):
        errors.append("phase handoff has a direction reversal")
    interface_y = float(plan["selector_interface_y"])
    for route in routes:
        if route.get("selector_interface_um") != [route["handoff_um"][0], interface_y]:
            errors.append(f"{route['net']} does not terminate at the selector interface")
    label_points = {(item["net"], *item["point_um"]) for item in geometry["labels"]}
    for route in routes:
        expected_label = (route["net"], *route["selector_interface_um"])
        if expected_label not in label_points:
            errors.append(f"{route['net']} lacks its selector-interface label")

    cuts = {layer: sum(item["layer"] == layer for item in shapes) for layer in VIAS}
    required = {"viali": 0, "via1": 0, "via2": 12, "via3": 4}
    if cuts != required:
        errors.append(f"phase cut counts {cuts} != {required}")
    errors.extend(cut_geometry_errors(shapes))
    for net in expected:
        jogs = [item for item in shapes if item["net"] == net and item["kind"] == "interface_jog"]
        if not jogs:
            continue
        landing = next(
            item for item in shapes
            if item["net"] == net and item["kind"] == "interface_via2_m2"
        )
        for jog in jogs:
            if (jog["bbox_um"][1] > landing["bbox_um"][1] + 1e-9
                    or jog["bbox_um"][3] < landing["bbox_um"][3] - 1e-9):
                errors.append(f"{jog['id']} leaves an M2 notch beside its via landing")

    component_counts: dict[str, int] = {}
    ownership_errors = 0
    for net in expected:
        conductors = [s for s in shapes if s["net"] == net and s["layer"] in CONDUCTORS]
        edges: dict[int, set[int]] = defaultdict(set)
        for i, first in enumerate(conductors):
            for j, second in enumerate(conductors[:i]):
                if first["layer"] == second["layer"] and intersects(first["bbox_um"], second["bbox_um"]):
                    edges[i].add(j); edges[j].add(i)
        for via in [s for s in shapes if s["net"] == net and s["layer"] in VIAS]:
            lower, upper = VIAS[via["layer"]]
            lo = [i for i, s in enumerate(conductors) if s["layer"] == lower and intersects(s["bbox_um"], via["bbox_um"])]
            hi = [i for i, s in enumerate(conductors) if s["layer"] == upper and intersects(s["bbox_um"], via["bbox_um"])]
            if not lo or not hi:
                ownership_errors += 1; errors.append(f"{via['id']} lacks two-sided ownership")
            for i in lo:
                for j in hi: edges[i].add(j); edges[j].add(i)
        unseen = set(range(len(conductors))); count = 0
        while unseen:
            count += 1; queue = deque([unseen.pop()])
            while queue:
                for neighbour in edges[queue.popleft()]:
                    if neighbour in unseen: unseen.remove(neighbour); queue.append(neighbour)
        component_counts[net] = count
        if count != 1: errors.append(f"{net} has {count} overlay components")

    spacing = {"metal1": .14, "metal2": .14, "metal3": .30, "metal4": .30}
    signal_shapes = [s for s in shapes if s["layer"] in spacing]
    intra_errors = 0
    for i, first in enumerate(signal_shapes):
        for second in signal_shapes[:i]:
            if first["net"] == second["net"] or first["layer"] != second["layer"]: continue
            if distance(first["bbox_um"], second["bbox_um"]) < spacing[first["layer"]] - 1e-9:
                intra_errors += 1; errors.append(f"{first['id']} is too close to {second['id']}")

    cross_errors = Counter()
    for stage_name, stage in (("power", power), ("trim", trim)):
        stage_shapes = [s for s in stage["shapes"] if s["layer"] in spacing]
        for signal in signal_shapes:
            for obstacle in stage_shapes:
                if signal["layer"] != obstacle["layer"]: continue
                if distance(signal["bbox_um"], obstacle["bbox_um"]) < spacing[signal["layer"]] - 1e-9:
                    cross_errors[stage_name] += 1
                    errors.append(f"{signal['id']} is too close to {stage_name} shape {obstacle['id']}")

    # Compare against the flattened source checkpoint, not just the overlays
    # generated in this routing pass.  This catches a legal-looking new wire
    # that silently crosses an existing phase-tree or analog conductor.
    source_endpoint_joins = 0
    source_interaction_errors = 0
    if source_rectangles is not None:
        layer_map = {"metal2": MET2, "metal3": MET3, "metal4": MET4}
        interface_y = float(plan["selector_interface_y"])
        boundary_by_net = {
            item["net"]: item["router_boundary_um"] for item in routes
        }
        boundary_bbox_by_net = {
            item["net"]: item["router_boundary_bbox_um"] for item in routes
        }
        for signal in signal_shapes:
            if signal["layer"] not in layer_map:
                continue
            source_layer = layer_map[signal["layer"]]
            for obstacle in source_rectangles[source_layer]:
                gap = rectangle_gap(tuple(signal["bbox_um"]), obstacle)
                if gap >= spacing[signal["layer"]] - 1e-9:
                    continue
                boundary_x, boundary_y = boundary_by_net[signal["net"]]
                boundary_bbox = boundary_bbox_by_net[signal["net"]]
                interface_x = next(
                    item["selector_interface_um"][0]
                    for item in routes if item["net"] == signal["net"]
                )
                contains_boundary = (
                    obstacle[0]-1e-9 <= boundary_x <= obstacle[2]+1e-9
                    and obstacle[1]-1e-9 <= boundary_y <= obstacle[3]+1e-9
                )
                contains_interface = (
                    obstacle[0]-1e-9 <= interface_x <= obstacle[2]+1e-9
                    and obstacle[1]-1e-9 <= interface_y <= obstacle[3]+1e-9
                )
                touches_boundary_pin = intersects(list(obstacle), boundary_bbox)
                intended_boundary = (
                    signal["kind"] == "analog_root_column"
                    and signal["layer"] == "metal2"
                    and (contains_boundary or touches_boundary_pin)
                )
                intended_interface = contains_interface and (
                    (signal["layer"] == "metal2"
                     and signal["kind"] in ("analog_root_column", "interface_jog", "interface_via2_m2"))
                    or (signal["layer"] == "metal3"
                        and signal["kind"] in ("interface_via2_m3", "interface_via3_m3"))
                    or (signal["layer"] == "metal4"
                        and signal["kind"] == "interface_m4")
                )
                if gap <= 1e-9 and (intended_boundary or intended_interface):
                    source_endpoint_joins += 1
                    continue
                source_interaction_errors += 1
                errors.append(
                    f"{signal['id']} has an unplanned {signal['layer']} interaction "
                    f"with flattened source rectangle {obstacle}"
                )

    return {
        "status": "pass" if not errors else "fail", "errors": errors,
        "route_count": len(routes), "cut_count_by_layer": cuts,
        "connected_component_count_by_net": dict(sorted(component_counts.items())),
        "via_ownership_error_count": ownership_errors,
        "cross_net_spacing_error_count": intra_errors,
        "cross_stage_spacing_error_count": dict(sorted(cross_errors.items())),
        "planned_source_endpoint_join_count": source_endpoint_joins,
        "unexpected_source_interaction_count": source_interaction_errors,
        "metal4_shape_count": sum(s["layer"] == "metal4" for s in shapes),
        "metal5_shape_count": sum(s["layer"] == "metal5" for s in shapes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, default=Path("build/v2/control_routing/phase_geometry.json"))
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_phase_route_plan.json"))
    parser.add_argument("--power", type=Path, default=Path("build/v2/control_power/control_power_geometry.json"))
    parser.add_argument("--trim", type=Path, default=Path("build/v2/control_routing/trim_geometry.json"))
    parser.add_argument("--source-gds", type=Path,
                        default=Path("build/v2/control_routing/direct/v2_control_trim_routed.gds"))
    parser.add_argument("--source-top", default="v2_control_trim_routed")
    parser.add_argument("--report", type=Path, default=Path("build/v2/control_routing/phase_route_audit.json"))
    args = parser.parse_args()
    structures, database_um = parse_gds(args.source_gds)
    source_rectangles = flatten_rectangles(structures, args.source_top, database_um)
    report = validate(json.loads(args.geometry.read_text()), json.loads(args.plan.read_text()),
                      json.loads(args.power.read_text()), json.loads(args.trim.read_text()),
                      source_rectangles)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass": raise SystemExit(1)


if __name__ == "__main__":
    main()
