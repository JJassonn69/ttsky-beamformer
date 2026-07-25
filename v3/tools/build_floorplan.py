#!/usr/bin/env python3
"""Build the authoritative V3 review-floorplan constraint manifest.

This script creates geometry constraints only.  It does not instantiate a
PCell, draw a route, create a layout database, or authorize GDS generation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = PROJECT_ROOT / "v3" / "evidence" / "implementation_checkpoint.json"
SUPPORT_STUDY = PROJECT_ROOT / "v3" / "evidence" / "support_floorplan_study.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "v3" / "layout" / "floorplan.json"

CHANNEL_CENTERS = [152.26, 132.94, 113.62, 94.30]
CHANNEL_WIDTH = 15.74
CHANNEL_HEIGHT = 93.99
CHANNEL_BOTTOM = 8.0
SELECTOR_BOTTOM = 134.0
SELECTOR_TOP = 168.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def segment(start: list[float], end: list[float], layer: str) -> dict[str, Any]:
    return {"from": start, "to": end, "layer": layer}


def build_floorplan() -> dict[str, Any]:
    checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    support = json.loads(SUPPORT_STUDY.read_text(encoding="utf-8"))
    if not checkpoint["layout_authorized"] or checkpoint["gds_authorized"]:
        raise RuntimeError("V3 checkpoint does not authorize review floorplanning")
    if support["status"] != "pass":
        raise RuntimeError("V3 shared-support dimension study has not passed")

    analog_pins = {
        "ua[0]": {"center": [152.26, 0.50], "size": [0.90, 1.00], "function": "element_0"},
        "ua[1]": {"center": [132.94, 0.50], "size": [0.90, 1.00], "function": "element_1"},
        "ua[2]": {"center": [113.62, 0.50], "size": [0.90, 1.00], "function": "element_2"},
        "ua[3]": {"center": [94.30, 0.50], "size": [0.90, 1.00], "function": "element_3"},
        "ua[4]": {"center": [74.98, 0.50], "size": [0.90, 1.00], "function": "combined_p"},
        "ua[5]": {"center": [55.66, 0.50], "size": [0.90, 1.00], "function": "combined_n"},
    }

    matrix = [[8, 8, 8], [4, 8, 4], [2, 1, 2], [4, 8, 4], [8, 8, 8]]
    channels = []
    for index, center_x in enumerate(CHANNEL_CENTERS):
        left = round(center_x - CHANNEL_WIDTH / 2.0, 3)
        right = round(center_x + CHANNEL_WIDTH / 2.0, 3)
        top = round(CHANNEL_BOTTOM + CHANNEL_HEIGHT, 3)
        # The two drain-collection anchors intentionally differ in y by the
        # 1.2 um output-bus pitch.  This makes both local vertical taps 6.01 um.
        channels.append(
            {
                "index": index,
                "pin": f"ua[{index}]",
                "center_x": center_x,
                "macro_bbox": [left, CHANNEL_BOTTOM, right, top],
                "input_entry": [center_x, CHANNEL_BOTTOM],
                "macro_orientation": "R0",
                "selector_bbox": [left, SELECTOR_BOTTOM, right, SELECTOR_TOP],
                "phase_leaf": [center_x, 169.0],
                "output_anchors": {
                    "p": [round(center_x - 1.0, 3), top],
                    "n": [round(center_x + 1.0, 3), round(top - 1.2, 3)],
                },
                "unit_matrix": matrix,
                "unit_matrix_orientation": "inversion-paired R0/MY",
            }
        )

    load_center_y = 123.0
    load_terminal_y = 115.29
    output_routes = {
        "p": [
            segment([132.94, load_terminal_y], [132.94, 108.0], "metal3"),
            segment([132.94, 108.0], [74.98, 108.0], "metal4"),
            segment([74.98, 108.0], [74.98, 8.0], "metal3"),
            segment([74.98, 8.0], [74.98, 0.50], "metal4"),
        ],
        "n": [
            segment([113.62, load_terminal_y], [113.62, 106.8], "metal3"),
            segment([113.62, 106.8], [55.66, 106.8], "metal4"),
            segment([55.66, 106.8], [55.66, 8.0], "metal3"),
            segment([55.66, 8.0], [55.66, 0.50], "metal4"),
        ],
    }

    output_taps = {"p": [], "n": []}
    for channel in channels:
        for side, bus_y in (("p", 108.0), ("n", 106.8)):
            anchor = channel["output_anchors"][side]
            output_taps[side].append(
                {
                    "channel": channel["index"],
                    "route": segment(anchor, [anchor[0], bus_y], "metal3"),
                    "via_at_bus": "via3",
                }
            )

    return {
        "schema_version": 1,
        "units": "um",
        "status": "review floorplan constraints; no placement database, routing, or GDS",
        "authorization": {
            "floorplan_authorized": True,
            "device_placement_authorized": False,
            "routing_authorized": False,
            "gds_authorized": False,
        },
        "provenance": {
            "generator": "v3/tools/build_floorplan.py",
            "prelayout_checkpoint": "v3/evidence/implementation_checkpoint.json",
            "prelayout_checkpoint_sha256": sha256(CHECKPOINT),
            "pcell_candidate": checkpoint["pcell_dimension_gate"]["recommended_candidate"],
            "pcell_scope": checkpoint["pcell_dimension_gate"]["scope"],
            "support_floorplan_study": "v3/evidence/support_floorplan_study.json",
            "support_floorplan_study_sha256": sha256(SUPPORT_STUDY),
        },
        "template": {
            "repository": "https://github.com/TinyTapeout/tt-support-tools",
            "commit": "d65690eeb1d4afd26aef795c805a23d9d9daf9d1",
            "path": "tech/sky130A/def/analog/tt_analog_2x2.def",
            "sha256": "c9bf60e875dc86e730424e7af724878977aec59586832a9b8fc937c2cd65c86f",
            "die": {"width": 334.88, "height": 225.76},
            "forbidden_signal_layers": ["metal5"],
        },
        "analog_pins": analog_pins,
        "digital_pin_contract": {
            "ui_in[2:0]": "automatic_beam_index",
            "ui_in[3]": "automatic_or_raw_mode",
            "ui_in[7:4]": "channel_enable_mask",
            "uio_in[0]": "configuration_clock",
            "uio_in[1]": "configuration_data",
            "uio_in[2]": "atomic_configuration_latch",
            "clk": "16 MHz system clock producing 4 MHz quadrature phases",
            "rst_n": "asynchronous active-low reset",
            "ena": "project enable",
        },
        "zones": [
            {"name": "shared_vcm", "bbox": [12.0, 18.0, 49.0, 156.0], "noise_class": "quiet_analog"},
            {"name": "four_channel_vector_core", "bbox": [84.0, 8.0, 162.0, 102.0], "noise_class": "critical_analog"},
            {"name": "differential_sum_corridor", "bbox": [50.0, 103.0, 162.0, 112.0], "noise_class": "critical_analog"},
            {"name": "differential_load_pair", "bbox": [108.0, 113.0, 138.0, 133.0], "noise_class": "critical_analog"},
            {"name": "local_group_selectors", "bbox": [84.0, 134.0, 162.0, 168.0], "noise_class": "clock"},
            {"name": "quadrature_tree", "bbox": [84.0, 169.0, 180.0, 198.0], "noise_class": "clock"},
            {"name": "static_control", "bbox": [181.0, 169.0, 320.0, 220.0], "noise_class": "digital_clock"},
            {"name": "shared_tail_bias_and_decap", "bbox": [181.0, 20.0, 320.0, 165.0], "noise_class": "quiet_mixed_signal"},
        ],
        "keepouts": [
            {"name": "combined_n_vertical_trunk", "bbox": [54.76, 0.0, 56.56, 112.5], "permitted_nets": ["ua[5]", "VGND_shield"]},
            {"name": "combined_p_vertical_trunk", "bbox": [74.08, 0.0, 75.88, 112.5], "permitted_nets": ["ua[4]", "VGND_shield"]},
            {"name": "analog_boundary_escape", "bbox": [50.0, 0.0, 163.0, 4.0], "permitted_nets": list(analog_pins)},
            {"name": "load_pair_no_crossing", "bbox": [108.0, 113.0, 138.0, 133.0], "permitted_nets": ["VAPWR", "beam_out_p", "beam_out_n"]},
        ],
        "channel_template": {
            "estimated_width": CHANNEL_WIDTH,
            "estimated_height": CHANNEL_HEIGHT,
            "channel_pitch": 19.32,
            "minimum_interchannel_guard_gap": 3.58,
            "array_columns": 3,
            "array_rows_active": 5,
            "array_rows_with_top_bottom_dummies": 7,
            "active_matrix_top_to_bottom": matrix,
            "group_counts": {"1": 1, "2": 2, "4": 4, "8": 8},
            "required_features": [
                "one shared substrate guard per channel",
                "device-row edge dummies",
                "top and bottom dummy coverage",
                "equal contact populations",
                "identical switch-route topology",
                "local ground strap",
                "local bias pass and blank devices",
            ],
            "orientation_policy": "unit-level inversion pairs only; keep all four channel macros R0 until mirrored extracted equivalence is proven",
        },
        "channels": channels,
        "output_pair": {
            "load_p_center": [132.94, load_center_y],
            "load_n_center": [113.62, load_center_y],
            "load_p_terminal": [132.94, load_terminal_y],
            "load_n_terminal": [113.62, load_terminal_y],
            "load_p_bbox": [131.405, 114.285, 134.475, 131.715],
            "load_n_bbox": [112.085, 114.285, 115.155, 131.715],
            "load_p_pin": "ua[4]",
            "load_n_pin": "ua[5]",
            "load_pcell": "V2-qualified 5 kohm output_load_resistor_guarded; re-extract in V3 context",
            "routes": output_routes,
            "sum_bus_extensions": {
                "p": segment([132.94, 108.0], [160.13, 108.0], "metal4"),
                "n": segment([113.62, 106.8], [160.13, 106.8], "metal4"),
            },
            "channel_taps": output_taps,
            "wire_width": 0.80,
            "max_drawn_pin_path_mismatch_percent": 0.10,
            "max_extracted_rc_mismatch_percent": 1.0,
            "equal_via_sites": ["via2", "via3"],
            "required_via3_sites_per_pin_path": 3,
            "note": "pin paths are length matched; full branched-net RC must be matched after extraction",
        },
        "phase_tree": {
            "topology": "four parallel copies of a two-level balanced H-tree",
            "root": [123.28, 194.0],
            "pair_branches": {"left": [103.96, 178.0], "right": [142.60, 178.0]},
            "leaves": [
                {"channel": 3, "branch": "left", "point": [94.30, 169.0]},
                {"channel": 2, "branch": "left", "point": [113.62, 169.0]},
                {"channel": 1, "branch": "right", "point": [132.94, 169.0]},
                {"channel": 0, "branch": "right", "point": [152.26, 169.0]},
            ],
            "phase_bus_order": ["phase_0", "phase_90", "phase_270", "phase_180"],
            "bundle_track_pitch": 0.80,
            "preferred_layers": {"horizontal": "metal4", "vertical": "metal3"},
            "wire_width": 0.50,
            "shield": "VGND",
            "max_drawn_leaf_mismatch_percent": 0.10,
            "max_extracted_leaf_skew_ps": 100.0,
            "equal_via_sites": ["via2", "via3"],
            "allow_meanders": False,
            "allow_u_turns": False,
        },
        "shared_support": {
            "tail_reference": "64 um / 1.00 um shared diode-connected NMOS reference",
            "tail_reference_status": "measured folding reserved; diode strap and DRC/LVS pending",
            "tail_reference_selected_folding": support["selected_candidate"],
            "tail_reference_bbox": support["selected_placement_bbox_um"],
            "tail_reference_orientation": support["placement_orientation"],
            "vcm": "reuse V2-qualified VCM topology only after V3 loading check",
            "power_partition": "1.8 V only; Tiny Tapeout VAPWR is unused",
            "next_gate": "draw/extract the diode strap, place VCM/decap, and route one selector without moving channel axes",
        },
        "net_classes": {
            "element_inputs": {"layers": ["metal3", "metal4"], "width": 0.40, "max_direction_reversals": 0, "max_pin_to_macro_entry_length": 8.0},
            "local_vector_core": {"layers": ["locali", "metal1", "metal2", "metal3"], "width_upper_metal": 0.40, "max_direction_reversals": 0, "leave_channel_macro": False},
            "differential_sum_and_output": {"layers": ["metal3", "metal4"], "width": 0.80, "max_direction_reversals": 0, "matched_route_topology": True},
            "phase_distribution": {"layers": ["metal3", "metal4"], "width": 0.50, "max_direction_reversals": 0, "branch_only_vias": True},
            "static_vector_control": {"layers": ["metal2", "metal3"], "width": 0.40, "max_direction_reversals": 0, "shield": "VGND", "signals_static_during_measurement": True},
        },
        "global_route_invariants": {
            "floating_stubs_allowed": False,
            "orphan_vias_allowed": False,
            "same_net_dead_end_landings_allowed": False,
            "unrelated_routes_inside_passive_keepouts_allowed": False,
            "length_matching_with_u_bends_allowed": False,
            "via_stacks_only_at_endpoints_or_named_branch_points": True,
            "route_regeneration_starts_from_clean_placement": True,
            "empty_area_policy": "leave quiet; add only required foundry density or extracted grounded shielding",
        },
        "promotion_gates": [
            "synthesized selector/control cells fit reserved regions at signoff density",
            "shared tail reference and VCM PCells are measured and placed",
            "transistor-level channel placement preserves the exact group centroids",
            "Magic DRC and independent KLayout flat-rule checks pass",
            "LVS proves all four channels and both branched output nets",
            "distributed-RC extraction closes phase-tree, channel, and output mismatch",
            "post-layout PVT, settling, spur, loading, noise, and independent calibration gates pass",
        ],
    }


def main() -> None:
    data = build_floorplan()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
