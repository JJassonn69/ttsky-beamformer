#!/usr/bin/env python3
"""Build the route-constrained V3 shared-reference and bias-tree manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FLOORPLAN = ROOT / "v3" / "layout" / "floorplan.json"
SUPPORT = ROOT / "v3" / "evidence" / "support_floorplan_study.json"
OUTPUT = ROOT / "v3" / "layout" / "bias_distribution.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def segment(layer: str, start: list[float], stop: list[float], width: float) -> dict[str, Any]:
    if start[0] != stop[0] and start[1] != stop[1]:
        raise ValueError(f"non-Manhattan segment: {start} -> {stop}")
    return {"layer": layer, "from": start, "to": stop, "width_um": width}


def build_manifest() -> dict[str, Any]:
    floorplan = json.loads(FLOORPLAN.read_text(encoding="utf-8"))
    support = json.loads(SUPPORT.read_text(encoding="utf-8"))
    channels = {item["index"]: item for item in floorplan["channels"]}
    reference_center = support["selected_placement_center_um"]
    if reference_center != [194.0, 48.0]:
        raise ValueError("reference center changed; terminal-access geometry must be remeasured")

    root = [123.28, 111.0]
    pair_y = 109.0
    leaf_y = 102.0
    pair_nodes = {
        "left": [103.96, root[1]],
        "right": [142.60, root[1]],
    }
    pair_rails = {
        "left": [103.96, pair_y],
        "right": [142.60, pair_y],
    }
    groups = {
        "left": [3, 2],
        "right": [1, 0],
    }
    leaves = {
        str(index): [channels[index]["center_x"], leaf_y]
        for index in range(4)
    }

    branch_paths: dict[str, dict[str, Any]] = {}
    tree_segments: list[dict[str, Any]] = []
    for side, indices in groups.items():
        node = pair_nodes[side]
        rail = pair_rails[side]
        first_stage = segment("metal2", root, node, 0.8)
        pair_drop = segment("metal2", node, rail, 0.8)
        tree_segments.extend((first_stage, pair_drop))
        xs = sorted(leaves[str(index)][0] for index in indices)
        pair_bus = segment("metal2", [xs[0], pair_y], [xs[1], pair_y], 0.8)
        tree_segments.append(pair_bus)
        for index in indices:
            leaf = leaves[str(index)]
            pair_leg = segment("metal2", rail, [leaf[0], pair_y], 0.8)
            leaf_drop = segment("metal2", [leaf[0], pair_y], leaf, 0.8)
            length = sum(
                abs(item["to"][0] - item["from"][0])
                + abs(item["to"][1] - item["from"][1])
                for item in (first_stage, pair_drop, pair_leg, leaf_drop)
            )
            branch_paths[str(index)] = {
                "side": side,
                "channel": index,
                "segments": [first_stage, pair_drop, pair_leg, leaf_drop],
                "drawn_length_um": round(length, 6),
                "branch_via_count": 0,
            }
        tree_segments.extend(
            segment("metal2", [leaves[str(index)][0], pair_y], leaves[str(index)], 0.8)
            for index in indices
        )

    unique_segments = []
    seen = set()
    for item in tree_segments:
        key = (item["layer"], tuple(item["from"]), tuple(item["to"]), item["width_um"])
        reverse = (item["layer"], tuple(item["to"]), tuple(item["from"]), item["width_um"])
        if key not in seen and reverse not in seen:
            unique_segments.append(item)
            seen.add(key)

    x0, y0 = reference_center
    diffusion_pitch = 1.29
    drain_x = [x0 + value for value in (-5.16, -2.58, 0.0, 2.58, 5.16)]
    source_x = [x0 + value for value in (-3.87, -1.29, 1.29, 3.87)]
    gate_x = [x0 + diffusion_pitch * value for value in (-3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5)]

    return {
        "schema_version": 1,
        "status": "physical pilot pass; top-level integration pending",
        "scope": "shared 64/1 um diode reference strap and four-leaf matched bias tree; VCM, decap, bias resistor, channel devices, and top-level integration remain outside this manifest",
        "provenance": {
            "generator": "v3/tools/build_bias_distribution.py",
            "floorplan": "v3/layout/floorplan.json",
            "floorplan_sha256": sha256(FLOORPLAN),
            "support_floorplan_study": "v3/evidence/support_floorplan_study.json",
            "support_floorplan_study_sha256": sha256(SUPPORT),
            "magic_version": "8.3.676",
            "sky130_pdk_commit": "0536d02d875c8f67dd7cca3902ac457e62f20005",
        },
        "reference": {
            "name": "XREF",
            "center_um": reference_center,
            "gencell_anchor_um": [188.27, 43.215],
            "gencell_anchor_note": "Magic's nfet PCell anchor is +5.73/+4.785 um from the fixed-bbox center for this exact folding",
            "bbox_um": support["selected_placement_bbox_um"],
            "pcell": "sky130_fd_pr__nfet_01v8",
            "parameters": {
                "finger_width_um": 8.0,
                "length_um": 1.0,
                "fingers": 8,
                "aggregate_width_um": 64.0,
                "guard": 1,
                "connected_gates": 1,
                "body_metal_coverage_percent": 100,
            },
            "terminal_access": {
                "drain_via1_centers_um": [[round(x, 6), 51.86] for x in drain_x],
                "gate_via1_centers_um": [[round(x, 6), 52.32] for x in gate_x],
                "source_via1_centers_um": [[round(x, 6), 44.14] for x in source_x],
                "body_via1_centers_um": [[189.0, 43.215], [194.0, 43.215], [199.0, 43.215]],
                "via1_box_um": [0.32, 0.32],
            },
            "straps": {
                "vbias_ref": {"layer": "metal2", "bbox_um": [188.68, 51.68, 199.32, 52.48]},
                "VGND": {"layer": "metal2", "bbox_um": [188.68, 42.90, 199.32, 44.32]},
            },
            "required_extracted_device_signature": {
                "count": 8,
                "model": "sky130_fd_pr__nfet_01v8",
                "diffusions": ["VGND", "vbias_ref"],
                "gate": "vbias_ref",
                "body": "VGND",
                "finger_width_um": 8.0,
                "length_um": 1.0,
            },
        },
        "common_route": {
            "start": [194.0, 52.2],
            "root": root,
            "segments": [
                segment("metal4", [194.0, 52.2], [194.0, 111.0], 0.5),
                segment("metal4", [194.0, 111.0], root, 0.5),
            ],
            "via_stack_at_start": ["via2", "via3"],
            "via_stack_at_root": ["via3", "via2"],
            "intermediate_metal3_landing_um": [0.60, 0.60],
            "note": "common impedance is upstream of the named star and therefore does not create channel-to-channel branch mismatch",
        },
        "bias_tree": {
            "topology": "two-level balanced binary tree",
            "net": "vbias_ref",
            "root": root,
            "pair_nodes": pair_nodes,
            "pair_rails": pair_rails,
            "leaves": leaves,
            "segments": unique_segments,
            "branch_paths": branch_paths,
            "layer": "metal2",
            "wire_width_um": 0.8,
            "drawn_branch_mismatch_percent": 0.0,
            "no_length_tuning_stubs": True,
            "no_orphan_vias": True,
            "all_segment_ends_are_named_nodes_or_leaves": True,
        },
        "layout_policy": {
            "metal5_used": False,
            "reference_device_flattened_before_parent_strapping": True,
            "reason_for_flattening": "the even-finger PCell leaves the outer D8 diffusion without a child port label; flat parent strapping is required to prove every drain is connected",
            "tree_crosses_output_corridor_only_on_metal2": True,
            "tree_max_y_um": 111.4,
            "load_pair_keepout_starts_y_um": 113.0,
        },
        "next_gate": [
            "place and requalify the shared VCM generator and local decoupling",
            "place the symmetric differential load pair and preserve its no-crossing corridor",
            "integrate the closed reference/tree geometry without changing its named star or leaves",
            "repeat topology, direct-GDS, and distributed-RC gates on the integrated top level",
        ],
    }


def main() -> None:
    manifest = build_manifest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
