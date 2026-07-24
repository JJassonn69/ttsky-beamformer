#!/usr/bin/env python3
"""Audit trim-route ownership, connectivity, spacing, and monotonicity."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from check_route_cut_geometry import cut_geometry_errors


CONDUCTORS = ("locali", "metal1", "metal2", "metal3", "metal4")
VIA_LAYERS = {
    "viali": ("locali", "metal1"),
    "via1": ("metal1", "metal2"),
    "via2": ("metal2", "metal3"),
    "via3": ("metal3", "metal4"),
}


def intersects(a: list[float], b: list[float]) -> bool:
    return not (
        float(a[2]) < float(b[0]) - 1e-9
        or float(b[2]) < float(a[0]) - 1e-9
        or float(a[3]) < float(b[1]) - 1e-9
        or float(b[3]) < float(a[1]) - 1e-9
    )


def distance(a: list[float], b: list[float]) -> float:
    dx = max(float(a[0]) - float(b[2]), float(b[0]) - float(a[2]), 0.0)
    dy = max(float(a[1]) - float(b[3]), float(b[1]) - float(a[3]), 0.0)
    return math.hypot(dx, dy)


def validate(
    geometry: dict[str, Any], plan: dict[str, Any],
    power_geometry: dict[str, Any] | None = None,
    allocation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    shapes = geometry["shapes"]
    routes = geometry["routes"]
    expected_nets = {f"active_trim_codes[{index}]" for index in range(16)}
    actual_nets = {item["net"] for item in routes}
    if actual_nets != expected_nets:
        errors.append(f"trim route nets differ: {sorted(actual_nets ^ expected_nets)}")
    if len(geometry["labels"]) != 16:
        errors.append(f"trim route label count is {len(geometry['labels'])}, expected 16")
    if any(item["layer"] in ("metal4", "metal5") for item in shapes):
        errors.append("trim handoff uses forbidden upper metal")
    if any(int(item["direction_reversals"]) != 0 for item in routes):
        errors.append("trim handoff contains a direction reversal")
    expected_cut_counts = {"viali": 0, "via1": 0, "via2": 32, "via3": 0}
    actual_cut_counts = {
        layer: sum(item["layer"] == layer for item in shapes)
        for layer in expected_cut_counts
    }
    if actual_cut_counts != expected_cut_counts:
        errors.append(
            f"trim cut counts {actual_cut_counts} != {expected_cut_counts}"
        )
    errors.extend(cut_geometry_errors(shapes))

    component_counts: dict[str, int] = {}
    via_ownership_errors = 0
    for net in expected_nets:
        conductors = [
            item for item in shapes if item["net"] == net and item["layer"] in CONDUCTORS
        ]
        edges: dict[int, set[int]] = defaultdict(set)
        for first in range(len(conductors)):
            for second in range(first + 1, len(conductors)):
                if (conductors[first]["layer"] == conductors[second]["layer"]
                        and intersects(conductors[first]["bbox_um"], conductors[second]["bbox_um"])):
                    edges[first].add(second)
                    edges[second].add(first)
        for via in [item for item in shapes if item["net"] == net and item["layer"] in VIA_LAYERS]:
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
                via_ownership_errors += 1
                errors.append(f"{via['id']} has incomplete {via['layer']} ownership")
            for first in lower_nodes:
                for second in upper_nodes:
                    edges[first].add(second)
                    edges[second].add(first)
        unseen = set(range(len(conductors)))
        components = 0
        while unseen:
            components += 1
            queue = deque([unseen.pop()])
            while queue:
                node = queue.popleft()
                for neighbour in edges[node]:
                    if neighbour in unseen:
                        unseen.remove(neighbour)
                        queue.append(neighbour)
        component_counts[net] = components
        if components != 1:
            errors.append(f"{net} has {components} disconnected overlay components")

    spacing_by_layer = {
        "metal1": 0.14,
        "metal2": float(plan["geometry_rules"]["minimum_metal2_clearance"]),
        "metal3": float(plan["geometry_rules"]["minimum_metal3_clearance"]),
    }
    spacing_errors = 0
    conductors = [item for item in shapes if item["layer"] in spacing_by_layer]
    for index, first in enumerate(conductors):
        for second in conductors[index + 1:]:
            if first["net"] == second["net"] or first["layer"] != second["layer"]:
                continue
            clearance = distance(first["bbox_um"], second["bbox_um"])
            if clearance < spacing_by_layer[first["layer"]] - 1e-9:
                spacing_errors += 1
                errors.append(
                    f"{first['id']} and {second['id']} have {clearance:.3f} um "
                    f"{first['layer']} clearance"
                )

    signal_power_spacing_errors = 0
    if power_geometry is not None:
        power_shapes = [
            item for item in power_geometry["shapes"]
            if item["layer"] in spacing_by_layer
        ]
        for signal in conductors:
            for power in power_shapes:
                if signal["layer"] != power["layer"]:
                    continue
                clearance = distance(signal["bbox_um"], power["bbox_um"])
                if clearance < spacing_by_layer[signal["layer"]] - 1e-9:
                    signal_power_spacing_errors += 1
                    errors.append(
                        f"{signal['id']} intersects/approaches {power['id']} "
                        f"({power['net']}) with only {clearance:.3f} um "
                        f"{signal['layer']} clearance"
                    )

    # Service routing is deliberately added after the trim handoffs.  Reserve
    # its natural M1-to-M2 landing at every trim-bank pin now, so a later
    # router never has to slide sideways on unmodelled standard-cell M1.
    service_access_keepout_errors = 0
    reserved_service_pin_count = 0
    if allocation is not None:
        half = float(plan["geometry_rules"]["reserved_service_m2_landing_half_width"])
        clearance = float(plan["geometry_rules"]["minimum_metal2_clearance"])
        service_pins: list[tuple[str, str, str, list[float]]] = []
        for record in allocation["nets"]:
            if record["class"] != "service_tree":
                continue
            for endpoint in record["endpoints"]:
                if (endpoint.get("kind") != "standard_cell_pin"
                        or endpoint.get("region") != "trim_configuration_bank"):
                    continue
                x, y = map(float, endpoint["point_um"])
                service_pins.append((
                    record["net"], endpoint["instance"], endpoint["pin"],
                    [x-half, y-half, x+half, y+half],
                ))
        reserved_service_pin_count = len(service_pins)
        for signal in [item for item in shapes if item["layer"] == "metal2"]:
            for net, instance, pin, keepout in service_pins:
                gap = distance(signal["bbox_um"], keepout)
                if gap < clearance - 1e-9:
                    service_access_keepout_errors += 1
                    errors.append(
                        f"{signal['id']} ({signal['net']}) blocks reserved direct "
                        f"M2 service access {net}:{instance}|{pin} with only "
                        f"{gap:.3f} um clearance"
                    )

    columns = sorted(float(item["m3_column_x_um"]) for item in routes)
    pitch = min(second - first for first, second in zip(columns, columns[1:]))
    if pitch < 0.70 - 1e-9:
        errors.append(f"trim M3 columns have only {pitch:.3f} um pitch")
    bus_rows = sorted(float(item["anchor_um"][1]) for item in routes)
    bus_pitch = min(second - first for first, second in zip(bus_rows, bus_rows[1:]))
    if bus_pitch < 0.64 - 1e-9:
        errors.append(f"trim M2 bus rows have only {bus_pitch:.3f} um pitch")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "route_count": len(routes),
        "connected_component_count_by_net": dict(sorted(component_counts.items())),
        "via_ownership_error_count": via_ownership_errors,
        "cut_count_by_layer": actual_cut_counts,
        "cross_net_spacing_error_count": spacing_errors,
        "signal_power_spacing_error_count": signal_power_spacing_errors,
        "reserved_service_pin_count": reserved_service_pin_count,
        "service_access_keepout_error_count": service_access_keepout_errors,
        "minimum_m3_column_pitch_um": pitch,
        "minimum_m2_bus_pitch_um": bus_pitch,
        "metal4_shape_count": sum(item["layer"] == "metal4" for item in shapes),
        "metal5_shape_count": sum(item["layer"] == "metal5" for item in shapes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path,
                        default=Path("build/v2/control_routing/trim_geometry.json"))
    parser.add_argument("--plan", type=Path,
                        default=Path("v2/layout/control_signal_plan.json"))
    parser.add_argument("--report", type=Path,
                        default=Path("build/v2/control_routing/trim_audit.json"))
    parser.add_argument("--power-geometry", type=Path,
                        default=Path("build/v2/control_power/control_power_geometry.json"))
    parser.add_argument("--allocation", type=Path,
                        default=Path("build/v2/control_routing/control_route_allocation.json"))
    args = parser.parse_args()
    report = validate(
        json.loads(args.geometry.read_text()), json.loads(args.plan.read_text()),
        json.loads(args.power_geometry.read_text()),
        json.loads(args.allocation.read_text()),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
