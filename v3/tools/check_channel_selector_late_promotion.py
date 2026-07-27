#!/usr/bin/env python3
"""Sign off the integrated late-promotion analog channel and selector."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from check_channel_architecture_service import parse_mos
from check_channel_phase_tree_late_promotion import audit as audit_phase_channel


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/channel_selector_late_promotion"
READBACK = ROOT / "build/v3/channel_selector_late_promotion_readback"
DEFAULT_OUTPUT = ROOT / "v3/evidence/channel_selector_late_promotion_gate.json"
ANALOG_PREFIX = "v3_channel_input_bias_late_promotion_0/"
SELECTOR_PREFIX = "v3_selector_route_pilot_0/"
JOIN_MAP = {
    "group0_lo_p": "g1_lop", "group0_lo_n": "g1_lon",
    "group1_lo_p": "g2_lop", "group1_lo_n": "g2_lon",
    "group2_lo_p": "g4_lop", "group2_lo_n": "g4_lon",
    "group3_lo_p": "g8_lop", "group3_lo_n": "g8_lon",
}
EXPECTED_ANALOG_SWITCHES = {
    "group0_lo_p": 2, "group0_lo_n": 2,
    "group1_lo_p": 4, "group1_lo_n": 4,
    "group2_lo_p": 8, "group2_lo_n": 8,
    "group3_lo_p": 16, "group3_lo_n": 16,
}
EXPECTED_TOP_LEVEL_PORTS = {
    "element_input", "ref", "vbias", "row_outp", "row_outn",
    "phase_0", "phase_90", "phase_180", "phase_270",
    *(f"group{group}_bit{bit}" for group in range(4) for bit in range(2)),
    "channel_enable", "mixers_blank", "VPWR", "VGND",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(first: float, second: float) -> bool:
    return math.isclose(first, second, rel_tol=0.0, abs_tol=1e-9)


def normalize_analog_node(node: object) -> str:
    value = str(node)
    if value.startswith(ANALOG_PREFIX):
        value = value[len(ANALOG_PREFIX):]
    if value == "element_input":
        return "sig"
    if value.startswith(SELECTOR_PREFIX):
        selector = value[len(SELECTOR_PREFIX):]
        if selector in JOIN_MAP:
            return JOIN_MAP[selector]
    return value


def parse_all_mos_lines(path: Path) -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = raw.split()
        if len(fields) < 7 or not fields[0].upper().startswith("X"):
            continue
        if "__nfet_" not in fields[5] and "__pfet_" not in fields[5]:
            continue
        devices.append({
            "name": fields[0], "d": fields[1], "g": fields[2],
            "s": fields[3], "b": fields[4], "model": fields[5],
            "raw": raw,
        })
    return devices


def marker_value(text: str, name: str) -> int | None:
    match = re.search(rf"^{re.escape(name)}=(\d+)$", text, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def audit(spice: Path) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    nfets = parse_mos(spice)
    selector_nodes = {SELECTOR_PREFIX + name for name in JOIN_MAP}

    def is_dummy(item: dict[str, object]) -> bool:
        grounded = {str(item[key]) for key in ("d", "g", "s", "b")} == {"VGND"}
        size = (
            (close(float(item["w"]), 5.07) and close(float(item["l"]), 1.0))
            or (close(float(item["w"]), 0.65) and close(float(item["l"]), 0.15))
        )
        return grounded and size

    def is_active_analog(item: dict[str, object]) -> bool:
        width, length = float(item["w"]), float(item["l"])
        if close(width, 5.07) and close(length, 1.0):
            return not is_dummy(item)
        if close(width, 0.84) and close(length, 0.6):
            return True
        return (
            close(width, 0.65) and close(length, 0.15)
            and str(item["g"]) in selector_nodes
            and any(str(item[key]).startswith(ANALOG_PREFIX) for key in ("d", "s"))
        )

    dummies = [item for item in nfets if is_dummy(item)]
    active = [item for item in nfets if is_active_analog(item)]
    normalized = [
        {
            **item,
            **{key: normalize_analog_node(item[key]) for key in ("d", "g", "s", "b")},
        }
        for item in active
    ]
    phase_errors, phase_topology = audit_phase_channel(normalized)
    errors.extend(phase_errors)
    dummy_sizes = Counter((float(item["w"]), float(item["l"])) for item in dummies)
    if dummy_sizes != {(5.07, 1.0): 3, (0.65, 0.15): 6}:
        errors.append(f"grounded edge-dummy population changed: {dict(dummy_sizes)}")

    text = spice.read_text(encoding="utf-8", errors="replace")
    xlines = [line for line in text.splitlines() if line.startswith("X")]
    root_checks: dict[str, Any] = {}
    for selector, expected_analog in EXPECTED_ANALOG_SWITCHES.items():
        node = SELECTOR_PREFIX + selector
        hits = [line for line in xlines if re.search(rf"(?:^|\s){re.escape(node)}(?:\s|$)", line)]
        analog_hits = [line for line in hits if ANALOG_PREFIX in line]
        group = int(selector[5])
        expected_cell = f"G{group}_LO_{'P_AND' if selector.endswith('_p') else 'N_ANDNOT'}"
        selector_hits = [line for line in hits if expected_cell in line and ANALOG_PREFIX not in line]
        wrong_cells = sorted({
            match.group(0)
            for line in hits
            for match in re.finditer(r"G[0-3]_LO_(?:P_AND|N_ANDNOT)", line)
            if match.group(0) != expected_cell
        })
        passed = (
            len(analog_hits) == expected_analog
            and len(selector_hits) == 2
            and not wrong_cells
        )
        if not passed:
            errors.append(
                f"{selector} join differs: analog={len(analog_hits)} "
                f"selector={len(selector_hits)} wrong={wrong_cells}"
            )
        root_checks[selector] = {
            "analog_switch_gate_hits": len(analog_hits),
            "expected_analog_switch_gate_hits": expected_analog,
            "selector_output_device_hits": len(selector_hits),
            "expected_selector_cell": expected_cell,
            "wrong_selector_cells": wrong_cells,
            "connected": passed,
        }

    root_aliases = [SELECTOR_PREFIX + name for name in JOIN_MAP]
    for line in xlines:
        found = [name for name in root_aliases if re.search(rf"(?:^|\s){re.escape(name)}(?:\s|$)", line)]
        if len(found) > 1:
            errors.append(f"device terminal contains multiple joined roots: {found}")

    resistors = [line.split() for line in xlines if "sky130_fd_pr__res_xhigh_po_0p35" in line]
    resistor_ok = (
        len(resistors) == 1
        and {normalize_analog_node(node) for node in resistors[0][1:4]} == {"ref", "sig", "VGND"}
        and "l=17.36" in resistors[0]
    )
    if not resistor_ok:
        errors.append("compact input-bias resistor terminals or dimensions changed")

    all_mos = parse_all_mos_lines(spice)
    bad_bodies = [
        item["name"]
        for item in all_mos
        if item["b"] != ("VGND" if "__nfet_" in item["model"] else "VPWR")
    ]
    if bad_bodies:
        errors.append(f"floating or mis-biased MOS bodies remain: {bad_bodies}")
    forbidden_supply_nodes = sorted({
        item[key]
        for item in all_mos
        for key in ("d", "g", "s", "b")
        if item[key] == "VSUBS"
        or re.search(r"/(?:VPWR|VGND|VNB|VPB)$", item[key])
    })
    if forbidden_supply_nodes:
        errors.append(f"unclosed hierarchical supply nodes remain: {forbidden_supply_nodes}")
    if not any("VPWR" in (item["d"], item["s"], item["b"]) for item in all_mos):
        errors.append("VPWR does not reach the selector devices")
    if not any("VGND" in (item["d"], item["s"], item["b"]) for item in all_mos):
        errors.append("VGND does not reach the selector/analog devices")
    extracted_nodes = {
        item[key] for item in all_mos for key in ("d", "g", "s", "b")
    } | {node for resistor in resistors for node in resistor[1:4]}
    missing_ports = sorted(EXPECTED_TOP_LEVEL_PORTS - extracted_nodes)
    hierarchical_port_aliases = sorted({
        node
        for node in extracted_nodes
        if any(node.endswith("/" + name) for name in EXPECTED_TOP_LEVEL_PORTS)
    })
    if missing_ports:
        errors.append(f"top-level interface ports missing after extraction: {missing_ports}")
    if hierarchical_port_aliases:
        errors.append(f"external ports remain trapped below the integration top: {hierarchical_port_aliases}")

    return errors, {
        "extracted_x_device_count": len(xlines),
        "mos_count": len(all_mos),
        "nfet_count": len(nfets),
        "active_analog_nmos_count": len(active),
        "grounded_edge_dummy_count": len(dummies),
        "phase_channel": phase_topology,
        "selector_root_joins": root_checks,
        "input_bias_resistor_ok": resistor_ok,
        "misbiased_mos_bodies": bad_bodies,
        "unclosed_hierarchical_supply_nodes": forbidden_supply_nodes,
        "top_level_ports": sorted(EXPECTED_TOP_LEVEL_PORTS - set(missing_ports)),
        "missing_top_level_ports": missing_ports,
        "hierarchical_external_port_aliases": hierarchical_port_aliases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    gds = BUILD / "v3_channel_selector_late_promotion.gds"
    spice = READBACK / "v3_channel_selector_late_promotion_flat.spice"
    magic_log = READBACK / "magic_readback.log"
    precheck_path = BUILD / "precheck_summary.json"
    frozen_path = BUILD / "frozen_routing_subset.json"
    join_path = ROOT / "v3/layout/channel_selector_join_late_promotion.json"
    selector_gate_path = ROOT / "v3/evidence/selector_route_late_promotion.json"
    input_gate_path = ROOT / "v3/evidence/channel_input_bias_late_promotion_gate.json"

    topology_errors, topology = audit(spice)
    log_text = magic_log.read_text(encoding="utf-8", errors="replace")
    markers = {
        "drc": marker_value(log_text, "V3_CHANNEL_SELECTOR_LATE_READBACK_DRC_COUNT"),
        "extraction": marker_value(log_text, "V3_CHANNEL_SELECTOR_LATE_READBACK_EXTRACTION_FEEDBACK_COUNT"),
        "after_clear": marker_value(log_text, "V3_CHANNEL_SELECTOR_LATE_READBACK_FEEDBACK_AFTER_CLEAR"),
    }
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    join = json.loads(join_path.read_text(encoding="utf-8"))
    selector_gate = json.loads(selector_gate_path.read_text(encoding="utf-8"))
    input_gate = json.loads(input_gate_path.read_text(encoding="utf-8"))
    gds_hash = sha256(gds)
    checks = {
        "magic_readback_drc_zero": markers["drc"] == 0,
        "only_nine_expected_grounded_dummy_notices": markers["extraction"] == 9,
        "magic_feedback_clears_to_zero": markers["after_clear"] == 0,
        "integrated_topology_exact": not topology_errors,
        "expected_total_extracted_devices": topology["extracted_x_device_count"] == 323,
        "all_eight_selector_roots_connected_once": all(
            item["connected"] for item in topology["selector_root_joins"].values()
        ),
        "vpwr_vgnd_separate_and_all_wells_closed": (
            not topology["misbiased_mos_bodies"]
            and not topology["unclosed_hierarchical_supply_nodes"]
        ),
        "compact_input_bias_resistor_connected": topology["input_bias_resistor_ok"],
        "all_twenty_one_external_ports_promoted": (
            len(topology["top_level_ports"]) == 21
            and not topology["missing_top_level_ports"]
            and not topology["hierarchical_external_port_aliases"]
        ),
        "direct_gds_precheck_zero": (
            precheck["status"] == "pass"
            and all(item["markers"] == 0 for item in precheck["checks"].values())
        ),
        "precheck_matches_exact_gds": precheck["gds_sha256"] == gds_hash,
        "frozen_analog_and_phase_routing_preserved": frozen["status"] == "pass",
        "frozen_subset_matches_exact_gds": frozen["candidate"]["sha256"] == gds_hash,
        "source_gates_passed": selector_gate["status"] == "pass" and input_gate["status"] == "pass",
        "straight_equal_length_phase_joins": (
            join["constraints"]["all_drawn_vertical_lengths_equal"]
            and join["constraints"]["no_horizontal_fanout"]
            and join["constraints"]["maximum_direction_reversals"] == 0
        ),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "15-cell weighted analog channel, edge dummies, compact input bias, shared guard, eight late-root phase joins, and local digital selector supply closure",
        "checks": checks,
        "topology": topology,
        "topology_errors": topology_errors,
        "magic_markers": markers,
        "gds": str(gds.relative_to(ROOT)),
        "gds_sha256": gds_hash,
        "sha256": {
            "spice": sha256(spice),
            "magic_log": sha256(magic_log),
            "precheck": sha256(precheck_path),
            "frozen_subset": sha256(frozen_path),
            "join_manifest": sha256(join_path),
            "join_builder": sha256(ROOT / "v3/tools/build_channel_selector_join_late_promotion.py"),
            "merge_script": sha256(ROOT / "v3/layout/merge_channel_selector_late_promotion.rb"),
            "checker": sha256(Path(__file__)),
        },
        "next_gate": "distributed-RC extraction of the integrated phase roots, then flattened visual review",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
