#!/usr/bin/env python3
"""Verify that all eight selector outputs join only their intended tree roots."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "v3" / "layout" / "channel_selector_join.json"
DEFAULT_SPICE = ROOT / "build" / "v3" / "channel_selector_readback" / "v3_channel_selector_pilot_flat.spice"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spice", type=Path, default=DEFAULT_SPICE)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "v3" / "channel_selector_pilot" / "topology.json")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    text = args.spice.read_text(encoding="utf-8", errors="replace")
    device_lines = [line for line in text.splitlines() if line.startswith("X")]
    errors: list[str] = []
    joins = []
    selector_device_count = 208
    numbered_lines = []
    for line in device_lines:
        match = re.match(r"X(\d+)\s", line)
        if not match:
            errors.append(f"cannot parse extracted device index: {line[:40]}")
            continue
        numbered_lines.append((int(match.group(1)), line))
    for item in manifest["joins"]:
        selector = item["selector_net"]
        analog = item["analog_net"]
        node = f"v3_channel_input_bias_pilot_0/{analog}"
        selector_lines = [line for index, line in numbered_lines if index < selector_device_count and re.search(rf"(?:^|\s){re.escape(node)}(?:\s|$)", line)]
        analog_lines = [line for index, line in numbered_lines if index >= selector_device_count and re.search(rf"(?:^|\s){re.escape(node)}(?:\s|$)", line)]
        group = int(selector[5])
        side = selector.rsplit("_", 1)[1]
        expected_cell = f"G{group}_LO_{'P_AND' if side == 'p' else 'N_ANDNOT'}"
        expected_selector_hits = sum(expected_cell in line for line in selector_lines)
        wrong_selector_cells = sorted({
            match.group(0)
            for line in selector_lines
            for match in re.finditer(r"G[0-3]_LO_(?:P_AND|N_ANDNOT)", line)
            if match.group(0) != expected_cell
        })
        connected = bool(selector_lines) and bool(analog_lines) and expected_selector_hits > 0 and not wrong_selector_cells
        if not connected:
            errors.append(f"{selector}/{analog} does not join the expected selector output cell to analog switch gates")
        joins.append({
            "selector_net": selector,
            "analog_net": analog,
            "surviving_extracted_node": node,
            "selector_output_device_hits": len(selector_lines),
            "expected_selector_cell_hits": expected_selector_hits,
            "analog_switch_device_hits": len(analog_lines),
            "wrong_selector_output_cells": wrong_selector_cells,
            "connected": connected,
        })

    # No extracted device line may contain two different group-root aliases;
    # that would indicate an unintended selector/tree short.
    aliases = [f"v3_channel_input_bias_pilot_0/{item['analog_net']}" for item in manifest["joins"]]
    for line in device_lines:
        found = [name for name in aliases if re.search(rf"(?:^|\s){re.escape(name)}(?:\s|$)", line)]
        if len(found) > 1:
            errors.append(f"device terminal line contains multiple joined-net aliases: {found}")
    report = {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "join_count": len(joins),
        "joins": joins,
        "extracted_device_count": len(device_lines),
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
