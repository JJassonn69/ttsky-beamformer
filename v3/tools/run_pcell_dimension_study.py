#!/usr/bin/env python3
"""Evaluate V3 15-slice physical feasibility from measured SKY130 PCells.

This consumes the dimension-only Magic catalogue.  It creates no placement,
routing, layout database, or GDS; layout remains blocked by the electrical
gates.  The preferred conservative estimate reserves device-row edge dummies,
top/bottom dummy height, and a shared channel guard-ring margin; a complete
dummy-unit border is retained as a rejected comparison candidate.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/pcell_dimensions"
MAG_DIR = BUILD / "remote_mag"
PARENT = MAG_DIR / "v3_pcell_measurement.mag"
INTERNAL_UNITS_PER_UM = 200.0
CHANNEL_PITCH_UM = 19.32
INTERNAL_DEVICE_GAP_UM = 0.50
UNIT_GAP_UM = 0.50
SHARED_GUARD_MARGIN_UM = 1.00

USE_RE = re.compile(
    r"^use\s+(?P<cell>\S+)\s+(?P<instance>\S+)\n"
    r"(?:.*\n)*?box\s+(?P<x0>-?\d+)\s+(?P<y0>-?\d+)\s+"
    r"(?P<x1>-?\d+)\s+(?P<y1>-?\d+)",
    re.MULTILINE,
)

PARAMETERS = {
    "XGM_U": {"role": "gm", "guard": 0, "width_um": 0.84, "length_um": 0.60, "fingers": 1},
    "XSW_U": {"role": "switch", "guard": 0, "width_um": 0.65, "length_um": 0.15, "fingers": 1},
    "XTAIL_U": {"role": "tail", "guard": 0, "width_um": 5.066666666, "length_um": 1.00, "fingers": 1},
    "XGM_G": {"role": "gm", "guard": 1, "width_um": 0.84, "length_um": 0.60, "fingers": 1},
    "XSW_G": {"role": "switch", "guard": 1, "width_um": 0.65, "length_um": 0.15, "fingers": 1},
    "XTAIL_G": {"role": "tail", "guard": 1, "width_um": 5.066666666, "length_um": 1.00, "fingers": 1},
    "XBIAS_PASS_U": {"role": "bias_pass", "guard": 0, "width_um": 2.0, "length_um": 0.15, "fingers": 1},
    "XBIAS_PULL_U": {"role": "bias_pulldown", "guard": 0, "width_um": 1.0, "length_um": 0.15, "fingers": 1},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measured_pcells() -> dict[str, dict[str, Any]]:
    if not PARENT.is_file():
        raise SystemExit(
            f"missing {PARENT.relative_to(ROOT)}; run v3/layout/measure_pcells.tcl "
            "under pinned Magic/sky130A first"
        )
    matches = {match.group("instance"): match.groupdict() for match in USE_RE.finditer(PARENT.read_text())}
    if set(matches) != set(PARAMETERS):
        raise RuntimeError(f"PCell catalogue changed: found {sorted(matches)}")
    result = {}
    for instance, parameters in PARAMETERS.items():
        match = matches[instance]
        x0, y0, x1, y1 = (
            int(match[key]) / INTERNAL_UNITS_PER_UM
            for key in ("x0", "y0", "x1", "y1")
        )
        cell_path = MAG_DIR / f"{match['cell']}.mag"
        if not cell_path.is_file():
            raise RuntimeError(f"missing generated child {cell_path}")
        result[instance] = {
            "generated_cell": match["cell"],
            "parameters": parameters,
            "bbox_um": [x0, y0, x1, y1],
            "width_um": x1 - x0,
            "height_um": y1 - y0,
            "mag_sha256": sha256(cell_path),
        }
    return result


def tile_dimensions(cells: dict[str, dict[str, Any]], guarded: bool, rotate_tail: bool) -> tuple[float, float]:
    suffix = "G" if guarded else "U"
    gm = cells[f"XGM_{suffix}"]
    switch = cells[f"XSW_{suffix}"]
    tail = cells[f"XTAIL_{suffix}"]
    gm_pair_width = 2.0 * gm["width_um"] + INTERNAL_DEVICE_GAP_UM
    gm_pair_height = gm["height_um"]
    switch_quad_width = 2.0 * switch["width_um"] + INTERNAL_DEVICE_GAP_UM
    switch_quad_height = 2.0 * switch["height_um"] + INTERNAL_DEVICE_GAP_UM
    tail_width = tail["height_um"] if rotate_tail else tail["width_um"]
    tail_height = tail["width_um"] if rotate_tail else tail["height_um"]
    return (
        max(gm_pair_width, switch_quad_width, tail_width),
        gm_pair_height + tail_height + switch_quad_height + 2.0 * INTERNAL_DEVICE_GAP_UM,
    )


def array_candidate(
    name: str,
    cells: dict[str, dict[str, Any]],
    *,
    guarded: bool,
    rotate_tail: bool,
    dummy_strategy: str,
) -> dict[str, Any]:
    tile_width, tile_height = tile_dimensions(cells, guarded, rotate_tail)
    if dummy_strategy not in {"none", "full_unit", "device_row"}:
        raise ValueError(f"unknown dummy strategy {dummy_strategy}")
    columns = 5 if dummy_strategy == "full_unit" else 3
    rows = 7 if dummy_strategy != "none" else 5
    guard = 0.0 if guarded else SHARED_GUARD_MARGIN_UM
    bias_support_width = (
        cells["XBIAS_PASS_U"]["width_um"]
        + cells["XBIAS_PULL_U"]["width_um"]
        + INTERNAL_DEVICE_GAP_UM
    )
    bias_support_height = max(
        cells["XBIAS_PASS_U"]["height_um"],
        cells["XBIAS_PULL_U"]["height_um"],
    )
    if dummy_strategy == "device_row":
        suffix = "G" if guarded else "U"
        edge_dummy_width = max(
            cells[f"XGM_{suffix}"]["width_um"],
            cells[f"XSW_{suffix}"]["width_um"],
            cells[f"XTAIL_{suffix}"]["width_um"],
        )
        width = (
            columns * tile_width + (columns - 1) * UNIT_GAP_UM
            + 2.0 * (edge_dummy_width + UNIT_GAP_UM) + 2.0 * guard
        )
    else:
        edge_dummy_width = None
        width = columns * tile_width + (columns - 1) * UNIT_GAP_UM + 2.0 * guard
    height = (
        rows * tile_height + (rows - 1) * UNIT_GAP_UM + 2.0 * guard
        + INTERNAL_DEVICE_GAP_UM + bias_support_height
    )
    return {
        "name": name,
        "individual_device_guards": guarded,
        "tail_rotated_90deg": rotate_tail,
        "dummy_strategy": dummy_strategy,
        "edge_dummy_device_width_um": edge_dummy_width,
        "unit_tile_width_um": tile_width,
        "unit_tile_height_um": tile_height,
        "array_columns": columns,
        "array_rows": rows,
        "estimated_width_um": width,
        "estimated_height_um": height,
        "bias_blank_support_width_um": bias_support_width,
        "bias_blank_support_height_um": bias_support_height,
        "channel_pitch_um": CHANNEL_PITCH_UM,
        "width_margin_um": CHANNEL_PITCH_UM - width,
        "fits_channel_pitch": width <= CHANNEL_PITCH_UM,
    }


def centroid_map() -> dict[str, Any]:
    # 3x5 active matrix, surrounded later by one full dummy-unit border.
    labels = (
        (8, 8, 8),
        (4, 8, 4),
        (2, 1, 2),
        (4, 8, 4),
        (8, 8, 8),
    )
    positions: dict[int, list[tuple[float, float]]] = {1: [], 2: [], 4: [], 8: []}
    for row, values in enumerate(labels):
        for column, group in enumerate(values):
            positions[group].append((float(column), float(row)))
    centroids = {
        str(group): [
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        ]
        for group, points in positions.items()
    }
    counts = {str(group): len(points) for group, points in positions.items()}
    exact = counts == {"1": 1, "2": 2, "4": 4, "8": 8} and all(
        centroid == [1.0, 2.0] for centroid in centroids.values()
    )
    return {
        "active_matrix_top_to_bottom": [list(row) for row in labels],
        "dummy_border_label": "D",
        "group_counts": counts,
        "group_centroids_in_unit_pitch": centroids,
        "all_group_centroids_are_exactly_common": exact,
        "orientation_rule": "use inversion-paired R0/MY units; every pair has identical contact and route topology",
    }


def main() -> None:
    cells = measured_pcells()
    candidates = [
        array_candidate("shared_guard_tall_narrow_device_row_dummies", cells, guarded=False, rotate_tail=False, dummy_strategy="device_row"),
        array_candidate("shared_guard_tall_narrow_full_unit_dummies", cells, guarded=False, rotate_tail=False, dummy_strategy="full_unit"),
        array_candidate("shared_guard_short_wide_device_row_dummies", cells, guarded=False, rotate_tail=True, dummy_strategy="device_row"),
        array_candidate("individual_guards_device_row_dummies", cells, guarded=True, rotate_tail=False, dummy_strategy="device_row"),
        array_candidate("shared_guard_without_dummies_reference_only", cells, guarded=False, rotate_tail=False, dummy_strategy="none"),
    ]
    centroid = centroid_map()
    recommended = candidates[0]
    gate = {
        "pcells_measured_in_pinned_magic_environment": len(cells) == 8,
        "fifteen_active_units_have_exact_group_counts": centroid["group_counts"] == {"1": 1, "2": 2, "4": 4, "8": 8},
        "all_binary_group_centroids_are_common": centroid["all_group_centroids_are_exactly_common"],
        "conservative_dummy_border_candidate_fits_19p32um_pitch": recommended["fits_channel_pitch"],
        "recommended_candidate_has_at_least_3um_width_margin": recommended["width_margin_um"] >= 3.0,
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(gate.values()) else "fail",
        "scope": "dimension-only PCell feasibility; no placement, routing, layout database, DRC, extraction, or GDS",
        "provenance": {
            "magic_version": "8.3.676",
            "sky130_pdk_commit": "0536d02d875c8f67dd7cca3902ac457e62f20005",
            "generator": "v3/layout/measure_pcells.tcl",
            "generator_sha256": sha256(ROOT / "v3/layout/measure_pcells.tcl"),
            "parent_mag": str(PARENT.relative_to(ROOT)),
            "parent_mag_sha256": sha256(PARENT),
            "coordinate_conversion": "Magic internal coordinates divided by 200 give micrometres",
        },
        "measured_pcells": cells,
        "assumptions": {
            "channel_pitch_um": CHANNEL_PITCH_UM,
            "internal_device_gap_um": INTERNAL_DEVICE_GAP_UM,
            "unit_to_unit_gap_um": UNIT_GAP_UM,
            "shared_guard_margin_each_side_um": SHARED_GUARD_MARGIN_UM,
        "dummy_border": "device-row edge dummies horizontally and conservative full-unit-height top/bottom rows",
        },
        "centroid_assignment": centroid,
        "candidates": candidates,
        "recommended_candidate": recommended["name"],
        "gate": gate,
        "limitations": [
            "route tracks, via arrays, taps, pin access, antenna rules, and density are not included",
            "the full dummy-unit border is an area bound; final transistor-level dummy implementation may be smaller",
            "passing this study permits a later floorplan experiment only after all electrical Gate-2 blockers close",
        ],
    }
    output = BUILD / "summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": report["status"],
        "gate": gate,
        "recommended_candidate": recommended,
        "centroid_assignment": centroid,
    }, indent=2, sort_keys=True))
    print(f"report={output.relative_to(ROOT)}")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
