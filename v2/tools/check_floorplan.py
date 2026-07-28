#!/usr/bin/env python3
"""Validate the V2 pre-placement floorplan and routing invariants."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def manhattan(a: list[float], b: list[float]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def bbox_inside(bbox: list[float], width: float, height: float) -> bool:
    return (
        len(bbox) == 4
        and 0.0 <= bbox[0] < bbox[2] <= width
        and 0.0 <= bbox[1] < bbox[3] <= height
    )


def bboxes_overlap(a: list[float], b: list[float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def segment_length(segment: dict[str, Any]) -> float:
    return manhattan(segment["from"], segment["to"])


def is_orthogonal(segment: dict[str, Any]) -> bool:
    start = segment["from"]
    end = segment["to"]
    return math.isclose(start[0], end[0], abs_tol=1e-9) or math.isclose(
        start[1], end[1], abs_tol=1e-9
    )


def collinear_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a["layer"] != b["layer"]:
        return False
    a0, a1 = a["from"], a["to"]
    b0, b1 = b["from"], b["to"]
    if math.isclose(a0[0], a1[0], abs_tol=1e-9) and math.isclose(
        b0[0], b1[0], abs_tol=1e-9
    ):
        if not math.isclose(a0[0], b0[0], abs_tol=1e-9):
            return False
        return max(min(a0[1], a1[1]), min(b0[1], b1[1])) < min(
            max(a0[1], a1[1]), max(b0[1], b1[1])
        )
    if math.isclose(a0[1], a1[1], abs_tol=1e-9) and math.isclose(
        b0[1], b1[1], abs_tol=1e-9
    ):
        if not math.isclose(a0[1], b0[1], abs_tol=1e-9):
            return False
        return max(min(a0[0], a1[0]), min(b0[0], b1[0])) < min(
            max(a0[0], a1[0]), max(b0[0], b1[0])
        )
    return False


def validate_floorplan(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    template = data["template"]
    die = template["die"]
    width = float(die["width"])
    height = float(die["height"])

    if not math.isclose(width, 334.88, abs_tol=1e-6):
        errors.append(f"unexpected 2x2 width: {width}")
    if not math.isclose(height, 225.76, abs_tol=1e-6):
        errors.append(f"unexpected 2x2 height: {height}")
    if "metal5" not in template["forbidden_signal_layers"]:
        errors.append("metal5 must be forbidden for project signals")

    pins = data["analog_pins"]
    expected_pin_x = [152.26, 132.94, 113.62, 94.30, 74.98, 55.66]
    for index, expected_x in enumerate(expected_pin_x):
        name = f"ua[{index}]"
        if name not in pins:
            errors.append(f"missing {name}")
            continue
        center = pins[name]["center"]
        if not math.isclose(center[0], expected_x, abs_tol=1e-6):
            errors.append(f"{name} x-coordinate changed: {center[0]}")
        if not math.isclose(center[1], 0.50, abs_tol=1e-6):
            errors.append(f"{name} is not on the official lower boundary")

    for zone in data["zones"]:
        if not bbox_inside(zone["bbox"], width, height):
            errors.append(f"zone {zone['name']} lies outside the die")
    for keepout in data["keepouts"]:
        if not bbox_inside(keepout["bbox"], width, height):
            errors.append(f"keepout {keepout['name']} lies outside the die")
        if not keepout["permitted_nets"]:
            errors.append(f"keepout {keepout['name']} has no permitted owner")

    channels = sorted(data["channels"], key=lambda channel: channel["index"])
    if len(channels) != 4:
        errors.append(f"expected four channels, found {len(channels)}")

    channel_pitch: list[float] = []
    input_lengths: list[float] = []
    for index, channel in enumerate(channels):
        expected_pin = f"ua[{index}]"
        if channel["pin"] != expected_pin:
            errors.append(f"channel {index} is assigned to {channel['pin']}, not {expected_pin}")
        pin_center = pins[expected_pin]["center"]
        if not math.isclose(channel["center_x"], pin_center[0], abs_tol=1e-6):
            errors.append(f"channel {index} center is not aligned to its analog pin")
        if not math.isclose(channel["input_entry"][0], pin_center[0], abs_tol=1e-6):
            errors.append(f"channel {index} input entry requires a lateral pin jog")
        length = manhattan(pin_center, channel["input_entry"])
        input_lengths.append(length)
        maximum = data["net_classes"]["element_inputs"]["max_pin_to_slice_entry_length"]
        if length > maximum:
            errors.append(f"channel {index} pin entry is {length:.3f} um, above {maximum:.3f} um")
        if not bbox_inside(channel["slice_bbox"], width, height):
            errors.append(f"channel {index} slice lies outside the die")
        if index:
            channel_pitch.append(abs(channel["center_x"] - channels[index - 1]["center_x"]))

    for left_index, left in enumerate(channels):
        for right in channels[left_index + 1 :]:
            if bboxes_overlap(left["slice_bbox"], right["slice_bbox"]):
                errors.append(f"channel slices {left['index']} and {right['index']} overlap")

    if channel_pitch and max(channel_pitch) - min(channel_pitch) > 1e-6:
        errors.append(f"channel pitch is not uniform: {channel_pitch}")
    if input_lengths and max(input_lengths) - min(input_lengths) > 1e-6:
        errors.append(f"input entry lengths are not equal: {input_lengths}")

    tree = data["clock_tree"]
    root = tree["root"]
    leaf_lengths: dict[str, float] = {}
    leaf_vias: dict[str, int] = {}
    for leaf in tree["leaves"]:
        branch = tree["pair_branches"][leaf["branch"]]
        length = manhattan(root, branch) + manhattan(branch, leaf["point"])
        leaf_lengths[str(leaf["channel"])] = length
        leaf_vias[str(leaf["channel"])] = len(tree["equal_via_sites"])
        expected_leaf = channels[leaf["channel"]]["phase_leaf"]
        if leaf["point"] != expected_leaf:
            errors.append(f"clock leaf {leaf['channel']} misses its channel phase entry")

    mean_channel_x = sum(channel["center_x"] for channel in channels) / len(channels)
    if not math.isclose(root[0], mean_channel_x, abs_tol=1e-6):
        errors.append("clock-tree root is not centered on the channel array")

    lengths = list(leaf_lengths.values())
    tree_mismatch = 0.0
    if lengths:
        tree_mismatch = 100.0 * (max(lengths) - min(lengths)) / max(lengths)
        if tree_mismatch > tree["max_drawn_path_mismatch_percent"]:
            errors.append(f"clock-tree path mismatch is {tree_mismatch:.6f}%")
    if tree["allow_meanders"] or tree["allow_u_turns"]:
        errors.append("clock tree permits a prohibited meander or U-turn")

    output = data["output_pair"]
    output_routes = output["routes"]
    for net_name, route in output_routes.items():
        if not route:
            errors.append(f"output route {net_name} is empty")
            continue
        expected_start = output[f"load_{net_name}"]
        expected_end = pins[output[f"pin_{net_name}"]]["center"]
        if route[0]["from"] != expected_start:
            errors.append(f"output route {net_name} does not start at its load")
        if route[-1]["to"] != expected_end:
            errors.append(f"output route {net_name} does not end at its pin")
        for segment_index, segment in enumerate(route):
            if not is_orthogonal(segment):
                errors.append(f"output route {net_name} segment {segment_index} is diagonal")
            if segment_index and route[segment_index - 1]["to"] != segment["from"]:
                errors.append(f"output route {net_name} is discontinuous at segment {segment_index}")

    output_p_length = sum(segment_length(segment) for segment in output_routes["p"])
    output_n_length = sum(segment_length(segment) for segment in output_routes["n"])
    output_mismatch = 100.0 * abs(output_p_length - output_n_length) / max(
        output_p_length, output_n_length
    )
    if output_mismatch > output["max_drawn_length_mismatch_percent"]:
        errors.append(f"output-pair planned mismatch is {output_mismatch:.6f}%")
    p_layer_lengths = {
        layer: sum(segment_length(segment) for segment in output_routes["p"] if segment["layer"] == layer)
        for layer in ("metal3", "metal4")
    }
    n_layer_lengths = {
        layer: sum(segment_length(segment) for segment in output_routes["n"] if segment["layer"] == layer)
        for layer in ("metal3", "metal4")
    }
    if any(
        not math.isclose(p_layer_lengths[layer], n_layer_lengths[layer], abs_tol=1e-9)
        for layer in p_layer_lengths
    ):
        errors.append(
            f"output layer lengths differ: P={p_layer_lengths}, N={n_layer_lengths}"
        )
    if any(
        collinear_overlap(p_segment, n_segment)
        for p_segment in output_routes["p"]
        for n_segment in output_routes["n"]
    ):
        errors.append("output P/N routes contain a same-layer collinear overlap")

    invariants = data["global_route_invariants"]
    forbidden_true = {
        "floating_stubs_allowed",
        "orphan_vias_allowed",
        "same_net_dead_end_landings_allowed",
        "unrelated_routes_inside_passive_keepouts_allowed",
        "length_matching_with_u_bends_allowed",
    }
    for rule in forbidden_true:
        if invariants[rule]:
            errors.append(f"forbidden route behavior enabled: {rule}")

    report = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "die_um": [width, height],
        "channel_pitch_um": channel_pitch,
        "input_entry_lengths_um": input_lengths,
        "keepout_count": len(data["keepouts"]),
        "clock_leaf_lengths_um": leaf_lengths,
        "clock_drawn_mismatch_percent": tree_mismatch,
        "clock_equal_via_site_types": leaf_vias,
        "output_p_planned_length_um": output_p_length,
        "output_n_planned_length_um": output_n_length,
        "output_p_layer_lengths_um": p_layer_lengths,
        "output_n_layer_lengths_um": n_layer_lengths,
        "output_planned_mismatch_percent": output_mismatch,
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = validate_floorplan(data)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
