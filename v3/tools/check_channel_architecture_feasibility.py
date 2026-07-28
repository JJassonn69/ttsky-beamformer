#!/usr/bin/env python3
"""Audit the selected exact matrix and real-pitch adjacent-guard pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MATRIX_BUILD = ROOT / "build/v3/channel_architecture_feasibility"
PAIR_BUILD = ROOT / "build/v3/channel_architecture_guard_pair"
DEFAULT_OUTPUT = ROOT / "v3/evidence/channel_architecture_feasibility_gate.json"
PREFIX = "v3_channel_architecture_feasibility_"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def markers(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        result[key] = int(value)
    return result


def owner(node: str) -> int | None:
    match = re.match(rf"^{re.escape(PREFIX)}([01])/", node)
    return int(match.group(1)) if match else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    architecture = ROOT / "v3/layout/channel_routing_architecture.json"
    matrix_manifest = MATRIX_BUILD / "channel_matrix_placement.json"
    matrix_gds = MATRIX_BUILD / "v3_channel_architecture_feasibility.gds"
    matrix_marker_path = MATRIX_BUILD / "physical_markers.txt"
    pair_gds = PAIR_BUILD / "v3_channel_architecture_guard_pair.gds"
    pair_spice = PAIR_BUILD / "v3_channel_architecture_guard_pair_flat.spice"
    pair_marker_path = PAIR_BUILD / "physical_markers.txt"

    matrix_markers = markers(matrix_marker_path)
    pair_markers = markers(pair_marker_path)
    devices: list[list[str]] = []
    for raw in pair_spice.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = raw.split()
        if len(fields) >= 10 and fields[0].upper().startswith("X") and fields[5] == "sky130_fd_pr__nfet_01v8":
            devices.append(fields)

    gate_owner_counts = {0: 0, 1: 0}
    mixed_owner_devices: list[str] = []
    unowned_signal_nodes: set[str] = set()
    per_owner_nodes: dict[int, set[str]] = {0: set(), 1: set()}
    for fields in devices:
        gate_owner = owner(fields[2])
        if gate_owner is not None:
            gate_owner_counts[gate_owner] += 1
        node_owners = {value for value in (owner(node) for node in fields[1:5]) if value is not None}
        if len(node_owners) > 1:
            mixed_owner_devices.append(fields[0])
        if gate_owner is not None:
            for node in fields[1:5]:
                if node != "VSUBS":
                    per_owner_nodes[gate_owner].add(node)
                    if owner(node) is None:
                        unowned_signal_nodes.add(node)

    shared_non_ground_nodes = sorted(per_owner_nodes[0] & per_owner_nodes[1])
    expected_matrix = {
        "V3_CHANNEL_ARCHITECTURE_DRC_COUNT": 0,
        "V3_CHANNEL_ARCHITECTURE_EXTRACTION_FEEDBACK_COUNT": 0,
        "V3_CHANNEL_ARCHITECTURE_GDS_FEEDBACK_COUNT": 0,
    }
    expected_pair = {
        "V3_CHANNEL_GUARD_PAIR_DRC_COUNT": 0,
        "V3_CHANNEL_GUARD_PAIR_EXTRACTION_FEEDBACK_COUNT": 0,
        "V3_CHANNEL_GUARD_PAIR_GDS_FEEDBACK_COUNT": 0,
    }
    checks = {
        "selected_architecture_geometry_pass": json.loads(architecture.read_text(encoding="utf-8"))["candidates"]["dual_service_corridors"]["geometry_status"] == "pass",
        "single_matrix_magic_markers_zero": matrix_markers == expected_matrix,
        "adjacent_pair_magic_markers_zero": pair_markers == expected_pair,
        "two_exact_105_mos_channels": len(devices) == 210 and gate_owner_counts == {0: 105, 1: 105},
        "no_device_touches_both_channel_namespaces": not mixed_owner_devices,
        "no_non_ground_node_shared_between_channels": not shared_non_ground_nodes,
        "no_unowned_non_ground_signal_node": not unowned_signal_nodes,
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "selected 6.96 um equal-column-pitch matrix plus two exact copies at the real 19.32 um channel pitch; local unit topology, shared guards, DRC, extraction feedback, and channel-to-channel short audit",
        "checks": checks,
        "physical_markers": {"single_matrix": matrix_markers, "adjacent_pair": pair_markers},
        "device_count": len(devices),
        "device_count_by_channel_namespace": gate_owner_counts,
        "mixed_owner_devices": mixed_owner_devices,
        "shared_non_ground_nodes": shared_non_ground_nodes,
        "unowned_non_ground_signal_nodes": sorted(unowned_signal_nodes),
        "geometry": {
            "column_pitch_um": 6.96,
            "channel_pitch_um": 19.32,
            "projected_active_array_gap_um": 0.84,
        },
        "artifacts": {
            "architecture": str(architecture.relative_to(ROOT)),
            "matrix_manifest": str(matrix_manifest.relative_to(ROOT)),
            "matrix_gds": str(matrix_gds.relative_to(ROOT)),
            "pair_gds": str(pair_gds.relative_to(ROOT)),
            "pair_spice": str(pair_spice.relative_to(ROOT)),
        },
        "sha256": {
            "architecture": sha256(architecture),
            "matrix_manifest": sha256(matrix_manifest),
            "matrix_gds": sha256(matrix_gds),
            "matrix_markers": sha256(matrix_marker_path),
            "pair_gds": sha256(pair_gds),
            "pair_spice": sha256(pair_spice),
            "pair_markers": sha256(pair_marker_path),
            "generator": sha256(ROOT / "v3/tools/generate_channel_architecture_feasibility_pilot.py"),
            "composer": sha256(ROOT / "v3/tools/compose_channel_architecture_guard_pair.rb"),
            "checker": sha256(Path(__file__)),
        },
        "next_gate": "exact one-row pilot with both M2 service corridors and all nine reserved row tracks",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
