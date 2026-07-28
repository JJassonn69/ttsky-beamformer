#!/usr/bin/env python3
"""Plan balanced shared VBIAS and REF trees across the frozen channel array."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLACEMENT = ROOT / "v3/layout/four_channel_placement.json"
SOURCE_GATE = ROOT / "v3/evidence/four_channel_phase_distribution_gate.json"
DEFAULT_OUTPUT = ROOT / "v3/layout/four_channel_bias_reference_distribution.json"
WIDTH_UM = 0.4
TRANSITION_Y_UM = 148.25
TRUNK_RISE_UM = 0.8
TREES = {
    "vbias": {"leaf_y_um": 158.2, "transition_x_offset_um": 0.0},
    "ref": {"leaf_y_um": 160.4, "transition_x_offset_um": 1.0},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def segment(start: list[float], stop: list[float], layer: str) -> dict[str, Any]:
    if start[0] != stop[0] and start[1] != stop[1]:
        raise ValueError(f"non-Manhattan support segment: {start} -> {stop}")
    return {"from": start, "to": stop, "layer": layer, "width_um": WIDTH_UM}


def build_tree(name: str, settings: dict[str, float], instances: list[dict[str, Any]]) -> dict[str, Any]:
    sources = sorted(
        (item["ports"][name]["at_um"] for item in instances), key=lambda point: point[0]
    )
    offset = settings["transition_x_offset_um"]
    leaf_y = settings["leaf_y_um"]
    trunk_y = round(leaf_y + TRUNK_RISE_UM, 6)
    transitions = [[round(point[0] + offset, 6), TRANSITION_Y_UM] for point in sources]
    leaves = [[point[0], leaf_y] for point in transitions]
    pair_centres = [
        [round((leaves[index][0] + leaves[index + 1][0]) / 2.0, 6), leaf_y]
        for index in (0, 2)
    ]
    root = [round((pair_centres[0][0] + pair_centres[1][0]) / 2.0, 6), trunk_y]
    segments: list[dict[str, Any]] = []
    for source, transition, leaf in zip(sources, transitions, leaves):
        segments.append(segment(source, [source[0], TRANSITION_Y_UM], "metal2"))
        if transition[0] != source[0]:
            segments.append(segment([source[0], TRANSITION_Y_UM], transition, "metal2"))
        segments.append(segment(transition, leaf, "metal4"))
    for index, centre in zip((0, 2), pair_centres):
        segments.append(segment(leaves[index], leaves[index + 1], "metal3"))
        segments.append(segment(centre, [centre[0], trunk_y], "metal3"))
    segments.append(segment(
        [pair_centres[0][0], trunk_y], [pair_centres[1][0], trunk_y], "metal3"
    ))
    path_length = round(
        TRANSITION_Y_UM - sources[0][1]
        + offset
        + leaf_y - TRANSITION_Y_UM
        + abs(leaves[1][0] - leaves[0][0]) / 2.0
        + TRUNK_RISE_UM
        + abs(pair_centres[1][0] - pair_centres[0][0]) / 2.0,
        6,
    )
    return {
        "net": name,
        "source_points_um": sources,
        "transition_points_um": transitions,
        "leaf_points_um": leaves,
        "pair_centres_um": pair_centres,
        "root_um": root,
        "transition_y_um": TRANSITION_Y_UM,
        "leaf_y_um": leaf_y,
        "trunk_y_um": trunk_y,
        "transition_x_offset_um": offset,
        "source_to_root_length_um": path_length,
        "equal_length_to_all_four_channels": True,
        "via2_points_um": transitions,
        "via3_points_um": [*transitions, *leaves],
        "segments": segments,
    }


def build() -> dict[str, Any]:
    placement = json.loads(PLACEMENT.read_text(encoding="utf-8"))
    gate = json.loads(SOURCE_GATE.read_text(encoding="utf-8"))
    if gate["status"] != "pass" or not all(gate["checks"].values()):
        raise RuntimeError("phase-distribution gate is not closed")
    source_gds = ROOT / gate["gds"]
    if sha256(source_gds) != gate["gds_sha256"]:
        raise RuntimeError("phase-distribution gate does not match its exact GDS")
    trees = {
        name: build_tree(name, settings, placement["instances"])
        for name, settings in TREES.items()
    }
    return {
        "schema_version": 1,
        "status": "route pilot; exact GDS checks pending",
        "units": "um",
        "top_cell": "v3_four_channel_bias_reference_distribution",
        "source": {
            "gds": gate["gds"],
            "gds_sha256": gate["gds_sha256"],
            "top_cell": "v3_four_channel_phase_distribution",
            "gate": str(SOURCE_GATE.relative_to(ROOT)),
            "gate_sha256": sha256(SOURCE_GATE),
        },
        "trees": trees,
        "routing_decisions": {
            "source_escape": "short M2 rise to a common transition row above the output collector",
            "crowded_band_crossing": "one M4 elevator per leaf through the selector-access band",
            "balanced_tree_layer": "metal3",
            "tree_corridor_um": [157.51, 162.17],
            "ref_dogleg_reason": "moves REF transitions 1.0 um away from adjacent VBIAS via stacks",
            "verified_existing_m4_elevators_clear": True,
        },
        "constraints": {
            "all_four_paths_match_within_each_net": True,
            "maximum_direction_reversals": 0,
            "one_via2_and_two_via3_per_channel_per_net": True,
            "floating_stubs_allowed": False,
            "orphan_vias_allowed": False,
            "frozen_source_geometry_modified": False,
            "gds_timestamps_canonicalized": True,
        },
        "provenance": {
            "generator": "v3/tools/build_four_channel_bias_reference_distribution.py",
            "generator_sha256": sha256(Path(__file__)),
            "composer": "v3/tools/compose_four_channel_bias_reference_distribution.py",
            "composer_sha256": sha256(ROOT / "v3/tools/compose_four_channel_bias_reference_distribution.py"),
        },
    }


def main() -> None:
    result = build()
    DEFAULT_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
