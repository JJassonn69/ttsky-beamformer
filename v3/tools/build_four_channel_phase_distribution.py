#!/usr/bin/env python3
"""Plan four matched top-corridor phase H-trees across the channel array."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLACEMENT = ROOT / "v3/layout/four_channel_placement.json"
SOURCE_GATE = ROOT / "v3/evidence/four_channel_output_collection_gate.json"
DEFAULT_OUTPUT = ROOT / "v3/layout/four_channel_phase_distribution.json"
WIDTH_UM = 0.4
TRUNK_RISE_UM = 0.8
PHASES = {
    # A 1.0 um staircase pitch leaves 0.49 um between a 0.62 um-wide M3
    # via-3 landing and the adjacent 0.40 um phase track.  Leaf heights are
    # paired with these offsets so horizontal escape plus vertical rise is
    # 8.19 um for every phase despite the 0.8 um source-port pitch.
    "phase_270": {"escape_left_um": 3.0, "leaf_y_um": 194.0},
    "phase_180": {"escape_left_um": 2.0, "leaf_y_um": 195.8},
    "phase_90": {"escape_left_um": 1.0, "leaf_y_um": 197.6},
    "phase_0": {"escape_left_um": 0.0, "leaf_y_um": 199.4},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def segment(start: list[float], stop: list[float], layer: str) -> dict[str, Any]:
    if start[0] != stop[0] and start[1] != stop[1]:
        raise ValueError(f"non-Manhattan phase segment: {start} -> {stop}")
    return {"from": start, "to": stop, "layer": layer, "width_um": WIDTH_UM}


def tree(name: str, settings: dict[str, float], instances: list[dict[str, Any]]) -> dict[str, Any]:
    ports = sorted(
        (item["ports"][name]["at_um"] for item in instances), key=lambda point: point[0]
    )
    offset = settings["escape_left_um"]
    leaf_y = settings["leaf_y_um"]
    trunk_y = round(leaf_y + TRUNK_RISE_UM, 6)
    tracks = [[round(point[0] - offset, 6), leaf_y] for point in ports]
    pair_centres = [
        [round((tracks[index][0] + tracks[index + 1][0]) / 2.0, 6), leaf_y]
        for index in (0, 2)
    ]
    root = [round((pair_centres[0][0] + pair_centres[1][0]) / 2.0, 6), trunk_y]
    segments: list[dict[str, Any]] = []
    for port, track in zip(ports, tracks):
        escape = [track[0], port[1]]
        segments.append(segment(port, escape, "metal3"))
        segments.append(segment(escape, track, "metal3"))
    for index, centre in zip((0, 2), pair_centres):
        segments.append(segment(tracks[index], tracks[index + 1], "metal4"))
        segments.append(segment(centre, [centre[0], trunk_y], "metal4"))
    segments.append(segment(
        [pair_centres[0][0], trunk_y], [pair_centres[1][0], trunk_y], "metal4"
    ))
    pre_tree_length = round(offset + leaf_y - ports[0][1], 6)
    source_to_root_length = round(
        pre_tree_length
        + abs(tracks[1][0] - tracks[0][0]) / 2.0
        + TRUNK_RISE_UM
        + abs(pair_centres[1][0] - pair_centres[0][0]) / 2.0,
        6,
    )
    return {
        "net": name,
        "source_points_um": ports,
        "m3_track_points_um": tracks,
        "via3_points_um": tracks,
        "pair_centres_um": pair_centres,
        "root_um": root,
        "leaf_y_um": leaf_y,
        "trunk_y_um": trunk_y,
        "escape_left_um": offset,
        "pre_tree_length_um": pre_tree_length,
        "source_to_root_length_um": source_to_root_length,
        "segments": segments,
        "equal_length_to_all_four_channels": True,
    }


def build() -> dict[str, Any]:
    placement = json.loads(PLACEMENT.read_text(encoding="utf-8"))
    gate = json.loads(SOURCE_GATE.read_text(encoding="utf-8"))
    if gate["status"] != "pass" or not all(gate["checks"].values()):
        raise RuntimeError("output-collection gate is not closed")
    source_gds = ROOT / gate["gds"]
    if sha256(source_gds) != gate["gds_sha256"]:
        raise RuntimeError("output-collection gate does not match its exact GDS")
    trees = {
        name: tree(name, settings, placement["instances"])
        for name, settings in PHASES.items()
    }
    lengths = {record["source_to_root_length_um"] for record in trees.values()}
    pre_lengths = {record["pre_tree_length_um"] for record in trees.values()}
    if len(lengths) != 1 or len(pre_lengths) != 1:
        raise RuntimeError("phase-distribution geometry is not fully matched")
    return {
        "schema_version": 1,
        "status": "route pilot; exact GDS checks pending",
        "units": "um",
        "top_cell": "v3_four_channel_phase_distribution",
        "source": {
            "gds": gate["gds"],
            "gds_sha256": gate["gds_sha256"],
            "top_cell": "v3_four_channel_output_collection",
            "gate": str(SOURCE_GATE.relative_to(ROOT)),
            "gate_sha256": sha256(SOURCE_GATE),
        },
        "trees": trees,
        "matched_source_to_root_length_um": next(iter(lengths)),
        "routing_decisions": {
            "local_escape_layer": "metal3",
            "balanced_tree_layer": "metal4",
            "tree_region": "above the 192.21 um frozen-macro top boundary",
            "staircase_rule": "lower phase ports escape farther left so no M3 branches cross",
            "height_compensation": "tree leaf heights rise 1.8 um per phase while source ports rise 0.8 um and horizontal escapes shrink 1.0 um",
        },
        "constraints": {
            "all_sixteen_channel_phase_paths_equal": True,
            "maximum_direction_reversals": 0,
            "one_via3_per_channel_per_phase": True,
            "floating_stubs_allowed": False,
            "orphan_vias_allowed": False,
            "frozen_source_geometry_modified": False,
        },
        "provenance": {
            "generator": "v3/tools/build_four_channel_phase_distribution.py",
            "generator_sha256": sha256(Path(__file__)),
        },
    }


def main() -> None:
    result = build()
    DEFAULT_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
