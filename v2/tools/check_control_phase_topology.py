#!/usr/bin/env python3
"""Audit extracted phase-control joins and preserve all standard-cell supplies."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from check_control_power_topology import POWER_EXPECTED, expected_helper_cells, logical_lines
from check_magic_rc_log import FATAL_PATTERNS


TOP = "v2_control_phase_routed"


def parse(
    text: str, top: str = TOP
) -> tuple[dict[str, list[str]], list[list[str]]]:
    signatures: dict[str, list[str]] = {}
    statements: list[list[str]] = []
    active = ""
    for line in logical_lines(text):
        if line.lower().startswith(".subckt "):
            tokens = line.split(); active = tokens[1]; signatures[active] = tokens[2:]
        elif line.lower() == ".ends":
            active = ""
        elif active == top and line.startswith("X"):
            statements.append(line.split())
    if top not in signatures: raise ValueError(f"missing .subckt {top}")
    return signatures, statements


def audit(
    spice: str,
    mapping: dict[str, Any],
    log: str,
    top: str = TOP,
    marker_prefix: str = "CONTROL_PHASE",
    physical_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    signatures, statements = parse(spice, top)
    attachments: dict[str, list[tuple[str, str, str]]] = {}
    for statement in statements:
        cell, nets = statement[-1], statement[1:-1]
        signature = signatures.get(cell)
        if signature is None or len(signature) != len(nets): continue
        for pin, net in zip(signature, nets):
            attachments.setdefault(net, []).append((statement[0], cell, pin))

    role_checks: list[dict[str, Any]] = []
    helper_roles = {
        "phase_select0": (("PMUX_A", "S"), ("PMUX_B", "S")),
        "phase_select1": (("PMUX_P", "S"), ("PMUX_N", "S")),
        "phase_enable": (("PAND_P", "B"), ("PAND_N", "B")),
    }
    driver_cells = {
        item["net"]: next(e["cell"] for e in item["endpoints"] if e["kind"] == "standard_cell_pin")
        for item in mapping["phase_routes"]
    }
    for channel in range(4):
        for signal, roles in helper_roles.items():
            net = f"{signal}[{channel}]"
            expected_helpers = {f"XCH{channel}_{name}.{pin}" for name, pin in roles}
            role_nets: dict[str, list[str]] = {}
            for expected_role in expected_helpers:
                expected_instance, expected_pin = expected_role.rsplit(".", 1)
                role_nets[expected_role] = [
                    extracted_net
                    for extracted_net, items in attachments.items()
                    if any(instance == expected_instance and pin == expected_pin
                           for instance, _cell, pin in items)
                ]
            candidate_nets = {item for nets in role_nets.values() for item in nets}
            extracted_net = next(iter(candidate_nets)) if len(candidate_nets) == 1 else None
            attached = attachments.get(extracted_net, []) if extracted_net else []
            driver = [item for item in attached if item[1] == driver_cells[net] and item[2] == "X"
                      and item[0].startswith("Xsky130_fd_sc_hd__")]
            actual_helpers = {f"{instance}.{pin}" for instance, _cell, pin in attached
                              if instance.startswith(f"XCH{channel}_")}
            expected_alias = (
                f"ch{channel}_phase_sel{signal[-1]}"
                if signal.startswith("phase_select")
                else f"ch{channel}_phase_enable"
            )
            role_checks.append({"net": net, "extracted_net": extracted_net,
                                "driver_count": len(driver),
                                "helper_roles": sorted(actual_helpers)})
            if any(len(nets) != 1 for nets in role_nets.values()):
                errors.append(f"{net}: helper pins do not each resolve to one extracted net: {role_nets}")
            if len(candidate_nets) != 1:
                errors.append(f"{net}: helper roles span extracted nets {sorted(candidate_nets)}")
            allowed_aliases = {net, expected_alias}
            if physical_labels and net in physical_labels:
                allowed_aliases.add(physical_labels[net])
            if len(candidate_nets) == 1 and extracted_net not in allowed_aliases:
                errors.append(f"{net}: unexpected extracted alias {extracted_net}")
            if len(driver) != 1: errors.append(f"{net}: extracted {len(driver)} core output drivers")
            if actual_helpers != expected_helpers:
                errors.append(f"{net}: helper roles {sorted(actual_helpers)} != {sorted(expected_helpers)}")

    extracted_phase_nets = [item["extracted_net"] for item in role_checks
                            if item["extracted_net"] is not None]
    if len(set(extracted_phase_nets)) != 12:
        errors.append("phase-control handoffs are not twelve independent extracted nets")

    expected_mapped = {f"sky130_fd_sc_hd__{name}_1": count
                       for name, count in mapping["mapping"]["counts"]["by_cell"].items()}
    mapped_instances = [s for s in statements if s[0].startswith("Xsky130_fd_sc_hd__")
                        and s[-1] in expected_mapped]
    if Counter(s[-1] for s in mapped_instances) != Counter(expected_mapped):
        errors.append("mapped standard-cell counts changed in phase extraction")
    helper_expected = expected_helper_cells()
    by_name = {s[0][1:]: s for s in statements if s[0][1:] in helper_expected}
    if set(by_name) != set(helper_expected): errors.append("fixed helper-cell set changed")
    verified_power_pins = 0
    signal_power_shorts = 0
    for statement in mapped_instances + list(by_name.values()):
        signature = signatures.get(statement[-1], []); nets = statement[1:-1]
        if len(signature) != len(nets): errors.append(f"{statement[0]} port alignment failed"); continue
        attached = dict(zip(signature, nets))
        for pin, expected in POWER_EXPECTED.items():
            if attached.get(pin) == expected: verified_power_pins += 1
            else: errors.append(f"{statement[0]}.{pin}={attached.get(pin)}, expected {expected}")
        for pin, net in attached.items():
            if pin not in POWER_EXPECTED and net in ("VDPWR", "VGND"):
                signal_power_shorts += 1; errors.append(f"{statement[0]}.{pin} is shorted to {net}")

    fatal = {name: pattern.search(log).group(0) for name, pattern in FATAL_PATTERNS.items()
             if pattern.search(log)}
    if fatal: errors.append(f"Magic phase extraction log has fatal markers: {fatal}")
    for marker in (f"{marker_prefix}_EXTRACTION_DRC_COUNT=0",
                   f"{marker_prefix}_EXTRACTION_FEEDBACK_COUNT=0",
                   f"{marker_prefix}_HIER_SPICE=", f"{marker_prefix}_FLAT_SPICE="):
        if marker not in log: errors.append(f"Magic phase extraction log lacks {marker}")
    if log.count("exttospice finished.") < 2: errors.append("both phase topology views were not written")

    return {"status": "pass" if not errors else "fail", "errors": errors,
            "verified_phase_net_count": len(role_checks), "phase_role_checks": role_checks,
            "mapped_standard_cell_count": len(mapped_instances),
            "fixed_helper_standard_cell_count": len(by_name),
            "verified_standard_cell_power_and_body_pins": verified_power_pins,
            "unexpected_signal_to_power_short_count": signal_power_shorts,
            "magic_log_fatal_matches": fatal,
            "magic_exttospice_completion_count": log.count("exttospice finished.")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spice", type=Path, default=Path("build/v2/control_routing/phase_extraction/control_phase_hier.spice"))
    parser.add_argument("--mapping", type=Path, default=Path("build/v2/control_mapping/physical_netlist.json"))
    parser.add_argument("--allocation", type=Path, default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--log", type=Path, default=Path("build/v2/control_routing/direct/phase_magic_extraction.log"))
    parser.add_argument("--report", type=Path, default=Path("build/v2/control_routing/phase_extraction/topology_audit.json"))
    parser.add_argument("--top", default=TOP)
    parser.add_argument("--marker-prefix", default="CONTROL_PHASE")
    parser.add_argument(
        "--openroad-geometry", type=Path,
        default=Path("build/v2/control_routing/openroad_route_geometry.json"),
    )
    args = parser.parse_args()
    combined = {"mapping": json.loads(args.mapping.read_text()),
                "phase_routes": [item for item in json.loads(args.allocation.read_text())["nets"]
                                 if item["class"] == "phase_handoff"]}
    openroad = json.loads(args.openroad_geometry.read_text())
    physical_labels = {
        logical: physical for physical, logical in openroad["label_net_map"].items()
    }
    report = audit(args.spice.read_text(errors="replace"), combined,
                   args.log.read_text(errors="replace"), args.top,
                   args.marker_prefix, physical_labels)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass": raise SystemExit(1)


if __name__ == "__main__":
    main()
