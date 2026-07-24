#!/usr/bin/env python3
"""Audit all service nets and preserved direct nets in exact extracted GDS."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from check_control_power_topology import (
    POWER_EXPECTED,
    audit_analog_supply_endpoints,
    expected_helper_cells,
    logical_lines,
)
from check_magic_rc_log import FATAL_PATTERNS


TOP = "v2_control_service_routed"


def parse(
    text: str, top: str = TOP,
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
    if top not in signatures:
        raise ValueError(f"missing .subckt {top}")
    return signatures, statements


def audit(spice: str, mapping: dict[str, Any], routes: list[dict[str, Any]],
          log: str, top: str = TOP, marker_prefix: str = "CONTROL_SERVICE",
          physical_labels: dict[str, str] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    signatures, statements = parse(spice, top)
    attachments: dict[str, list[tuple[str, str, str]]] = {}
    for statement in statements:
        cell, nets = statement[-1], statement[1:-1]
        signature = signatures.get(cell)
        if signature is None or len(signature) != len(nets):
            continue
        for pin, net in zip(signature, nets):
            attachments.setdefault(net, []).append((statement[0], cell, pin))

    checks: list[dict[str, Any]] = []
    for route in sorted(routes, key=lambda item: item["net"]):
        net = route["net"]
        extracted_net = (
            physical_labels.get(net, net) if physical_labels is not None else net
        )
        expected = Counter(
            (item["cell"], item["pin"]) for item in route["endpoints"]
            if item["kind"] == "standard_cell_pin"
        )
        actual_attached = attachments.get(extracted_net, [])
        actual = Counter(
            (cell, pin) for instance, cell, pin in actual_attached
            if instance.startswith("Xsky130_fd_sc_hd__") and pin not in POWER_EXPECTED
        )
        helpers = sorted(
            f"{instance}.{pin}" for instance, _cell, pin in actual_attached
            if instance.startswith("XCH")
        )
        expected_drivers = sum(
            item["direction"] == "output" for item in route["endpoints"]
            if item["kind"] == "standard_cell_pin"
        )
        driver_roles = {
            (item["cell"], item["pin"]) for item in route["endpoints"]
            if item["kind"] == "standard_cell_pin" and item["direction"] == "output"
        }
        actual_drivers = sum(count for role, count in actual.items() if role in driver_roles)
        checks.append({
            "net": net, "extracted_net": extracted_net,
            "route_class": route["class"],
            "expected_driver_count": expected_drivers,
            "actual_driver_count": actual_drivers,
            "expected_mapped_roles": {f"{cell}.{pin}": count for (cell, pin), count in sorted(expected.items())},
            "actual_mapped_roles": {f"{cell}.{pin}": count for (cell, pin), count in sorted(actual.items())},
            "unexpected_helper_roles": helpers,
        })
        if extracted_net not in attachments:
            errors.append(f"{net}: named extracted net is absent")
        if actual != expected:
            errors.append(f"{net}: mapped roles {actual} != {expected}")
        if helpers:
            errors.append(f"{net}: unexpectedly reaches analog helper roles {helpers}")
        if actual_drivers != expected_drivers:
            errors.append(f"{net}: extracted {actual_drivers} mapped drivers, expected {expected_drivers}")
    if len({
        item["extracted_net"] for item in checks
        if item["extracted_net"] in attachments
    }) != len(routes):
        errors.append("service/direct routes are not independent named extracted nets")

    expected_mapped_types = {
        f"sky130_fd_sc_hd__{name}_1": count for name, count in mapping["counts"]["by_cell"].items()
    }
    mapped_instances = [
        item for item in statements
        if item[0].startswith("Xsky130_fd_sc_hd__") and item[-1] in expected_mapped_types
    ]
    if Counter(item[-1] for item in mapped_instances) != Counter(expected_mapped_types):
        errors.append("mapped standard-cell counts changed in service extraction")
    helper_expected = expected_helper_cells()
    helpers = {item[0][1:]: item for item in statements if item[0][1:] in helper_expected}
    if set(helpers) != set(helper_expected):
        errors.append("fixed helper-cell set changed")

    power_pins = 0
    signal_power_shorts = 0
    for statement in mapped_instances + list(helpers.values()):
        signature = signatures.get(statement[-1], [])
        nets = statement[1:-1]
        if len(signature) != len(nets):
            errors.append(f"{statement[0]} port alignment failed")
            continue
        attached = dict(zip(signature, nets))
        for pin, expected_power in POWER_EXPECTED.items():
            if attached.get(pin) == expected_power:
                power_pins += 1
            else:
                errors.append(f"{statement[0]}.{pin}={attached.get(pin)}, expected {expected_power}")
        for pin, attached_net in attached.items():
            if pin not in POWER_EXPECTED and attached_net in ("VDPWR", "VGND"):
                signal_power_shorts += 1
                errors.append(f"{statement[0]}.{pin} is shorted to {attached_net}")

    analog_supply_checks, analog_supply_errors = audit_analog_supply_endpoints(
        signatures, statements
    )
    errors.extend(analog_supply_errors)

    fatal = {name: pattern.search(log).group(0)
             for name, pattern in FATAL_PATTERNS.items() if pattern.search(log)}
    if fatal:
        errors.append(f"Magic service extraction log has fatal markers: {fatal}")
    for marker in (
        f"{marker_prefix}_EXTRACTION_DRC_COUNT=0",
        f"{marker_prefix}_EXTRACTION_FEEDBACK_COUNT=0",
        f"{marker_prefix}_HIER_SPICE=", f"{marker_prefix}_FLAT_SPICE=",
    ):
        if marker not in log:
            errors.append(f"Magic service extraction log lacks {marker}")
    if log.count("exttospice finished.") < 2:
        errors.append("both service topology views were not written")
    return {
        "status": "pass" if not errors else "fail", "errors": errors,
        "route_role_checks": checks, "verified_named_route_count": len(checks),
        "mapped_standard_cell_count": len(mapped_instances),
        "fixed_helper_standard_cell_count": len(helpers),
        "verified_standard_cell_power_and_body_pins": power_pins,
        "unexpected_signal_to_power_short_count": signal_power_shorts,
        "analog_supply_checks": analog_supply_checks,
        "magic_log_fatal_matches": fatal,
        "magic_exttospice_completion_count": log.count("exttospice finished."),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spice", type=Path, default=Path("build/v2/control_routing/service_extraction/control_service_hier.spice"))
    parser.add_argument("--mapping", type=Path, default=Path("build/v2/control_mapping/physical_netlist.json"))
    parser.add_argument("--allocation", type=Path, default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--log", type=Path, default=Path("build/v2/control_routing/direct/service_magic_extraction.log"))
    parser.add_argument("--report", type=Path, default=Path("build/v2/control_routing/service_extraction/topology_audit.json"))
    parser.add_argument("--top", default=TOP)
    parser.add_argument("--marker-prefix", default="CONTROL_SERVICE")
    parser.add_argument(
        "--openroad-geometry", type=Path,
        default=Path("build/v2/control_routing/openroad_route_geometry.json"),
    )
    args = parser.parse_args()
    allocation = json.loads(args.allocation.read_text())
    openroad = json.loads(args.openroad_geometry.read_text())
    physical_labels = {
        logical: physical for physical, logical in openroad["label_net_map"].items()
    }
    report = audit(
        args.spice.read_text(errors="replace"), json.loads(args.mapping.read_text()),
        [item for item in allocation["nets"] if item["class"] in ("direct_boundary", "service_tree")],
        args.log.read_text(errors="replace"), args.top, args.marker_prefix,
        physical_labels,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
