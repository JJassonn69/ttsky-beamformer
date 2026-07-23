#!/usr/bin/env python3
"""Check that extracted trim routes join the exact mapped Q/A0 pins."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from check_control_power_topology import parse_spice
from check_magic_rc_log import FATAL_PATTERNS


TOP = "v2_control_trim_routed"


def audit(
    spice: str,
    mapping: dict[str, Any],
    geometry: dict[str, Any],
    log: str,
    top: str = TOP,
    marker_prefix: str = "CONTROL_TRIM",
) -> dict[str, Any]:
    errors: list[str] = []
    signatures, statements = parse_spice(spice.replace(
        f".subckt {top}", ".subckt v2_four_channel_control_powered", 1
    ))
    # parse_spice's power checker top name is intentionally fixed.  The text
    # replacement affects only parsing; extracted instance/net names remain exact.
    attachments: dict[str, list[tuple[str, str, str]]] = {}
    for statement in statements:
        cell = statement[-1]
        signature = signatures.get(cell)
        if not signature:
            continue
        nets = statement[1:-1]
        if len(signature) == len(nets):
            for pin, net in zip(signature, nets):
                attachments.setdefault(net, []).append((statement[0], cell, pin))

    checks: list[dict[str, str]] = []
    logical_to_physical = {
        logical: physical
        for physical, logical in geometry["label_net_map"].items()
    }
    for index in range(16):
        net = f"active_trim_codes[{index}]"
        physical = logical_to_physical.get(net)
        if physical is None:
            errors.append(f"{net}: absent from frozen OpenROAD label map")
            attached = []
        else:
            attached = attachments.get(physical, [])
        expected_roles = {
            "active_ff_q": [
                item for item in attached
                if item[1] in ("sky130_fd_sc_hd__dfrtp_1", "sky130_fd_sc_hd__dfstp_1")
                and item[2] == "Q"
            ],
            "active_mux_a0": [
                item for item in attached
                if item[1] == "sky130_fd_sc_hd__mux2_1" and item[2] == "A0"
            ],
            "analog_trim_inverter_a": [
                item for item in attached
                if item[1] == "sky130_fd_sc_hd__inv_1" and item[2] == "A"
            ],
        }
        for role, matches in expected_roles.items():
            expected_instances = (
                [f"XCH{index // 4}_TINV{index % 4}"]
                if role == "analog_trim_inverter_a"
                else []
            )
            actual_instances = sorted(item[0] for item in matches)
            checks.append({
                "net": net,
                "physical_label": physical or "",
                "role": role,
                "match_count": str(len(matches)),
                "instances": ",".join(actual_instances),
                "expected_instances": ",".join(expected_instances),
            })
            if len(matches) != 1:
                errors.append(f"{net}: extracted {len(matches)} {role} attachments, expected one")
            if expected_instances and actual_instances != expected_instances:
                errors.append(
                    f"{net}: extracted {role} attachment {actual_instances}, "
                    f"expected exact channel/bit sink {expected_instances}"
                )

    fatal = {
        name: pattern.search(log).group(0)
        for name, pattern in FATAL_PATTERNS.items() if pattern.search(log)
    }
    if fatal:
        errors.append(f"Magic extraction log has fatal markers: {fatal}")
    for marker in (
        f"{marker_prefix}_EXTRACTION_DRC_COUNT=0",
        f"{marker_prefix}_EXTRACTION_FEEDBACK_COUNT=0",
        f"{marker_prefix}_HIER_SPICE=",
    ):
        if marker not in log:
            errors.append(f"Magic extraction log lacks marker {marker}")
    if log.count("exttospice finished.") < 1:
        errors.append("Magic trim extraction did not finish")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "verified_trim_role_count": sum(item["match_count"] == "1" for item in checks),
        "verified_exact_analog_sink_count": sum(
            item["role"] == "analog_trim_inverter_a"
            and item["instances"] == item["expected_instances"]
            for item in checks
        ),
        "pin_checks": checks,
        "magic_log_fatal_matches": fatal,
        "magic_exttospice_completion_count": log.count("exttospice finished."),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spice", type=Path,
                        default=Path("build/v2/control_routing/extraction/control_trim_hier.spice"))
    parser.add_argument("--mapping", type=Path,
                        default=Path("build/v2/control_mapping/physical_netlist.json"))
    parser.add_argument(
        "--geometry", type=Path,
        default=Path("build/v2/control_routing/openroad_route_geometry.json"),
    )
    parser.add_argument("--log", type=Path,
                        default=Path("build/v2/control_routing/direct/magic_extraction.log"))
    parser.add_argument("--report", type=Path,
                        default=Path("build/v2/control_routing/extraction/trim_topology_audit.json"))
    parser.add_argument("--top", default=TOP)
    parser.add_argument("--marker-prefix", default="CONTROL_TRIM")
    args = parser.parse_args()
    report = audit(
        args.spice.read_text(errors="replace"),
        json.loads(args.mapping.read_text()),
        json.loads(args.geometry.read_text()),
        args.log.read_text(errors="replace"),
        args.top,
        args.marker_prefix,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
