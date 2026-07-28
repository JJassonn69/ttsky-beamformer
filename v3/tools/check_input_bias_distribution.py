#!/usr/bin/env python3
"""Check V3 input-bias placement and balanced VCM-tree constraints."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "v3" / "layout" / "input_bias_distribution.json"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "input_bias_distribution_check.json"


def length(segment: dict[str, Any]) -> float:
    x0, y0 = segment["from"]
    x1, y1 = segment["to"]
    if not (math.isclose(x0, x1) or math.isclose(y0, y1)):
        raise ValueError(f"non-Manhattan segment {segment}")
    return abs(x1 - x0) + abs(y1 - y0)


def path_length(segments: list[dict[str, Any]]) -> float:
    return sum(length(item) for item in segments)


def tree_leaf_lengths(tree: dict[str, Any]) -> dict[int, float]:
    root_x, root_y = tree["root"]
    result = {}
    for leaf in tree["leaves"]:
        x, y = leaf["point"]
        # The authoritative two-level H-tree has roots at the midpoint of
        # each adjacent pair, so this formula is independent of list order.
        pair_x = min(tree["pair_roots"], key=lambda point: abs(point[0] - x))[0]
        branch_y = tree["pair_roots"][0][1]
        result[int(leaf["channel"])] = (
            abs(root_x - pair_x) + abs(root_y - branch_y)
            + abs(pair_x - x) + abs(branch_y - y)
        )
    return result


def check(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    resistors = data["placement"]["resistors"]
    if len(resistors) != 4 or {item["channel"] for item in resistors} != {0, 1, 2, 3}:
        errors.append("exactly one input-bias resistor is required for each of four channels")
    offsets = []
    for item in resistors:
        input_route = next(route for route in data["input_branches"] if route["channel"] == item["channel"])
        r2 = item["terminals"]["R2"]
        if input_route["segments"][0]["from"] != r2:
            errors.append(f"channel {item['channel']} input route does not start at R2")
        if item["nets"] != {"B": "VGND", "R1": "vcm", "R2": f"element_{item['channel']}"}:
            errors.append(f"channel {item['channel']} resistor net mapping changed")
        offsets.append(round(item["center"][0] + data["placement"]["channel_pitch_um"] / 2.0, 6))

    input_lengths = {
        int(item["channel"]): path_length(item["segments"])
        for item in data["input_branches"]
    }
    if max(input_lengths.values()) - min(input_lengths.values()) > 1e-9:
        errors.append(f"input branch lengths differ: {input_lengths}")

    tree_lengths = tree_leaf_lengths(data["vcm_distribution"])
    if max(tree_lengths.values()) - min(tree_lengths.values()) > 1e-9:
        errors.append(f"VCM H-tree leaf lengths differ: {tree_lengths}")

    local_lengths = {
        int(item["channel"]): path_length(item["segments"])
        for item in data["vcm_distribution"]["local_channel_entries"]
    }
    if max(local_lengths.values()) - min(local_lengths.values()) > 1e-9:
        errors.append(f"local VCM entry lengths differ: {local_lengths}")

    bboxes = sorted((item["bbox"], item["name"]) for item in resistors)
    for index, (first, first_name) in enumerate(bboxes):
        for second, second_name in bboxes[index + 1:]:
            overlap_x = min(first[2], second[2]) - max(first[0], second[0])
            overlap_y = min(first[3], second[3]) - max(first[1], second[1])
            if overlap_x > 0 and overlap_y > 0:
                errors.append(f"resistor PCells overlap: {first_name}/{second_name}")

    all_layers = {
        item["layer"]
        for item in data["vcm_distribution"]["segments"]
    }
    if all_layers != {"metal3"}:
        errors.append(f"VCM H-tree must remain single-layer Metal 3, found {sorted(all_layers)}")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "resistor_count": len(resistors),
        "input_branch_lengths_um": input_lengths,
        "input_branch_mismatch_percent": 100.0 * (
            max(input_lengths.values()) - min(input_lengths.values())
        ) / max(input_lengths.values()),
        "vcm_tree_leaf_lengths_um": tree_lengths,
        "vcm_tree_leaf_mismatch_percent": 100.0 * (
            max(tree_lengths.values()) - min(tree_lengths.values())
        ) / max(tree_lengths.values()),
        "local_vcm_entry_lengths_um": local_lengths,
        "local_vcm_entry_mismatch_percent": 100.0 * (
            max(local_lengths.values()) - min(local_lengths.values())
        ) / max(local_lengths.values()),
        "physical_guard_merge_status": "pending exact one-channel pilot",
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
