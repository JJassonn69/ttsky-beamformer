#!/usr/bin/env python3
"""Validate V3 local selector placement, logic, and routing reservations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def overlap(a: list[float], b: list[float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def inside(inner: list[float], outer: list[float]) -> bool:
    return outer[0] <= inner[0] < inner[2] <= outer[2] and outer[1] <= inner[1] < inner[3] <= outer[3]


def validate(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    template = data["channel_template"]
    constraints = data["constraints"]
    instances = template["instances"]
    if template["raw_cell_utilization_percent"] > constraints["maximum_raw_cell_utilization_percent"]:
        errors.append("selector raw-cell utilization exceeds floorplan limit")
    if len(data["channels"]) != 4:
        errors.append("selector placement does not contain four channels")

    role_counts: dict[str, int] = {}
    group_counts: dict[int, dict[str, int]] = {}
    row_widths: dict[int, float] = {}
    taps_by_row: set[int] = set()
    for item in instances:
        role = item["cell_role"]
        role_counts[role] = role_counts.get(role, 0) + 1
        row_widths[item["row"]] = max(row_widths.get(item["row"], 0.0), item["bbox"][2]) - min(
            [candidate["bbox"][0] for candidate in instances if candidate["row"] == item["row"]]
        )
        if role == "tap":
            taps_by_row.add(item["row"])
        if item["group"] is not None:
            counts = group_counts.setdefault(item["group"], {})
            counts[role] = counts.get(role, 0) + 1
    expected_roles = {"tap": 5, "and2b": 5, "mux2": 12, "and2": 4}
    if role_counts != expected_roles:
        errors.append(f"unexpected per-channel role counts: {role_counts}")
    for group in range(4):
        if group_counts.get(group) != {"tap": 1, "mux2": 3, "and2": 1, "and2b": 1}:
            errors.append(f"group {group} selector topology changed: {group_counts.get(group)}")
    if max(row_widths.values()) > constraints["maximum_row_width_um"]:
        errors.append(f"selector row exceeds width budget: {row_widths}")
    for row in range(template["row_count"]):
        nearest = min(abs(row - tap_row) for tap_row in taps_by_row)
        if nearest >= constraints["one_tap_at_least_every_rows"]:
            errors.append(f"row {row} is too far from a well tap")

    for first_index, first in enumerate(instances):
        for second in instances[first_index + 1 :]:
            if overlap(first["bbox"], second["bbox"]):
                errors.append(f"template instances overlap: {first['name']} / {second['name']}")
    canonical = [(item["name"], item["cell_role"], item["row"], item["orientation"]) for item in instances]
    for channel in data["channels"]:
        if not all(inside(item["bbox"], channel["bbox"]) for item in channel["instances"]):
            errors.append(f"channel {channel['channel']} selector instance leaves reservation")
        observed = [(item["name"], item["cell_role"], item["row"], item["orientation"]) for item in channel["instances"]]
        if observed != canonical:
            errors.append(f"channel {channel['channel']} is not an identical template copy")

    # Exhaustively evaluate the actual named cell/pin graph for every phase
    # input combination, axis code, channel-enable, and blank state.
    truth_table = []
    logical_instances = [item for item in instances if item["cell_role"] != "tap"]
    for phase_pattern in range(16):
        phases = {
            "phase_0": (phase_pattern >> 0) & 1,
            "phase_90": (phase_pattern >> 1) & 1,
            "phase_180": (phase_pattern >> 2) & 1,
            "phase_270": (phase_pattern >> 3) & 1,
        }
        for code in range(4):
            for channel_enable in (0, 1):
                for blank in (0, 1):
                    nets = {**phases, "channel_enable": channel_enable, "mixers_blank": blank}
                    for group in range(4):
                        nets[f"group{group}_bit0"] = code & 1
                        nets[f"group{group}_bit1"] = (code >> 1) & 1
                    for item in logical_instances:
                        pins = item["connections"]
                        role = item["cell_role"]
                        if role == "mux2":
                            nets[pins["X"]] = nets[pins["A1"]] if nets[pins["S"]] else nets[pins["A0"]]
                        elif role == "and2":
                            nets[pins["X"]] = nets[pins["A"]] & nets[pins["B"]]
                        elif role == "and2b":
                            nets[pins["X"]] = (1 - nets[pins["A_N"]]) & nets[pins["B"]]
                        else:
                            errors.append(f"unsupported logical cell role {role}")
                    expected_enable = channel_enable & (1 - blank)
                    phase_names = ("phase_0", "phase_90", "phase_180", "phase_270")
                    expected_selected = nets[phase_names[code]]
                    for group in range(4):
                        lo_p = nets[f"group{group}_lo_p"]
                        lo_n = nets[f"group{group}_lo_n"]
                        if lo_p != expected_selected * expected_enable:
                            errors.append(f"group {group} lo_p logic mismatch")
                        if lo_n != (1 - expected_selected) * expected_enable:
                            errors.append(f"group {group} lo_n logic mismatch")
                    if phase_pattern in (0b1001, 0b0110) and channel_enable == 1 and blank == 0:
                        truth_table.append({"phase_pattern": phase_pattern, "code": code, "lo_p": nets["group0_lo_p"], "lo_n": nets["group0_lo_n"]})

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "scope": "local selector standard-cell placement skeleton; no detailed routing, DRC, extraction, or GDS",
        "instances_per_channel": len(instances),
        "role_counts_per_channel": role_counts,
        "row_widths_um": {str(row): round(width, 3) for row, width in row_widths.items()},
        "raw_cell_utilization_percent": round(template["raw_cell_utilization_percent"], 6),
        "truth_table": truth_table,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?", default=ROOT / "v3" / "layout" / "selector_placement.json")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate(json.loads(args.manifest.read_text(encoding="utf-8")))
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
