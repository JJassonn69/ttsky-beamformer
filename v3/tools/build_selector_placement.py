#!/usr/bin/env python3
"""Build the V3 per-channel vector-selector standard-cell placement skeleton."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FLOORPLAN = ROOT / "v3" / "layout" / "floorplan.json"
DEFAULT_OUTPUT = ROOT / "v3" / "layout" / "selector_placement.json"
CELL_ROOT = ROOT / "third_party" / "sky130_fd_sc_hd_cells"
CELL_FILES = {
    "mux2": CELL_ROOT / "sky130_fd_sc_hd__mux2_1.lef",
    "and2": CELL_ROOT / "sky130_fd_sc_hd__and2_1.lef",
    "and2b": CELL_ROOT / "sky130_fd_sc_hd__and2b_1.lef",
    "tap": CELL_ROOT / "sky130_fd_sc_hd__tapvpwrvgnd_1.lef",
}
SIZE_RE = re.compile(r"^\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;", re.MULTILINE)
ROW_HEIGHT = 2.72
ROW_COUNT = 9


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cell_catalog() -> dict[str, dict[str, Any]]:
    result = {}
    for role, path in CELL_FILES.items():
        text = path.read_text(encoding="utf-8")
        match = SIZE_RE.search(text)
        if not match:
            raise RuntimeError(f"missing LEF SIZE in {path}")
        result[role] = {
            "lef": str(path.relative_to(ROOT)),
            "lef_sha256": sha256(path),
            "width_um": float(match.group(1)),
            "height_um": float(match.group(2)),
        }
    if any(abs(cell["height_um"] - ROW_HEIGHT) > 1e-9 for cell in result.values()):
        raise RuntimeError("selector cell library does not share a 2.72 um row height")
    return result


def add_instance(
    instances: list[dict[str, Any]],
    cells: dict[str, dict[str, Any]],
    name: str,
    role: str,
    x: float,
    y: float,
    row: int,
    orientation: str,
    group: int | None = None,
    connections: dict[str, str] | None = None,
) -> float:
    width = cells[role]["width_um"]
    instances.append(
        {
            "name": name,
            "cell_role": role,
            "group": group,
            "row": row,
            "orientation": orientation,
            "connections": connections or {},
            "bbox": [round(x, 3), round(y, 3), round(x + width, 3), round(y + ROW_HEIGHT, 3)],
        }
    )
    return x + width


def build_channel_template(cells: dict[str, dict[str, Any]]) -> dict[str, Any]:
    selector_width = 15.74
    selector_height = 34.0
    used_height = ROW_COUNT * ROW_HEIGHT
    lower_margin = (selector_height - used_height) / 2.0
    instances: list[dict[str, Any]] = []
    cell_start_x = 3.30

    def row_y(row: int) -> float:
        return lower_margin + row * ROW_HEIGHT

    def orientation(row: int) -> str:
        return "R0" if row % 2 == 0 else "MX"

    # One channel-level gate generates ENABLE = channel_enable & !blank.
    x = cell_start_x
    x = add_instance(instances, cells, "TAP_ENABLE", "tap", x, row_y(0), 0, orientation(0))
    add_instance(
        instances, cells, "ENABLE_ANDNOT", "and2b", x, row_y(0), 0, orientation(0),
        connections={"A_N": "mixers_blank", "B": "channel_enable", "X": "group_enable"},
    )

    for group in range(4):
        first_row = 1 + 2 * group
        second_row = first_row + 1

        # First row: the two first-level 2:1 muxes. One chooses I+/Q+;
        # the other chooses I-/Q-. A tap every two rows bounds well distance.
        x = cell_start_x
        x = add_instance(instances, cells, f"TAP_G{group}", "tap", x, row_y(first_row), first_row, orientation(first_row), group)
        x = add_instance(
            instances, cells, f"G{group}_MUX_POS", "mux2", x, row_y(first_row), first_row,
            orientation(first_row), group,
            {"A0": "phase_0", "A1": "phase_90", "S": f"group{group}_bit0", "X": f"group{group}_positive_axis"},
        )
        add_instance(
            instances, cells, f"G{group}_MUX_NEG", "mux2", x, row_y(first_row), first_row,
            orientation(first_row), group,
            {"A0": "phase_180", "A1": "phase_270", "S": f"group{group}_bit0", "X": f"group{group}_negative_axis"},
        )

        # Second row: final axis mux and complementary output gates.
        x = cell_start_x
        x = add_instance(
            instances, cells, f"G{group}_MUX_AXIS", "mux2", x, row_y(second_row), second_row,
            orientation(second_row), group,
            {"A0": f"group{group}_positive_axis", "A1": f"group{group}_negative_axis", "S": f"group{group}_bit1", "X": f"group{group}_selected_phase"},
        )
        x = add_instance(
            instances, cells, f"G{group}_LO_P_AND", "and2", x, row_y(second_row), second_row,
            orientation(second_row), group,
            {"A": f"group{group}_selected_phase", "B": "group_enable", "X": f"group{group}_lo_p"},
        )
        add_instance(
            instances, cells, f"G{group}_LO_N_ANDNOT", "and2b", x, row_y(second_row), second_row,
            orientation(second_row), group,
            {"A_N": f"group{group}_selected_phase", "B": "group_enable", "X": f"group{group}_lo_n"},
        )

    cell_area = sum(
        cells[item["cell_role"]]["width_um"] * cells[item["cell_role"]]["height_um"]
        for item in instances
    )
    return {
        "bbox": [0.0, 0.0, selector_width, selector_height],
        "row_height_um": ROW_HEIGHT,
        "row_count": ROW_COUNT,
        "row_lower_margin_um": lower_margin,
        "instances": instances,
        "cell_area_um2": cell_area,
        "reserved_area_um2": selector_width * selector_height,
        "raw_cell_utilization_percent": 100.0 * cell_area / (selector_width * selector_height),
        "route_reservations": {
            "phase_spine": {
                "bbox": [0.20, 0.0, 2.95, selector_height],
                "layer": "metal3",
                "tracks": ["phase_0", "phase_90", "phase_180", "phase_270"],
                "wire_width_um": 0.50,
                "note": "upper-metal spine is separate from standard-cell local interconnect",
            },
            "static_code_entry": {
                "bbox": [12.20, 0.0, 15.74, selector_height],
                "preferred_layer": "metal2",
                "tracks": [f"group{group}_bit{bit}" for group in range(4) for bit in range(2)],
                "note": "tracks may cross cell footprints on legal upper-metal resources; detailed pin access remains a routing gate",
            },
        },
        "logic_contract": {
            "axis_code": {"00": "phase_0", "01": "phase_90", "10": "phase_180", "11": "phase_270"},
            "lo_p": "selected_phase AND channel_group_enable",
            "lo_n": "NOT selected_phase AND channel_group_enable",
            "channel_group_enable": "channel_enable AND NOT mixers_blank",
        },
    }


def translated_bbox(bbox: list[float], dx: float, dy: float) -> list[float]:
    return [round(bbox[0] + dx, 3), round(bbox[1] + dy, 3), round(bbox[2] + dx, 3), round(bbox[3] + dy, 3)]


def build_selector_placement() -> dict[str, Any]:
    floorplan = json.loads(FLOORPLAN.read_text(encoding="utf-8"))
    cells = cell_catalog()
    template = build_channel_template(cells)
    channels = []
    for channel in floorplan["channels"]:
        bbox = channel["selector_bbox"]
        dx, dy = bbox[0], bbox[1]
        channels.append(
            {
                "channel": channel["index"],
                "bbox": bbox,
                "instances": [
                    {**item, "bbox": translated_bbox(item["bbox"], dx, dy)}
                    for item in template["instances"]
                ],
                "phase_spine_bbox": translated_bbox(template["route_reservations"]["phase_spine"]["bbox"], dx, dy),
                "static_code_entry_bbox": translated_bbox(template["route_reservations"]["static_code_entry"]["bbox"], dx, dy),
            }
        )
    return {
        "schema_version": 1,
        "status": "review placement skeleton; no routed DEF/GDS or physical signoff",
        "provenance": {
            "generator": "v3/tools/build_selector_placement.py",
            "floorplan": "v3/layout/floorplan.json",
            "floorplan_sha256": sha256(FLOORPLAN),
        },
        "cell_catalog": cells,
        "channel_template": template,
        "channels": channels,
        "constraints": {
            "maximum_raw_cell_utilization_percent": 45.0,
            "maximum_row_width_um": 12.60,
            "one_tap_at_least_every_rows": 2,
            "all_channels_identical": True,
            "channel_macro_orientation": "R0",
            "phase_spines_balanced": True,
            "detailed_routing_authorized": False,
        },
        "next_gate": [
            "synthesize the complete control core and compare mapped logic with this template",
            "route one selector against real LEF pin obstructions",
            "check power-rail abutment, tap spacing, antenna, DRC, and extracted phase skew",
        ],
    }


def main() -> None:
    data = build_selector_placement()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": data["status"],
        "instances_per_channel": len(data["channel_template"]["instances"]),
        "raw_cell_utilization_percent": data["channel_template"]["raw_cell_utilization_percent"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
