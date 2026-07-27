#!/usr/bin/env python3
"""Place the compact V3 input-bias resistor under a grounded phase shield."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "v3" / "layout" / "input_bias_pcell_catalog.json"
DUMMIES = ROOT / "v3" / "layout" / "channel_edge_dummies.json"
DUMMY_GATE = ROOT / "v3" / "evidence" / "channel_edge_dummy_physical_gate.json"
EQUIVALENCE = ROOT / "v3" / "evidence" / "input_bias_equivalence.json"
DEFAULT_OUTPUT = ROOT / "v3" / "layout" / "compact_input_bias_placement.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def translated(point: list[float], center: list[float]) -> list[float]:
    return [round(point[0] + center[0], 6), round(point[1] + center[1], 6)]


def build() -> dict[str, Any]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    dummy_gate = json.loads(DUMMY_GATE.read_text(encoding="utf-8"))
    equivalence = json.loads(EQUIVALENCE.read_text(encoding="utf-8"))
    if catalog["status"] != "pass" or dummy_gate["status"] != "pass" or equivalence["status"] != "pass":
        raise RuntimeError("compact PCell, dummy physical, and electrical-equivalence gates must pass")
    name = catalog["selected_candidate"]
    cell = catalog["cells"][name]
    center = [17.47, 8.91]
    ports = {
        terminal: translated(values[0]["point_um"], center)
        for terminal, values in cell["ports"].items()
    }
    bbox = [
        round(center[0] + cell["bbox_um"][0], 6),
        round(center[1] + cell["bbox_um"][1], 6),
        round(center[0] + cell["bbox_um"][2], 6),
        round(center[1] + cell["bbox_um"][3], 6),
    ]
    shield = [16.01, -2.50, 19.32, 20.70]
    return {
        "schema_version": 1,
        "units": "um",
        "status": "exact compact placement and shielding contract; physical pilot pending",
        "resistor": {
            "name": "RINPUT_BIAS",
            "catalog_cell": name,
            "model": "sky130_fd_pr__res_xhigh_po_0p35",
            "width_um": 0.35,
            "length_um": 17.36,
            "guard": 1,
            "center": center,
            "bbox": bbox,
            "orientation": "R0",
            "terminals": ports,
            "nets": {"R1": "vcm", "R2": "element_input", "B": "VGND"},
        },
        "terminal_routes": [
            {"net": "vcm", "layer": "metal2", "from": ports["R1"], "to": [19.05, ports["R1"][1]], "width_um": 0.30},
            {"net": "element_input", "layer": "metal2", "from": ports["R2"], "to": [19.05, ports["R2"][1]], "width_um": 0.30},
        ],
        "ports": {
            "vcm": {"point": [19.05, ports["R1"][1]], "layer": "metal2"},
            "element_input": {"point": [19.05, ports["R2"][1]], "layer": "metal2"},
            "VGND": {"point": [15.30, 3.775], "layer": "metal3"},
        },
        "ground_shield": {
            "bbox": shield,
            "layer": "metal3",
            "net": "VGND",
            "join": "one narrow M3 bridge at y=3.775 joins the shield x=15.86 to the exact channel VGND bus x=15.30; one named Via-2 joins the guarded resistor body to the shield",
            "covers_phase_trunks_x_um": [16.52, 18.47],
            "top_clearance_to_lowest_m3_phase_branch_um": 0.95,
        },
        "urpm_width_repair": {
            "bbox": [16.82, -2.05, 18.12, 19.87],
            "layer": "URPM",
            "reason": "the characterized 0.35 um PCell emits a 0.75 um derived URPM strip; the shuttle direct deck requires 1.27 um minimum. A 1.30 um parent mask hint fixes only the implant width and does not change xpolyres geometry.",
        },
        "placement_rationale": {
            "old_guarded_bbox_um": [3.07, 76.32],
            "new_guarded_bbox_um": [cell["width_um"], cell["height_um"]],
            "new_height_reduction_percent": 100.0 * (1.0 - cell["height_um"] / 76.32),
            "uses_only_existing_channel_pitch": bbox[2] <= 19.32,
            "global_y_when_channel_bottom_is_8um": [bbox[1] + 8.0, bbox[3] + 8.0],
            "reason": "place near the analog input, below the first phase branch, and screen the overpassing M4 clocks with grounded M3 instead of accepting direct clock-to-input-resistor coupling",
        },
        "constraints": {
            "no_phase_root_moves": True,
            "no_dummy_moves": True,
            "no_m3_phase_overlap": shield[3] <= 21.65,
            "minimum_wide_m3_shield_to_active_m3_spacing_um": 0.40,
            "no_signal_via_through_shield": True,
            "one_body_ground_transition": True,
            "one_shield_ground_transition": True,
            "no_u_turns": True,
            "no_floating_vias": True,
        },
        "provenance": {
            "generator": "v3/tools/build_compact_input_bias_placement.py",
            "generator_sha256": sha256(Path(__file__)),
            "pcell_catalog_sha256": sha256(CATALOG),
            "edge_dummy_manifest_sha256": sha256(DUMMIES),
            "edge_dummy_gate_sha256": sha256(DUMMY_GATE),
            "electrical_equivalence_sha256": sha256(EQUIVALENCE),
        },
    }


def main() -> None:
    data = build()
    DEFAULT_OUTPUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": data["status"], "resistor": data["resistor"], "ground_shield": data["ground_shield"], "constraints": data["constraints"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
