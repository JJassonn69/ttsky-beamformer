#!/usr/bin/env python3
"""Audit four extracted quadrature drivers, digital loads, and selector leaves."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from check_control_power_topology import POWER_EXPECTED, expected_helper_cells, logical_lines
from check_magic_rc_log import FATAL_PATTERNS

TOP = "v2_control_quadrature_routed"


def parse(text: str) -> tuple[dict[str, list[str]], list[list[str]]]:
    signatures: dict[str, list[str]] = {}
    statements: list[list[str]] = []
    active = ""
    for line in logical_lines(text):
        if line.lower().startswith(".subckt "):
            tokens = line.split(); active = tokens[1]; signatures[active] = tokens[2:]
        elif line.lower() == ".ends":
            active = ""
        elif active == TOP and line.startswith("X"):
            statements.append(line.split())
    if TOP not in signatures: raise ValueError(f"missing .subckt {TOP}")
    return signatures, statements


def audit(spice: str, mapping: dict[str, Any], routes: list[dict[str, Any]], log: str,
          physical_labels: dict[str, str] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    signatures, statements = parse(spice)
    attachments: dict[str, list[tuple[str, str, str]]] = {}
    for statement in statements:
        cell, nets = statement[-1], statement[1:-1]
        signature = signatures.get(cell)
        if signature is None or len(signature) != len(nets): continue
        for pin, net in zip(signature, nets):
            attachments.setdefault(net, []).append((statement[0], cell, pin))

    helper_contract = {
        0: ("PMUX_A", "A0", "ch0_phase_0_leaf"),
        1: ("PMUX_A", "A1", "ch0_phase_90_leaf"),
        2: ("PMUX_B", "A0", "ch0_phase_180_leaf"),
        3: ("PMUX_B", "A1", "ch0_phase_270_leaf"),
    }
    checks: list[dict[str, Any]] = []
    extracted_nets: list[str] = []
    by_net = {item["net"]: item for item in routes}
    for index in range(4):
        logical_net = f"phase_wave[{index}]"
        helper_name, helper_pin, alias = helper_contract[index]
        expected_helpers = {f"XCH{channel}_{helper_name}.{helper_pin}" for channel in range(4)}
        role_nets: dict[str, list[str]] = {}
        for role in expected_helpers:
            instance, pin = role.rsplit(".", 1)
            role_nets[role] = [net for net, items in attachments.items()
                               if any(item[0] == instance and item[2] == pin for item in items)]
        candidates = {net for nets in role_nets.values() for net in nets}
        extracted = next(iter(candidates)) if len(candidates) == 1 else None
        attached = attachments.get(extracted, []) if extracted else []
        actual_helpers = {f"{instance}.{pin}" for instance, _cell, pin in attached
                          if instance.startswith("XCH")}
        expected_mapped = Counter((item["cell"], item["pin"])
                                  for item in by_net[logical_net]["endpoints"]
                                  if item["kind"] == "standard_cell_pin")
        actual_mapped = Counter((cell, pin) for instance, cell, pin in attached
                                if instance.startswith("Xsky130_fd_sc_hd__")
                                and pin not in POWER_EXPECTED)
        driver_count = sum(count for (cell, pin), count in actual_mapped.items()
                           if any(item["cell"] == cell and item["pin"] == pin
                                  and item["direction"] == "output"
                                  for item in by_net[logical_net]["endpoints"]
                                  if item["kind"] == "standard_cell_pin"))
        checks.append({"net": logical_net, "extracted_net": extracted,
                       "driver_count": driver_count,
                       "mapped_roles": {f"{cell}.{pin}": count
                                        for (cell, pin), count in sorted(actual_mapped.items())},
                       "helper_roles": sorted(actual_helpers)})
        if any(len(nets) != 1 for nets in role_nets.values()):
            errors.append(f"{logical_net}: selector leaves do not each resolve once: {role_nets}")
        if len(candidates) != 1:
            errors.append(f"{logical_net}: selector leaves span extracted nets {sorted(candidates)}")
        allowed_aliases = {logical_net, alias}
        if physical_labels and logical_net in physical_labels:
            allowed_aliases.add(physical_labels[logical_net])
        if len(candidates) == 1 and extracted not in allowed_aliases:
            errors.append(f"{logical_net}: unexpected extracted alias {extracted}")
        elif len(candidates) == 1:
            extracted_nets.append(extracted)
        if actual_helpers != expected_helpers:
            errors.append(f"{logical_net}: helper roles differ from four intended selector leaves")
        if actual_mapped != expected_mapped:
            errors.append(f"{logical_net}: mapped roles {actual_mapped} != {expected_mapped}")
        if driver_count != 1:
            errors.append(f"{logical_net}: extracted {driver_count} mapped output drivers")
    if len(set(extracted_nets)) != 4:
        errors.append("quadrature roots are not four independent extracted nets")

    expected_mapped_types = {f"sky130_fd_sc_hd__{name}_1": count
                             for name, count in mapping["counts"]["by_cell"].items()}
    mapped_instances = [item for item in statements if item[0].startswith("Xsky130_fd_sc_hd__")
                        and item[-1] in expected_mapped_types]
    if Counter(item[-1] for item in mapped_instances) != Counter(expected_mapped_types):
        errors.append("mapped standard-cell counts changed in quadrature extraction")
    helper_expected = expected_helper_cells()
    helpers = {item[0][1:]: item for item in statements if item[0][1:] in helper_expected}
    if set(helpers) != set(helper_expected): errors.append("fixed helper-cell set changed")
    power_pins = 0
    signal_power_shorts = 0
    for statement in mapped_instances + list(helpers.values()):
        signature = signatures.get(statement[-1], []); nets = statement[1:-1]
        if len(signature) != len(nets): errors.append(f"{statement[0]} port alignment failed"); continue
        attached = dict(zip(signature, nets))
        for pin, expected in POWER_EXPECTED.items():
            if attached.get(pin) == expected: power_pins += 1
            else: errors.append(f"{statement[0]}.{pin}={attached.get(pin)}, expected {expected}")
        for pin, net in attached.items():
            if pin not in POWER_EXPECTED and net in ("VDPWR", "VGND"):
                signal_power_shorts += 1; errors.append(f"{statement[0]}.{pin} is shorted to {net}")

    fatal = {name: pattern.search(log).group(0) for name, pattern in FATAL_PATTERNS.items()
             if pattern.search(log)}
    if fatal: errors.append(f"Magic quadrature extraction log has fatal markers: {fatal}")
    for marker in ("CONTROL_QUADRATURE_EXTRACTION_DRC_COUNT=0",
                   "CONTROL_QUADRATURE_EXTRACTION_FEEDBACK_COUNT=0",
                   "CONTROL_QUADRATURE_HIER_SPICE=", "CONTROL_QUADRATURE_FLAT_SPICE="):
        if marker not in log: errors.append(f"Magic quadrature extraction log lacks {marker}")
    if log.count("exttospice finished.") < 2:
        errors.append("both quadrature topology views were not written")
    return {"status": "pass" if not errors else "fail", "errors": errors,
            "quadrature_role_checks": checks, "verified_quadrature_net_count": len(checks),
            "mapped_standard_cell_count": len(mapped_instances),
            "fixed_helper_standard_cell_count": len(helpers),
            "verified_standard_cell_power_and_body_pins": power_pins,
            "unexpected_signal_to_power_short_count": signal_power_shorts,
            "magic_log_fatal_matches": fatal,
            "magic_exttospice_completion_count": log.count("exttospice finished.")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spice", type=Path, default=Path("build/v2/control_routing/quadrature_extraction/control_quadrature_hier.spice"))
    parser.add_argument("--mapping", type=Path, default=Path("build/v2/control_mapping/physical_netlist.json"))
    parser.add_argument("--allocation", type=Path, default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--log", type=Path, default=Path("build/v2/control_routing/direct/quadrature_magic_extraction.log"))
    parser.add_argument("--openroad-geometry", type=Path,
                        default=Path("build/v2/control_routing/openroad_route_geometry.json"))
    parser.add_argument("--report", type=Path, default=Path("build/v2/control_routing/quadrature_extraction/topology_audit.json"))
    args = parser.parse_args()
    allocation = json.loads(args.allocation.read_text())
    openroad = json.loads(args.openroad_geometry.read_text())
    physical_labels = {logical: physical for physical, logical in openroad["label_net_map"].items()}
    report = audit(args.spice.read_text(errors="replace"), json.loads(args.mapping.read_text()),
                   [item for item in allocation["nets"] if item["class"] == "quadrature_handoff"],
                   args.log.read_text(errors="replace"), physical_labels)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass": raise SystemExit(1)


if __name__ == "__main__":
    main()
