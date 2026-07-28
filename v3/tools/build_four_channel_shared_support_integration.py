#!/usr/bin/env python3
"""Bind the exact VCM and tail-bias support blocks to the balanced channel trees."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_GATE = ROOT / "v3/evidence/four_channel_bias_reference_distribution_gate.json"
DEFAULT_OUTPUT = ROOT / "v3/layout/four_channel_shared_support_integration.json"
BLOCKS = {
    "vcm": {
        "gds": "build/v3/vcm_support_block/v3_vcm_support_block.gds",
        "top_cell": "v3_vcm_support_block",
        "precheck": "build/v3/vcm_support_block/precheck_summary.json",
        "magic_log": "build/v3/vcm_support_block/magic_build.log",
        "drc_marker": "V3_VCM_SUPPORT_BLOCK_DRC_COUNT",
        "extraction_marker": "V3_VCM_SUPPORT_BLOCK_EXTRACTION_FEEDBACK_COUNT",
        "bbox_um": [15.0, 4.6, 53.25, 141.795],
        "signal_root_um": [53.0, 90.0],
        "signal": "ref",
    },
    "tail_bias": {
        "gds": "build/v3/tail_bias_support_block/v3_tail_bias_support_block.gds",
        "top_cell": "v3_tail_bias_support_block",
        "precheck": "build/v3/tail_bias_support_block/precheck_summary.json",
        "magic_log": "build/v3/tail_bias_support_block/magic_build.log",
        "drc_marker": "V3_TAIL_BIAS_SUPPORT_BLOCK_DRC_COUNT",
        "extraction_marker": "V3_TAIL_BIAS_SUPPORT_BLOCK_EXTRACTION_FEEDBACK_COUNT",
        "bbox_um": [188.06, 29.6, 268.08, 105.345],
        "signal_root_um": [194.0, 52.2],
        "signal": "vbias",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(text: str, name: str) -> int | None:
    match = re.search(rf"^{re.escape(name)}=(\d+)$", text, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def route(start: list[float], stop: list[float], net: str) -> dict[str, Any]:
    if start[0] != stop[0] and start[1] != stop[1]:
        raise ValueError(f"non-Manhattan common route: {start} -> {stop}")
    return {"from": start, "to": stop, "layer": "metal3", "width_um": 0.5, "net": net}


def build() -> dict[str, Any]:
    source_gate = json.loads(SOURCE_GATE.read_text(encoding="utf-8"))
    if source_gate["status"] != "pass" or not all(source_gate["checks"].values()):
        raise RuntimeError("bias/reference distribution gate is not closed")
    source_gds = ROOT / source_gate["gds"]
    if sha256(source_gds) != source_gate["gds_sha256"]:
        raise RuntimeError("bias/reference gate does not bind the exact source GDS")

    blocks: dict[str, Any] = {}
    for name, record in BLOCKS.items():
        gds = ROOT / record["gds"]
        precheck_path = ROOT / record["precheck"]
        log_path = ROOT / record["magic_log"]
        precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
        log = log_path.read_text(encoding="utf-8", errors="replace")
        if precheck["status"] != "pass" or precheck["gds_sha256"] != sha256(gds):
            raise RuntimeError(f"{name} direct-GDS gate is stale")
        if marker(log, record["drc_marker"]) != 0 or marker(log, record["extraction_marker"]) != 0:
            raise RuntimeError(f"{name} Magic gate is not closed")
        blocks[name] = {
            **record,
            "gds_sha256": sha256(gds),
            "precheck_sha256": sha256(precheck_path),
            "magic_log_sha256": sha256(log_path),
            "orientation": "R0",
            "translation_um": [0.0, 0.0],
        }

    roots = source_gate["support_path_lengths_um"]
    if set(roots) != {"ref", "vbias"}:
        raise RuntimeError("support-tree gate is missing a root")
    ref_root = [125.68, 161.2]
    vbias_root = [123.98, 159.0]
    routes = {
        "ref": [
            route(ref_root, [53.0, ref_root[1]], "ref"),
            route([53.0, ref_root[1]], blocks["vcm"]["signal_root_um"], "ref"),
        ],
        "vbias": [
            route(vbias_root, [194.0, vbias_root[1]], "vbias"),
            route([194.0, vbias_root[1]], blocks["tail_bias"]["signal_root_um"], "vbias"),
        ],
    }
    return {
        "schema_version": 1,
        "status": "integration pilot; exact GDS checks pending",
        "units": "um",
        "top_cell": "v3_four_channel_shared_support_integration",
        "source": {
            "gds": source_gate["gds"],
            "gds_sha256": source_gate["gds_sha256"],
            "top_cell": "v3_four_channel_bias_reference_distribution",
            "gate": str(SOURCE_GATE.relative_to(ROOT)),
            "gate_sha256": sha256(SOURCE_GATE),
        },
        "blocks": blocks,
        "tree_roots_um": {"ref": ref_root, "vbias": vbias_root},
        "common_routes": routes,
        "via3_points_um": [[53.0, 90.0]],
        "routing_decisions": {
            "ref": "M3 west from the balanced root, then down outside the channel-array boundary",
            "vbias": "M3 east from the balanced root, then down outside the channel-array boundary",
            "support_placement": "validated support blocks remain at their original absolute coordinates in empty edge regions",
            "no_route_crosses_a_frozen_channel": True,
        },
        "constraints": {
            "blocks_are_exact_hash_bound": True,
            "all_common_route_ends_are_named_roots": True,
            "maximum_direction_reversals": 0,
            "floating_stubs_allowed": False,
            "orphan_vias_allowed": False,
            "frozen_source_geometry_modified": False,
            "gds_timestamps_canonicalized": True,
        },
        "provenance": {
            "generator": "v3/tools/build_four_channel_shared_support_integration.py",
            "generator_sha256": sha256(Path(__file__)),
            "composer": "v3/tools/compose_four_channel_shared_support_integration.py",
            "composer_sha256": sha256(ROOT / "v3/tools/compose_four_channel_shared_support_integration.py"),
        },
    }


def main() -> None:
    DEFAULT_OUTPUT.write_text(json.dumps(build(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
