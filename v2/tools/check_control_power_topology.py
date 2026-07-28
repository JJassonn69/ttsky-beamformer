#!/usr/bin/env python3
"""Audit real Magic topology for every mapped control-cell supply pin."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from check_magic_rc_log import FATAL_PATTERNS


TOP = "v2_four_channel_control_powered"
POWER_EXPECTED = {"VPWR": "VDPWR", "VPB": "VDPWR", "VGND": "VGND", "VNB": "VGND"}
ANALOG_SUPPLY_EXPECTED = {
    "RBIAS": {"B": "VGND", "R1": "VDPWR", "R2": "ch0_vbias"},
    "RVCM_TOP": {"B": "VGND", "R1": "VDPWR", "R2": "ch0_vcm"},
    "LOAD_N": {"B": "VGND", "R1": "VDPWR", "R2": "ch0_out_n"},
    "LOAD_P": {"B": "VGND", "R1": "VDPWR", "R2": "ch0_out_p"},
}


def expected_helper_cells() -> dict[str, str]:
    result: dict[str, str] = {}
    for channel in range(4):
        prefix = f"CH{channel}_"
        for index in range(4):
            result[f"{prefix}TINV{index}"] = "sky130_fd_sc_hd__inv_1"
        for suffix in ("A", "B", "P", "N"):
            result[f"{prefix}PMUX_{suffix}"] = "sky130_fd_sc_hd__mux2_1"
        for suffix in ("P", "N"):
            result[f"{prefix}PAND_{suffix}"] = "sky130_fd_sc_hd__and2_1"
            result[f"{prefix}PBUF_{suffix}"] = "sky130_fd_sc_hd__buf_4"
    return result


def logical_lines(text: str) -> list[str]:
    result: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if raw.startswith("+") and result:
            result[-1] += " " + raw[1:].strip()
        else:
            result.append(line)
    return result


def parse_spice(
    text: str, top: str = TOP
) -> tuple[dict[str, list[str]], list[list[str]]]:
    lines = logical_lines(text)
    signatures: dict[str, list[str]] = {}
    top_statements: list[list[str]] = []
    active = ""
    for line in lines:
        if line.lower().startswith(".subckt "):
            tokens = line.split()
            active = tokens[1]
            signatures[active] = tokens[2:]
            continue
        if line.lower() == ".ends":
            active = ""
            continue
        if active == top and line.startswith("X"):
            top_statements.append(line.split())
    if top not in signatures:
        raise ValueError(f"top subcircuit {top} is absent")
    return signatures, top_statements


def audit_analog_supply_endpoints(
    signatures: dict[str, list[str]], statements: list[list[str]],
) -> tuple[list[dict[str, str]], list[str]]:
    """Require every powered analog resistor to retain three distinct ports.

    Checking only whether VDPWR appears somewhere near a PCell is insufficient:
    an unrelated ground route can collapse R1 into the body node and make the
    extracted cell signature lose the R1 port entirely.  The exact B/R1/R2 map
    catches that topology error even when full-chip DRC is zero.
    """

    errors: list[str] = []
    checks: list[dict[str, str]] = []
    instance_by_name = {
        item[0][1:]: item for item in statements if item and item[0].startswith("X")
    }
    for name, expected in ANALOG_SUPPLY_EXPECTED.items():
        statement = instance_by_name.get(name)
        if statement is None:
            errors.append(f"missing extracted analog supply endpoint {name}")
            continue
        cell = statement[-1]
        signature = signatures.get(cell, [])
        nets = statement[1:-1]
        if len(signature) != len(nets):
            errors.append(f"{name}: cannot align extracted resistor ports")
            continue
        attached = dict(zip(signature, nets))
        record = {"instance": name}
        record.update({pin: attached.get(pin, "") for pin in ("B", "R1", "R2")})
        checks.append(record)
        missing_ports = [pin for pin in ("B", "R1", "R2") if pin not in signature]
        if missing_ports:
            errors.append(
                f"{name}: extracted resistor signature lost ports {missing_ports}; "
                "possible terminal-to-body short"
            )
        for pin, expected_net in expected.items():
            if attached.get(pin) != expected_net:
                errors.append(
                    f"{name}.{pin}={attached.get(pin)}, expected {expected_net}"
                )
    return checks, errors


def audit(
    spice_text: str,
    mapping: dict[str, Any],
    log_text: str,
    top: str = TOP,
    marker_prefix: str = "CONTROL_POWER",
) -> dict[str, Any]:
    errors: list[str] = []
    signatures, statements = parse_spice(spice_text, top)
    expected_by_cell = {
        f"sky130_fd_sc_hd__{name}_1": count
        for name, count in mapping["counts"]["by_cell"].items()
    }
    mapped_types = set(expected_by_cell)
    mapped_instances = [item for item in statements if item[-1] in mapped_types
                        and item[0].startswith("Xsky130_fd_sc_hd__")]
    actual_by_cell = Counter(item[-1] for item in mapped_instances)
    if actual_by_cell != Counter(expected_by_cell):
        errors.append(
            f"mapped-cell extraction counts differ: {dict(actual_by_cell)} != {expected_by_cell}"
        )

    supply_connections = 0
    signal_power_short_count = 0
    for statement in mapped_instances:
        instance, cell = statement[0], statement[-1]
        signature = signatures.get(cell)
        nets = statement[1:-1]
        if signature is None or len(signature) != len(nets):
            errors.append(f"{instance}: cannot align {cell} ports with extracted nets")
            continue
        attached = dict(zip(signature, nets))
        for pin, expected in POWER_EXPECTED.items():
            if pin not in attached:
                errors.append(f"{instance}: {cell} has no extracted {pin} pin")
                continue
            if attached[pin] != expected:
                errors.append(f"{instance}.{pin}={attached[pin]}, expected {expected}")
            else:
                supply_connections += 1
        for pin, net in attached.items():
            if pin not in POWER_EXPECTED and net in ("VDPWR", "VGND"):
                signal_power_short_count += 1
                errors.append(f"{instance}.{pin} is unexpectedly shorted to {net}")

    helper_expected = expected_helper_cells()
    helper_by_name: dict[str, list[list[str]]] = {}
    for statement in statements:
        name = statement[0][1:] if statement and statement[0].startswith("X") else ""
        if name in helper_expected:
            helper_by_name.setdefault(name, []).append(statement)
    helper_supply_connections = 0
    helper_signal_power_short_count = 0
    helper_types: Counter[str] = Counter()
    for name, expected_cell in helper_expected.items():
        matches = helper_by_name.get(name, [])
        if len(matches) != 1:
            errors.append(f"{name}: extracted {len(matches)} helper instances, expected one")
            continue
        statement = matches[0]
        cell = statement[-1]
        helper_types[cell] += 1
        if cell != expected_cell:
            errors.append(f"{name}: extracted as {cell}, expected {expected_cell}")
            continue
        signature = signatures.get(cell)
        nets = statement[1:-1]
        if signature is None or len(signature) != len(nets):
            errors.append(f"{name}: cannot align {cell} ports with extracted nets")
            continue
        attached = dict(zip(signature, nets))
        for pin, expected in POWER_EXPECTED.items():
            if pin not in attached:
                errors.append(f"{name}: {cell} has no extracted {pin} pin")
                continue
            if attached[pin] != expected:
                errors.append(f"{name}.{pin}={attached[pin]}, expected {expected}")
            else:
                helper_supply_connections += 1
        for pin, net in attached.items():
            if pin not in POWER_EXPECTED and net in ("VDPWR", "VGND"):
                helper_signal_power_short_count += 1
                errors.append(f"{name}.{pin} is unexpectedly shorted to {net}")

    analog_checks, analog_errors = audit_analog_supply_endpoints(
        signatures, statements
    )
    errors.extend(analog_errors)

    fatal_matches = {
        name: pattern.search(log_text).group(0)
        for name, pattern in FATAL_PATTERNS.items() if pattern.search(log_text)
    }
    if fatal_matches:
        errors.append(f"Magic extraction log has fatal markers: {fatal_matches}")
    required_markers = (
        f"{marker_prefix}_EXTRACTION_DRC_COUNT=0",
        f"{marker_prefix}_EXTRACTION_FEEDBACK_COUNT=0",
        f"{marker_prefix}_HIER_SPICE=",
        f"{marker_prefix}_FLAT_SPICE=",
    )
    missing_markers = [item for item in required_markers if item not in log_text]
    if missing_markers:
        errors.append(f"Magic extraction log lacks markers: {missing_markers}")
    if log_text.count("exttospice finished.") < 2:
        errors.append("Magic extraction did not finish both topology views")

    top_text = "\n".join(" ".join(item) for item in statements)
    if "VDPWR" not in top_text or "VGND" not in top_text:
        errors.append("top extraction lacks named VDPWR or VGND")
    if "RBIAS/R1" in top_text:
        errors.append("VDPWR still aliases to the device-local RBIAS/R1 name")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "mapped_standard_cell_count": len(mapped_instances),
        "mapped_standard_cells_by_type": dict(sorted(actual_by_cell.items())),
        "verified_standard_cell_power_and_body_pins": supply_connections,
        "unexpected_signal_to_power_short_count": signal_power_short_count,
        "fixed_helper_standard_cell_count": sum(len(items) for items in helper_by_name.values()),
        "fixed_helper_standard_cells_by_type": dict(sorted(helper_types.items())),
        "verified_fixed_helper_power_and_body_pins": helper_supply_connections,
        "fixed_helper_unexpected_signal_to_power_short_count": helper_signal_power_short_count,
        "analog_vdpwr_checks": analog_checks,
        "magic_log_fatal_matches": fatal_matches,
        "magic_exttospice_completion_count": log_text.count("exttospice finished."),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spice", type=Path,
                        default=Path("build/v2/control_power/extraction/control_power_hier.spice"))
    parser.add_argument("--mapping", type=Path,
                        default=Path("build/v2/control_mapping/physical_netlist.json"))
    parser.add_argument("--log", type=Path,
                        default=Path("build/v2/control_power/direct/magic_extraction.log"))
    parser.add_argument("--report", type=Path,
                        default=Path("build/v2/control_power/extraction/topology_audit.json"))
    parser.add_argument("--top", default=TOP)
    parser.add_argument("--marker-prefix", default="CONTROL_POWER")
    args = parser.parse_args()
    report = audit(
        args.spice.read_text(encoding="utf-8", errors="replace"),
        json.loads(args.mapping.read_text(encoding="utf-8")),
        args.log.read_text(encoding="utf-8", errors="replace"),
        args.top,
        args.marker_prefix,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
