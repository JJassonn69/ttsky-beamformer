#!/usr/bin/env python3
"""Validate the exact-unit V3 channel matrix and local LO route contract."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "v3" / "layout" / "channel_matrix_placement.json"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "channel_matrix_placement_check.json"


def overlap(a: list[float], b: list[float]) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def connected(segments: list[dict[str, Any]], required: list[list[float]]) -> bool:
    graph: dict[tuple[float, float], set[tuple[float, float]]] = defaultdict(set)
    for item in segments:
        a, b = tuple(item["from"]), tuple(item["to"])
        graph[a].add(b)
        graph[b].add(a)
    if not graph:
        return False
    pending = deque([next(iter(graph))])
    seen = set()
    while pending:
        node = pending.popleft()
        if node in seen:
            continue
        seen.add(node)
        pending.extend(graph[node] - seen)
    return seen == set(graph) and all(tuple(point) in seen for point in required)


def check(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    instances = data["matrix"]["instances"]
    channel = data["channel_bbox"]
    if len(instances) != 15:
        errors.append(f"matrix must contain exactly 15 units, found {len(instances)}")

    counts = Counter(str(item["group_weight"]) for item in instances)
    required_counts = data["constraints"]["required_group_counts"]
    if dict(sorted(counts.items())) != required_counts:
        errors.append(f"binary group counts changed: {dict(counts)}")

    positions: dict[int, list[tuple[float, float]]] = defaultdict(list)
    orientations: dict[int, Counter[str]] = defaultdict(Counter)
    route_status = {}
    via3_count = 0
    for item in instances:
        row = float(item["row_top_to_bottom"])
        column = float(item["column_left_to_right"])
        group = int(item["group_weight"])
        positions[group].append((column, row))
        orientations[group][item["orientation"]] += 1
        box = item["bbox"]
        if box[0] < channel[0] or box[1] < channel[1] or box[2] > channel[2] or box[3] > channel[3]:
            errors.append(f"{item['name']} exceeds channel bbox: {box}")
        for net, route in item["local_lo_routes"].items():
            segments = route["segments"]
            manhattan = all(
                math.isclose(segment["from"][0], segment["to"][0])
                or math.isclose(segment["from"][1], segment["to"][1])
                for segment in segments
            )
            required = route["source_ports"] + [route["root"]]
            is_connected = connected(segments, required)
            expected_layer = "metal4" if net == "lop" else "metal3"
            layer_set = {segment["layer"] for segment in segments}
            via_points = route["via3_at_source_ports"]
            via3_count += len(via_points)
            if not manhattan:
                errors.append(f"{item['name']} {net} contains a non-Manhattan segment")
            if not is_connected:
                errors.append(f"{item['name']} {net} does not connect both ports to its root")
            if layer_set != {expected_layer}:
                errors.append(f"{item['name']} {net} uses {sorted(layer_set)}, expected {expected_layer}")
            if (net == "lop" and via_points != route["source_ports"]) or (net == "lon" and via_points):
                errors.append(f"{item['name']} {net} Via-3 contract changed")
            route_status[f"{item['name']}.{net}"] = {
                "connected": is_connected,
                "manhattan": manhattan,
                "layer": expected_layer,
                "segment_count": len(segments),
            }

    for index, first in enumerate(instances):
        for second in instances[index + 1:]:
            if overlap(first["bbox"], second["bbox"]):
                errors.append(f"unit bbox overlap: {first['name']} / {second['name']}")

    centroids = {
        str(group): [
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        ]
        for group, points in sorted(positions.items())
    }
    expected_centroid = data["constraints"]["required_common_centroid_unit_pitch"]
    for group, centroid in centroids.items():
        if centroid != expected_centroid:
            errors.append(f"group {group} centroid changed: {centroid}")
    for group in (2, 4, 8):
        if orientations[group] != Counter({"R0": len(positions[group]) // 2, "MY": len(positions[group]) // 2}):
            errors.append(f"group {group} is not inversion-balanced: {dict(orientations[group])}")
    centre = next(item for item in instances if item["group_weight"] == 1)
    if [centre["column_left_to_right"], centre["row_top_to_bottom"]] != [1, 2]:
        errors.append("single group-1 unit is not at the array centre")

    active = data["active_array_bbox"]
    width = active[2] - active[0]
    height = active[3] - active[1]
    if width > data["constraints"]["maximum_channel_width_um"]:
        errors.append(f"active width {width} exceeds channel allowance")
    if height > data["constraints"]["maximum_channel_height_um"]:
        errors.append(f"active height {height} exceeds channel allowance")
    row_gaps = data["routing_reservations"]["inter_row_channels"]
    minimum_row_gap = min(box[3] - box[1] for box in row_gaps)
    unique_columns = sorted({item["bbox"][0] for item in instances})
    column_boxes = []
    for left in unique_columns:
        boxes = [item["bbox"] for item in instances if item["bbox"][0] == left]
        column_boxes.append([min(box[0] for box in boxes), max(box[2] for box in boxes)])
    minimum_column_gap = min(
        second[0] - first[1] for first, second in zip(column_boxes, column_boxes[1:])
    )
    minimum_required = float(data["constraints"]["minimum_unit_bbox_spacing_um"])
    if minimum_column_gap < minimum_required:
        errors.append(f"column bbox spacing {minimum_column_gap} is below {minimum_required}")
    if minimum_row_gap < 2.0:
        errors.append(f"inter-row routing channel {minimum_row_gap} is too narrow")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "unit_count": len(instances),
        "group_counts": dict(sorted(counts.items())),
        "group_centroids_in_unit_pitch": centroids,
        "orientation_counts": {
            str(group): dict(sorted(values.items())) for group, values in sorted(orientations.items())
        },
        "active_array_bbox": active,
        "active_array_width_um": width,
        "active_array_height_um": height,
        "minimum_column_bbox_gap_um": minimum_column_gap,
        "minimum_inter_row_channel_um": minimum_row_gap,
        "local_route_status": route_status,
        "named_via3_count": via3_count,
        "physical_status": "exact row/full local-merge pilots closed; balanced group H-tree pending",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = check(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
