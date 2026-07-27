#!/usr/bin/env python3
"""Build eight straight, matched selector-to-phase-root joins."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TREES = ROOT / "v3/layout/group_phase_trees_late_promotion.json"
SELECTOR_SUMMARY = ROOT / "build/v3/selector_route_late_promotion/input_summary.json"
ANALOG_GATE = ROOT / "v3/evidence/channel_input_bias_late_promotion_gate.json"
SELECTOR_GATE = ROOT / "v3/evidence/selector_route_late_promotion.json"
OUTPUT = ROOT / "v3/layout/channel_selector_join_late_promotion.json"
NET_MAP = {
    "group0_lo_p": "g1_lop", "group0_lo_n": "g1_lon",
    "group1_lo_p": "g2_lop", "group1_lo_n": "g2_lon",
    "group2_lo_p": "g4_lop", "group2_lo_n": "g4_lon",
    "group3_lo_p": "g8_lop", "group3_lo_n": "g8_lon",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict[str, object]:
    trees = json.loads(TREES.read_text(encoding="utf-8"))
    selector = json.loads(SELECTOR_SUMMARY.read_text(encoding="utf-8"))
    if json.loads(ANALOG_GATE.read_text(encoding="utf-8"))["status"] != "pass":
        raise RuntimeError("connected input-bias gate must pass")
    if json.loads(SELECTOR_GATE.read_text(encoding="utf-8"))["status"] != "pass":
        raise RuntimeError("late-root selector gate must pass")

    channel_origin = [20.0, 20.0]
    selector_origin = [20.0, 143.0]
    selector_pin_y = selector_origin[1] - channel_origin[1] + 0.42
    transitions = [116.0 + 0.8 * index for index in range(8)]
    joins = []
    for transition_y, selector_net in zip(transitions, NET_MAP):
        analog_net = NET_MAP[selector_net]
        x = float(trees["trees"][analog_net]["root"][0])
        root_y = float(trees["trees"][analog_net]["root"][1])
        selector_x = float(selector["pins"][selector_net]["fixed"][0])
        if x != selector_x:
            raise RuntimeError(f"{selector_net}/{analog_net} root misalignment")
        joins.append({
            "selector_net": selector_net, "analog_net": analog_net, "x_um": x,
            "selector_pin_center_y_um": selector_pin_y,
            "transition_y_um": round(transition_y, 6), "analog_root_y_um": root_y,
            "segments": [
                {"layer": "metal2", "from": [x, selector_pin_y], "to": [x, transition_y], "width_um": 0.30},
                {"layer": "metal4", "from": [x, transition_y], "to": [x, root_y], "width_um": 0.40},
            ],
            "transitions": [
                {"at": [x, transition_y], "from": "metal2", "to": "metal3", "via": "via2"},
                {"at": [x, transition_y], "from": "metal3", "to": "metal4", "via": "via3"},
            ],
            "drawn_vertical_length_um": round(selector_pin_y - root_y, 6),
            "direction_reversals": 0,
        })
    return {
        "schema_version": 1, "units": "um",
        "status": "exact late-promotion selector/channel join contract",
        "channel_gds_origin_um": channel_origin,
        "selector_instance_origin_um": selector_origin,
        "joins": joins,
        "selector_power": {
            "rail_tap_x_um": 3.53,
            "vpwr_strap_x_um": 2.25,
            # Keep the two vertical straps on opposite sides of the common
            # standard-cell rail tap.  With both straps on the left, every
            # VPWR M4 tap crossed the VGND vertical strap and silently shorted
            # the supplies even though all spacing DRCs passed.
            "vgnd_strap_x_um": 4.81,
            "strap_layer": "metal4",
            "strap_width_um": 0.40,
            "vpwr_rail_y_um": [7.48, 12.92, 18.36, 23.80, 29.24],
            "vgnd_rail_y_um": [4.76, 10.20, 15.64, 21.08, 26.52],
            "vgnd_guard_join_y_absolute_um": 134.065,
            "vgnd_guard_join": "one Via-3 landing from the isolated M4 ground strap onto the existing grounded top-dummy M3 bus",
            "vpwr_external_port": True,
            "top_row_well_tap": {
                "cell": "sky130_fd_sc_hd__tapvpwrvgnd_1",
                "origin_um": [13.42, 26.52],
                "orientation": "N",
                "purpose": "tie the otherwise unshared PMOS well of the final N-oriented selector row to VPWR",
            },
        },
        "top_level_ports": [
            {"name": "element_input", "layer": "metal2_label", "at_um": [32.44, 128.70], "direction": "input", "domain": "analog"},
            {"name": "ref", "layer": "metal2_label", "at_um": [33.84, 128.70], "direction": "input", "domain": "analog"},
            {"name": "vbias", "layer": "metal2_label", "at_um": [33.14, 128.70], "direction": "input", "domain": "analog"},
            {"name": "row_outp", "layer": "metal2_label", "at_um": [25.53, 128.70], "direction": "output", "domain": "analog"},
            {"name": "row_outn", "layer": "metal2_label", "at_um": [26.33, 128.70], "direction": "output", "domain": "analog"},
            {"name": "phase_0", "layer": "metal3_label", "at_um": [20.42, 176.00], "direction": "input", "domain": "clock"},
            {"name": "phase_90", "layer": "metal3_label", "at_um": [20.42, 175.20], "direction": "input", "domain": "clock"},
            {"name": "phase_180", "layer": "metal3_label", "at_um": [20.42, 174.40], "direction": "input", "domain": "clock"},
            {"name": "phase_270", "layer": "metal3_label", "at_um": [20.42, 173.60], "direction": "input", "domain": "clock"},
            {"name": "group0_bit0", "layer": "metal3_label", "at_um": [35.32, 171.80], "direction": "input", "domain": "digital"},
            {"name": "group0_bit1", "layer": "metal3_label", "at_um": [35.32, 171.00], "direction": "input", "domain": "digital"},
            {"name": "group1_bit0", "layer": "metal3_label", "at_um": [35.32, 170.20], "direction": "input", "domain": "digital"},
            {"name": "group1_bit1", "layer": "metal3_label", "at_um": [35.32, 169.40], "direction": "input", "domain": "digital"},
            {"name": "group2_bit0", "layer": "metal3_label", "at_um": [35.32, 168.60], "direction": "input", "domain": "digital"},
            {"name": "group2_bit1", "layer": "metal3_label", "at_um": [35.32, 167.80], "direction": "input", "domain": "digital"},
            {"name": "group3_bit0", "layer": "metal3_label", "at_um": [35.32, 167.00], "direction": "input", "domain": "digital"},
            {"name": "group3_bit1", "layer": "metal3_label", "at_um": [35.32, 166.20], "direction": "input", "domain": "digital"},
            {"name": "channel_enable", "layer": "metal3_label", "at_um": [35.32, 164.60], "direction": "input", "domain": "digital"},
            {"name": "mixers_blank", "layer": "metal3_label", "at_um": [35.32, 163.80], "direction": "input", "domain": "digital"},
            {"name": "VPWR", "layer": "metal4_label", "at_um": [22.25, 172.24], "direction": "inout", "domain": "power"},
            {"name": "VGND", "layer": "metal4_label", "at_um": [24.81, 169.52], "direction": "inout", "domain": "power"}
        ],
        "constraints": {
            "expected_join_count": 8, "maximum_direction_reversals": 0,
            "required_via2_per_join": 1, "required_via3_per_join": 1,
            "all_drawn_vertical_lengths_equal": len({item["drawn_vertical_length_um"] for item in joins}) == 1,
            "minimum_transition_y_spacing_um": 0.8,
            "no_horizontal_fanout": True, "no_floating_stubs": True,
            "phase_tree_geometry_frozen": True, "input_bias_geometry_frozen": True,
            "selector_power_rails_all_tapped": True,
            "selector_ground_joins_shared_analog_guard": True,
            "all_external_interface_nets_promoted_without_added_signal_routes": True,
        },
        "provenance": {
            "generator": "v3/tools/build_channel_selector_join_late_promotion.py",
            "generator_sha256": sha256(Path(__file__)),
            "phase_trees_sha256": sha256(TREES), "selector_summary_sha256": sha256(SELECTOR_SUMMARY),
            "analog_gate_sha256": sha256(ANALOG_GATE), "selector_gate_sha256": sha256(SELECTOR_GATE),
        },
    }


def main() -> None:
    data = build()
    OUTPUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
