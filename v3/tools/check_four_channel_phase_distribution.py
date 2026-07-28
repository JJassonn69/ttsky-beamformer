#!/usr/bin/env python3
"""Audit the four shared, length-matched phase H-trees."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/four_channel_phase_distribution"
DEFAULT_OUTPUT = ROOT / "v3/evidence/four_channel_phase_distribution_gate.json"
CHANNEL_PREFIX = (
    "v3_four_channel_output_collection_0/v3_four_channel_placement_0/"
    "v3_channel_selector_late_promotion_"
)
OUTPUT_PREFIX = "v3_four_channel_output_collection_0/"
PHASES = ["phase_0", "phase_90", "phase_180", "phase_270"]
ISOLATED_INTERFACES = [
    "element_input", "ref", "vbias",
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
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_four_channel_phase_distribution.gds")
    parser.add_argument("--spice", type=Path, default=BUILD / "readback/v3_four_channel_phase_distribution_flat.spice")
    parser.add_argument("--magic-log", type=Path, default=BUILD / "magic_readback.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "v3/layout/four_channel_phase_distribution.json")
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

    phase_hits = {name: sum(row[1:5].count(name) for row in rows) for name in PHASES}
    hierarchical_phase_nodes = sorted(
        node for node in nodes if any(node.endswith("/" + phase) for phase in PHASES)
    )
    observed_isolated = {
        name: sorted(node for node in nodes if node.endswith("/" + name))
        for name in ISOLATED_INTERFACES
    }
    expected_isolated = {
        name: [f"{CHANNEL_PREFIX}{channel}/{name}" for channel in range(4)]
        for name in ISOLATED_INTERFACES
    }
    output_hits = {
        polarity: sum(row[1:5].count(OUTPUT_PREFIX + f"combined_{polarity}_internal") for row in rows)
        for polarity in ("p", "n")
    }
    cross_channel_rows = []
    for row in rows:
        found = sorted(set(re.findall(rf"{re.escape(CHANNEL_PREFIX)}([0-3])/", " ".join(row))))
        if len(found) > 1:
            cross_channel_rows.append(" ".join(row))
    allowed_top_nodes = {"VSUBS", *PHASES}
    unprefixed = sorted(
        node for node in nodes
        if node not in allowed_top_nodes
        and not node.startswith(CHANNEL_PREFIX)
        and not node.startswith(OUTPUT_PREFIX)
    )
    lengths = {
        name: record["source_to_root_length_um"]
        for name, record in manifest["trees"].items()
    }

    checks = {
        "source_is_exact_gated_output_collector": (
            manifest["source"]["gds_sha256"]
            == json.loads((ROOT / "v3/evidence/four_channel_output_collection_gate.json").read_text())["gds_sha256"]
        ),
        "gds_matches_precheck": precheck["gds_sha256"] == sha256(args.gds),
        "direct_gds_precheck_zero": (
            precheck["status"] == "pass"
            and all(item["markers"] == 0 for item in precheck["checks"].values())
        ),
        "magic_drc_zero": marker(log, "V3_FOUR_CHANNEL_PHASE_DRC_COUNT") == 0,
        "only_nine_hierarchical_dummy_feedback_markers": (
            marker(log, "V3_FOUR_CHANNEL_PHASE_EXTRACTION_FEEDBACK_COUNT") == 9
        ),
        "device_population_unchanged": len(rows) == 1292,
        "model_population_unchanged": models == {
            "sky130_fd_pr__nfet_01v8": 872,
            "sky130_fd_pr__pfet_01v8_hvt": 416,
            "sky130_fd_pr__res_xhigh_po_0p35": 4,
        },
        "each_shared_phase_reaches_exactly_32_selector_terminals": (
            set(phase_hits.values()) == {32}
        ),
        "no_hierarchical_phase_nodes_remain": not hierarchical_phase_nodes,
        "output_collector_remains_exactly_120_per_polarity": output_hits == {"p": 120, "n": 120},
        "other_channel_interfaces_remain_isolated": observed_isolated == expected_isolated,
        "no_device_bridges_two_channel_namespaces": not cross_channel_rows,
        "no_unexpected_unprefixed_nodes": not unprefixed,
        "all_sixteen_phase_paths_are_geometrically_equal": set(lengths.values()) == {37.97},
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "four shared phase inputs: matched top-corridor H-trees, direct geometry, and flat topology",
        "checks": checks,
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "device_count": len(rows),
        "phase_terminal_hits": phase_hits,
        "phase_path_lengths_um": lengths,
        "output_terminal_hits": output_hits,
        "hierarchical_phase_nodes": hierarchical_phase_nodes,
        "cross_channel_device_rows": cross_channel_rows,
        "unexpected_unprefixed_nodes": unprefixed,
        "sha256": {
            "manifest": sha256(args.manifest),
            "flat_spice": sha256(args.spice),
            "magic_log": sha256(args.magic_log),
            "precheck": sha256(args.precheck),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "place shared bias/reference support and route symmetric ref/vbias trees without entering the closed output or phase corridors",
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
