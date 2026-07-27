#!/usr/bin/env python3
"""Audit the balanced four-channel differential current-summing collector."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/four_channel_output_collection"
DEFAULT_OUTPUT = ROOT / "v3/evidence/four_channel_output_collection_gate.json"
PREFIX = "v3_four_channel_placement_0/v3_channel_selector_late_promotion_"
ISOLATED_INTERFACES = [
    "element_input", "ref", "vbias",
    "phase_0", "phase_90", "phase_180", "phase_270",
    *(f"group{group}_bit{bit}" for group in range(4) for bit in range(2)),
    "channel_enable", "mixers_blank", "VPWR",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(text: str, name: str) -> int | None:
    match = re.search(rf"^{re.escape(name)}=(\d+)$", text, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_four_channel_output_collection.gds")
    parser.add_argument("--spice", type=Path, default=BUILD / "readback/v3_four_channel_output_collection_flat.spice")
    parser.add_argument("--magic-log", type=Path, default=BUILD / "magic_readback.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "v3/layout/four_channel_output_collection.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = [
        line.split() for line in args.spice.read_text(encoding="utf-8").splitlines()
        if line.startswith("X")
    ]
    nodes: set[str] = set()
    models = Counter()
    for row in rows:
        model_index = next(index for index, value in enumerate(row) if value.startswith("sky130_"))
        nodes.update(row[1:model_index])
        models[row[model_index]] += 1
    log = args.magic_log.read_text(encoding="utf-8", errors="replace")
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    cross_channel_rows = []
    for row in rows:
        found = sorted(set(re.findall(rf"{re.escape(PREFIX)}([0-3])/", " ".join(row))))
        if len(found) > 1:
            cross_channel_rows.append(" ".join(row))
    expected_isolated = {
        name: [f"{PREFIX}{channel}/{name}" for channel in range(4)]
        for name in ISOLATED_INTERFACES
    }
    observed_isolated = {
        name: sorted(node for node in nodes if node.endswith("/" + name))
        for name in ISOLATED_INTERFACES
    }
    combined_hits = {
        name: sum(row[1:5].count(name) for row in rows)
        for name in ("combined_p_internal", "combined_n_internal")
    }
    combined_rows = [
        row for row in rows
        if "combined_p_internal" in row[1:5] or "combined_n_internal" in row[1:5]
    ]
    stale_output_nodes = sorted(
        node for node in nodes if node.endswith("/row_outp") or node.endswith("/row_outn")
    )
    unprefixed = sorted(
        node for node in nodes
        if node not in {"VSUBS", "combined_p_internal", "combined_n_internal"}
        and not node.startswith(PREFIX)
    )

    checks = {
        "source_is_exact_gated_placement": (
            manifest["source"]["gds_sha256"]
            == json.loads((ROOT / "v3/evidence/four_channel_placement_gate.json").read_text())["gds_sha256"]
        ),
        "gds_matches_precheck": precheck["gds_sha256"] == sha256(args.gds),
        "direct_gds_precheck_zero": (
            precheck["status"] == "pass"
            and all(item["markers"] == 0 for item in precheck["checks"].values())
        ),
        "magic_drc_zero": marker(log, "V3_FOUR_CHANNEL_OUTPUT_DRC_COUNT") == 0,
        "only_nine_hierarchical_dummy_feedback_markers": (
            marker(log, "V3_FOUR_CHANNEL_OUTPUT_EXTRACTION_FEEDBACK_COUNT") == 9
        ),
        "device_population_unchanged": len(rows) == 1292,
        "model_population_unchanged": models == {
            "sky130_fd_pr__nfet_01v8": 872,
            "sky130_fd_pr__pfet_01v8_hvt": 416,
            "sky130_fd_pr__res_xhigh_po_0p35": 4,
        },
        "both_collectors_reach_exactly_120_output_terminals": combined_hits == {
            "combined_p_internal": 120,
            "combined_n_internal": 120,
        },
        "collectors_touch_only_0p65um_nfet_switches": all(
            row[5] == "sky130_fd_pr__nfet_01v8" and "w=0.65" in row
            for row in combined_rows
        ),
        "no_per_channel_output_nodes_remain": not stale_output_nodes,
        "other_channel_interfaces_remain_isolated": observed_isolated == expected_isolated,
        "no_device_bridges_two_channel_namespaces": not cross_channel_rows,
        "no_unexpected_unprefixed_nodes": not unprefixed,
        "all_paths_equal_within_each_polarity": all(
            tree["equal_length_for_all_four_sources"] for tree in manifest["trees"].values()
        ),
        "p_root_compensation_is_explicit": (
            manifest["routing_decisions"]["p_root_compensation_required_um"] == 2.0
        ),
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "four-channel differential current-summing H-trees: direct geometry, flat topology, and namespace isolation",
        "checks": checks,
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "device_count": len(rows),
        "models": dict(sorted(models.items())),
        "combined_terminal_hits": combined_hits,
        "stale_output_nodes": stale_output_nodes,
        "cross_channel_device_rows": cross_channel_rows,
        "unexpected_unprefixed_nodes": unprefixed,
        "path_lengths_um": {
            polarity: tree["source_to_root_length_um"]
            for polarity, tree in manifest["trees"].items()
        },
        "p_root_compensation_required_um": manifest["routing_decisions"]["p_root_compensation_required_um"],
        "sha256": {
            "manifest": sha256(args.manifest),
            "flat_spice": sha256(args.spice),
            "magic_log": sha256(args.magic_log),
            "precheck": sha256(args.precheck),
            "auditor": sha256(Path(__file__)),
        },
        "rejected_candidate": {
            "architecture": "N collector promoted to Metal 4 inside the channel corridor",
            "reason": "Magic extracted combined_n on 352 terminals because the vertical M4 escapes crossed selector phase conductors",
        },
        "next_gate": "connect matched root-to-load/pad escapes while adding 2.0 um to P, then run distributed conductor RC",
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
