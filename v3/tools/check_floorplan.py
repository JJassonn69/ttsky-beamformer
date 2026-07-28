#!/usr/bin/env python3
"""Validate V3 review-floorplan geometry and promotion invariants."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def manhattan(a: list[float], b: list[float]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def length(route: list[dict[str, Any]]) -> float:
    return sum(manhattan(item["from"], item["to"]) for item in route)


def layer_lengths(route: list[dict[str, Any]]) -> dict[str, float]:
    return {
        layer: sum(manhattan(item["from"], item["to"]) for item in route if item["layer"] == layer)
        for layer in ("metal3", "metal4")
    }


def inside(bbox: list[float], width: float, height: float) -> bool:
    return len(bbox) == 4 and 0 <= bbox[0] < bbox[2] <= width and 0 <= bbox[1] < bbox[3] <= height


def overlap(a: list[float], b: list[float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def orthogonal(item: dict[str, Any]) -> bool:
    a, b = item["from"], item["to"]
    return math.isclose(a[0], b[0], abs_tol=1e-9) or math.isclose(a[1], b[1], abs_tol=1e-9)


def centroid(matrix: list[list[int]], group: int) -> tuple[float, float, int]:
    points = [(x, y) for y, row in enumerate(matrix) for x, value in enumerate(row) if value == group]
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
        len(points),
    )


def validate_floorplan(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    die = data["template"]["die"]
    width, height = float(die["width"]), float(die["height"])
    if (width, height) != (334.88, 225.76):
        errors.append(f"unexpected Tiny Tapeout 2x2 die: {(width, height)}")
    if "metal5" not in data["template"]["forbidden_signal_layers"]:
        errors.append("metal5 must remain unavailable to project signals")

    auth = data["authorization"]
    if not auth["floorplan_authorized"] or any(auth[key] for key in ("device_placement_authorized", "routing_authorized", "gds_authorized")):
        errors.append("review floorplan has invalid authorization state")

    checkpoint_path = PROJECT_ROOT / data["provenance"]["prelayout_checkpoint"]
    observed_checkpoint_hash = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    if observed_checkpoint_hash != data["provenance"]["prelayout_checkpoint_sha256"]:
        errors.append("pre-layout checkpoint hash changed")

    for zone in data["zones"]:
        if not inside(zone["bbox"], width, height):
            errors.append(f"zone outside die: {zone['name']}")
    for item in data["keepouts"]:
        if not inside(item["bbox"], width, height):
            errors.append(f"keepout outside die: {item['name']}")
        if not item["permitted_nets"]:
            errors.append(f"ownerless keepout: {item['name']}")

    channels = sorted(data["channels"], key=lambda item: item["index"])
    if len(channels) != 4:
        errors.append(f"expected four channels, found {len(channels)}")
    pitches: list[float] = []
    entry_lengths: list[float] = []
    gaps: list[float] = []
    matrix_centroids: dict[str, list[float]] = {}
    matrix = data["channel_template"]["active_matrix_top_to_bottom"]
    expected_counts = {1: 1, 2: 2, 4: 4, 8: 8}
    for group, expected_count in expected_counts.items():
        cx, cy, count = centroid(matrix, group)
        matrix_centroids[str(group)] = [cx, cy]
        if count != expected_count or not math.isclose(cx, 1.0) or not math.isclose(cy, 2.0):
            errors.append(f"group {group} common-centroid assignment changed")

    pins = data["analog_pins"]
    expected_x = [152.26, 132.94, 113.62, 94.30, 74.98, 55.66]
    for index, x in enumerate(expected_x):
        pin = pins[f"ua[{index}]"]["center"]
        if pin != [x, 0.5]:
            errors.append(f"ua[{index}] moved from the official boundary location")

    for position, channel in enumerate(channels):
        pin = pins[channel["pin"]]["center"]
        bbox = channel["macro_bbox"]
        selector = channel["selector_bbox"]
        if not inside(bbox, width, height) or not inside(selector, width, height):
            errors.append(f"channel {channel['index']} region outside die")
        if not math.isclose(channel["center_x"], pin[0]) or not math.isclose(channel["input_entry"][0], pin[0]):
            errors.append(f"channel {channel['index']} is not centered over its pin")
        entry_lengths.append(manhattan(pin, channel["input_entry"]))
        if not math.isclose(bbox[2] - bbox[0], data["channel_template"]["estimated_width"], abs_tol=1e-9):
            errors.append(f"channel {channel['index']} width changed")
        if not math.isclose(bbox[3] - bbox[1], data["channel_template"]["estimated_height"], abs_tol=1e-9):
            errors.append(f"channel {channel['index']} height changed")
        if not math.isclose((selector[0] + selector[2]) / 2, channel["center_x"], abs_tol=1e-9):
            errors.append(f"channel {channel['index']} selector is not centered")
        if channel["unit_matrix"] != matrix:
            errors.append(f"channel {channel['index']} matrix differs from template")
        if position:
            pitches.append(abs(channel["center_x"] - channels[position - 1]["center_x"]))
    for first, second in zip(sorted(channels, key=lambda item: item["center_x"]), sorted(channels, key=lambda item: item["center_x"])[1:]):
        if overlap(first["macro_bbox"], second["macro_bbox"]):
            errors.append(f"channel macros {first['index']} and {second['index']} overlap")
        gaps.append(second["macro_bbox"][0] - first["macro_bbox"][2])
    if max(pitches, default=19.32) - min(pitches, default=19.32) > 1e-9:
        errors.append(f"nonuniform channel pitch: {pitches}")
    if max(entry_lengths, default=0) - min(entry_lengths, default=0) > 1e-9:
        errors.append(f"unequal input entry lengths: {entry_lengths}")
    if min(gaps, default=99) < data["channel_template"]["minimum_interchannel_guard_gap"] - 1e-9:
        errors.append(f"interchannel gap below bound: {gaps}")

    phase = data["phase_tree"]
    if phase["allow_meanders"] or phase["allow_u_turns"]:
        errors.append("phase tree allows prohibited route reversals")
    leaf_lengths: dict[str, float] = {}
    for leaf in phase["leaves"]:
        branch = phase["pair_branches"][leaf["branch"]]
        leaf_lengths[str(leaf["channel"])] = manhattan(phase["root"], branch) + manhattan(branch, leaf["point"])
        if leaf["point"] != channels[leaf["channel"]]["phase_leaf"]:
            errors.append(f"phase leaf misses channel {leaf['channel']}")
    phase_values = list(leaf_lengths.values())
    phase_mismatch = 100 * (max(phase_values) - min(phase_values)) / max(phase_values)
    if phase_mismatch > phase["max_drawn_leaf_mismatch_percent"]:
        errors.append(f"phase leaf mismatch is {phase_mismatch:.6f}%")

    output = data["output_pair"]
    pin_lengths: dict[str, float] = {}
    per_layer: dict[str, dict[str, float]] = {}
    local_tap_lengths: dict[str, list[float]] = {"p": [], "n": []}
    for side in ("p", "n"):
        route = output["routes"][side]
        if route[0]["from"] != output[f"load_{side}_terminal"]:
            errors.append(f"output {side} route misses load terminal")
        if route[-1]["to"] != pins[output[f"load_{side}_pin"]]["center"]:
            errors.append(f"output {side} route misses pad")
        for index, item in enumerate(route):
            if not orthogonal(item):
                errors.append(f"output {side} segment {index} is diagonal")
            if index and route[index - 1]["to"] != item["from"]:
                errors.append(f"output {side} route discontinuity")
        pin_lengths[side] = length(route)
        per_layer[side] = layer_lengths(route)
        extension = output["sum_bus_extensions"][side]
        if extension["from"] != route[0]["to"] or not orthogonal(extension):
            errors.append(f"output {side} sum bus is not rooted at its load branch")
        taps = output["channel_taps"][side]
        if len(taps) != 4:
            errors.append(f"output {side} does not have four channel taps")
        bus_y = route[0]["to"][1]
        for tap in taps:
            item = tap["route"]
            local_tap_lengths[side].append(manhattan(item["from"], item["to"]))
            if item["to"][1] != bus_y or item["layer"] != "metal3" or tap["via_at_bus"] != "via3":
                errors.append(f"output {side} channel tap has wrong endpoint topology")
    pin_mismatch = 100 * abs(pin_lengths["p"] - pin_lengths["n"]) / max(pin_lengths.values())
    if pin_mismatch > output["max_drawn_pin_path_mismatch_percent"]:
        errors.append(f"output pin paths mismatch by {pin_mismatch:.6f}%")
    if any(
        not math.isclose(per_layer["p"][layer], per_layer["n"][layer], abs_tol=1e-9)
        for layer in ("metal3", "metal4")
    ):
        errors.append(f"output per-layer path lengths differ: {per_layer}")
    all_taps = local_tap_lengths["p"] + local_tap_lengths["n"]
    if max(all_taps) - min(all_taps) > 1e-9:
        errors.append(f"local P/N output taps are not equal: {local_tap_lengths}")

    forbidden = ("floating_stubs_allowed", "orphan_vias_allowed", "same_net_dead_end_landings_allowed", "unrelated_routes_inside_passive_keepouts_allowed", "length_matching_with_u_bends_allowed")
    for rule in forbidden:
        if data["global_route_invariants"][rule]:
            errors.append(f"forbidden route behavior enabled: {rule}")
    for name, net_class in data["net_classes"].items():
        if net_class["max_direction_reversals"] != 0:
            errors.append(f"net class {name} permits direction reversal")

    def rounded(values: list[float]) -> list[float]:
        return [round(value, 6) for value in values]

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "scope": "constraint-only review floorplan; no PCell placement, routing, DRC, LVS, extraction, or GDS",
        "channel_pitch_um": rounded(pitches),
        "interchannel_guard_gaps_um": rounded(gaps),
        "input_entry_lengths_um": rounded(entry_lengths),
        "matrix_centroids": matrix_centroids,
        "phase_leaf_lengths_um": {key: round(value, 6) for key, value in leaf_lengths.items()},
        "phase_drawn_mismatch_percent": round(phase_mismatch, 9),
        "output_pin_path_lengths_um": {key: round(value, 6) for key, value in pin_lengths.items()},
        "output_pin_layer_lengths_um": {
            side: {layer: round(value, 6) for layer, value in values.items()}
            for side, values in per_layer.items()
        },
        "output_pin_path_mismatch_percent": round(pin_mismatch, 9),
        "local_output_tap_lengths_um": {
            side: rounded(values) for side, values in local_tap_lengths.items()
        },
        "promotion_gate_count": len(data["promotion_gates"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?", default=PROJECT_ROOT / "v3" / "layout" / "floorplan.json")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate_floorplan(json.loads(args.manifest.read_text(encoding="utf-8")))
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
