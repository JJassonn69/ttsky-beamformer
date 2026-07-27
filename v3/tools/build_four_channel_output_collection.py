#!/usr/bin/env python3
"""Plan balanced differential output H-trees above four frozen V3 channels."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLACEMENT = ROOT / "v3/layout/four_channel_placement.json"
PLACEMENT_GATE = ROOT / "v3/evidence/four_channel_placement_gate.json"
DEFAULT_OUTPUT = ROOT / "v3/layout/four_channel_output_collection.json"
TREE_LEVELS = {
    # This M3 corridor lies above the grounded 142.52..142.92 um bus and below
    # the next existing M3 phase/control band beginning at 149.075 um.
    "p": {"leaf_y_um": 144.5, "trunk_y_um": 145.3},
    "n": {"leaf_y_um": 146.5, "trunk_y_um": 147.3},
}
WIDTH_UM = 0.4


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def segment(start: list[float], stop: list[float], layer: str) -> dict[str, Any]:
    if start[0] != stop[0] and start[1] != stop[1]:
        raise ValueError(f"non-Manhattan output segment: {start} -> {stop}")
    return {"from": start, "to": stop, "layer": layer, "width_um": WIDTH_UM}


def tree(source_name: str, polarity: str, instances: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(instances, key=lambda item: item["ports"][source_name]["at_um"][0])
    source_points = [item["ports"][source_name]["at_um"] for item in ordered]
    levels = TREE_LEVELS[polarity]
    leaf_y = levels["leaf_y_um"]
    trunk_y = levels["trunk_y_um"]
    transition_points = [[point[0], leaf_y] for point in source_points]
    route_layer = "metal3"
    pair_centres = [
        [round((transition_points[index][0] + transition_points[index + 1][0]) / 2.0, 6), leaf_y]
        for index in (0, 2)
    ]
    root = [round((pair_centres[0][0] + pair_centres[1][0]) / 2.0, 6), trunk_y]
    segments = []
    for source, transition in zip(source_points, transition_points):
        # Stay on M2 through the occupied lower phase region, then promote
        # directly into the verified empty M3 collector band.
        segments.append(segment(source, transition, "metal2"))
    for index, centre in zip((0, 2), pair_centres):
        segments.append(segment(
            [transition_points[index][0], leaf_y],
            [transition_points[index + 1][0], leaf_y],
            route_layer,
        ))
        segments.append(segment(centre, [centre[0], trunk_y], route_layer))
    segments.append(segment(
        [pair_centres[0][0], trunk_y], [pair_centres[1][0], trunk_y], route_layer
    ))
    source_to_root_length = round(
        (leaf_y - source_points[0][1])
        + abs(transition_points[1][0] - transition_points[0][0]) / 2.0
        + (trunk_y - leaf_y)
        + abs(pair_centres[1][0] - pair_centres[0][0]) / 2.0,
        6,
    )
    return {
        "net": f"combined_{polarity}_internal",
        "source_port": source_name,
        "route_layer": route_layer,
        "source_points_um": source_points,
        "transition_points_um": transition_points,
        "via2_points_um": transition_points,
        "via3_points_um": [],
        "pair_centres_um": pair_centres,
        "root_um": root,
        "segments": segments,
        "source_to_root_length_um": source_to_root_length,
        "equal_length_for_all_four_sources": True,
    }


def build() -> dict[str, Any]:
    placement = json.loads(PLACEMENT.read_text(encoding="utf-8"))
    gate = json.loads(PLACEMENT_GATE.read_text(encoding="utf-8"))
    if gate["status"] != "pass" or not all(gate["checks"].values()):
        raise RuntimeError("four-channel placement gate is not closed")
    source_gds = ROOT / gate["gds"]
    if sha256(source_gds) != gate["gds_sha256"]:
        raise RuntimeError("placement gate does not match its exact GDS")
    p_tree = tree("row_outp", "p", placement["instances"])
    n_tree = tree("row_outn", "n", placement["instances"])
    differential_length_delta = round(
        n_tree["source_to_root_length_um"] - p_tree["source_to_root_length_um"], 6
    )
    return {
        "schema_version": 1,
        "status": "route pilot; exact GDS checks pending",
        "units": "um",
        "top_cell": "v3_four_channel_output_collection",
        "source": {
            "gds": gate["gds"],
            "gds_sha256": gate["gds_sha256"],
            "top_cell": placement["top_cell"],
            "placement_manifest": str(PLACEMENT.relative_to(ROOT)),
            "placement_manifest_sha256": sha256(PLACEMENT),
            "placement_gate": str(PLACEMENT_GATE.relative_to(ROOT)),
            "placement_gate_sha256": sha256(PLACEMENT_GATE),
        },
        "trees": {"p": p_tree, "n": n_tree},
        "routing_decisions": {
            "m2_escape": "straight vertical from each output through the occupied lower routing band",
            "p_tree": "lower Metal-3 H-tree at 144.5/145.3 um",
            "n_tree": "upper Metal-3 H-tree at 146.5/147.3 um",
            "m4_rejected": "a trial N tree on M4 shorted into selector phase outputs despite clean DRC",
            "verified_empty_m3_corridor_um": [143.22, 148.775],
            "p_root_compensation_required_um": differential_length_delta,
            "future_root_match": "add the recorded P-path compensation in the load/pad escape, then confirm with distributed RC",
        },
        "constraints": {
            "maximum_direction_reversals": 0,
            "one_via2_per_source": True,
            "via3_count": 0,
            "all_four_paths_equal_within_each_polarity": True,
            "p_and_n_length_delta_deferred_to_root_escape_um": differential_length_delta,
            "floating_stubs_allowed": False,
            "orphan_vias_allowed": False,
            "frozen_channel_geometry_modified": False,
        },
        "provenance": {
            "generator": "v3/tools/build_four_channel_output_collection.py",
            "generator_sha256": sha256(Path(__file__)),
        },
    }


def main() -> None:
    result = build()
    DEFAULT_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
