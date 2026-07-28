#!/usr/bin/env python3
"""Freeze evidence for the exact one-channel selector/tree integration gate."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "v3" / "channel_selector_pilot"
READBACK = ROOT / "build" / "v3" / "channel_selector_readback"
MANIFEST = ROOT / "v3" / "layout" / "channel_selector_join.json"
OUTPUT = ROOT / "v3" / "evidence" / "channel_selector_physical_gate.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def value(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    precheck = json.loads((BUILD / "precheck_summary.json").read_text(encoding="utf-8"))
    topology = json.loads((BUILD / "topology.json").read_text(encoding="utf-8"))
    log = (READBACK / "readback.log").read_text(encoding="utf-8", errors="replace")
    gds = BUILD / "v3_channel_selector_pilot.gds"
    marker_counts = {name: item["markers"] for name, item in precheck["checks"].items() if "markers" in item}
    magic = {
        "drc_errors": value(r"V3_CHANNEL_SELECTOR_READBACK_DRC_COUNT=(\d+)", log),
        "extraction_feedback": value(r"V3_CHANNEL_SELECTOR_READBACK_EXTRACTION_FEEDBACK_COUNT=(\d+)", log),
        "feedback_after_intentional_dummy_clear": value(r"V3_CHANNEL_SELECTOR_READBACK_FEEDBACK_AFTER_CLEAR=(\d+)", log),
    }
    checks = {
        "eight_root_aligned_joins": len(manifest["joins"]) == 8,
        "zero_direction_reversals": all(item["direction_reversals"] == 0 for item in manifest["joins"]),
        "equal_drawn_join_lengths": len({item["drawn_vertical_length_um"] for item in manifest["joins"]}) == 1,
        "one_via2_and_via3_per_join": all(len(item["transitions"]) == 2 for item in manifest["joins"]),
        "magic_drc_zero": magic["drc_errors"] == 0,
        "only_nine_intentional_dummy_extraction_markers": magic["extraction_feedback"] == 9,
        "magic_feedback_cleared": magic["feedback_after_intentional_dummy_clear"] == 0,
        "all_joined_nets_survive_topology": topology["status"] == "pass" and all(item["connected"] for item in topology["joins"]),
        "no_wrong_selector_output_cell": all(not item["wrong_selector_output_cells"] for item in topology["joins"]),
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(count == 0 for count in marker_counts.values()),
        "precheck_binds_canonical_gds": precheck["gds_sha256"] == sha256(gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "one exact root-aligned selector joined to one 15-unit analog channel; selector power/global phase inputs and four-channel replication remain separate gates",
        "checks": checks,
        "join_metrics": {
            "count": len(manifest["joins"]),
            "drawn_vertical_length_um": manifest["joins"][0]["drawn_vertical_length_um"],
            "direction_reversals_per_join": 0,
            "via2_per_join": 1,
            "via3_per_join": 1,
            "horizontal_fanout_um": 0.0,
        },
        "magic_readback": magic,
        "topology": topology,
        "direct_gds_marker_counts": marker_counts,
        "gds": str(gds.relative_to(ROOT)),
        "gds_sha256": sha256(gds),
        "provenance": {
            "manifest": str(MANIFEST.relative_to(ROOT)),
            "manifest_sha256": sha256(MANIFEST),
            "merger": "v3/layout/merge_channel_selector.rb",
            "merger_sha256": sha256(ROOT / "v3" / "layout" / "merge_channel_selector.rb"),
            "readback": "v3/layout/readback_channel_selector.tcl",
            "readback_sha256": sha256(ROOT / "v3" / "layout" / "readback_channel_selector.tcl"),
            "topology_checker": "v3/tools/check_channel_selector_extraction.py",
            "topology_checker_sha256": sha256(ROOT / "v3" / "tools" / "check_channel_selector_extraction.py"),
            "selector_route_gate_sha256": sha256(ROOT / "v3" / "evidence" / "selector_route_pilot.json"),
            "analog_channel_gate_sha256": sha256(ROOT / "v3" / "evidence" / "channel_input_bias_physical_gate.json"),
            "precheck_summary_sha256": sha256(BUILD / "precheck_summary.json"),
            "readback_log_sha256": sha256(READBACK / "readback.log"),
            "flat_spice_sha256": sha256(READBACK / "v3_channel_selector_pilot_flat.spice"),
        },
        "remaining_gates": [
            "selector VPWR/VGND straps and shared guard integration",
            "one-channel output collection",
            "four-channel replication and differential summing",
            "distributed-RC timing/extracted beam-mode regression",
        ],
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": checks, "join_metrics": report["join_metrics"]}, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
