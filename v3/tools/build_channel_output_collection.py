#!/usr/bin/env python3
"""Build the authoritative balanced V3 per-channel output collector."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3/layout/channel_matrix_placement.json"
DEFAULT_OUTPUT = ROOT / "v3/layout/channel_output_collection.json"

BUS_OFFSETS = {"p": 15.45, "n": 16.35}
ESCAPE_LEVELS = {"low": 17.25, "high": 18.15}
TRANSITION_X = 15.65
SPINES = {"p": 16.65, "n": 17.55}
ROOT_Y = 108.50


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def segment(first: list[float], second: list[float], layer: str, width: float) -> dict[str, Any]:
    if first[0] != second[0] and first[1] != second[1]:
        raise ValueError(f"non-Manhattan output segment: {first} -> {second}")
    return {"from": first, "to": second, "layer": layer, "width_um": width}


def build() -> dict[str, Any]:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    all_bus_via2: list[list[float]] = []
    all_transition_via2: list[list[float]] = []
    all_segments: list[dict[str, Any]] = []
    instances = matrix["matrix"]["instances"]
    for row_index in range(5):
        row_instances = sorted(
            (item for item in instances if item["row_top_to_bottom"] == row_index),
            key=lambda item: item["column_left_to_right"],
        )
        origin_y = float(row_instances[0]["origin"][1])
        row_record: dict[str, Any] = {"row_top_to_bottom": row_index, "origin_y_um": origin_y, "nets": {}}
        roots = {
            polarity: sorted(
                ([float(item["ports"][f"out{polarity}"]["point"][0]),
                  float(item["ports"][f"out{polarity}"]["point"][1])]
                 for item in row_instances),
                key=lambda point: point[0],
            )
            for polarity in ("p", "n")
        }
        # The left physical root takes the higher escape track.  It therefore
        # crosses the right root only after that root's M2 vertical has ended.
        left_polarity = min(("p", "n"), key=lambda polarity: roots[polarity][1][0])
        for polarity in ("p", "n"):
            taps = roots[polarity]
            bus_y = round(origin_y + BUS_OFFSETS[polarity], 6)
            escape_role = "high" if polarity == left_polarity else "low"
            escape_y = round(origin_y + ESCAPE_LEVELS[escape_role], 6)
            median_x = taps[1][0]
            bus_via2 = [[point[0], point[1]] for point in taps]
            bus_via2 += [[point[0], bus_y] for point in taps]
            transition_via2 = [[TRANSITION_X, escape_y], [SPINES[polarity], escape_y]]
            segments: list[dict[str, Any]] = []
            for tap in taps:
                segments.append(segment(tap, [tap[0], bus_y], "metal2", 0.40))
            segments.append(segment([taps[0][0], bus_y], [taps[-1][0], bus_y], "metal3", 0.60))
            segments.append(segment([median_x, bus_y], [median_x, escape_y], "metal2", 0.60))
            segments.append(segment([median_x, escape_y], [TRANSITION_X, escape_y], "metal2", 0.60))
            segments.append(segment([TRANSITION_X, escape_y], [SPINES[polarity], escape_y], "metal3", 0.60))
            row_record["nets"][f"out{polarity}"] = {
                "tap_points": taps,
                "bus_y_um": bus_y,
                "bus_root_x_um": median_x,
                "escape_role": escape_role,
                "escape_y_um": escape_y,
                "spine_x_um": SPINES[polarity],
                "segments": segments,
                "via2_points": bus_via2 + transition_via2,
            }
            all_segments.extend(segments)
            all_bus_via2.extend(bus_via2)
            all_transition_via2.extend(transition_via2)
        rows.append(row_record)

    spine_bottom = min(
        net["escape_y_um"] for row in rows for net in row["nets"].values()
    )
    for polarity in ("p", "n"):
        all_segments.append(segment(
            [SPINES[polarity], spine_bottom], [SPINES[polarity], ROOT_Y], "metal2", 0.60
        ))

    def unique(points: list[list[float]]) -> list[list[float]]:
        return [list(item) for item in sorted({tuple(item) for item in points})]

    return {
        "schema_version": 1,
        "units": "um",
        "status": "authoritative output-route contract; exact combined physical gate pending",
        "rows": rows,
        "segments": all_segments,
        "via2_points": unique(all_bus_via2 + all_transition_via2 + [
            [SPINES["p"], ROOT_Y], [SPINES["n"], ROOT_Y]
        ]),
        "spines": {
            polarity: {
                "net": f"channel_out{polarity}",
                "layer": "metal2",
                "x_um": SPINES[polarity],
                "width_um": 0.60,
                "bottom_y_um": spine_bottom,
                "root": [SPINES[polarity], ROOT_Y],
                "root_layer": "metal3",
            }
            for polarity in ("p", "n")
        },
        "constraints": {
            "channel_pitch_um": 19.32,
            "metal5_used": False,
            "same_topology_per_polarity": True,
            "same_via2_population_per_leaf": True,
            "route_meanders_allowed": False,
            "u_turns_allowed": False,
            "floating_stubs_allowed": False,
            "orphan_vias_allowed": False,
            "minimum_same_layer_spacing_um": 0.30,
            "maximum_leaf_resistance_spread_percent": 2.0,
            "maximum_p_n_total_capacitance_delta_percent": 2.0,
            "phase_trees_must_be_replanned_with_this_exact_gds_as_obstacle_source": True,
        },
        "rationale": {
            "row_pitch_um": matrix["matrix"]["row_pitch_um"],
            "reserved_bus_offsets_um": BUS_OFFSETS,
            "reserved_escape_offsets_um": ESCAPE_LEVELS,
            "side_spines_share_x_band_with_phase_trunks_on_a_different_layer": True,
            "compact_input_bias_clearance_um": round(spine_bottom - 20.70, 6),
            "reason": "reserve output access before phase routing; use M2 spines under M4 phase trunks and named M3 bridges so no same-layer crossing or Metal 5 is required",
        },
        "provenance": {
            "generator": "v3/tools/build_channel_output_collection.py",
            "generator_sha256": sha256(Path(__file__)),
            "matrix_manifest": "v3/layout/channel_matrix_placement.json",
            "matrix_manifest_sha256": sha256(MATRIX),
        },
    }


def main() -> None:
    data = build()
    DEFAULT_OUTPUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
