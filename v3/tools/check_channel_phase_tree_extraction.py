#!/usr/bin/env python3
"""Audit topology and physical evidence for the eight-tree V3 channel pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from check_channel_row_extraction import audit_unit, parse_mos


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "v3" / "channel_phase_tree_pilot"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "channel_phase_tree_physical_gate.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(log: str, name: str) -> int | None:
    values = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spice", type=Path, default=BUILD / "v3_channel_phase_tree_pilot_flat.spice")
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_channel_phase_tree_pilot.gds")
    parser.add_argument("--log", type=Path, default=BUILD / "magic_extract.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument("--matrix", type=Path, default=ROOT / "v3" / "layout" / "channel_matrix_placement.json")
    parser.add_argument("--trees", type=Path, default=ROOT / "v3" / "layout" / "group_phase_trees.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    devices = parse_mos(args.spice)
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    trees = json.loads(args.trees.read_text(encoding="utf-8"))
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    log = args.log.read_text(encoding="utf-8", errors="replace")
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed = re.compile(r'^Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.$')
    unexpected = [line for line in warnings if not allowed.fullmatch(line)]

    unit_group = {
        f"u{index:02d}": int(instance["group_weight"])
        for index, instance in enumerate(sorted(
            matrix["matrix"]["instances"],
            key=lambda item: (item["row_top_to_bottom"], item["column_left_to_right"]),
        ))
    }
    by_prefix: dict[str, list[dict[str, object]]] = defaultdict(list)
    ownership_errors = []
    observed_phase_gates: Counter[str] = Counter()
    for device in devices:
        copied = dict(device)
        gate_match = re.match(r"^(u\d{2})_", str(device["g"]))
        output_prefixes = {
            match.group(1)
            for node in (str(device["d"]), str(device["s"]))
            if (match := re.match(r"^(u\d{2})_out[pn]$", node))
        }
        if gate_match:
            prefix = gate_match.group(1)
        elif len(output_prefixes) == 1 and re.fullmatch(r"g[1248]_(?:lop|lon)", str(device["g"])):
            prefix = next(iter(output_prefixes))
            expected_group = unit_group.get(prefix)
            expected_gate = f"g{expected_group}_{str(device['g']).rsplit('_', 1)[1]}"
            if device["g"] != expected_gate:
                ownership_errors.append(
                    f"{device['name']} owned by {prefix} uses {device['g']}, expected {expected_gate}"
                )
            observed_phase_gates[str(device["g"])] += 1
            copied["g"] = f"{prefix}_{str(device['g']).rsplit('_', 1)[1]}"
        else:
            ownership_errors.append(
                f"cannot assign {device['name']} gate={device['g']} outputs={sorted(output_prefixes)}"
            )
            continue
        by_prefix[prefix].append(copied)

    expected_prefixes = [f"u{index:02d}" for index in range(15)]
    topology_errors = list(ownership_errors)
    inferred = {}
    for prefix in expected_prefixes:
        errors, nodes = audit_unit(prefix, by_prefix[prefix])
        topology_errors.extend(errors)
        inferred[prefix] = nodes

    private_nodes = []
    for nodes in inferred.values():
        if "tail_node" in nodes:
            private_nodes.append(nodes["tail_node"])
        private_nodes.extend(nodes.get("gm_nodes", {}).values())
    if len(private_nodes) != len(set(private_nodes)):
        topology_errors.append("an internal tail/GM node is shared between units")

    expected_phase_gate_counts = {
        f"g{group}_{polarity}": count * 2
        for group, count in ((1, 1), (2, 2), (4, 4), (8, 8))
        for polarity in ("lop", "lon")
    }
    manifest_via2_count = sum(
        len(path.get("via2_points", [])) + len(path.get("compact_via2_points", []))
        for tree in trees["trees"].values() for path in tree["paths"]
    )
    manifest_via3_count = sum(
        len(path.get("via3_points", [])) + len(path.get("compact_via3_points", []))
        for tree in trees["trees"].values() for path in tree["paths"]
    )
    checks = {
        "magic_drc_zero": marker(log, "V3_CHANNEL_PHASE_TREE_DRC_COUNT") == 0,
        "magic_extraction_feedback_zero": marker(log, "V3_CHANNEL_PHASE_TREE_EXTRACTION_FEEDBACK_COUNT") == 0,
        "magic_gds_feedback_zero": marker(log, "V3_CHANNEL_PHASE_TREE_GDS_FEEDBACK_COUNT") == 0,
        "only_classified_magic_warnings": not unexpected,
        "exactly_one_hundred_five_nmos": len(devices) == 105,
        "exactly_fifteen_seven_device_units": set(by_prefix) == set(expected_prefixes) and all(
            len(by_prefix[prefix]) == 7 for prefix in expected_prefixes
        ),
        "all_unit_topologies_exact": not topology_errors,
        "all_eight_group_phase_gates_exact": dict(sorted(observed_phase_gates.items())) == dict(sorted(expected_phase_gate_counts.items())),
        "exactly_eight_named_tree_roots": set(trees["trees"]) == set(expected_phase_gate_counts),
        "exactly_two_m2_centre_bridges": manifest_via2_count == 4,
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_is_for_exact_gds": precheck["gds_sha256"] == sha256(args.gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact 15-unit channel plus eight 1/2/4/8 LON/LOP phase trees; Magic topology and independent direct-GDS geometry",
        "checks": checks,
        "topology_errors": topology_errors,
        "unexpected_magic_warnings": unexpected,
        "device_count": len(devices),
        "device_counts_by_unit": {prefix: len(by_prefix[prefix]) for prefix in expected_prefixes},
        "phase_switch_counts": dict(sorted(observed_phase_gates.items())),
        "manifest_via2_count": manifest_via2_count,
        "manifest_via3_count": manifest_via3_count,
        "m2_bridge_scope": "two G8-LON centre taps only; each enters/exits M2 in a quiet inter-row gap",
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "sha256": {
            "spice": sha256(args.spice),
            "magic_log": sha256(args.log),
            "precheck_summary": sha256(args.precheck),
            "matrix_manifest": sha256(args.matrix),
            "phase_tree_manifest": sha256(args.trees),
            "generator": sha256(ROOT / "v3" / "tools" / "generate_channel_phase_tree_pilot.py"),
            "planner": sha256(ROOT / "v3" / "tools" / "plan_group_phase_trees.py"),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "distributed-RC extraction of all eight root-to-leaf trees, followed by edge-dummy and input-bias integration",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
