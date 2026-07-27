#!/usr/bin/env python3
"""Build edge dummies around the frozen late-promotion phase-tree channel."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3/layout/channel_matrix_late_promotion.json"
UNIT = ROOT / "v3/layout/vector_unit_late_promotion.json"
TREES = ROOT / "v3/layout/group_phase_trees_late_promotion.json"
PHYSICAL_GATE = ROOT / "v3/evidence/channel_phase_tree_late_promotion_gate.json"
RC_GATE = ROOT / "v3/evidence/channel_phase_tree_late_promotion_rc.json"
OUTPUT = ROOT / "v3/layout/channel_edge_dummies_late_promotion.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def translated_device(
    source: dict[str, Any], *, name: str, dx: float, dy: float,
) -> dict[str, Any]:
    def point(value: list[float]) -> list[float]:
        return [round(float(value[0]) + dx, 6), round(float(value[1]) + dy, 6)]

    return {
        **source,
        "name": name,
        "center": point(source["center"]),
        "bbox": [
            round(float(source["bbox"][0]) + dx, 6),
            round(float(source["bbox"][1]) + dy, 6),
            round(float(source["bbox"][2]) + dx, 6),
            round(float(source["bbox"][3]) + dy, 6),
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
    physical_gate = json.loads(PHYSICAL_GATE.read_text(encoding="utf-8"))
    rc_gate = json.loads(RC_GATE.read_text(encoding="utf-8"))
    if physical_gate["status"] != "pass" or rc_gate["status"] != "pass":
        raise RuntimeError("late-promotion phase-tree physical and RC gates must pass")

    templates = {item["name"]: item for item in unit["devices"]}
    column_origins = [float(value) for value in matrix["matrix"]["column_origins"]]
    devices: list[dict[str, Any]] = []

    # The late-promotion sig/vbias/ref M1 buses occupy y=6.05/6.75/7.45.
    # The old y=0.8 dummy origin put the tail gate metal into that band and
    # extraction correctly reported sig/vbias/VGND shorts.  Drop the row far
    # enough that its complete PCell bbox ends at y=5.35.
    bottom_dy = -0.6
    for column, origin_x in enumerate(column_origins):
        devices.append(translated_device(
            templates["XTAIL"], name=f"XDUMMY_BOTTOM_TAIL_C{column}",
            dx=origin_x, dy=bottom_dy,
        ))

    # Keep the top dummy ground collection above the frozen M4 root bank.  A
    # row inside the old 106.5..112.99 band would put grounded M3 underneath
    # the g4/g8 phase roots and alter their parasitic load before extraction.
    top_dy = 102.6
    for column, origin_x in enumerate(column_origins):
        for name in ("XSW_PP", "XSW_NN"):
            devices.append(translated_device(
                templates[name], name=f"XDUMMY_TOP_{name.removeprefix('XSW_')}_C{column}",
                dx=origin_x, dy=top_dy,
            ))

    bottom_bus_y = float(devices[0]["terminals"]["D"][0][1])
    top_bus_y = float(devices[3]["terminals"]["D"][0][1])
    active = matrix["active_array_bbox"]
    guard = [
        round(float(active[0]) + 0.05, 6),
        -1.4,
        round(float(active[2]) - 0.05, 6),
        round(max(float(item["bbox"][3]) for item in devices) + 0.835, 6),
    ]
    phase_root_y = max(
        float(value["root"][1])
        for value in json.loads(TREES.read_text(encoding="utf-8"))["trees"].values()
    )
    return {
        "schema_version": 1,
        "units": "um",
        "status": "exact late-promotion edge-dummy placement contract",
        "strategy": {
            "bottom_boundary": "three exact tail PCells, one per active column",
            "top_boundary": "six exact switch PCells above the frozen M4 root bank",
            "lateral_boundary": "continuous shared substrate guard; no transistor columns",
            "all_dummy_terminals_tied_to_vgnd": True,
            "phase_tree_geometry_frozen": True,
            "reason": "separating the top grounded M3 bus from the M3/M4 phase-root bank avoids an avoidable clock-to-ground capacitance increase",
        },
        "devices": devices,
        "ground_collection": {
            "layer": "metal3",
            "width_um": 0.40,
            "bottom_bus_y_um": bottom_bus_y,
            "top_bus_y_um": top_bus_y,
            "bus_x_range_um": [guard[0], guard[2]],
            "ground_spine_x_um": 6.98,
            "guard_contacts_at_both_bus_ends": True,
        },
        "shared_guard_bbox": guard,
        "keepouts": {
            "phase_root_y_um": phase_root_y,
            "top_dummy_bbox_bottom_y_um": min(float(item["bbox"][1]) for item in devices[3:]),
            "minimum_phase_root_to_top_dummy_bbox_gap_um": round(
                min(float(item["bbox"][1]) for item in devices[3:]) - phase_root_y, 6
            ),
            "minimum_dummy_to_active_device_bbox_gap_um": round(
                float(active[1]) - max(float(item["bbox"][3]) for item in devices[:3]), 6
            ),
            "minimum_bottom_dummy_to_sig_bus_gap_um": round(
                6.05 - max(float(item["bbox"][3]) for item in devices[:3]), 6
            ),
        },
        "expected_extraction": {
            "active_nmos": 105,
            "dummy_nmos": 9,
            "total_nmos": 114,
            "dummy_types": {"tail_w5p07_l1": 3, "switch_w0p65_l0p15": 6},
            "only_dummy_terminal_net": "VGND",
        },
        "provenance": {
            "generator": "v3/tools/build_channel_edge_dummies_late_promotion.py",
            "generator_sha256": sha256(Path(__file__)),
            "matrix_manifest": str(MATRIX.relative_to(ROOT)),
            "matrix_manifest_sha256": sha256(MATRIX),
            "unit_manifest": str(UNIT.relative_to(ROOT)),
            "unit_manifest_sha256": sha256(UNIT),
            "phase_tree_manifest": str(TREES.relative_to(ROOT)),
            "phase_tree_manifest_sha256": sha256(TREES),
            "phase_tree_physical_gate_sha256": sha256(PHYSICAL_GATE),
            "phase_tree_rc_gate_sha256": sha256(RC_GATE),
        },
    }


def main() -> None:
    data = build()
    OUTPUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
