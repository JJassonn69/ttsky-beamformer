#!/usr/bin/env python3
"""Validate the V2 support/control floorplan before generating more GDS."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


Rect = tuple[float, float, float, float]


def bbox_inside(inner: Rect, outer: Rect) -> bool:
    return (
        outer[0] <= inner[0] < inner[2] <= outer[2]
        and outer[1] <= inner[1] < inner[3] <= outer[3]
    )


def bboxes_overlap(first: Rect, second: Rect) -> bool:
    return not (
        first[2] <= second[0]
        or second[2] <= first[0]
        or first[3] <= second[1]
        or second[3] <= first[1]
    )


def rectangle_gap(first: Rect, second: Rect) -> float:
    dx = max(0.0, first[0] - second[2], second[0] - first[2])
    dy = max(0.0, first[1] - second[3], second[1] - first[3])
    return math.hypot(dx, dy)


def support_bbox(component: dict[str, Any], dimensions: dict[str, Any]) -> Rect:
    pcell = dimensions["pcells"][component["pcell"]]
    x0, y0, x1, y1 = map(float, pcell["bbox_um"])
    cx, cy = map(float, component["center"])
    if component["orientation"] == "R0":
        return cx + x0, cy + y0, cx + x1, cy + y1
    if component["orientation"] == "MY":
        return cx - x1, cy + y0, cx - x0, cy + y1
    raise ValueError(f"{component['name']}: unsupported orientation")


def primitive_counts(stats: dict[str, Any]) -> dict[str, int]:
    modules = stats["modules"]
    storage = sorted(
        int(module["num_cells"])
        for name, module in modules.items()
        if "v2_config_storage" in name
    )
    core_modules = [
        module
        for name, module in modules.items()
        if "v2_config_storage" not in name
    ]
    sequential = 0
    combinational = 0
    for module in core_modules:
        for kind, count in module["num_cells_by_type"].items():
            if not kind.startswith("$_"):
                continue
            if kind.startswith("$_DFF"):
                sequential += int(count)
            else:
                combinational += int(count)
    return {
        "phase_storage_primitives": storage[0] if storage else 0,
        "trim_storage_primitives": storage[1] if len(storage) > 1 else 0,
        "global_sequential_primitives": sequential,
        "global_combinational_primitives": combinational,
        "total_primitives": sum(storage) + sequential + combinational,
    }


def validate(
    plan: dict[str, Any],
    floorplan: dict[str, Any],
    dimensions: dict[str, Any],
    stats: dict[str, Any],
    repository_root: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    rules = plan["rules"]
    die = tuple(map(float, rules["die_bbox"]))

    checkpoint = plan["base_checkpoint"]
    gds = repository_root / checkpoint["gds"]
    actual_hash = hashlib.sha256(gds.read_bytes()).hexdigest() if gds.exists() else None
    if actual_hash != checkpoint["sha256"]:
        errors.append(
            f"base GDS hash {actual_hash} does not match {checkpoint['sha256']}"
        )

    forbidden_true = (
        "floating_stubs_allowed",
        "orphan_vias_allowed",
        "length_matching_u_bends_allowed",
        "metal5_project_signals_allowed",
    )
    for name in forbidden_true:
        if rules[name]:
            errors.append(f"forbidden integration behavior enabled: {name}")
    if int(rules["maximum_route_direction_reversals"]) != 0:
        errors.append("route direction reversals must remain zero")

    regions: dict[str, Rect] = {}
    for region in plan["placement_regions"]:
        bbox = tuple(map(float, region["bbox"]))
        regions[region["name"]] = bbox
        if not bbox_inside(bbox, die):
            errors.append(f"placement region {region['name']} leaves the die")
    for index, first in enumerate(plan["placement_regions"]):
        for second in plan["placement_regions"][index + 1 :]:
            if bboxes_overlap(regions[first["name"]], regions[second["name"]]):
                errors.append(
                    f"placement regions {first['name']} and {second['name']} overlap"
                )

    bounds = plan["standard_cell_area_upper_bounds"]
    seq_area = math.prod(map(float, bounds["sequential_cell"]))
    comb_area = math.prod(map(float, bounds["combinational_cell"]))
    utilization: dict[str, float] = {}
    for region in plan["placement_regions"]:
        area = (region["bbox"][2] - region["bbox"][0]) * (
            region["bbox"][3] - region["bbox"][1]
        )
        if "mapped_cell_width_um" in region:
            used = float(region["mapped_cell_width_um"]) * float(rules["row_height"])
            available_rows = math.floor(
                (float(region["bbox"][3]) - float(region["bbox"][1]))
                / float(rules["row_height"]) + 1e-9
            )
            if int(region["row_count"]) > available_rows:
                errors.append(
                    f"{region['name']} requests {region['row_count']} rows but only "
                    f"{available_rows} fit"
                )
        elif "primitive_count" in region:
            used = int(region["primitive_count"]) * seq_area
        elif "sequential_primitive_count" in region:
            used = int(region["sequential_primitive_count"]) * seq_area
            used += int(region["combinational_primitive_count"]) * comb_area
        else:
            continue
        value = used / area
        utilization[region["name"]] = value
        if value > float(rules["maximum_standard_cell_utilization"]) + 1e-12:
            errors.append(
                f"{region['name']} conservative utilization {value:.3f} exceeds limit"
            )

    actual_counts = primitive_counts(stats)
    expected_counts = plan["synthesis_checkpoint"]
    for name, actual in actual_counts.items():
        if actual != int(expected_counts[name]):
            errors.append(
                f"synthesis {name} changed from {expected_counts[name]} to {actual}"
            )

    mapping_checkpoint = plan["physical_mapping_checkpoint"]
    mapping_path = repository_root / mapping_checkpoint["netlist"]
    if not mapping_path.exists():
        errors.append(f"physical mapping checkpoint is missing: {mapping_path}")
    else:
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        if int(mapping["counts"]["total_cells"]) != int(
            mapping_checkpoint["total_standard_cells"]
        ):
            errors.append("physical mapped standard-cell count changed")
        if int(mapping["counts"]["signal_nets"]) != int(
            mapping_checkpoint["signal_nets"]
        ):
            errors.append("physical mapped signal-net count changed")
        if mapping["counts"]["by_region"] != mapping_checkpoint["cells_by_region"]:
            errors.append("physical mapped region counts changed")
        width_by_region: dict[str, float] = {}
        for cell in mapping["cells"]:
            width_by_region[cell["region"]] = width_by_region.get(cell["region"], 0.0) + float(
                cell["size_um"][0]
            )
        for region in plan["placement_regions"]:
            if "mapped_cell_width_um" not in region:
                continue
            actual_width = width_by_region.get(region["name"], 0.0)
            if not math.isclose(
                actual_width, float(region["mapped_cell_width_um"]), abs_tol=1e-6
            ):
                errors.append(
                    f"{region['name']} mapped width changed from "
                    f"{region['mapped_cell_width_um']} to {actual_width:.6f} um"
                )

    support_regions = {
        name: tuple(map(float, bbox))
        for name, bbox in plan["analog_support_regions"].items()
    }
    support: dict[str, Rect] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for component in plan["analog_support_components"]:
        by_name[component["name"]] = component
        try:
            bbox = support_bbox(component, dimensions)
        except (KeyError, ValueError) as error:
            errors.append(str(error))
            continue
        support[component["name"]] = bbox
        if not bbox_inside(bbox, die):
            errors.append(f"{component['name']} leaves the die")
        region = support_regions[component["region"]]
        if not bbox_inside(bbox, region):
            errors.append(f"{component['name']} leaves {component['region']}")

    support_gaps: dict[str, float] = {}
    minimum_gap = float(rules["minimum_component_gap"])
    names = list(support)
    for index, first_name in enumerate(names):
        for second_name in names[index + 1 :]:
            first = support[first_name]
            second = support[second_name]
            gap = rectangle_gap(first, second)
            support_gaps[f"{first_name}:{second_name}"] = gap
            if bboxes_overlap(first, second) or gap < minimum_gap - 1e-9:
                errors.append(
                    f"support components {first_name}/{second_name} gap {gap:.3f} um"
                )

    cap = support.get("CVCM")
    for resistor in ("RVCM_BOTTOM", "RVCM_TOP"):
        if cap is not None and resistor in support:
            gap = rectangle_gap(cap, support[resistor])
            if gap < float(rules["minimum_capm_to_unrelated_met3"]) - 1e-9:
                errors.append(f"CVCM/{resistor} conservative gap {gap:.3f} um")

    pair = [by_name.get("BIAS_DIODE_A"), by_name.get("BIAS_DIODE_B")]
    if all(pair):
        first, second = pair
        if first["pcell"] != second["pcell"] or first["orientation"] != second["orientation"]:
            errors.append("bias-diode halves do not use identical PCell/orientation")
        if not math.isclose(first["center"][1], second["center"][1], abs_tol=1e-9):
            errors.append("bias-diode halves do not share one placement row")
        axis = (float(first["center"][0]) + float(second["center"][0])) / 2.0
        if not math.isclose(axis, 172.5, abs_tol=1e-9):
            errors.append(f"bias-diode pair axis moved to {axis}")

    channels = {int(item["index"]): item for item in floorplan["channels"]}
    vcm_x = [float(item["center_x"]) + 8.34 for item in channels.values()]
    vbias_x = [float(item["center_x"]) + 6.30 for item in channels.values()]
    shared_routes = {route["net"]: route for route in plan["shared_analog_routes"]}
    for net, anchors in (("vcm", vcm_x), ("vbias", vbias_x)):
        route = shared_routes[net]
        x0, x1 = sorted((float(route["from"][0]), float(route["to"][0])))
        if min(anchors) < x0 - 1e-9 or max(anchors) > x1 + 1e-9:
            errors.append(f"{net} bus does not cover all four channel anchors")
        if int(route["direction_reversals"]) != 0:
            errors.append(f"{net} bus permits a route reversal")

    trim = plan["trim_control_bus"]
    count = int(trim["track_count"])
    pitch = float(trim["track_pitch"])
    width = float(trim["width"])
    first_y = float(trim["first_track_y"])
    expected_last = first_y + (count - 1) * pitch
    if not math.isclose(expected_last, float(trim["last_track_y"]), abs_tol=1e-9):
        errors.append("trim bus last track is inconsistent with count and pitch")
    if pitch - width < float(rules["minimum_met2_spacing"]) - 1e-9:
        errors.append("trim bus M2 spacing is below the frozen minimum")
    if trim["transition_layers"] != ["metal2", "via2", "metal3"]:
        errors.append("trim bus transition is not the approved M2-via2-M3 stack")
    if trim["forbidden_transition_layer"] != "metal4":
        errors.append("trim bus no longer explicitly forbids an M4 transition")
    trim_tracks: list[dict[str, float | int]] = []
    index = 0
    for channel in trim["channel_order"]:
        for bit in trim["bit_order_within_channel"]:
            sink_x = float(channels[int(channel)]["center_x"]) + float(
                trim["sink_local_x"][str(bit)]
            )
            trim_tracks.append(
                {"channel": int(channel), "bit": int(bit), "x": sink_x,
                 "y": first_y + index * pitch}
            )
            index += 1
    if len(trim_tracks) != 16 or len({item["y"] for item in trim_tracks}) != 16:
        errors.append("trim bus does not resolve to sixteen unique tracks")

    phase = plan["phase_control_handoffs"]
    phase_routes = {
        (int(item["channel"]), item["signal"]): item for item in phase["routes"]
    }
    offsets = {"phase_select0": -3.40, "phase_select1": 5.24, "phase_enable": 7.00}
    for channel, record in channels.items():
        for signal, offset in offsets.items():
            route = phase_routes.get((channel, signal))
            expected_x = float(record["center_x"]) + offset
            if route is None or not math.isclose(float(route["x"]), expected_x, abs_tol=1e-9):
                errors.append(f"CH{channel} {signal} misses its measured selector handoff")
    roots = plan["quadrature_root_handoffs"]
    mean_x = sum(float(item["center_x"]) for item in channels.values()) / 4.0
    expected_roots = [mean_x - 2.20, mean_x + 0.1975, mean_x + 1.6425, mean_x + 4.04]
    if any(
        not math.isclose(float(root["point"][0]), expected, abs_tol=1e-9)
        for root, expected in zip(roots, expected_roots)
    ):
        errors.append("quadrature roots no longer align to the balanced H-tree")

    service = plan["control_service_bundle"]
    xs = list(map(float, service["x_tracks"]))
    if len(xs) != len(service["signals"]):
        errors.append("control service signal/track counts differ")
    if any(
        not math.isclose(second - first, float(service["track_pitch"]), abs_tol=1e-9)
        for first, second in zip(xs, xs[1:])
    ):
        errors.append("control service tracks do not follow their pitch")
    if int(service["maximum_direction_reversals"]) != 0:
        errors.append("control service corridor permits a direction reversal")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "base_gds_sha256": actual_hash,
        "synthesis_counts": actual_counts,
        "conservative_region_utilization": utilization,
        "support_bboxes_um": {name: list(bbox) for name, bbox in support.items()},
        "support_gaps_um": support_gaps,
        "trim_tracks": trim_tracks,
        "phase_handoff_count": len(phase_routes),
        "quadrature_root_x_um": [root["point"][0] for root in roots],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("floorplan", type=Path)
    parser.add_argument("dimensions", type=Path)
    parser.add_argument("stats", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = validate(
        json.loads(args.plan.read_text(encoding="utf-8")),
        json.loads(args.floorplan.read_text(encoding="utf-8")),
        json.loads(args.dimensions.read_text(encoding="utf-8")),
        json.loads(args.stats.read_text(encoding="utf-8")),
        args.repository_root.resolve(),
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
