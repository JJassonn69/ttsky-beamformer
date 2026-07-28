#!/usr/bin/env python3
"""Audit topology and physical evidence for the exact 15-unit V3 matrix pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from check_channel_row_extraction import audit_unit, parse_mos


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "v3" / "channel_matrix_pilot"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "channel_matrix_physical_gate.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(log: str, name: str) -> int | None:
    values = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spice", type=Path, default=BUILD / "v3_channel_matrix_pilot_flat.spice")
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_channel_matrix_pilot.gds")
    parser.add_argument("--log", type=Path, default=BUILD / "magic_extract.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument("--matrix", type=Path, default=ROOT / "v3" / "layout" / "channel_matrix_placement.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    devices = parse_mos(args.spice)
    log = args.log.read_text(encoding="utf-8", errors="replace")
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed = re.compile(r'^Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.$')
    unexpected = [line for line in warnings if not allowed.fullmatch(line)]

    expected_prefixes = [f"u{index:02d}" for index in range(15)]
    by_prefix: dict[str, list[dict[str, object]]] = defaultdict(list)
    unowned = []
    for device in devices:
        gate = str(device["g"])
        match = re.match(r"^(u\d{2})_", gate)
        if match:
            by_prefix[match.group(1)].append(device)
        else:
            unowned.append(device["name"])

    topology_errors = []
    inferred = {}
    for prefix in expected_prefixes:
        errors, nodes = audit_unit(prefix, by_prefix[prefix])
        topology_errors.extend(errors)
        inferred[prefix] = nodes
    if unowned:
        topology_errors.append(f"devices without a unit-owned gate: {unowned}")
    if set(by_prefix) != set(expected_prefixes):
        topology_errors.append(f"unit gate prefixes changed: {sorted(by_prefix)}")

    private_nodes = []
    for nodes in inferred.values():
        if "tail_node" in nodes:
            private_nodes.append(nodes["tail_node"])
        private_nodes.extend(nodes.get("gm_nodes", {}).values())
    if len(private_nodes) != len(set(private_nodes)):
        topology_errors.append("an internal tail/GM node is shared between units")

    matrix_counts: dict[str, int] = defaultdict(int)
    for item in matrix["matrix"]["instances"]:
        matrix_counts[str(item["group_weight"])] += 1
    checks = {
        "magic_drc_zero": marker(log, "V3_CHANNEL_MATRIX_DRC_COUNT") == 0,
        "magic_extraction_feedback_zero": marker(log, "V3_CHANNEL_MATRIX_EXTRACTION_FEEDBACK_COUNT") == 0,
        "magic_gds_feedback_zero": marker(log, "V3_CHANNEL_MATRIX_GDS_FEEDBACK_COUNT") == 0,
        "only_classified_magic_warnings": not unexpected,
        "exactly_one_hundred_five_nmos": len(devices) == 105,
        "exactly_fifteen_seven_device_units": set(by_prefix) == set(expected_prefixes) and all(
            len(by_prefix[prefix]) == 7 for prefix in expected_prefixes
        ),
        "all_unit_topologies_exact": not topology_errors,
        "binary_group_population_exact": dict(sorted(matrix_counts.items())) == {"1": 1, "2": 2, "4": 4, "8": 8},
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_is_for_exact_gds": precheck["gds_sha256"] == sha256(args.gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact 15-unit V3 matrix: repeated topology, R0/MY transforms, local LO merges, shared guard, and direct-GDS geometry; group H-trees absent",
        "checks": checks,
        "topology_errors": topology_errors,
        "unexpected_magic_warnings": unexpected,
        "device_count": len(devices),
        "device_counts_by_unit": {prefix: len(by_prefix[prefix]) for prefix in expected_prefixes},
        "group_counts": dict(sorted(matrix_counts.items())),
        "inferred_private_node_count": len(set(private_nodes)),
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "sha256": {
            "spice": sha256(args.spice),
            "magic_log": sha256(args.log),
            "precheck_summary": sha256(args.precheck),
            "matrix_manifest": sha256(args.matrix),
            "generator": sha256(ROOT / "v3" / "tools" / "generate_channel_matrix_pilot.py"),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "allocate eight balanced group phase trees with named layer transitions, then regenerate this exact matrix with those routes",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
