#!/usr/bin/env python3
"""Reject avoidable V2 lane conflicts before detailed metal is generated."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def spans_overlap(first: list[float], second: list[float]) -> bool:
    return min(first[1], second[1]) > max(first[0], second[0])


def component_x(components: dict[str, dict[str, Any]], name: str) -> float:
    return float(components[name]["x"])


def validate(plan: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    rules = plan["rules"]
    axis = float(plan["critical_symmetry_axis_x"])
    tracks = plan["local_vertical_tracks"]
    by_track = {track["name"]: track for track in tracks}

    if len(by_track) != len(tracks):
        errors.append("local track names are not unique")
    if axis != float(template["critical_symmetry_axis_x"]):
        errors.append("routing and placement symmetry axes differ")
    for required_false in (
        "length_matching_u_bends_allowed",
        "floating_stubs_allowed",
        "orphan_vias_allowed",
    ):
        if rules.get(required_false) is not False:
            errors.append(f"{required_false} must be false")
    if int(rules.get("direction_reversals_per_branch", -1)) != 0:
        errors.append("direction_reversals_per_branch must be zero")

    clearance = float(rules["minimum_same_layer_clearance_um"])
    conflicts: list[dict[str, Any]] = []
    for index, first in enumerate(tracks):
        if not (-9.0 <= float(first["x"]) <= 9.0):
            errors.append(f"{first['net']}: track leaves the 18 um channel slice")
        if float(first["width"]) <= 0.0:
            errors.append(f"{first['net']}: track width is not positive")
        if first["y_span"][1] <= first["y_span"][0]:
            errors.append(f"{first['net']}: invalid y span")
        for second in tracks[index + 1 :]:
            if first["layer"] != second["layer"]:
                continue
            if not spans_overlap(first["y_span"], second["y_span"]):
                continue
            edge_gap = abs(float(first["x"]) - float(second["x"])) - (
                float(first["width"]) + float(second["width"])
            ) / 2.0
            if edge_gap < clearance - 1e-9:
                conflicts.append(
                    {
                        "nets": [first["net"], second["net"]],
                        "edge_gap_um": edge_gap,
                        "required_um": clearance,
                    }
                )
    if conflicts:
        errors.extend(f"same-layer lane conflict: {item}" for item in conflicts)

    mirror_reports: dict[str, Any] = {}
    for group in plan["mirror_groups"]:
        track_names = group.get("tracks", group.get("nets"))
        first, second = (by_track[name] for name in track_names)
        offsets = [abs(float(item["x"]) - axis) for item in (first, second)]
        if group.get("require_equal_axis_offset") and abs(offsets[0] - offsets[1]) > 1e-9:
            errors.append(f"{group['name']}: axis offsets differ")
        if group.get("require_equal_width") and first["width"] != second["width"]:
            errors.append(f"{group['name']}: widths differ")
        if first["layer"] != second["layer"]:
            errors.append(f"{group['name']}: layers differ")
        mirror_reports[group["name"]] = {
            "tracks": track_names,
            "nets": [first["net"], second["net"]],
            "axis_offsets_um": offsets,
            "widths_um": [first["width"], second["width"]],
            "layer": first["layer"],
        }

    components = {item["name"]: item for item in template["components"]}
    trim = plan["trim_bit_alignment"]
    positions: list[dict[str, Any]] = []
    for bit_text, current_name in trim["bit_to_current_device"].items():
        bit = int(bit_text)
        switch_names = [f"TSW{bit}_ON", f"TSW{bit}_OFF"]
        switch_x = sum(component_x(components, name) for name in switch_names) / 2.0
        inverter_name = f"TINV{bit}"
        inverter_x = component_x(components, inverter_name)
        inverter_y = float(components[inverter_name]["y"])
        switch_y = sum(float(components[name]["y"]) for name in switch_names) / 2.0
        distance = abs(switch_x - inverter_x) + abs(switch_y - inverter_y)
        if distance > float(trim["maximum_switch_to_inverter_manhattan_um"]) + 1e-9:
            errors.append(f"trim bit {bit}: switch-to-inverter span {distance:.3f} um exceeds budget")
        positions.append(
            {
                "bit": bit,
                "current_x": component_x(components, current_name),
                "switch_x": switch_x,
                "inverter_x": inverter_x,
                "switch_to_inverter_manhattan_um": distance,
            }
        )
    for key in ("current_x", "switch_x", "inverter_x"):
        order = [item["bit"] for item in sorted(positions, key=lambda item: item[key])]
        if order != trim["required_left_to_right_bit_order"]:
            errors.append(f"trim {key} order {order} does not match crossing-free order")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "same_layer_conflicts": conflicts,
        "track_count": len(tracks),
        "mirror_groups": mirror_reports,
        "trim_bit_positions": sorted(positions, key=lambda item: item["bit"]),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("template", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = validate(
        json.loads(args.plan.read_text(encoding="utf-8")),
        json.loads(args.template.read_text(encoding="utf-8")),
    )
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output, encoding="utf-8")
    print(output, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
