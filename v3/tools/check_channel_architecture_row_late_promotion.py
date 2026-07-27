#!/usr/bin/env python3
"""Bind topology and geometry evidence for the late-promotion row pilot."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

from check_channel_architecture_row_routing import (  # noqa: E402
    audit_topology,
    markers,
    parse_mos,
)


BUILD = ROOT / "build/v3/channel_architecture_row_late_promotion"
OUTPUT = ROOT / "v3/evidence/channel_architecture_row_late_promotion_gate.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    spice = BUILD / "v3_channel_architecture_row_late_promotion_flat.spice"
    gds = BUILD / "v3_channel_architecture_row_late_promotion.gds"
    marker_path = BUILD / "physical_markers.txt"
    precheck_path = BUILD / "precheck_summary.json"
    rc_path = BUILD / "distributed_rc_audit.json"
    devices = parse_mos(spice)
    topology_errors, topology = audit_topology(devices)
    physical = markers(marker_path)
    expected_physical = {
        "V3_CHANNEL_ARCHITECTURE_ROW_LATE_DRC_COUNT": 0,
        "V3_CHANNEL_ARCHITECTURE_ROW_LATE_EXTRACTION_FEEDBACK_COUNT": 0,
        "V3_CHANNEL_ARCHITECTURE_ROW_LATE_GDS_FEEDBACK_COUNT": 0,
    }
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    rc = json.loads(rc_path.read_text(encoding="utf-8"))
    checks = {
        "magic_and_export_markers_zero": physical == expected_physical,
        "exactly_twenty_one_nmos": len(devices) == 21,
        "named_net_topology_exact": not topology_errors,
        "pinned_direct_gds_precheck_pass": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_matches_exact_gds": precheck["gds_sha256"] == sha256(gds),
        "distributed_rc_gate_passes": rc["status"] == "pass",
        "distributed_rc_matches_exact_gds": rc["gds_sha256"] == sha256(gds),
    }
    sources = {
        "baseline_unit": ROOT / "v3/layout/vector_unit_placement.json",
        "late_unit": ROOT / "v3/layout/vector_unit_late_promotion.json",
        "late_unit_builder": ROOT / "v3/tools/build_vector_unit_late_promotion.py",
        "row_generator": ROOT / "v3/tools/generate_channel_architecture_row_late_promotion_pilot.py",
        "rc_extractor": ROOT / "v3/layout/extract_channel_row_late_promotion_rc.tcl",
        "rc_auditor": ROOT / "v3/tools/check_channel_row_late_promotion_rc.py",
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "three-unit all-net row with M1 analog collection, M2 drops/spines, and unchanged M2/M3 output plus M3/M4 phase routing",
        "checks": checks,
        "physical_markers": physical,
        "device_count": len(devices),
        "topology": topology,
        "topology_errors": topology_errors,
        "distributed_rc": {
            "maximum_gate_path_ohm": max(
                value
                for view in rc["views"].values()
                for value in view["root_to_gate_ohm_left_to_right"]
            ),
            "maximum_sig_ref_pair_mismatch_percent": rc[
                "maximum_sig_ref_pair_mismatch_percent"
            ],
        },
        "artifacts": {
            "gds": str(gds.relative_to(ROOT)),
            "spice": str(spice.relative_to(ROOT)),
            "precheck": str(precheck_path.relative_to(ROOT)),
            "distributed_rc": str(rc_path.relative_to(ROOT)),
        },
        "gds_sha256": sha256(gds),
        "sha256": {
            "spice": sha256(spice),
            "physical_markers": sha256(marker_path),
            "precheck": sha256(precheck_path),
            "distributed_rc": sha256(rc_path),
            **{name: sha256(path) for name, path in sources.items()},
            "checker": sha256(Path(__file__)),
        },
        "stale_evidence_policy": "regenerate after any source, manifest, GDS, SPICE, marker, precheck, or distributed-RC change",
        "next_gate": "replicate the accepted late-promotion access into all five rows; retain an explicit bottom-row guard-safe exception",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
