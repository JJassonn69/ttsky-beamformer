#!/usr/bin/env python3
"""Build the exact top/bottom edge-dummy contract for one V3 channel.

The routed phase-tree pilot proved that the earlier dimension-only proposal
for complete left/right dummy columns is no longer geometrically honest: the
six named side trunks consume that pitch band.  The exact implementation uses
device-type-matched boundary rows instead.  Three tail devices reproduce the
bottom-facing environment and six switch devices reproduce the top-facing
environment.  Every dummy terminal is tied to VGND and the shared substrate
guard is extended around both rows.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3" / "layout" / "channel_matrix_placement.json"
UNIT = ROOT / "v3" / "layout" / "vector_unit_placement.json"
TREES = ROOT / "v3" / "layout" / "group_phase_trees.json"
PHYSICAL_GATE = ROOT / "v3" / "evidence" / "channel_phase_tree_physical_gate.json"
RC_GATE = ROOT / "v3" / "evidence" / "channel_phase_tree_rc.json"
DEFAULT_OUTPUT = ROOT / "v3" / "layout" / "channel_edge_dummies.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def translated_device(
    source: dict[str, Any], *, name: str, dx: float, dy: float,
) -> dict[str, Any]:
    def point(value: list[float]) -> list[float]:
        return [round(value[0] + dx, 6), round(value[1] + dy, 6)]

    return {
        **source,
        "name": name,
        "center": point(source["center"]),
        "bbox": [
            round(source["bbox"][0] + dx, 6),
            round(source["bbox"][1] + dy, 6),
            round(source["bbox"][2] + dx, 6),
            round(source["bbox"][3] + dy, 6),
        ],
        "terminals": {
            terminal: [point(item) for item in points]
            for terminal, points in source["terminals"].items()
        },
        "nets": {"B": "VGND", "D": "VGND", "G": "VGND", "S": "VGND"},
        "dummy_role": "electrically-inert process edge replica",
    }


def build() -> dict[str, Any]:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    unit = json.loads(UNIT.read_text(encoding="utf-8"))
    phase_gate = json.loads(PHYSICAL_GATE.read_text(encoding="utf-8"))
    rc_gate = json.loads(RC_GATE.read_text(encoding="utf-8"))
    if phase_gate["status"] != "pass" or rc_gate["status"] != "pass":
        raise RuntimeError("both phase-tree physical and distributed-RC gates must pass")

    templates = {item["name"]: item for item in unit["devices"]}
    column_origins = [float(value) for value in matrix["matrix"]["column_origins"]]
    devices: list[dict[str, Any]] = []

    # Bottom active tails occupy y=8.0..13.95.  Place an identical row at
    # y=0.8..6.75, retaining 1.25 um of device-bbox separation.
    for column, origin_x in enumerate(column_origins):
        devices.append(translated_device(
            templates["XTAIL"], name=f"XDUMMY_BOTTOM_TAIL_C{column}",
            dx=origin_x, dy=0.8,
        ))

    # The top-facing boundary devices are the PP/NN switch row.  Replicate
    # their exact x/orientation pattern at y=87.8..89.33, safely above the
    # highest M3 phase branch at y=85.85 and below the roots at y=93.05.
    top_dy = 77.1
    for column, origin_x in enumerate(column_origins):
        for name in ("XSW_PP", "XSW_NN"):
            devices.append(translated_device(
                templates[name], name=f"XDUMMY_TOP_{name.removeprefix('XSW_')}_C{column}",
                dx=origin_x, dy=top_dy,
            ))

    bottom_y = devices[0]["terminals"]["D"][0][1]
    top_y = devices[3]["terminals"]["D"][0][1]
    guard = [0.44, 0.0, 15.30, 90.165]
    return {
        "schema_version": 1,
        "units": "um",
        "status": "exact placement contract; physical pilot pending",
        "strategy": {
            "bottom_boundary": "three exact tail PCells, one per active column",
            "top_boundary": "six exact switch PCells matching the upper PP/NN row",
            "lateral_boundary": "continuous shared substrate guard; no transistor columns",
            "retired_assumption": "dimension-only full left/right transistor dummy columns",
            "reason": "the closed six-trunk phase bank occupies the 3.58 um side corridor; forcing transistor columns there would overlap named routing or expand beyond one channel pitch",
            "all_dummy_terminals_tied_to_vgnd": True,
        },
        "devices": devices,
        "ground_collection": {
            "layer": "metal3",
            "width_um": 0.40,
            "bottom_bus_y_um": bottom_y,
            "top_bus_y_um": top_y,
            "bus_x_range_um": [0.44, 15.30],
            "one_via2_per_dummy": True,
            "guard_contacts_at_both_bus_ends": True,
        },
        "shared_guard_bbox": guard,
        "keepouts": {
            "highest_existing_m3_phase_branch_y_um": 85.85,
            "phase_root_y_um": 93.05,
            "minimum_dummy_to_active_device_bbox_gap_um": 1.25,
            "minimum_top_dummy_to_phase_branch_bbox_gap_um": 1.75,
        },
        "expected_extraction": {
            "active_nmos": 105,
            "dummy_nmos": 9,
            "total_nmos": 114,
            "dummy_types": {"tail_w5p066_l1": 3, "switch_w0p65_l0p15": 6},
            "only_dummy_terminal_net": "VGND",
        },
        "provenance": {
            "generator": "v3/tools/build_channel_edge_dummies.py",
            "generator_sha256": sha256(Path(__file__)),
            "matrix_manifest": "v3/layout/channel_matrix_placement.json",
            "matrix_manifest_sha256": sha256(MATRIX),
            "unit_manifest": "v3/layout/vector_unit_placement.json",
            "unit_manifest_sha256": sha256(UNIT),
            "phase_tree_manifest": "v3/layout/group_phase_trees.json",
            "phase_tree_manifest_sha256": sha256(TREES),
            "phase_tree_physical_gate_sha256": sha256(PHYSICAL_GATE),
            "phase_tree_rc_gate_sha256": sha256(RC_GATE),
        },
    }


def main() -> None:
    data = build()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
