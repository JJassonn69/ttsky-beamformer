#!/usr/bin/env python3
"""Allocate every V2 control net to a production routing topology.

This stage deliberately emits no geometry.  It proves that the frozen
placement has enough track capacity and assigns every mapped net to a named
local, regional, service, or handoff topology before detailed routing starts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


POWER_PINS = {"VPWR", "VPB", "VGND", "VNB"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def anchor_catalog(
    floorplan: dict[str, Any], integration: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    pins = floorplan["digital_reference_pins"]
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add(net: str, point: list[float], kind: str, layer: str = "metal4") -> None:
        result[net].append({
            "kind": kind,
            "point_um": list(map(float, point)),
            "layer": layer,
        })

    external = {
        "clk": "clk",
        "rst_n": "rst_n",
        "ena": "ena",
        "beam_select[0]": "ui_in[0]",
        "beam_select[1]": "ui_in[1]",
        "manual_mode": "ui_in[3]",
        "channel_enable[0]": "ui_in[4]",
        "channel_enable[1]": "ui_in[5]",
        "channel_enable[2]": "ui_in[6]",
        "channel_enable[3]": "ui_in[7]",
        "cfg_clk": "uio_in[0]",
        "cfg_data": "uio_in[1]",
        "cfg_latch": "uio_in[2]",
    }
    for net, pin in external.items():
        add(net, pins[pin], "external_top_pin")

    transition_y = float(integration["phase_control_handoffs"]["transition_y"])
    for item in integration["phase_control_handoffs"]["routes"]:
        add(
            f"{item['signal']}[{item['channel']}]",
            [float(item["x"]), transition_y],
            "phase_selector_handoff",
            item.get("interface_layer", item["layer"]),
        )
    for item in integration["quadrature_root_handoffs"]:
        add(
            item["control_net"], item["point"], "quadrature_root_handoff", item["layer"]
        )

    trim = integration["trim_control_bus"]
    channel_centers = {
        int(item["index"]): float(item["center_x"])
        for item in floorplan["channels"]
    }
    trim_slots = [
        (int(channel), int(bit))
        for channel in trim["channel_order"]
        for bit in trim["bit_order_within_channel"]
    ]
    expected_slots = [(index // 4, index % 4) for index in range(16)]
    if trim_slots != expected_slots:
        raise ValueError(
            "trim_control_bus must map active_trim_codes[4*channel+bit] "
            "to the same CH/channel trim bit; got " + repr(trim_slots)
        )
    for index, (channel, bit) in enumerate(trim_slots):
        add(
            f"active_trim_codes[{index}]",
            [
                float(trim["source_region_x"]),
                float(trim["first_track_y"]) + index * float(trim["track_pitch"]),
            ],
            "trim_bus_handoff",
            trim["layer"],
        )
        result[f"active_trim_codes[{index}]"][-1].update({
            "channel": channel,
            "bit": bit,
            "sink_point_um": [
                channel_centers[channel] + float(trim["sink_local_x"][str(bit)]),
                float(trim["sink_transition_y"]),
            ],
        })
    return dict(result)


def interval_colors(
    intervals: list[dict[str, Any]], clearance: float
) -> tuple[list[dict[str, Any]], int]:
    ends: list[float] = []
    assigned: list[dict[str, Any]] = []
    for item in sorted(intervals, key=lambda value: (
        float(value["x_span_um"][0]), float(value["x_span_um"][1]), value["net"]
    )):
        start, stop = map(float, item["x_span_um"])
        color = next(
            (index for index, end in enumerate(ends) if end + clearance <= start),
            len(ends),
        )
        if color == len(ends):
            ends.append(stop)
        else:
            ends[color] = stop
        assigned.append({**item, "track_index": color})
    return assigned, len(ends)


def plan_routes(
    plan: dict[str, Any],
    mapping: dict[str, Any],
    placement: dict[str, Any],
    floorplan: dict[str, Any],
    integration: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    source = project_root / plan["source_checkpoint"]["gds"]
    actual_hash = sha256(source)
    if actual_hash != plan["source_checkpoint"]["sha256"]:
        errors.append(
            f"powered source hash {actual_hash} != {plan['source_checkpoint']['sha256']}"
        )

    placed = {item["instance"]: item for item in placement["placements"]}
    mapped = {item["instance"]: item for item in mapping["cells"]}
    anchors = anchor_catalog(floorplan, integration)
    service = set(plan["service_bundle"]["signals"])
    direct_boundary = set(plan["direct_boundary_signals"])
    external_nets = {
        net for net, items in anchors.items()
        if any(item["kind"] == "external_top_pin" for item in items)
    }
    phase_nets = {
        net for net, items in anchors.items()
        if any(item["kind"] == "phase_selector_handoff" for item in items)
    }
    quadrature_nets = set(plan["handoff_classes"]["quadrature_roots"]["nets"])
    trim_nets = {
        net for net, items in anchors.items()
        if any(item["kind"] == "trim_bus_handoff" for item in items)
    }

    endpoint_by_net: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cell in mapping["cells"]:
        instance = cell["instance"]
        if instance not in placed:
            errors.append(f"mapped cell {instance} has no frozen placement")
            continue
        item = placed[instance]
        for pin, net in cell["pins"].items():
            if pin in POWER_PINS:
                continue
            access = item["pin_access"].get(pin)
            if access is None:
                errors.append(f"{instance}.{pin} has no measured access point")
                continue
            endpoint_by_net[net].append({
                "kind": "standard_cell_pin",
                "instance": instance,
                "pin": pin,
                "cell": cell["cell"],
                "direction": mapping["library"][cell["short_cell"]]["pins"][pin]["direction"],
                "point_um": list(map(float, access["point_um"])),
                "layer": access["layer"],
                "region": item["region"],
                "row": int(item["row"]),
            })
    for net, items in anchors.items():
        endpoint_by_net[net].extend(items)

    direct_limit = int(plan["local_topology_selection"]["direct_max_endpoint_count"])
    direct_span = float(plan["local_topology_selection"]["direct_max_manhattan_span"])
    adjacent_span = float(plan["local_topology_selection"]["adjacent_row_max_vertical_span"])
    route_records: list[dict[str, Any]] = []
    classifications: Counter[str] = Counter()
    unplanned_cross_region: list[str] = []

    for net in sorted(mapping["nets"]):
        endpoints = endpoint_by_net[net]
        cell_endpoints = [item for item in endpoints if item["kind"] == "standard_cell_pin"]
        regions = sorted({item["region"] for item in cell_endpoints})
        xs = [float(item["point_um"][0]) for item in endpoints]
        ys = [float(item["point_um"][1]) for item in endpoints]
        x_span = max(xs) - min(xs)
        y_span = max(ys) - min(ys)
        hpwl = x_span + y_span

        if net in service:
            route_class, topology = "service_tree", "shielded_m3_spine_with_m4_region_branches"
        elif net in phase_nets:
            route_class = "phase_handoff"
            topology = (
                "direct_m2_to_m3_drop"
                if x_span <= float(plan["geometry_rules"]["maximum_pin_escape_length"])
                else "short_m4_branch_to_m3_drop"
            )
        elif net in quadrature_nets:
            route_class, topology = "quadrature_handoff", "ordered_m4_trunk_with_m3_root_drop"
        elif net in trim_nets:
            route_class, topology = "trim_handoff", "unique_m3_q_column_to_monotonic_m2_row"
        elif net == plan["handoff_classes"]["blanking"]["net"]:
            route_class, topology = "observation_only", "no_physical_route"
        elif net in external_nets:
            route_class, topology = "external_input", "top_pin_m3_drop_with_local_m4_branch"
        elif net in direct_boundary:
            route_class, topology = "direct_boundary", "one_boundary_m3_column_with_local_m4_branches"
        elif len(regions) > 1:
            route_class, topology = "unplanned_cross_region", "none"
            unplanned_cross_region.append(net)
        elif len(endpoints) <= direct_limit and hpwl <= direct_span:
            route_class = "local_direct"
            topology = (
                "same_row_m2"
                if y_span < 0.70
                else "adjacent_row_m2_m3" if y_span <= adjacent_span
                else "compact_m2_m3"
            )
        else:
            route_class, topology = "regional_trunk", "interval_colored_m4_with_m3_leaves"
        classifications[route_class] += 1
        route_records.append({
            "net": net,
            "class": route_class,
            "topology": topology,
            "mapped_endpoint_count": len(mapping["nets"][net]),
            "anchor_count": len(endpoints) - len(cell_endpoints),
            "regions": regions,
            "bbox_um": [min(xs), min(ys), max(xs), max(ys)],
            "hpwl_um": hpwl,
            "endpoints": endpoints,
        })

    if unplanned_cross_region:
        errors.append(f"cross-region nets lack named topology: {unplanned_cross_region}")
    singletons_without_anchor = [
        item["net"] for item in route_records
        if item["mapped_endpoint_count"] == 1 and item["anchor_count"] == 0
        and item["class"] != "observation_only"
    ]
    if singletons_without_anchor:
        errors.append(f"one-pin mapped nets lack physical anchors: {singletons_without_anchor}")

    capacity: dict[str, Any] = {}
    pitch = float(plan["geometry_rules"]["preferred_track_pitch"])
    clearance = float(plan["geometry_rules"]["minimum_metal4_clearance"])
    by_net = {item["net"]: item for item in route_records}
    service_columns = dict(zip(
        plan["service_bundle"]["signals"], plan["service_bundle"]["x_tracks"]
    ))
    boundary_columns = dict(zip(
        plan["direct_boundary_signals"], plan["direct_boundary_bundle"]["x_tracks"]
    ))
    for region, window in plan["routing_windows"].items():
        intervals: list[dict[str, Any]] = []
        for net, record in by_net.items():
            local = [
                endpoint for endpoint in record["endpoints"]
                if endpoint.get("region") == region
            ]
            if not local:
                continue
            local_x = [float(endpoint["point_um"][0]) for endpoint in local]
            if record["class"] == "service_tree":
                local_x.append(float(service_columns[net]))
                needs_trunk = True
            elif record["class"] == "direct_boundary":
                local_x.append(float(boundary_columns[net]))
                # A region with one sink beside its dedicated M3 boundary
                # column needs only one short M2 landing.  Reserving an M4
                # trunk here would add two vias and a dead regional segment.
                needs_trunk = not (
                    len(local) == 1
                    and max(local_x) - min(local_x)
                    <= float(plan["geometry_rules"]["maximum_pin_escape_length"])
                )
            elif record["class"] in {
                "phase_handoff", "quadrature_handoff", "blanking_handoff",
                "external_input",
            }:
                local_x.extend(
                    float(endpoint["point_um"][0]) for endpoint in record["endpoints"]
                    if endpoint["kind"] != "standard_cell_pin"
                )
                needs_trunk = record["topology"] != "direct_m2_to_m3_drop"
            elif record["class"] == "regional_trunk":
                needs_trunk = True
            else:
                needs_trunk = False
            if needs_trunk:
                intervals.append({
                    "net": net,
                    "x_span_um": [min(local_x), max(local_x)],
                    "local_endpoint_count": len(local),
                })
        assigned, required = interval_colors(intervals, clearance)
        available = int(window["available_track_count"])
        if required > available:
            errors.append(f"{region} needs {required} M4 tracks but has {available}")
        start_y = float(window["horizontal_m4_tracks"][0])
        for item in assigned:
            item["track_y_um"] = start_y + int(item["track_index"]) * pitch
        capacity[region] = {
            "regional_m4_interval_count": len(intervals),
            "required_track_count": required,
            "available_track_count": available,
            "margin_track_count": available - required,
            "assignments": assigned,
        }

    pin_density: dict[str, Any] = {}
    for region in placement["regions"]:
        row_counts: Counter[int] = Counter()
        dense_pairs = 0
        row_points: dict[int, list[float]] = defaultdict(list)
        for endpoints in endpoint_by_net.values():
            for endpoint in endpoints:
                if endpoint.get("region") != region:
                    continue
                row = int(endpoint["row"])
                row_counts[row] += 1
                row_points[row].append(float(endpoint["point_um"][0]))
        for points in row_points.values():
            ordered = sorted(points)
            dense_pairs += sum(
                second - first < pitch - 1e-9
                for first, second in zip(ordered, ordered[1:])
            )
        pin_density[region] = {
            "endpoint_count": sum(row_counts.values()),
            "maximum_endpoints_in_one_row": max(row_counts.values(), default=0),
            "adjacent_pin_pairs_below_m3_pitch": dense_pairs,
            "required_action": "stagger colliding pin escapes on M2 before assigning private M3 leaves",
        }

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "source_checkpoint_sha256": actual_hash,
        "mapped_signal_net_count": len(mapping["nets"]),
        "planned_signal_net_count": len(route_records),
        "mapped_pin_endpoint_count": sum(len(items) for items in mapping["nets"].values()),
        "physical_anchor_count": sum(len(items) for items in anchors.values()),
        "class_counts": dict(sorted(classifications.items())),
        "track_capacity": capacity,
        "pin_escape_density": pin_density,
        "nets": route_records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_signal_plan.json"))
    parser.add_argument("--mapping", type=Path,
                        default=Path("build/v2/control_mapping/physical_netlist.json"))
    parser.add_argument("--placement", type=Path,
                        default=Path("build/v2/control_placement/control_placement.json"))
    parser.add_argument("--floorplan", type=Path, default=Path("v2/layout/floorplan.json"))
    parser.add_argument("--integration", type=Path,
                        default=Path("v2/layout/integration_plan.json"))
    parser.add_argument("--output", type=Path,
                        default=Path("build/v2/control_routing/control_route_allocation.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = plan_routes(
        json.loads(args.plan.read_text()),
        json.loads(args.mapping.read_text()),
        json.loads(args.placement.read_text()),
        json.loads(args.floorplan.read_text()),
        json.loads(args.integration.read_text()),
        root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    summary = {key: result[key] for key in (
        "status", "errors", "mapped_signal_net_count", "mapped_pin_endpoint_count",
        "physical_anchor_count", "class_counts", "track_capacity", "pin_escape_density",
    )}
    for item in summary["track_capacity"].values():
        item.pop("assignments", None)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
