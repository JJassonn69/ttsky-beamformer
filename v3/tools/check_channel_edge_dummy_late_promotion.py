#!/usr/bin/env python3
"""Audit late-promotion edge dummies without weakening topology checks."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from check_channel_architecture_service import markers, parse_mos
from check_channel_phase_tree_late_promotion import audit


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/channel_edge_dummy_late_promotion"
OUTPUT = ROOT / "v3/evidence/channel_edge_dummy_late_promotion_gate.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    spice = BUILD / "v3_channel_edge_dummy_late_promotion_flat.spice"
    gds = BUILD / "v3_channel_edge_dummy_late_promotion.gds"
    marker_path = BUILD / "physical_markers.txt"
    log_path = BUILD / "magic_extract.log"
    feedback_path = BUILD / "extraction_feedback.txt"
    precheck_path = BUILD / "precheck_summary.json"
    frozen_path = BUILD / "frozen_routing_subset.json"
    manifest_path = ROOT / "v3/layout/channel_edge_dummies_late_promotion.json"

    devices = parse_mos(spice)
    inert = [
        item for item in devices
        if {str(item[key]) for key in ("d", "g", "s", "b")} == {"VGND"}
    ]
    active = [item for item in devices if item not in inert]
    topology_errors, topology = audit(active)
    physical = markers(marker_path)
    expected_physical = {
        "V3_CHANNEL_EDGE_DUMMY_LATE_DRC_COUNT": 0,
        "V3_CHANNEL_EDGE_DUMMY_LATE_EXTRACTION_FEEDBACK_COUNT": 9,
        "V3_CHANNEL_EDGE_DUMMY_LATE_GDS_FEEDBACK_COUNT": 0,
    }
    feedback = feedback_path.read_text(encoding="utf-8", errors="replace")
    classified = len(re.findall(
        r'device missing 1 terminal;\s*connecting remainder to node VGND', feedback
    ))
    log = log_path.read_text(encoding="utf-8", errors="replace")
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed = re.compile(r'^Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.$')
    unexpected_warnings = [line for line in warnings if not allowed.fullmatch(line)]
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    checks = {
        "magic_markers_exact": physical == expected_physical,
        "only_nine_classified_inert_dummy_markers": classified == 9,
        "no_unexpected_magic_warnings": not unexpected_warnings,
        "active_device_count_unchanged": len(active) == 105,
        "grounded_dummy_device_count_exact": len(inert) == 9,
        "active_topology_unchanged": not topology_errors,
        "all_eight_phase_populations_exact": topology.get("switch_gate_counts") == {
            "g1_lon": 2, "g1_lop": 2, "g2_lon": 4, "g2_lop": 4,
            "g4_lon": 8, "g4_lop": 8, "g8_lon": 16, "g8_lop": 16,
        },
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_matches_exact_gds": precheck["gds_sha256"] == sha256(gds),
        "frozen_routing_is_geometrically_preserved": frozen["status"] == "pass" and frozen["candidate"]["sha256"] == sha256(gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "frozen late-promotion phase channel plus enlarged shared guard and nine grounded edge dummies",
        "checks": checks,
        "physical_markers": physical,
        "topology": topology,
        "topology_errors": topology_errors,
        "classified_dummy_feedback_count": classified,
        "unexpected_magic_warnings": unexpected_warnings,
        "gds": str(gds.relative_to(ROOT)),
        "gds_sha256": sha256(gds),
        "sha256": {
            "spice": sha256(spice), "magic_log": sha256(log_path),
            "precheck": sha256(precheck_path), "frozen_routing": sha256(frozen_path),
            "manifest": sha256(manifest_path),
            "generator": sha256(ROOT / "v3/tools/generate_channel_edge_dummy_late_promotion_pilot.py"),
            "checker": sha256(Path(__file__)),
        },
        "next_gate": "compact input-bias resistor and direct sig/vcm connections",
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
