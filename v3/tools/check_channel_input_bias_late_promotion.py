#!/usr/bin/env python3
"""Audit the repaired, connected late-promotion input-bias GDS."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from check_channel_architecture_service import markers, parse_mos
from check_channel_phase_tree_late_promotion import audit


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/channel_input_bias_late_promotion"
READBACK = ROOT / "build/v3/channel_input_bias_late_promotion_readback"
OUTPUT = ROOT / "v3/evidence/channel_input_bias_late_promotion_gate.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(log: str, name: str) -> int | None:
    values = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def main() -> None:
    raw_spice = BUILD / "v3_channel_input_bias_late_promotion_flat.spice"
    readback_spice = READBACK / "v3_channel_input_bias_late_promotion_readback.spice"
    raw_gds = BUILD / "v3_channel_input_bias_late_promotion_magic.gds"
    final_gds = BUILD / "v3_channel_input_bias_late_promotion.gds"
    raw_log_path = BUILD / "magic_extract.log"
    readback_log_path = READBACK / "magic_readback.log"
    marker_path = BUILD / "physical_markers.txt"
    precheck_path = BUILD / "precheck_summary.json"
    frozen_path = BUILD / "frozen_routing_subset.json"
    repair_path = ROOT / "v3/evidence/input_bias_late_promotion_urpm_repair.json"
    placement_path = ROOT / "v3/layout/compact_input_bias_late_promotion.json"

    raw_text = raw_spice.read_text(encoding="utf-8")
    readback_text = readback_spice.read_text(encoding="utf-8")
    devices = parse_mos(readback_spice)
    inert = [item for item in devices if {str(item[key]) for key in ("d", "g", "s", "b")} == {"VGND"}]
    active = [dict(item) for item in devices if item not in inert]
    # Reuse the frozen phase-tree topology auditor after mapping the final
    # external pin name back to the internal role it checks.
    for item in active:
        if item["g"] == "element_input":
            item["g"] = "sig"
    topology_errors, topology = audit(active)
    resistor_lines = [line for line in readback_text.splitlines() if "res_xhigh_po_0p35" in line]
    resistor_ok = len(resistor_lines) == 1 and re.fullmatch(
        r"X\S+ ref element_input VGND sky130_fd_pr__res_xhigh_po_0p35 l=17\.36",
        resistor_lines[0],
    ) is not None
    raw_log = raw_log_path.read_text(encoding="utf-8", errors="replace")
    readback_log = readback_log_path.read_text(encoding="utf-8", errors="replace")
    physical = markers(marker_path)
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    repair = json.loads(repair_path.read_text(encoding="utf-8"))
    checks = {
        "raw_magic_markers_exact": physical == {
            "V3_CHANNEL_INPUT_BIAS_LATE_DRC_COUNT": 0,
            "V3_CHANNEL_INPUT_BIAS_LATE_EXTRACTION_FEEDBACK_COUNT": 9,
            "V3_CHANNEL_INPUT_BIAS_LATE_GDS_FEEDBACK_COUNT": 0,
        },
        "raw_no_port_short_warning": "electrically shorted" not in raw_log,
        "final_readback_drc_zero": marker(readback_log, "V3_CHANNEL_INPUT_BIAS_LATE_READBACK_DRC_COUNT") == 0,
        "final_readback_nine_dummy_markers": marker(readback_log, "V3_CHANNEL_INPUT_BIAS_LATE_READBACK_EXTRACTION_FEEDBACK_COUNT") == 9,
        "final_readback_feedback_cleared": marker(readback_log, "V3_CHANNEL_INPUT_BIAS_LATE_READBACK_FEEDBACK_AFTER_CLEAR") == 0,
        "final_no_port_short_warning": "electrically shorted" not in readback_log,
        "mask_repair_preserves_exact_netlist": raw_text == readback_text,
        "active_and_dummy_counts_exact": len(active) == 105 and len(inert) == 9,
        "active_topology_unchanged": not topology_errors,
        "one_resistor_connects_ref_to_element_input": resistor_ok,
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(item["markers"] == 0 for item in precheck["checks"].values()),
        "precheck_and_repair_bind_final_gds": precheck["gds_sha256"] == sha256(final_gds) == repair["output_sha256"],
        "frozen_edge_and_phase_routing_preserved": frozen["status"] == "pass" and frozen["candidate"]["sha256"] == sha256(final_gds),
        "raw_and_final_gds_are_distinct": sha256(raw_gds) != sha256(final_gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "connected element-input-to-ref bias resistor beneath the frozen phase/dummy channel with common grounded guard",
        "checks": checks,
        "topology": topology,
        "topology_errors": topology_errors,
        "resistor_line": resistor_lines,
        "gds": str(final_gds.relative_to(ROOT)),
        "gds_sha256": sha256(final_gds),
        "sha256": {
            "raw_spice": sha256(raw_spice), "readback_spice": sha256(readback_spice),
            "raw_magic_gds": sha256(raw_gds), "raw_magic_log": sha256(raw_log_path),
            "readback_log": sha256(readback_log_path), "precheck": sha256(precheck_path),
            "frozen_routing": sha256(frozen_path), "repair": sha256(repair_path),
            "placement": sha256(placement_path), "generator": sha256(ROOT / "v3/tools/generate_channel_input_bias_late_promotion_pilot.py"),
            "checker": sha256(Path(__file__)),
        },
        "next_gate": "place the rebuilt root-aligned selector and add only eight short vertical phase joins",
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
