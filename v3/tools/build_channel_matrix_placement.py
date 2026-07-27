#!/usr/bin/env python3
"""Build the authoritative placement and local-LO route contract for one V3 channel.

This stage places fifteen already-closed vector units in the selected 3x5
common-centroid assignment.  It also fixes the first routing hierarchy: each
unit's two LON gate breakouts merge on Metal 3 and its crossing LOP pair merges
on Metal 4.  Group-level 1/2/4/8 fanout remains a later physical pilot.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "v3" / "layout" / "vector_unit_placement.json"
UNIT_GATE = ROOT / "v3" / "evidence" / "vector_unit_physical_gate.json"
DEFAULT_OUTPUT = ROOT / "v3" / "layout" / "channel_matrix_placement.json"

CHANNEL_BBOX = [0.0, 0.0, 19.32, 112.99]
GROUP_MATRIX_TOP_TO_BOTTOM = [
    [8, 8, 8],
    [4, 8, 4],
    [2, 1, 2],
    [4, 8, 4],
    [8, 8, 8],
]
ORIENTATION_MATRIX_TOP_TO_BOTTOM = [
    ["R0", "R0", "R0"],
    ["R0", "R0", "R0"],
    ["R0", "R0", "MY"],
    ["MY", "MY", "MY"],
    ["MY", "MY", "MY"],
]

# Origins refer to the exact vector-unit coordinate system.  Its bbox is
# [-0.85, 0.0, 3.71, 12.365], so these values give a 0.39 um outer margin,
# 0.64 um between adjacent unit bboxes, and 7.635 um row routing channels.
# The wider vertical channel is intentional: two output-collection tracks are
# reserved before the phase trees, avoiding the unroutable phase-first result.
COLUMN_ORIGINS = [1.24, 6.44, 11.64]
ROW_ORIGINS_TOP_TO_BOTTOM = [88.0, 68.0, 48.0, 28.0, 8.0]
UNIT_MIRROR_AXIS_X = 1.43
LOCAL_LON_LEVEL_OFFSET = 13.15
LOCAL_LOP_LEVEL_OFFSET = 13.95
# 0.85 um leaves 0.34 um between the 0.62 um-wide Via-3 M3 landing on the
# other LO polarity and the 0.40 um LON escape.  The direct shuttle deck
# requires 0.30 um; the earlier 0.70 um trial left only 0.19 um.
LOW_PORT_INWARD_ESCAPE = 0.85


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def transform_point(point: list[float], origin: list[float], orientation: str) -> list[float]:
    x, y = point
    if orientation == "MY":
        x = 2.0 * UNIT_MIRROR_AXIS_X - x
    elif orientation != "R0":
        raise ValueError(f"unsupported unit orientation {orientation}")
    return [round(origin[0] + x, 6), round(origin[1] + y, 6)]


def segment(start: list[float], stop: list[float], layer: str, width: float) -> dict[str, Any]:
    if start[0] != stop[0] and start[1] != stop[1]:
        raise ValueError(f"non-Manhattan matrix segment: {start} -> {stop}")
    return {"from": start, "to": stop, "layer": layer, "width_um": width}


def local_merge(
    net: str,
    ports: list[list[float]],
    root: list[float],
    layer: str,
) -> dict[str, Any]:
    top = max(ports, key=lambda point: point[1])
    lower = min(ports, key=lambda point: point[1])
    centre_x = root[0]
    inward_x = round(
        lower[0] + (LOW_PORT_INWARD_ESCAPE if lower[0] < centre_x else -LOW_PORT_INWARD_ESCAPE),
        6,
    )
    lower_escape = [inward_x, lower[1]]
    lower_level = [inward_x, root[1]]
    top_level = [top[0], root[1]]
    return {
        "net": net,
        "layer": layer,
        "width_um": 0.40,
        "root": root,
        "source_ports": ports,
        "segments": [
            segment(top, top_level, layer, 0.40),
            segment(top_level, root, layer, 0.40),
            segment(lower, lower_escape, layer, 0.40),
            segment(lower_escape, lower_level, layer, 0.40),
            segment(lower_level, root, layer, 0.40),
        ],
        "via3_at_source_ports": ports if layer == "metal4" else [],
        "lower_port_escape_um": LOW_PORT_INWARD_ESCAPE,
    }


def build(
    *,
    column_origins: list[float] | None = None,
    unit_path: Path = UNIT,
    unit_gate_path: Path = UNIT_GATE,
) -> dict[str, Any]:
    columns = list(COLUMN_ORIGINS if column_origins is None else column_origins)
    if len(columns) != 3:
        raise ValueError("the channel matrix requires exactly three column origins")
    if not (columns[0] < columns[1] < columns[2]):
        raise ValueError("column origins must be strictly increasing")
    if abs((columns[1] - columns[0]) - (columns[2] - columns[1])) > 1e-9:
        raise ValueError("column origins must retain equal common-centroid pitch")
    unit = json.loads(unit_path.read_text(encoding="utf-8"))
    unit_gate = json.loads(unit_gate_path.read_text(encoding="utf-8"))
    if unit_gate["status"] != "pass":
        raise RuntimeError("exact vector-unit physical gate is not closed")
    gate_manifest_sha256 = unit_gate.get("manifest_sha256")
    if gate_manifest_sha256 is None:
        gate_manifest_sha256 = unit_gate.get("sha256", {}).get("manifest")
    if gate_manifest_sha256 != sha256(unit_path):
        raise RuntimeError("vector-unit gate does not match its routing manifest")
    if unit_gate["gds_sha256"] != sha256(ROOT / unit_gate["gds"]):
        raise RuntimeError("vector-unit gate does not match its exact GDS")

    tx0, ty0, tx1, ty1 = [float(value) for value in unit["tile_bbox"]]
    instances = []
    group_roots: dict[str, dict[str, list[dict[str, Any]]]] = {
        str(group): {"lop": [], "lon": []} for group in (1, 2, 4, 8)
    }
    for row, (groups, orientations, origin_y) in enumerate(zip(
        GROUP_MATRIX_TOP_TO_BOTTOM,
        ORIENTATION_MATRIX_TOP_TO_BOTTOM,
        ROW_ORIGINS_TOP_TO_BOTTOM,
    )):
        for column, (group, orientation, origin_x) in enumerate(zip(
            groups, orientations, columns
        )):
            origin = [origin_x, origin_y]
            ports = {
                name: {
                    "point": transform_point(value["point"], origin, orientation),
                    "layer": value["layer"],
                }
                for name, value in unit["boundary_ports"].items()
            }
            centre_x = round(origin_x + UNIT_MIRROR_AXIS_X, 6)
            lon_root = [centre_x, round(origin_y + LOCAL_LON_LEVEL_OFFSET, 6)]
            lop_root = [centre_x, round(origin_y + LOCAL_LOP_LEVEL_OFFSET, 6)]
            local_routes = {
                "lon": local_merge(
                    "lon",
                    [ports["lon_left"]["point"], ports["lon_right"]["point"]],
                    lon_root,
                    "metal3",
                ),
                "lop": local_merge(
                    "lop",
                    [ports["lop_left"]["point"], ports["lop_right"]["point"]],
                    lop_root,
                    "metal4",
                ),
            }
            name = f"U_R{row}_C{column}_G{group}"
            instance = {
                "name": name,
                "row_top_to_bottom": row,
                "column_left_to_right": column,
                "group_weight": group,
                "origin": origin,
                "orientation": orientation,
                "mirror_axis_local_x_um": UNIT_MIRROR_AXIS_X,
                "bbox": [
                    round(origin_x + tx0, 6), round(origin_y + ty0, 6),
                    round(origin_x + tx1, 6), round(origin_y + ty1, 6),
                ],
                "ports": ports,
                "local_lo_routes": local_routes,
            }
            instances.append(instance)
            for net in ("lop", "lon"):
                group_roots[str(group)][net].append({
                    "unit": name,
                    "point": local_routes[net]["root"],
                    "layer": local_routes[net]["layer"],
                })

    active_bbox = [
        min(item["bbox"][0] for item in instances),
        min(item["bbox"][1] for item in instances),
        max(item["bbox"][2] for item in instances),
        max(item["bbox"][3] for item in instances),
    ]
    row_gaps = []
    rows_bottom_to_top = sorted({item["origin"][1] for item in instances})
    for lower, upper in zip(rows_bottom_to_top, rows_bottom_to_top[1:]):
        row_gaps.append([
            active_bbox[0], round(lower + (ty1 - ty0), 6),
            active_bbox[2], upper,
        ])

    return {
        "schema_version": 1,
        "units": "um",
        "status": "exact-unit matrix placement and local LO merge physically closed in row and full-matrix pilots; group H-trees pending",
        "channel_bbox": CHANNEL_BBOX,
        "active_array_bbox": active_bbox,
        "unit_reference": {
            "manifest": str(unit_path.relative_to(ROOT)),
            "manifest_sha256": sha256(unit_path),
            "physical_gate": str(unit_gate_path.relative_to(ROOT)),
            "physical_gate_sha256": sha256(unit_gate_path),
            "gds": unit_gate["gds"],
            "gds_sha256": unit_gate["gds_sha256"],
            "tile_bbox": unit["tile_bbox"],
        },
        "matrix": {
            "groups_top_to_bottom": GROUP_MATRIX_TOP_TO_BOTTOM,
            "orientations_top_to_bottom": ORIENTATION_MATRIX_TOP_TO_BOTTOM,
            "column_origins": columns,
            "row_origins_top_to_bottom": ROW_ORIGINS_TOP_TO_BOTTOM,
            "column_pitch_um": round(columns[1] - columns[0], 6),
            "row_pitch_um": round(ROW_ORIGINS_TOP_TO_BOTTOM[0] - ROW_ORIGINS_TOP_TO_BOTTOM[1], 6),
            "instances": instances,
        },
        "local_lo_contract": {
            "lon_layer": "metal3",
            "lop_layer": "metal4",
            "reason": "separate layers resolve each unit's diagonal LO crossover without a meander",
            "via3_only_at_lop_source_ports": True,
            "one_root_per_unit_per_polarity": True,
            "group_roots": group_roots,
            "floating_stubs_allowed": False,
            "orphan_vias_allowed": False,
            "u_turns_allowed": False,
        },
        "routing_reservations": {
            "inter_row_channels": row_gaps,
            "bottom_dummy_and_input_band": [0.0, 0.0, CHANNEL_BBOX[2], active_bbox[1]],
            "top_dummy_and_output_band": [0.0, 106.5, CHANNEL_BBOX[2], CHANNEL_BBOX[3]],
            "narrow_column_gaps_are_not_global_trunk_corridors": True,
            "group_tree_strategy": "balanced group-local H-trees; promote only at named roots and branches",
            "local_merge_physical_status": "exact R0/MY row and full 15-unit matrix pilots pass Magic topology plus direct-GDS geometry",
            "group_tree_physical_status": "pending exact route allocation",
            "output_collection_physical_status": "reserved before group-tree planning",
            "edge_dummy_physical_status": "pending exact transistor-row dummy pilot",
            "shared_guard_physical_status": "pending full-channel pilot",
        },
        "constraints": {
            "required_group_counts": {"1": 1, "2": 2, "4": 4, "8": 8},
            "required_common_centroid_unit_pitch": [1.0, 2.0],
            "orientation_balance_required_for_multiunit_groups": True,
            "group_1_orientation_exemption": "single central unit cannot form an inversion pair",
            "minimum_unit_bbox_spacing_um": 0.30,
            "maximum_channel_width_um": 19.32,
            "maximum_channel_height_um": 112.99,
            "maximum_direction_reversals": 0,
        },
        "provenance": {
            "generator": "v3/tools/build_channel_matrix_placement.py",
            "generator_sha256": sha256(Path(__file__)),
        },
    }


def main() -> None:
    data = build()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
