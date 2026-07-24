#!/usr/bin/env python3
"""Validate the measured repeated V2 channel placement template."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def centroid(components: list[dict[str, Any]]) -> tuple[float, float]:
    return (
        sum(float(component["x"]) for component in components) / len(components),
        sum(float(component["y"]) for component in components) / len(components),
    )


def validate_placement_plan(
    floorplan: dict[str, Any],
    dimensions: dict[str, Any],
    template: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    cells = dimensions["pcells"]
    components = template["components"]
    allowed_orientations = set(
        floorplan["orientation_policy"]["allowed_channel_orientations_for_study"]
    )

    names = [component["name"] for component in components]
    if len(names) != len(set(names)):
        errors.append("channel template contains duplicate component names")
    if any("r2r" in component["pcell"].lower() for component in components):
        errors.append("R-2R device appears in the V2A production placement")

    rectangles: list[tuple[str, float, float, float, float]] = []
    for component in components:
        pcell_name = component["pcell"]
        if pcell_name not in cells:
            errors.append(f"{component['name']}: unknown measured PCell {pcell_name}")
            continue
        if component["orientation"] not in allowed_orientations:
            errors.append(
                f"{component['name']}: orientation {component['orientation']} is not permitted"
            )
        cell = cells[pcell_name]
        half_width = float(cell["width_um"]) / 2.0
        half_height = float(cell["height_um"]) / 2.0
        rectangles.append(
            (
                component["name"],
                float(component["x"]) - half_width,
                float(component["y"]) - half_height,
                float(component["x"]) + half_width,
                float(component["y"]) + half_height,
            )
        )

    for channel in floorplan["channels"]:
        center_x = float(channel["center_x"])
        component_by_name = {component["name"]: component for component in components}
        for name, x0, y0, x1, y1 in rectangles:
            component = component_by_name[name]
            slice_bbox = (
                channel["phase_selector_bbox"]
                if component.get("placement_region") == "phase_selector"
                else channel["slice_bbox"]
            )
            absolute = (center_x + x0, y0, center_x + x1, y1)
            if (
                absolute[0] < slice_bbox[0] - 1e-9
                or absolute[1] < slice_bbox[1] - 1e-9
                or absolute[2] > slice_bbox[2] + 1e-9
                or absolute[3] > slice_bbox[3] + 1e-9
            ):
                errors.append(
                    f"CH{channel['index']} {name} bbox {absolute} leaves slice {slice_bbox}"
                )

    overlaps: list[tuple[str, str]] = []
    for index, first in enumerate(rectangles):
        for second in rectangles[index + 1 :]:
            _, ax0, ay0, ax1, ay1 = first
            _, bx0, by0, bx1, by1 = second
            overlap_x = min(ax1, bx1) - max(ax0, bx0)
            overlap_y = min(ay1, by1) - max(ay0, by0)
            if overlap_x > 1e-9 and overlap_y > 1e-9:
                overlaps.append((first[0], second[0]))
    if overlaps:
        errors.append(f"component bounding boxes overlap: {overlaps}")

    role_groups: dict[str, list[dict[str, Any]]] = {}
    for component in components:
        role_groups.setdefault(component["role"], []).append(component)

    centroid_pairs = (
        ("gm_signal", "gm_reference"),
        ("mixer_out_p", "mixer_out_n"),
    )
    centroid_report: dict[str, dict[str, list[float]]] = {}
    for first_role, second_role in centroid_pairs:
        first_centroid = centroid(role_groups[first_role])
        second_centroid = centroid(role_groups[second_role])
        centroid_report[f"{first_role}_vs_{second_role}"] = {
            first_role: list(first_centroid),
            second_role: list(second_centroid),
        }
        if math.dist(first_centroid, second_centroid) > 1e-9:
            errors.append(
                f"{first_role}/{second_role} centroids differ: {first_centroid} vs {second_centroid}"
            )

    lop = [component for component in components if component.get("lo_gate") == "lop"]
    lon = [component for component in components if component.get("lo_gate") == "lon"]
    if math.dist(centroid(lop), centroid(lon)) > 1e-9:
        errors.append(f"lop/lon mixer gate centroids differ: {centroid(lop)} vs {centroid(lon)}")

    gm_branch_p = [component for component in components if component.get("gm_branch") == "p"]
    gm_branch_n = [component for component in components if component.get("gm_branch") == "n"]
    if math.dist(centroid(gm_branch_p), centroid(gm_branch_n)) > 1e-9:
        errors.append(
            "mixer gm-p/gm-n source centroids differ: "
            f"{centroid(gm_branch_p)} vs {centroid(gm_branch_n)}"
        )

    fixed_fingers = sum(
        int(component["role"].rsplit("_", 1)[1])
        for component in components
        if component["role"].startswith("trim_fixed_")
    )
    binary_fingers = sorted(
        int(component["role"].rsplit("_", 1)[1])
        for component in components
        if component["role"].startswith("trim_binary_")
    )
    trim = floorplan["gain_trim"]
    if fixed_fingers != trim["fixed_unit_fingers"]:
        errors.append(f"fixed trim fingers {fixed_fingers} != {trim['fixed_unit_fingers']}")
    if binary_fingers != sorted(trim["binary_unit_fingers"]):
        errors.append(f"binary trim groups {binary_fingers} != {trim['binary_unit_fingers']}")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "component_count_per_channel": len(components),
        "absolute_component_count_four_channels": 4 * len(components),
        "bbox_overlap_count": len(overlaps),
        "matched_centroids": centroid_report,
        "lop_centroid": list(centroid(lop)),
        "lon_centroid": list(centroid(lon)),
        "gm_branch_p_centroid": list(centroid(gm_branch_p)),
        "gm_branch_n_centroid": list(centroid(gm_branch_n)),
        "fixed_trim_fingers": fixed_fingers,
        "binary_trim_fingers": binary_fingers,
        "unresolved_before_geometry": template["unresolved_before_geometry"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("floorplan", type=Path)
    parser.add_argument("dimensions", type=Path)
    parser.add_argument("template", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = validate_placement_plan(
        json.loads(args.floorplan.read_text(encoding="utf-8")),
        json.loads(args.dimensions.read_text(encoding="utf-8")),
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
