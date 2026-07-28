#!/usr/bin/env python3
"""Plan and compare complete V3 channel-routing architectures.

This is deliberately a geometry/ownership gate, not a detailed router.  It
reserves every high-level net class before another exact GDS is generated, so
closing one net cannot silently consume the only escape path of another.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FLOORPLAN = ROOT / "v3/layout/floorplan.json"
MATRIX = ROOT / "v3/layout/channel_matrix_placement.json"
SELECTOR = ROOT / "v3/layout/selector_placement.json"
OUTPUT_EXPERIMENT = ROOT / "v3/layout/channel_output_collection.json"
DEFAULT_OUTPUT = ROOT / "v3/layout/channel_routing_architecture.json"

CHANNEL_WIDTH = 19.32
CHANNEL_HEIGHT = 112.99
UNIT_BBOX = [-0.85, 0.0, 3.71, 12.365]
ROW_ORIGINS = [88.0, 68.0, 48.0, 28.0, 8.0]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bbox_for_columns(origins: list[float]) -> list[float]:
    return [
        round(origins[0] + UNIT_BBOX[0], 6),
        8.0,
        round(origins[-1] + UNIT_BBOX[2], 6),
        round(ROW_ORIGINS[0] + UNIT_BBOX[3], 6),
    ]


def row_tracks() -> list[dict[str, Any]]:
    # Each gap is budgeted as a whole.  The centre-column group keeps the two
    # local-root levels; an outer-column group gets two independent levels.
    # P/N output buses then join their M2 spines directly through one named
    # Via-2 each.  The final three tracks serve the *next* row's sig/vbias/ref
    # ports, so no unbudgeted analog bus has to be squeezed in later.
    groups = [(8, None), (8, 4), (1, 2), (8, 4), (8, None)]
    records = []
    for row, (origin, (centre_group, outer_group)) in enumerate(zip(ROW_ORIGINS, groups)):
        records.append({
            "row_top_to_bottom": row,
            "origin_y_um": origin,
            "centre_group": centre_group,
            "outer_group": outer_group,
            "tracks": {
                "phase_centre_lon_m3": round(origin + 13.15, 6),
                "phase_centre_lop_m3": round(origin + 13.95, 6),
                "phase_outer_lon_m3": round(origin + 14.75, 6),
                "phase_outer_lop_m3": round(origin + 15.55, 6),
                "output_p_bus_m3": round(origin + 16.35, 6),
                "output_n_bus_m3": round(origin + 17.25, 6),
                "next_row_sig_m3": round(origin + 18.05, 6),
                "next_row_vbias_m3": round(origin + 18.75, 6),
                "next_row_ref_m3": round(origin + 19.45, 6),
            },
            "track_widths_um": {
                "phase_centre_lon_m3": 0.4,
                "phase_centre_lop_m3": 0.4,
                "phase_outer_lon_m3": 0.4,
                "phase_outer_lop_m3": 0.4,
                "output_p_bus_m3": 0.6,
                "output_n_bus_m3": 0.6,
                "next_row_sig_m3": 0.4,
                "next_row_vbias_m3": 0.4,
                "next_row_ref_m3": 0.3,
            },
        })
    return records


def candidate_service_corridors() -> dict[str, Any]:
    # A 6.96 um equal column pitch leaves two 2.40 um service corridors.
    # Common-centroid symmetry is retained; the larger pitch is an explicit
    # matching trade, not an accidental by-product of routing.
    columns = [1.27, 8.23, 15.19]
    active = bbox_for_columns(columns)
    left_gap = [4.98, 7.38]
    right_gap = [11.94, 14.34]
    output_spines = {"p": 5.53, "n": 6.33}
    analog_spines = {"sig": 12.44, "vbias": 13.14, "ref": 13.84}
    side_phase = [15.25, 15.95, 16.65, 17.35, 18.05, 18.75]
    return {
        "name": "dual_service_corridors",
        "recommendation": "selected for exact feasibility pilot",
        "channel_bbox": [0.0, 0.0, CHANNEL_WIDTH, CHANNEL_HEIGHT],
        "column_origins_um": columns,
        "column_pitch_um": 6.96,
        "active_array_bbox": active,
        "row_origins_top_to_bottom_um": ROW_ORIGINS,
        "row_pitch_um": 20.0,
        "service_corridors": {
            "output_left": {
                "bbox": [left_gap[0], 7.7, left_gap[1], 108.8],
                "layer": "metal2",
                "spines": output_spines,
                "width_um": 0.5,
                "pitch_um": 0.8,
            },
            "analog_right": {
                "bbox": [right_gap[0], 7.7, right_gap[1], 112.0],
                "layer": "metal2",
                "spines": analog_spines,
                "width_um": 0.4,
                "pitch_um": 0.7,
            },
        },
        "phase_distribution": {
            "horizontal_layer": "metal3",
            "vertical_layer": "metal4",
            "internal_g1_trunks_x_um": [11.60, 10.36],
            "mixed_centre_g8_handoffs_x_um": [12.15, 13.05],
            "side_bank_trunks_x_um": side_phase,
            "side_bank_bbox": [15.05, 20.7, 18.95, 112.0],
            "trunk_width_um": 0.4,
            "trunk_pitch_um": 0.7,
            "policy": "G1 uses two central handoffs; mixed G8/G4 rows hand centre-G8 off inside the right inter-column gap before the outer roots; G2/G4 and all-G8 rows use the right bank; global trees route later against the exact service GDS",
        },
        "row_track_plan": row_tracks(),
        "support_band_global": {
            "bbox": [82.0, 115.0, 160.5, 141.0],
            "compact_input_bias_resistor_centers_x_um": [98.87, 118.19, 137.51, 156.83],
            "compact_input_bias_bbox_y_um": [117.5, 140.68],
            "output_load_centers_um": {"n": [111.68, 123.0], "p": [131.0, 123.0]},
            "reason": "attach each bias resistor to the top of its required signal spine; keep both inter-column routing corridors clear",
        },
        "selector_and_global_phase": {
            "selector_band_global_y_um": [144.0, 178.0],
            "phase_tree_band_global_y_um": [179.0, 208.0],
            "selector_rebuild_required": True,
            "selector_outputs_must_land_directly_on_reserved_phase_trunks": True,
        },
        "global_output_collection": {
            "channel_root_y_um": 116.5,
            "pair_topology": "two-level balanced H-tree per polarity",
            "p_channel_roots_x_um": [91.96, 111.28, 130.60, 149.92],
            "n_channel_roots_x_um": [92.76, 112.08, 131.40, 150.72],
            "p_tree_centroid_x_um": 120.94,
            "n_tree_centroid_x_um": 121.74,
            "load_centers_x_um": {"p": 131.0, "n": 111.68},
            "tree_root_to_load_length_um": {"p": 10.06, "n": 10.06},
            "load_to_output_pin_horizontal_length_um": {"p": 56.02, "n": 56.02},
            "load_relocation_required": True,
        },
        "guard_and_power": {
            "guard_layers": ["diffusion", "locali", "metal1"],
            "ground_collection_layer": "metal3",
            "named_crossings": [
                "M3 row-output bridges across the left guard only at row roots",
                "M3 analog branches across the right guard only at unit row roots",
                "M4 phase handoff across the top guard only at eight named trunks",
            ],
            "selector_power": "local M1 rails with top-band M2 straps; do not enter the analog row channels",
            "floating_metal_allowed": False,
            "projected_interchannel_active_gap_um": 0.84,
            "interchannel_policy": "one abutted/shared grounded guard boundary; exact adjacent-channel guard pilot is mandatory before promotion",
        },
        "known_tradeoffs": [
            "column pitch grows from 5.20 um to 6.96 um; mismatch geometry must be re-qualified",
            "the projected 0.84 um active-array gap requires an exact shared-guard abutment proof",
            "selector and load placement evidence must be regenerated",
            "phase routes must be replanned against the exact output and analog-spine GDS",
        ],
        "scores": {
            "topology_and_capacity": 24,
            "matching": 16,
            "coupling_isolation": 13,
            "support_integration": 18,
            "route_simplicity": 8,
            "reuse_of_closed_evidence": 3,
        },
    }


def candidate_same_side() -> dict[str, Any]:
    columns = [1.24, 6.44, 11.64]
    return {
        "name": "same_side_layer_overlay",
        "recommendation": "reference only; do not promote without defeating the coupling/capacity findings",
        "channel_bbox": [0.0, 0.0, CHANNEL_WIDTH, CHANNEL_HEIGHT],
        "column_origins_um": columns,
        "column_pitch_um": 5.20,
        "active_array_bbox": bbox_for_columns(columns),
        "row_origins_top_to_bottom_um": ROW_ORIGINS,
        "row_pitch_um": 20.0,
        "service_corridors": {
            "output_right": {
                "bbox": [15.35, 20.7, 18.0, 108.8],
                "layer": "metal2",
                "spines": {"p": 16.65, "n": 17.55},
                "width_um": 0.6,
            },
            "compact_input_bias_right_bottom": {
                "bbox": [16.01, 0.0, 19.32, 20.7],
                "layer": "device_and_metal3_shield",
            },
        },
        "phase_distribution": {
            "horizontal_layer": "metal3",
            "vertical_layer": "metal4",
            "side_bank_bbox": [15.62, 20.7, 19.32, 112.0],
            "policy": "six phase trunks run directly above and beside the two output spines; two G1 trunks remain internal",
        },
        "row_track_plan": row_tracks(),
        "known_tradeoffs": [
            "long parallel M2-output/M4-phase overlap remains for most of the channel height",
            "the compact input-bias shield, phase bank, and output bank all claim the same right edge",
            "the output-only GDS is DRC clean, but the previously closed phase tree is not integrated with it",
            "local obstacle routing produced direction reversals and scarce output access",
        ],
        "scores": {
            "topology_and_capacity": 15,
            "matching": 20,
            "coupling_isolation": 6,
            "support_integration": 8,
            "route_simplicity": 5,
            "reuse_of_closed_evidence": 8,
        },
    }


def validate(candidate: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    active = candidate["active_array_bbox"]
    if not (0 <= active[0] < active[2] <= CHANNEL_WIDTH):
        errors.append("active array exceeds channel width")
    left_pitch = candidate["column_origins_um"][1] - candidate["column_origins_um"][0]
    right_pitch = candidate["column_origins_um"][2] - candidate["column_origins_um"][1]
    if not math.isclose(left_pitch, right_pitch, abs_tol=1e-9):
        errors.append("column pitch is not symmetric")
    tracks = candidate["row_track_plan"]
    for record in tracks:
        ordered = list(record["tracks"].values())
        if ordered != sorted(ordered):
            errors.append(f"row {record['row_top_to_bottom']} track order is not monotonic")
        if record["row_top_to_bottom"] and max(ordered) >= tracks[record["row_top_to_bottom"] - 1]["origin_y_um"]:
            errors.append(f"row {record['row_top_to_bottom']} tracks enter the row above")
        names = list(record["tracks"])
        for first_name, second_name in zip(names, names[1:]):
            first_y = record["tracks"][first_name]
            second_y = record["tracks"][second_name]
            first_w = record["track_widths_um"][first_name]
            second_w = record["track_widths_um"][second_name]
            edge_gap = second_y - second_w / 2 - (first_y + first_w / 2)
            if edge_gap < 0.30 - 1e-9:
                errors.append(
                    f"row {record['row_top_to_bottom']} {first_name}/{second_name} "
                    f"edge spacing is {edge_gap:.3f} um"
                )
    if candidate["name"] == "dual_service_corridors":
        left = candidate["service_corridors"]["output_left"]
        right = candidate["service_corridors"]["analog_right"]
        for name, corridor in (("output", left), ("analog", right)):
            xs = sorted(corridor["spines"].values())
            width = corridor["width_um"]
            for first, second in zip(xs, xs[1:]):
                if second - first - width < 0.30 - 1e-9:
                    errors.append(f"{name} spine spacing below 0.30 um")
            if xs[0] - width / 2 < corridor["bbox"][0] or xs[-1] + width / 2 > corridor["bbox"][2]:
                errors.append(f"{name} spines exceed their corridor")
        phase = candidate["phase_distribution"]
        if phase["side_bank_bbox"][0] < right["bbox"][2] + 0.30:
            errors.append("phase bank lacks 0.30 um projected separation from analog corridor")
        output = candidate["global_output_collection"]
        if output["tree_root_to_load_length_um"]["p"] != output["tree_root_to_load_length_um"]["n"]:
            errors.append("P/N output tree root-to-load paths differ")
        if output["load_to_output_pin_horizontal_length_um"]["p"] != output["load_to_output_pin_horizontal_length_um"]["n"]:
            errors.append("P/N load-to-pin paths differ")
    return errors


def build() -> dict[str, Any]:
    candidates = [candidate_service_corridors(), candidate_same_side()]
    for candidate in candidates:
        candidate["score_total"] = sum(candidate["scores"].values())
        candidate["geometry_errors"] = validate(candidate)
        candidate["geometry_status"] = "pass" if not candidate["geometry_errors"] else "fail"
    selected = max(
        (candidate for candidate in candidates if candidate["geometry_status"] == "pass"),
        key=lambda candidate: candidate["score_total"],
    )
    return {
        "schema_version": 1,
        "units": "um",
        "status": "architecture selected; exact one-channel feasibility GDS not yet authorized",
        "decision": {
            "selected": selected["name"],
            "reason": "it reserves all five analog/output spines, eight phase trunks, row tracks, support passives, selector handoff, guard crossings, and matched output tails before detailed routing",
            "reopens": [
                "channel matrix placement",
                "group phase trees",
                "edge dummies and shared guard",
                "compact input-bias integration",
                "selector placement and selector-to-channel join",
                "output-load placement and differential sum tree",
            ],
            "preserves": [
                "vector-unit transistor dimensions and internal topology",
                "3x5 group common-centroid assignment",
                "20 um row pitch",
                "four fixed analog input pins",
                "1.8 V-only power contract",
                "no Metal 5, no meanders, no floating stubs, no orphan vias",
            ],
        },
        "fixed_constraints": {
            "die_bbox": [0.0, 0.0, 334.88, 225.76],
            "channel_pitch_um": 19.32,
            "channel_origins_x_um": [86.43, 105.75, 125.07, 144.39],
            "channel_input_pin_centers_x_um": [94.30, 113.62, 132.94, 152.26],
            "metal5_signal_use": False,
            "minimum_same_layer_spacing_um": 0.30,
            "floating_stubs_allowed": False,
            "orphan_vias_allowed": False,
            "u_turns_or_meanders_allowed": False,
        },
        "score_weights": {
            "topology_and_capacity": 25,
            "matching": 20,
            "coupling_isolation": 15,
            "support_integration": 20,
            "route_simplicity": 10,
            "reuse_of_closed_evidence": 10,
        },
        "candidates": {candidate["name"]: candidate for candidate in candidates},
        "promotion_gates": [
            "render and visually review the complete one-channel and four-channel skeleton",
            "prove two adjacent widened arrays can share/abut a grounded guard with zero DRC and no channel-to-channel signal short",
            "regenerate the exact 3x5 matrix at 6.96 um equal column pitch",
            "prove one row with all local LO, output, signal, vbias, and ref transitions",
            "route the full channel with outputs first, analog spines second, phase last",
            "merge compact input bias, edge dummies, guard, selector, and output loads",
            "pass Magic DRC/topology, distributed RC, and the direct-GDS shuttle-equivalent precheck",
            "repeat mismatch/calibration geometry study for the larger symmetric column pitch",
        ],
        "provenance": {
            "generator": "v3/tools/plan_channel_routing_architecture.py",
            "generator_sha256": sha256(Path(__file__)),
            "floorplan": "v3/layout/floorplan.json",
            "floorplan_sha256": sha256(FLOORPLAN),
            "matrix": "v3/layout/channel_matrix_placement.json",
            "matrix_sha256": sha256(MATRIX),
            "selector": "v3/layout/selector_placement.json",
            "selector_sha256": sha256(SELECTOR),
            "output_experiment": "v3/layout/channel_output_collection.json",
            "output_experiment_sha256": sha256(OUTPUT_EXPERIMENT),
        },
    }


def main() -> None:
    data = build()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)
    print(f"selected={data['decision']['selected']}")
    for name, candidate in data["candidates"].items():
        print(f"{name}: score={candidate['score_total']} geometry={candidate['geometry_status']}")


if __name__ == "__main__":
    main()
