#!/usr/bin/env python3
"""Audit the final compact-input-bias GDS and Magic readback topology."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from check_channel_row_extraction import parse_mos


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "v3" / "channel_input_bias_pilot"
READBACK = ROOT / "build" / "v3" / "channel_input_bias_readback"
OUTPUT = ROOT / "v3" / "evidence" / "channel_input_bias_physical_gate.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(log: str, name: str) -> int | None:
    values = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def classified_feedback(path: Path) -> int:
    return len(re.findall(
        r'feedback add "device missing 1 terminal;\s*connecting remainder to node VGND" pale',
        path.read_text(encoding="utf-8", errors="replace"),
    ))


def main() -> None:
    raw_spice = BUILD / "v3_channel_input_bias_pilot_flat.spice"
    readback_spice = READBACK / "v3_channel_input_bias_pilot_readback.spice"
    raw_gds = BUILD / "v3_channel_input_bias_pilot_magic.gds"
    final_gds = BUILD / "v3_channel_input_bias_pilot.gds"
    raw_log_path = BUILD / "magic_extract.log"
    readback_log_path = READBACK / "magic_readback.log"
    precheck_path = BUILD / "precheck_summary.json"
    repair_path = ROOT / "v3" / "evidence" / "input_bias_urpm_repair.json"
    placement_path = ROOT / "v3" / "layout" / "compact_input_bias_placement.json"

    raw_log = raw_log_path.read_text(encoding="utf-8", errors="replace")
    readback_log = readback_log_path.read_text(encoding="utf-8", errors="replace")
    raw_text = raw_spice.read_text(encoding="utf-8")
    readback_text = readback_spice.read_text(encoding="utf-8")
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    repair = json.loads(repair_path.read_text(encoding="utf-8"))
    devices = parse_mos(readback_spice)
    inert = [item for item in devices if {str(item[key]) for key in ("d", "g", "s", "b")} == {"VGND"}]
    active = [item for item in devices if item not in inert]
    phase_counts = Counter(
        str(item["g"]) for item in active
        if re.fullmatch(r"g[1248]_(?:lop|lon)", str(item["g"]))
    )
    expected_phase = {
        f"g{group}_{polarity}": count * 2
        for group, count in ((1, 1), (2, 2), (4, 4), (8, 8))
        for polarity in ("lop", "lon")
    }
    resistor_lines = [line for line in readback_text.splitlines() if "res_xhigh_po_0p35" in line]
    checks = {
        "raw_magic_drc_zero": marker(raw_log, "V3_CHANNEL_INPUT_BIAS_DRC_COUNT") == 0,
        "raw_nine_classified_dummy_markers": marker(raw_log, "V3_CHANNEL_INPUT_BIAS_EXTRACTION_FEEDBACK_COUNT") == 9 and classified_feedback(BUILD / "extraction_feedback.txt") == 9,
        "raw_gds_feedback_zero": marker(raw_log, "V3_CHANNEL_INPUT_BIAS_GDS_FEEDBACK_COUNT") == 0,
        "no_raw_port_short_or_unknown_layer_warning": "electrically shorted" not in raw_log and "Unrecognized layer" not in raw_log,
        "final_gds_readback_drc_zero": marker(readback_log, "V3_CHANNEL_INPUT_BIAS_READBACK_DRC_COUNT") == 0,
        "final_gds_readback_nine_classified_dummy_markers": marker(readback_log, "V3_CHANNEL_INPUT_BIAS_READBACK_EXTRACTION_FEEDBACK_COUNT") == 9 and classified_feedback(READBACK / "extraction_feedback.txt") == 9,
        "final_gds_readback_feedback_cleared": marker(readback_log, "V3_CHANNEL_INPUT_BIAS_READBACK_FEEDBACK_AFTER_CLEAR") == 0,
        "no_readback_port_short_warning": "electrically shorted" not in readback_log,
        "mask_repair_preserves_exact_extracted_netlist": raw_text == readback_text,
        "active_and_dummy_device_counts_exact": len(active) == 105 and len(inert) == 9,
        "all_eight_phase_populations_exact": dict(sorted(phase_counts.items())) == dict(sorted(expected_phase.items())),
        "one_compact_resistor_between_vcm_and_element_input": resistor_lines == ["X49 vcm element_input VGND sky130_fd_pr__res_xhigh_po_0p35 l=17.36"],
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(item["markers"] == 0 for item in precheck["checks"].values()),
        "precheck_and_repair_bind_final_gds": precheck["gds_sha256"] == sha256(final_gds) == repair["output_sha256"],
        "raw_and_final_gds_are_distinct": sha256(raw_gds) != sha256(final_gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact eight-tree/dummy channel plus compact guarded input-bias resistor, grounded clock shield, direct-GDS mask repair, and final-GDS Magic readback",
        "checks": checks,
        "device_counts": {"active_nmos": len(active), "grounded_dummy_nmos": len(inert), "input_bias_resistors": len(resistor_lines)},
        "phase_switch_counts": dict(sorted(phase_counts.items())),
        "gds": str(final_gds.relative_to(ROOT)),
        "gds_sha256": sha256(final_gds),
        "raw_magic_gds_sha256": sha256(raw_gds),
        "extracted_spice_sha256": sha256(readback_spice),
        "sha256": {
            "precheck": sha256(precheck_path),
            "urpm_repair": sha256(repair_path),
            "placement": sha256(placement_path),
            "generator": sha256(ROOT / "v3" / "tools" / "generate_channel_input_bias_pilot.py"),
            "readback_tcl": sha256(ROOT / "v3" / "layout" / "readback_channel_input_bias.tcl"),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "rerun the complete four-channel support PVT set with res_xhigh_po_0p35 l=17.36, then integrate the route-closed selector",
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
