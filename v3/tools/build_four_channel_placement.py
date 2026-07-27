#!/usr/bin/env python3
"""Build the hash-bound four-copy placement contract for the frozen V3 channel."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CURRENT = ROOT / "v3/CURRENT.json"
CHANNEL_INTERFACE = ROOT / "v3/layout/channel_selector_join_late_promotion.json"
BASE_FLOORPLAN = ROOT / "v3/layout/floorplan.json"
DEFAULT_OUTPUT = ROOT / "v3/layout/four_channel_placement.json"

MACRO_BBOX = [20.0, -7.21, 39.32, 177.0]
PLACED_BOTTOM = 8.0
CHANNEL_INPUT_PINS = {
    0: "ua[0]",
    1: "ua[1]",
    2: "ua[2]",
    3: "ua[3]",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def translated(point: list[float], offset: list[float]) -> list[float]:
    return [round(point[0] + offset[0], 6), round(point[1] + offset[1], 6)]


def build() -> dict[str, Any]:
    current = json.loads(CURRENT.read_text(encoding="utf-8"))
    interface = json.loads(CHANNEL_INTERFACE.read_text(encoding="utf-8"))
    base = json.loads(BASE_FLOORPLAN.read_text(encoding="utf-8"))
    macro = ROOT / current["gds"]
    observed = sha256(macro)
    if observed != current["gds_sha256"]:
        raise RuntimeError("CURRENT.json does not match the frozen channel macro")

    ports = {item["name"]: item for item in interface["top_level_ports"]}
    required = {
        "element_input", "ref", "vbias", "row_outp", "row_outn",
        "phase_0", "phase_90", "phase_180", "phase_270",
        "channel_enable", "mixers_blank", "VPWR", "VGND",
        *(f"group{group}_bit{bit}" for group in range(4) for bit in range(2)),
    }
    missing = sorted(required - ports.keys())
    if missing:
        raise RuntimeError(f"frozen macro interface is incomplete: {missing}")

    y_offset = round(PLACED_BOTTOM - MACRO_BBOX[1], 6)
    instances: list[dict[str, Any]] = []
    for channel in range(4):
        pin_name = CHANNEL_INPUT_PINS[channel]
        pin_x = float(base["analog_pins"][pin_name]["center"][0])
        x_offset = round(pin_x - float(ports["element_input"]["at_um"][0]), 6)
        offset = [x_offset, y_offset]
        bbox = [
            round(MACRO_BBOX[0] + x_offset, 6),
            round(MACRO_BBOX[1] + y_offset, 6),
            round(MACRO_BBOX[2] + x_offset, 6),
            round(MACRO_BBOX[3] + y_offset, 6),
        ]
        transformed_ports = {
            name: {
                **record,
                "at_um": translated(record["at_um"], offset),
            }
            for name, record in ports.items()
        }
        instances.append({
            "name": f"XCHANNEL{channel}",
            "channel": channel,
            "orientation": "R0",
            "translation_um": offset,
            "bbox_um": bbox,
            "analog_input_pin": pin_name,
            "ports": transformed_ports,
        })

    physical_order = sorted(instances, key=lambda item: item["bbox_um"][0])
    gaps = [
        round(right["bbox_um"][0] - left["bbox_um"][2], 6)
        for left, right in zip(physical_order, physical_order[1:])
    ]
    die = base["template"]["die"]
    if any(gap != 0.0 for gap in gaps):
        raise RuntimeError(f"four channels must abut on the 19.32 um pin pitch, got gaps {gaps}")
    if any(
        item["bbox_um"][0] < 0.0 or item["bbox_um"][1] < 0.0
        or item["bbox_um"][2] > die["width"] or item["bbox_um"][3] > die["height"]
        for item in instances
    ):
        raise RuntimeError("four-channel placement exceeds the 2x2 template")

    return {
        "schema_version": 1,
        "status": "placement pilot; no shared conductors added yet",
        "units": "um",
        "top_cell": "v3_four_channel_placement",
        "die_bbox_um": [0.0, 0.0, die["width"], die["height"]],
        "placed_array_bbox_um": [
            physical_order[0]["bbox_um"][0],
            physical_order[0]["bbox_um"][1],
            physical_order[-1]["bbox_um"][2],
            physical_order[-1]["bbox_um"][3],
        ],
        "frozen_macro": {
            "gds": current["gds"],
            "gds_sha256": observed,
            "top_cell": current["top_cell"],
            "bbox_um": MACRO_BBOX,
            "interface_manifest": str(CHANNEL_INTERFACE.relative_to(ROOT)),
            "interface_manifest_sha256": sha256(CHANNEL_INTERFACE),
        },
        "placement_strategy": {
            "orientation": "four R0 vertical columns",
            "reason": "the 19.32 um macro width exactly equals the analog-pin pitch",
            "physical_left_to_right_channels": [item["channel"] for item in physical_order],
            "inter_macro_gaps_um": gaps,
            "input_axes_are_pad_aligned": True,
            "channel_geometry_is_immutable": True,
        },
        "instances": instances,
        "shared_net_plan": {
            "phase": ["phase_0", "phase_90", "phase_180", "phase_270"],
            "bias": ["ref", "vbias"],
            "power": ["VPWR", "VGND"],
            "per_channel_analog_inputs": [f"element_input[{index}]" for index in range(4)],
            "differential_current_sum": ["row_outp", "row_outn"],
            "per_channel_control_bits": [
                f"channel{channel}_group{group}_bit{bit}"
                for channel in range(4) for group in range(4) for bit in range(2)
            ],
            "per_channel_safety_controls": [
                f"channel{channel}_{name}"
                for channel in range(4) for name in ("channel_enable", "mixers_blank")
            ],
        },
        "routing_sequence": [
            "prove exact-abutment DRC and no hierarchy/port aliasing",
            "reserve differential output collection before any shared clock/control trunk",
            "route four straight pad-aligned element inputs as independent matched branches",
            "route shared ref and vbias as symmetric trees",
            "route four phase nets as matched top-corridor trees",
            "route VPWR/VGND straps and substrate continuity",
            "route per-channel control from the digital selector/serial register",
            "extract topology and distributed RC after each net class closes",
        ],
        "constraints": {
            "channel_count": 4,
            "orientation_locked": "R0",
            "macro_mutation_allowed": False,
            "inter_macro_overlap_allowed": False,
            "inter_macro_gap_um": 0.0,
            "maximum_direction_reversals_per_escape": 0,
            "floating_stubs_allowed": False,
            "orphan_vias_allowed": False,
            "shared_routing_added_in_this_stage": False,
        },
        "provenance": {
            "generator": "v3/tools/build_four_channel_placement.py",
            "generator_sha256": sha256(Path(__file__)),
            "current_manifest_sha256": sha256(CURRENT),
        },
    }


def main() -> None:
    result = build()
    DEFAULT_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
