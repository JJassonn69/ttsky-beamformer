#!/usr/bin/env python3
"""Build the exact straight-drop contract joining one selector to one channel."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TREES = ROOT / "v3" / "layout" / "group_phase_trees.json"
SELECTOR = ROOT / "v3" / "layout" / "selector_placement.json"
OUTPUT = ROOT / "v3" / "layout" / "channel_selector_join.json"
SELECTOR_BOTTOM_Y = 126.0
SELECTOR_PIN_CENTER_Y = SELECTOR_BOTTOM_Y + 0.42
ANALOG_ROOT_Y = 93.05
TRANSITION_Y = (118.0, 118.8, 119.6, 120.4, 121.2, 122.0, 122.8, 123.6)
NET_MAP = {
    "group0_lo_p": "g1_lop",
    "group0_lo_n": "g1_lon",
    "group1_lo_p": "g2_lop",
    "group1_lo_n": "g2_lon",
    "group2_lo_p": "g4_lop",
    "group2_lo_n": "g4_lon",
    "group3_lo_p": "g8_lop",
    "group3_lo_n": "g8_lon",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict[str, object]:
    trees = json.loads(TREES.read_text(encoding="utf-8"))
    selector = json.loads(SELECTOR.read_text(encoding="utf-8"))
    anchors = selector["channel_template"]["route_reservations"]["analog_group_output_entry"]["anchors"]
    joins = []
    for transition_y, selector_net in zip(TRANSITION_Y, NET_MAP):
        analog_net = NET_MAP[selector_net]
        selector_x = anchors[selector_net][0]
        root = trees["trees"][analog_net]["root"]
        if selector_x != root[0] or root[1] != ANALOG_ROOT_Y:
            raise RuntimeError(f"{selector_net}/{analog_net} is not vertically aligned")
        joins.append({
            "selector_net": selector_net,
            "analog_net": analog_net,
            "x_um": selector_x,
            "selector_pin_center_y_um": SELECTOR_PIN_CENTER_Y,
            "transition_y_um": transition_y,
            "analog_root_y_um": ANALOG_ROOT_Y,
            "segments": [
                {"layer": "metal2", "from": [selector_x, SELECTOR_PIN_CENTER_Y], "to": [selector_x, transition_y], "width_um": 0.30},
                {"layer": "metal4", "from": [selector_x, transition_y], "to": [selector_x, ANALOG_ROOT_Y], "width_um": 0.30},
            ],
            "transitions": [
                {"at": [selector_x, transition_y], "from": "metal2", "to": "metal3", "via": "via2"},
                {"at": [selector_x, transition_y], "from": "metal3", "to": "metal4", "via": "via3"},
            ],
            "drawn_vertical_length_um": round(SELECTOR_PIN_CENTER_Y - ANALOG_ROOT_Y, 6),
            "direction_reversals": 0,
        })
    lengths = {item["drawn_vertical_length_um"] for item in joins}
    return {
        "schema_version": 1,
        "status": "exact root-aligned selector/channel join contract",
        "units": "um",
        "channel_gds_origin_um": [20.0, 20.0],
        "selector_instance_origin_um": [20.0, 146.0],
        "joins": joins,
        "constraints": {
            "expected_join_count": 8,
            "maximum_direction_reversals": 0,
            "required_via2_per_join": 1,
            "required_via3_per_join": 1,
            "all_drawn_vertical_lengths_equal": len(lengths) == 1,
            "minimum_transition_y_spacing_um": 0.8,
            "no_horizontal_fanout": True,
            "no_floating_stubs": True,
        },
        "provenance": {
            "generator": "v3/tools/build_channel_selector_join.py",
            "generator_sha256": sha256(Path(__file__)),
            "group_phase_trees_sha256": sha256(TREES),
            "selector_placement_sha256": sha256(SELECTOR),
        },
    }


def main() -> None:
    report = build()
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "join_count": len(report["joins"]), "constraints": report["constraints"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
