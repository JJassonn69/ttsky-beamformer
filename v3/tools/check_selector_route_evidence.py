#!/usr/bin/env python3
"""Summarize the bounded V3 selector route, DRC, and extraction pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILD = ROOT / "build" / "v3" / "selector_route_pilot"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "selector_route_pilot.json"
PLACEMENT = ROOT / "v3" / "layout" / "selector_placement.json"
ROUTE_GENERATOR = ROOT / "v3" / "tools" / "generate_selector_route_pilot.py"
PRECHECK_RUNNER = ROOT / "v3" / "tools" / "run_selector_precheck.py"
CELL_SPICE = {
    "mux2": ROOT / "third_party" / "sky130_fd_sc_hd_cells" / "sky130_fd_sc_hd__mux2_1.spice",
    "and2": ROOT / "third_party" / "sky130_fd_sc_hd_cells" / "sky130_fd_sc_hd__and2_1.spice",
    "and2b": ROOT / "third_party" / "sky130_fd_sc_hd_cells" / "sky130_fd_sc_hd__and2b_1.spice",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def count_spice_devices(path: Path) -> int:
    return sum(line.startswith("X") for line in path.read_text(encoding="utf-8").splitlines())


def boundary_nets() -> list[str]:
    return [
        "phase_0", "phase_90", "phase_180", "phase_270",
        *(f"group{group}_bit{bit}" for group in range(4) for bit in range(2)),
        "channel_enable", "mixers_blank",
        *(f"group{group}_lo_{side}" for group in range(4) for side in ("p", "n")),
    ]


def summarize(build: Path) -> dict[str, Any]:
    placement = json.loads(PLACEMENT.read_text(encoding="utf-8"))
    input_summary = json.loads((build / "input_summary.json").read_text(encoding="utf-8"))
    openroad_log = (build / "openroad.log").read_text(encoding="utf-8", errors="replace")
    magic_log = (build / "magic_extract.log").read_text(encoding="utf-8", errors="replace")
    flat_path = build / "v3_selector_route_pilot_flat.spice"
    flat_lines = flat_path.read_text(encoding="utf-8", errors="replace").splitlines()
    device_lines = [line for line in flat_lines if line.startswith("X")]
    extracted_nodes = {token for line in device_lines for token in line.split()[1:5]}
    expected_boundary = boundary_nets()
    missing_boundary = sorted(set(expected_boundary) - extracted_nodes)

    role_counts: dict[str, int] = {}
    for item in placement["channel_template"]["instances"]:
        role = item["cell_role"]
        role_counts[role] = role_counts.get(role, 0) + 1
    expected_devices = sum(role_counts.get(role, 0) * count_spice_devices(path) for role, path in CELL_SPICE.items())

    violation_matches = [int(value) for value in re.findall(r"Number of violations = (\d+)", openroad_log)]
    wire_matches = [int(value) for value in re.findall(r"Total wire length = (\d+) um", openroad_log)]
    via_matches = [int(value) for value in re.findall(r"Total number of vias = (\d+)", openroad_log)]
    pin_access = re.search(r"#stdCellPinNoAp\s*=\s*(\d+)", openroad_log)
    magic_version = re.search(r"Magic ([0-9.]+) revision (\d+)", magic_log)
    magic_drc = re.search(r"V3_SELECTOR_ROUTE_MAGIC_DRC_COUNT=(\d+)", magic_log)
    extraction_feedback = re.search(r"V3_SELECTOR_ROUTE_EXTRACTION_FEEDBACK_COUNT=(\d+)", magic_log)
    gds_feedback = re.search(r"V3_SELECTOR_ROUTE_GDS_FEEDBACK_COUNT=(\d+)", magic_log)
    import_errors = len(re.findall(r"DEF read, Line \d+ \(Error\)", magic_log))
    guide_total = (build / "guide_coverage.csv").read_text(encoding="utf-8").splitlines()[-1].split(",")[-2]
    precheck_files = {
        "feol": "precheck_feol.xml",
        "beol": "precheck_beol.xml",
        "offgrid": "precheck_offgrid.xml",
        "zero_area": "precheck_zero_area.xml",
        "pin_purpose_overlap": "precheck_pin_purpose_overlap.xml",
    }
    precheck_markers = {
        name: len(ET.parse(build / filename).getroot().findall(".//items/item"))
        for name, filename in precheck_files.items()
    }

    errors: list[str] = []
    checks = {
        "component_count": input_summary.get("component_count") == len(placement["channel_template"]["instances"]),
        "pin_count": input_summary.get("pin_count") == 22,
        "net_count": input_summary.get("net_count") == 35,
        "openroad_final_drc_zero": bool(violation_matches) and violation_matches[-1] == 0,
        "openroad_all_standard_cell_pins_accessible": bool(pin_access) and int(pin_access.group(1)) == 0,
        "openroad_drc_report_empty": (build / "detailed_route_drc.rpt").stat().st_size == 0,
        "magic_def_import_errors_zero": import_errors == 0,
        "magic_drc_zero": bool(magic_drc) and int(magic_drc.group(1)) == 0,
        "magic_extraction_feedback_zero": bool(extraction_feedback) and int(extraction_feedback.group(1)) == 0,
        "magic_gds_feedback_zero": bool(gds_feedback) and int(gds_feedback.group(1)) == 0,
        "extracted_device_count_matches_library": len(device_lines) == expected_devices,
        "all_boundary_nets_survive_extraction": not missing_boundary,
        "tiny_tapeout_pilot_geometry_precheck_zero": all(value == 0 for value in precheck_markers.values()),
    }
    for name, passed in checks.items():
        if not passed:
            errors.append(name)

    artifact_names = (
        "input.def", "input_summary.json", "route.tcl", "routed.def", "detailed_route_drc.rpt",
        "guide_coverage.csv", "wire_length.csv", "openroad.log", "magic_extract.log",
        "v3_selector_route_pilot.gds", "v3_selector_route_pilot_flat.spice",
        "precheck_summary.json",
    )
    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "scope": "one complete V3 per-channel selector signal-route pilot; full four-channel integration, power, antenna, timing/skew, and analog-core routing remain outside this gate",
        "selected_constraints": {
            "row_gap_um": placement["channel_template"]["row_gap_um"],
            "row_gap_routing_tracks": round(placement["channel_template"]["row_gap_um"] / 0.34),
            "signal_cell_gap_sites": placement["channel_template"]["cell_gap_sites"],
            "signal_cell_gap_um": placement["channel_template"]["cell_site_width_um"],
            "filler_cells_per_channel": role_counts["fill"],
        },
        "design_counts": {
            "components": input_summary["component_count"],
            "functional_and_tap_components": input_summary["component_count"] - role_counts["fill"],
            "filler_components": role_counts["fill"],
            "boundary_pins": input_summary["pin_count"],
            "signal_nets": input_summary["net_count"],
            "extracted_transistors": len(device_lines),
            "expected_transistors_from_library": expected_devices,
        },
        "route_results": {
            "openroad_detailed_route_violations": violation_matches[-1] if violation_matches else None,
            "openroad_unreachable_standard_cell_pins": int(pin_access.group(1)) if pin_access else None,
            "detailed_wire_length_um": wire_matches[-1] if wire_matches else None,
            "via_count": via_matches[-1] if via_matches else None,
            "guide_coverage_total": guide_total,
        },
        "independent_magic_results": {
            "version": f"{magic_version.group(1)} revision {magic_version.group(2)}" if magic_version else None,
            "def_import_errors": import_errors,
            "drc_errors": int(magic_drc.group(1)) if magic_drc else None,
            "extraction_feedback": int(extraction_feedback.group(1)) if extraction_feedback else None,
            "gds_writer_feedback": int(gds_feedback.group(1)) if gds_feedback else None,
            "missing_boundary_nets_after_flat_extraction": missing_boundary,
        },
        "tiny_tapeout_precheck_compatible_geometry": {
            "status": "pass" if all(value == 0 for value in precheck_markers.values()) else "fail",
            "marker_counts": precheck_markers,
            "support_tools_commit": "d65690eeb1d4afd26aef795c805a23d9d9daf9d1",
            "klayout_version": "0.30.9",
            "sky130_rule_deck_release": "2025.10.29_01.10",
            "scope_note": "directly applicable pilot-GDS geometry decks only; full wrapper/pin/boundary/interface checks require the integrated Tiny Tapeout top level",
        },
        "checks": checks,
        "rejected_or_diagnostic_candidates": [
            {"row_gap_um": 0.00, "cell_gap_sites": 0, "result": "10 LI spacing violations before bounded run was stopped", "disposition": "rejected"},
            {"row_gap_um": 0.68, "cell_gap_sites": 0, "result": "7 LI spacing violations", "disposition": "rejected"},
            {"row_gap_um": 1.00, "cell_gap_sites": 0, "result": "off 0.34 um routing grid", "disposition": "invalid and stopped"},
            {"row_gap_um": 1.02, "cell_gap_sites": 0, "result": "vertical spacing did not target horizontal abutment failures", "disposition": "diagnostic and stopped"},
            {"row_gap_um": 0.68, "cell_gap_sites": 1, "result": "route/Magic clean but 33 official MR_nwell.SP.1 FEOL markers", "disposition": "rejected"},
            {"row_gap_um": 0.00, "cell_gap_sites": 1, "result": "0 route/Magic/FEOL/BEOL/off-grid/zero-area/pin-overlap markers", "disposition": "selected"},
        ],
        "provenance": {
            "openroad_version": "v2.0-17598-ga008522d8",
            "openroad_binary_sha256": "93fe61454a52b927602fd6c798c4402214c19e80e7d614636345f0f427ea2f46",
            "sky130_commit": "0536d02d875c8f67dd7cca3902ac457e62f20005",
            "technology_lef_sha256": "8e99b4e8b016db0713029ebcae6b2cc2aedd9c2c49682e2f23521dd0b1a2085e",
            "merged_cell_lef_sha256": "44180aaa0068b1fcb0789f128b090304c01ad48f511d3f7afa66c90b3e176ec5",
            "tiny_tapeout_support_tools_commit": "d65690eeb1d4afd26aef795c805a23d9d9daf9d1",
            "selector_placement": "v3/layout/selector_placement.json",
            "selector_placement_sha256": sha256(PLACEMENT),
            "route_generator": "v3/tools/generate_selector_route_pilot.py",
            "route_generator_sha256": sha256(ROUTE_GENERATOR),
            "precheck_runner": "v3/tools/run_selector_precheck.py",
            "precheck_runner_sha256": sha256(PRECHECK_RUNNER),
            "artifacts": {
                **{name: sha256(build / name) for name in artifact_names},
                **{filename: sha256(build / filename) for filename in precheck_files.values()},
            },
        },
        "remaining_gates": [
            "route and compare all four selector copies with balanced phase-spine and LO-output skew constraints",
            "add and verify VPWR/VGND straps plus antenna repair",
            "extract routed selector RC and verify phase/control timing across PVT",
            "integrate with the analog cores and complete direct-GDS DRC/LVS/PEX signoff",
            "run the complete official Tiny Tapeout wrapper/LEF/Verilog/power/analog-pin/boundary precheck on the integrated top-level artifact",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = summarize(args.build)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
