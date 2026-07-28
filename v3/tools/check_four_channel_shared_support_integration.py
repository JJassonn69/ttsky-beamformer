#!/usr/bin/env python3
"""Audit exact shared-support integration and the merged REF/VBIAS topology."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/four_channel_shared_support_integration"
DEFAULT_OUTPUT = ROOT / "v3/evidence/four_channel_shared_support_integration_gate.json"
CHANNEL_PREFIX = (
    "v3_four_channel_bias_reference_distribution_0/v3_four_channel_phase_distribution_0/"
    "v3_four_channel_output_collection_0/v3_four_channel_placement_0/"
    "v3_channel_selector_late_promotion_"
)
PHASE_PREFIX = "v3_four_channel_bias_reference_distribution_0/v3_four_channel_phase_distribution_0/"
OUTPUT_PREFIX = PHASE_PREFIX + "v3_four_channel_output_collection_0/"
ISOLATED_INTERFACES = [
    "element_input", *(f"group{group}_bit{bit}" for group in range(4) for bit in range(2)),
    "channel_enable", "mixers_blank", "VPWR",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(text: str, name: str) -> int | None:
    match = re.search(rf"^{re.escape(name)}=(\d+)$", text, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_four_channel_shared_support_integration.gds")
    parser.add_argument("--spice", type=Path, default=BUILD / "readback/v3_four_channel_shared_support_integration_flat.spice")
    parser.add_argument("--magic-log", type=Path, default=BUILD / "magic_readback.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "v3/layout/four_channel_shared_support_integration.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = []
    nodes: set[str] = set()
    models = Counter()
    for line in args.spice.read_text(encoding="utf-8").splitlines():
        if not line.startswith("X"):
            continue
        row = line.split()
        model_index = next(index for index, value in enumerate(row) if value.startswith("sky130_"))
        rows.append(row)
        nodes.update(row[1:model_index])
        models[row[model_index]] += 1
    log = args.magic_log.read_text(encoding="utf-8", errors="replace")
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    ref_nodes = sorted(node for node in nodes if node.endswith("/ref"))
    vbias_nodes = sorted(node for node in nodes if node.endswith("/vbias"))
    ref_hits = sum(rows_item[1:5].count(ref_nodes[0]) for rows_item in rows) if len(ref_nodes) == 1 else 0
    vbias_hits = sum(rows_item[1:5].count(vbias_nodes[0]) for rows_item in rows) if len(vbias_nodes) == 1 else 0
    phase_hits = {
        name: sum(row[1:5].count(PHASE_PREFIX + name) for row in rows)
        for name in ("phase_0", "phase_90", "phase_180", "phase_270")
    }
    output_hits = {
        polarity: sum(row[1:5].count(OUTPUT_PREFIX + f"combined_{polarity}_internal") for row in rows)
        for polarity in ("p", "n")
    }
    observed_isolated = {
        name: sorted(node for node in nodes if node.endswith("/" + name))
        for name in ISOLATED_INTERFACES
    }
    expected_isolated = {
        name: [f"{CHANNEL_PREFIX}{channel}/{name}" for channel in range(4)]
        for name in ISOLATED_INTERFACES
    }
    cross_channel_rows = []
    for row in rows:
        found = sorted(set(re.findall(rf"{re.escape(CHANNEL_PREFIX)}([0-3])/", " ".join(row))))
        if len(found) > 1:
            cross_channel_rows.append(" ".join(row))
    vdpwr_nodes = sorted(node for node in nodes if node.endswith("/VDPWR"))
    unprefixed = sorted(node for node in nodes if "/" not in node and node != "VSUBS")

    checks = {
        "source_is_exact_gated_bias_reference_distribution": (
            manifest["source"]["gds_sha256"]
            == json.loads((ROOT / "v3/evidence/four_channel_bias_reference_distribution_gate.json").read_text())["gds_sha256"]
        ),
        "both_support_blocks_are_hash_bound": all(
            sha256(ROOT / record["gds"]) == record["gds_sha256"]
            for record in manifest["blocks"].values()
        ),
        "gds_matches_precheck": precheck["gds_sha256"] == sha256(args.gds),
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "magic_drc_zero": marker(log, "V3_FOUR_CHANNEL_SUPPORT_DRC_COUNT") == 0,
        "only_nine_hierarchical_dummy_feedback_markers": marker(
            log, "V3_FOUR_CHANNEL_SUPPORT_EXTRACTION_FEEDBACK_COUNT"
        ) == 9,
        "device_population_is_exact": len(rows) == 1312,
        "model_population_is_exact": models == {
            "sky130_fd_pr__nfet_01v8": 880,
            "sky130_fd_pr__pfet_01v8_hvt": 416,
            "sky130_fd_pr__res_xhigh_po_0p35": 4,
            "sky130_fd_pr__res_xhigh_po_1p41": 6,
            "sky130_fd_pr__res_high_po_1p41": 1,
            "sky130_fd_pr__cap_mim_m3_1": 5,
        },
        "one_shared_ref_node_reaches_channels_and_vcm": len(ref_nodes) == 1 and ref_hits == 69,
        "one_shared_vbias_node_reaches_channels_and_tail_support": len(vbias_nodes) == 1 and vbias_hits == 79,
        "phase_trees_remain_exactly_32_terminals_each": set(phase_hits.values()) == {32},
        "output_collector_remains_exactly_120_per_polarity": output_hits == {"p": 120, "n": 120},
        "other_channel_interfaces_remain_isolated": observed_isolated == expected_isolated,
        "support_power_inputs_remain_two_named_nodes_until_power_stage": len(vdpwr_nodes) == 2,
        "no_device_bridges_two_channel_namespaces": not cross_channel_rows,
        "no_unexpected_unprefixed_nodes": not unprefixed,
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact VCM/tail-bias block placement, edge routes, direct geometry, and flat topology",
        "checks": checks,
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "device_count": len(rows),
        "model_population": dict(sorted(models.items())),
        "shared_nodes": {"ref": ref_nodes, "vbias": vbias_nodes},
        "shared_terminal_hits": {"ref": ref_hits, "vbias": vbias_hits},
        "phase_terminal_hits": phase_hits,
        "output_terminal_hits": output_hits,
        "support_vdpwr_nodes": vdpwr_nodes,
        "cross_channel_device_rows": cross_channel_rows,
        "unexpected_unprefixed_nodes": unprefixed,
        "sha256": {
            "manifest": sha256(args.manifest),
            "flat_spice": sha256(args.spice),
            "magic_log": sha256(args.magic_log),
            "precheck": sha256(args.precheck),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "add matched differential output loads and pad escapes, then close shared power, control, and analog-input routing",
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
