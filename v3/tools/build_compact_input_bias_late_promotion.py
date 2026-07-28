#!/usr/bin/env python3
"""Place the compact input-bias resistor beneath the guarded V3 channel."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PCELLS = ROOT / "v3/layout/input_bias_pcell_catalog.json"
DUMMIES = ROOT / "v3/layout/channel_edge_dummies_late_promotion.json"
EDGE_GATE = ROOT / "v3/evidence/channel_edge_dummy_late_promotion_gate.json"
OUTPUT = ROOT / "v3/layout/compact_input_bias_late_promotion.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict[str, object]:
    gate = json.loads(EDGE_GATE.read_text(encoding="utf-8"))
    dummies = json.loads(DUMMIES.read_text(encoding="utf-8"))
    if gate["status"] != "pass":
        raise RuntimeError("edge-dummy gate must pass before input-bias placement")

    center = [13.14, -14.39]
    resistor = {
        "name": "RINPUT_BIAS",
        "catalog_cell": "XIN_0P35_L17P36_G",
        "model": "sky130_fd_pr__res_xhigh_po_0p35",
        "width_um": 0.35,
        "length_um": 17.36,
        "guard": 1,
        "orientation": "R0",
        "center": center,
        "bbox": [12.135, -25.98, 14.145, -2.8],
        "terminals": {
            "B": [13.14, -25.715],
            "R1": [13.14, -3.805],
            "R2": [13.14, -24.975],
        },
        "nets": {"B": "VGND", "R1": "ref", "R2": "element_input"},
    }
    old_guard = dummies["shared_guard_bbox"]
    guard = [float(old_guard[0]), -27.0, float(old_guard[2]), float(old_guard[3])]
    return {
        "schema_version": 1,
        "units": "um",
        "status": "exact connected compact input-bias placement contract",
        "resistor": resistor,
        "shared_guard_bbox": guard,
        "routes": {
            "element_input": [
                {"layer": "metal2", "from": resistor["terminals"]["R2"], "to": [12.44, -24.975], "width_um": 0.30},
                {"layer": "metal2", "from": [12.44, -24.975], "to": [12.44, 5.60], "width_um": 0.40},
            ],
            "ref": [
                {"layer": "metal2", "from": resistor["terminals"]["R1"], "to": [13.84, -3.805], "width_um": 0.30},
                {"layer": "metal2", "from": [13.84, -3.805], "to": [13.84, 5.60], "width_um": 0.30},
            ],
            "body_ground": [
                {"layer": "metal2", "from": resistor["terminals"]["B"], "to": [6.98, -25.715], "width_um": 0.40},
                {"layer": "metal2", "from": [6.98, -27.0], "to": [6.98, float(old_guard[1])], "width_um": 0.40},
            ],
        },
        "ports": {
            "element_input": {"layer": "metal2", "point": [12.44, -24.975]},
            "ref": {"layer": "metal2", "point": [13.84, 108.80]},
            "vbias": {"layer": "metal2", "point": [13.14, 108.80]},
        },
        "constraints": {
            "phase_tree_geometry_frozen": True,
            "edge_dummy_geometry_frozen": True,
            "no_m3_or_m4_added_to_input_path": True,
            "no_input_route_u_turns": True,
            "resistor_to_bottom_dummy_bbox_gap_um": 2.20,
            "signal_ref_vertical_spacing_um": 1.40,
            "signal_and_ref_join_existing_spines_at_their_existing_bottom_end": True,
            "resistor_connects_element_input_to_ref_vcm": True,
        },
        "urpm_width_repair": {
            "layer": "URPM",
            "bbox": [12.49, -25.35, 13.79, -3.43],
            "reason": "the 0.35 um resistor PCell needs the same 1.30 um parent-mask hint already proven by the earlier compact-input pilot",
        },
        "provenance": {
            "generator": "v3/tools/build_compact_input_bias_late_promotion.py",
            "generator_sha256": sha256(Path(__file__)),
            "pcell_catalog_sha256": sha256(PCELLS),
            "edge_dummy_manifest_sha256": sha256(DUMMIES),
            "edge_dummy_gate_sha256": sha256(EDGE_GATE),
        },
    }


def main() -> None:
    data = build()
    OUTPUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
