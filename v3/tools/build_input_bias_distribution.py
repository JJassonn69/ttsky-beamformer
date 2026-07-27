#!/usr/bin/env python3
"""Build the reproducible V3 input-bias placement and balanced VCM tree.

The four high-value resistors sit at the same offset on the left of their
channel axes.  Three use the inter-channel gaps and the fourth uses the equal
outer-edge slot.  The resistor-to-input branches and the two-level VCM tree
are therefore identical for all four channels.  Exact guard merging and DRC
remain a one-channel physical-pilot gate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FLOORPLAN = ROOT / "v3" / "layout" / "floorplan.json"
PCELL_CATALOG = ROOT / "v3" / "layout" / "shared_support_pcell_catalog.json"
DEFAULT_OUTPUT = ROOT / "v3" / "layout" / "input_bias_distribution.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def translate(point: list[float], center: list[float]) -> list[float]:
    return [round(center[0] + point[0], 6), round(center[1] + point[1], 6)]


def segment(start: list[float], end: list[float], layer: str, width: float) -> dict[str, Any]:
    return {"from": start, "to": end, "layer": layer, "width_um": width}


def build() -> dict[str, Any]:
    floorplan = json.loads(FLOORPLAN.read_text(encoding="utf-8"))
    catalog = json.loads(PCELL_CATALOG.read_text(encoding="utf-8"))
    if catalog["status"] != "pass":
        raise RuntimeError("V3 shared-support PCell catalogue has not passed")
    pcell = catalog["cells"]["XINPUT_BIAS"]
    pcell_ports = pcell["ports"]
    pitch = float(floorplan["channel_template"]["channel_pitch"])
    channel_centers = [float(channel["center_x"]) for channel in floorplan["channels"]]
    resistor_y = 46.16
    centers = [[round(x - pitch / 2.0, 6), resistor_y] for x in channel_centers]

    resistors = []
    input_routes = []
    vcm_local_routes = []
    for channel, center in zip(floorplan["channels"], centers):
        r1 = translate(pcell_ports["R1"][0]["point_um"], center)
        r2 = translate(pcell_ports["R2"][0]["point_um"], center)
        body = translate(pcell_ports["B"][0]["point_um"], center)
        half_w = float(pcell["width_um"]) / 2.0
        half_h = float(pcell["height_um"]) / 2.0
        bbox = [
            round(center[0] - half_w, 6), round(center[1] - half_h, 6),
            round(center[0] + half_w, 6), round(center[1] + half_h, 6),
        ]
        macro_left = float(channel["macro_bbox"][0])
        input_entry = [float(channel["input_entry"][0]), float(channel["input_entry"][1])]
        local_vcm_entry = [macro_left, r1[1]]
        index = int(channel["index"])
        resistors.append({
            "name": f"RIN_CH{index}",
            "channel": index,
            "pcell": "input_bias_resistor_guarded",
            "center": center,
            "bbox": bbox,
            "orientation": "R0",
            "terminals": {"R1": r1, "R2": r2, "B": body},
            "nets": {"R1": "vcm", "R2": f"element_{index}", "B": "VGND"},
            "guard_integration": "join the resistor substrate guard to the adjacent channel shared guard; prove by exact one-channel DRC/extraction",
        })
        input_routes.append({
            "channel": index,
            "net": f"element_{index}",
            "segments": [
                segment(r2, [r2[0], input_entry[1]], "metal2", 0.40),
                segment([r2[0], input_entry[1]], input_entry, "metal2", 0.40),
            ],
            "contact_stacks": [r2],
        })
        vcm_local_routes.append({
            "channel": index,
            "net": "vcm",
            "segments": [segment(r1, local_vcm_entry, "metal3", 0.50)],
            "resistor_terminal": r1,
            "channel_entry": local_vcm_entry,
            "contact_stacks": [r1],
        })

    # centers are ordered CH0..CH3 from right to left in the floorplan.
    leaves = sorted(
        ({"channel": item["channel"], "point": item["terminals"]["R1"]} for item in resistors),
        key=lambda item: item["point"][0],
    )
    pair_left_x = round((leaves[0]["point"][0] + leaves[1]["point"][0]) / 2.0, 6)
    pair_right_x = round((leaves[2]["point"][0] + leaves[3]["point"][0]) / 2.0, 6)
    root_x = round((pair_left_x + pair_right_x) / 2.0, 6)
    root_y = 90.0
    branch_y = 86.5
    tree_segments = [
        segment([pair_left_x, root_y], [pair_right_x, root_y], "metal3", 0.50),
        segment([pair_left_x, root_y], [pair_left_x, branch_y], "metal3", 0.50),
        segment([pair_right_x, root_y], [pair_right_x, branch_y], "metal3", 0.50),
        segment([leaves[0]["point"][0], branch_y], [leaves[1]["point"][0], branch_y], "metal3", 0.50),
        segment([leaves[2]["point"][0], branch_y], [leaves[3]["point"][0], branch_y], "metal3", 0.50),
    ]
    for leaf in leaves:
        tree_segments.append(segment(
            [leaf["point"][0], branch_y], leaf["point"], "metal3", 0.50
        ))

    return {
        "schema_version": 1,
        "units": "um",
        "status": "constraint placement; exact channel-guard merge, DRC, extraction, and top-level VCM feed pending",
        "provenance": {
            "generator": "v3/tools/build_input_bias_distribution.py",
            "floorplan": "v3/layout/floorplan.json",
            "floorplan_sha256": sha256(FLOORPLAN),
            "measured_pcell_catalog": "v3/layout/shared_support_pcell_catalog.json",
            "measured_pcell_catalog_sha256": sha256(PCELL_CATALOG),
            "measurement_scope": "dimensions and terminal coordinates from V3 PCells generated by pinned Magic 8.3.676 and SKY130 commit 0536d02d875c8f67dd7cca3902ac457e62f20005; exact placed instances still require DRC/extraction",
        },
        "electrical_contract": {
            "input_coupling": "external 100 pF nominal AC coupling",
            "resistor_pcell": "sky130_fd_pr__res_xhigh_po_1p41, w=1.41 um, l=70.5 um, guarded",
            "nominal_resistance_ohm": 100000.0,
            "one_resistor_per_channel": True,
            "r1_net": "vcm",
            "r2_net": "element input",
            "body_net": "VGND",
        },
        "placement": {
            "channel_pitch_um": pitch,
            "resistor_offset_from_channel_axis_um": -pitch / 2.0,
            "resistor_center_y_um": resistor_y,
            "pcell_width_um": pcell["width_um"],
            "pcell_height_um": pcell["height_um"],
            "resistors": resistors,
        },
        "input_branches": input_routes,
        "vcm_distribution": {
            "topology": "two-level center-fed H-tree plus identical short local channel entries",
            "root": [root_x, root_y],
            "pair_roots": [[pair_left_x, branch_y], [pair_right_x, branch_y]],
            "leaves": leaves,
            "segments": tree_segments,
            "local_channel_entries": vcm_local_routes,
            "common_feed": "pending selected VCM capacitor terminal; must join only at the named root",
            "wire_width_um": 0.50,
            "layer": "metal3",
            "allow_meanders": False,
            "allow_u_turns": False,
        },
        "promotion_gates": [
            "four-channel support sweep selects the physical VCM bypass",
            "one complete channel pilot proves resistor/channel guard integration with zero DRC",
            "extraction proves four 100 kohm input-bias paths and no input-to-VCM shorts",
            "distributed RC proves equal input branch and VCM leaf resistance within 1 percent",
        ],
    }


def main() -> None:
    data = build()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
