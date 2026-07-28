#!/usr/bin/env python3
"""Audit named terminals of the final extracted V2 signal path.

Earlier checkpoint audits intentionally compare their exact, local net names.
The final routed cell has powered helper cells and physical router labels, and
Magic may reorder generated-PCell ports.  This audit aligns every instance to
its extracted ``.subckt`` signature before checking terminal meaning.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from check_control_power_topology import parse_spice
from check_magic_rc_log import FATAL_PATTERNS


TOP = "v2_control_quadrature_routed"
POWER = {"VPWR": "VDPWR", "VPB": "VDPWR", "VGND": "VGND", "VNB": "VGND"}


def _instance_maps(
    spice: str, top: str,
) -> tuple[dict[str, dict[str, str]], list[str]]:
    signatures, statements = parse_spice(spice, top)
    instances: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for statement in statements:
        name, cell = statement[0], statement[-1]
        pins, nets = signatures.get(cell), statement[1:-1]
        if pins is None or len(pins) != len(nets):
            errors.append(f"{name}: cannot align extracted {cell} ports")
            continue
        if name in instances:
            errors.append(f"{name}: duplicate extracted instance")
            continue
        instances[name] = dict(zip(pins, nets))
    return instances, errors


def audit(
    spice: str,
    flat: str,
    geometry: dict[str, Any],
    log: str,
    top: str = TOP,
    marker_prefix: str = "CONTROL_QUADRATURE",
) -> dict[str, Any]:
    instances, errors = _instance_maps(spice, top)
    checked: list[str] = []
    logical_to_physical = {
        logical: physical for physical, logical in geometry["label_net_map"].items()
    }

    def require(name: str, expected: dict[str, str]) -> dict[str, str]:
        actual = instances.get(name)
        checked.append(name)
        if actual is None:
            errors.append(f"{name}: missing extracted instance")
            return {}
        for pin, net in expected.items():
            if actual.get(pin) != net:
                errors.append(f"{name}.{pin}={actual.get(pin)}, expected {net}")
        return actual

    def require_mos_groups(
        name: str, gate: str, drain: str, source: str, body_pin: str = "B",
    ) -> None:
        actual = require(name, {"G": gate, body_pin: "VGND"})
        if not actual:
            return
        classified = {"G", body_pin}
        drain_pins = [pin for pin in actual if pin.startswith("D") or pin.startswith("a_")]
        source_pins = [pin for pin in actual if pin.startswith("S")]
        if not drain_pins or not source_pins:
            errors.append(f"{name}: missing extracted drain or source terminals")
        for pin in drain_pins:
            classified.add(pin)
            if actual[pin] != drain:
                errors.append(f"{name}.{pin}={actual[pin]}, expected drain {drain}")
        for pin in source_pins:
            classified.add(pin)
            if actual[pin] != source:
                errors.append(f"{name}.{pin}={actual[pin]}, expected source {source}")
        unknown = sorted(set(actual) - classified)
        if unknown:
            errors.append(f"{name}: unclassified extracted pins {unknown}")

    for channel in range(4):
        prefix = f"XCH{channel}_"
        net = lambda suffix: f"ch{channel}_{suffix}"
        require(prefix + "RINPUT", {"B": "VGND", "R1": "ch0_vcm", "R2": net("input")})

        for suffix, drain, gate in (
            ("GM_SIG_A", "gm_p", "input"),
            ("GM_SIG_B", "gm_p", "input"),
            ("GM_REF_A", "gm_n", "vcm"),
            ("GM_REF_B", "gm_n", "vcm"),
        ):
            require_mos_groups(
                prefix + suffix,
                "ch0_vcm" if gate == "vcm" else net(gate),
                net(drain), net("tail"),
            )

        for suffix, output, lo, gm in (
            ("SW1_A", "out_p", "lop", "gm_p"), ("SW1_B", "out_p", "lop", "gm_p"),
            ("SW2_A", "out_n", "lon", "gm_p"), ("SW2_B", "out_n", "lon", "gm_p"),
            ("SW3_A", "out_n", "lop", "gm_n"), ("SW3_B", "out_n", "lop", "gm_n"),
            ("SW4_A", "out_p", "lon", "gm_n"), ("SW4_B", "out_p", "lon", "gm_n"),
        ):
            require_mos_groups(prefix + suffix, net(lo), f"ch0_{output}", net(gm))

        for row in range(3):
            require_mos_groups(
                prefix + f"TMAIN{row}", "ch0_vbias", net("tail"), "VGND", "VSUBS"
            )
        for weight in (1, 2, 4, 8):
            require_mos_groups(
                prefix + f"TTRIM{weight}", f"CH{channel}_TTRIM{weight}/G",
                net("tail"), "VGND", "VSUBS",
            )

        for bit, weight in enumerate((1, 2, 4, 8)):
            physical = logical_to_physical.get(f"active_trim_codes[{channel * 4 + bit}]")
            if physical is None:
                errors.append(f"active_trim_codes[{channel * 4 + bit}]: missing physical label")
                physical = "<missing>"
            trim_gate = f"CH{channel}_TTRIM{weight}/G"
            require(prefix + f"TSW{bit}_ON", {
                "G": physical, "D": trim_gate, "S": "ch0_vbias", "VSUBS": "VGND",
            })
            require(prefix + f"TSW{bit}_OFF", {
                "G": f"CH{channel}_TINV{bit}/Y", "D": trim_gate,
                "S": "VGND", "VSUBS": "VGND",
            })

        q = [logical_to_physical.get(f"phase_wave[{index}]", "<missing>") for index in range(4)]
        select0 = logical_to_physical.get(f"phase_select0[{channel}]", "<missing>")
        select1 = logical_to_physical.get(f"phase_select1[{channel}]", "<missing>")
        enable = logical_to_physical.get(f"phase_enable[{channel}]", "<missing>")
        helper_expectations = {
            "PMUX_A": {"X": f"CH{channel}_PMUX_A/X", "A0": q[0], "A1": q[1], "S": select0},
            "PMUX_B": {"X": f"CH{channel}_PMUX_B/X", "A0": q[2], "A1": q[3], "S": select0},
            "PMUX_P": {"X": f"CH{channel}_PMUX_P/X", "A0": f"CH{channel}_PMUX_A/X", "A1": f"CH{channel}_PMUX_B/X", "S": select1},
            "PMUX_N": {"X": f"CH{channel}_PMUX_N/X", "A0": f"CH{channel}_PMUX_B/X", "A1": f"CH{channel}_PMUX_A/X", "S": select1},
            "PAND_P": {"X": f"CH{channel}_PBUF_P/A", "A": f"CH{channel}_PMUX_P/X", "B": enable},
            "PAND_N": {"X": f"CH{channel}_PBUF_N/A", "A": f"CH{channel}_PMUX_N/X", "B": enable},
            "PBUF_P": {"X": net("lop"), "A": f"CH{channel}_PBUF_P/A"},
            "PBUF_N": {"X": net("lon"), "A": f"CH{channel}_PBUF_N/A"},
        }
        for suffix, signal_pins in helper_expectations.items():
            require(prefix + suffix, POWER | signal_pins)

    for polarity in ("P", "N"):
        require(f"XLOAD_{polarity}", {
            "B": "VGND", "R1": "VDPWR", "R2": f"ch0_out_{polarity.lower()}",
        })
    require("XRVCM_BOTTOM", {"B": "VGND", "R1": "ch0_vcm", "R2": "VGND"})
    require("XRVCM_TOP", {"B": "VGND", "R1": "VDPWR", "R2": "ch0_vcm"})
    require("XCVCM", {"C1": "ch0_vcm", "C2": "VGND", "VSUBS": "VGND"})
    require("XRBIAS", {"B": "VGND", "R1": "VDPWR", "R2": "ch0_vbias"})
    for suffix in ("A", "B"):
        require_mos_groups(f"XBIAS_DIODE_{suffix}", "ch0_vbias", "ch0_vbias", "VGND")
    for index in range(4):
        require(f"XCVCM_VAR{index}", {"G": "ch0_vcm", "D": "VGND", "B": "VGND"})

    critical_nets = ["VDPWR", "VGND", "ch0_vcm", "ch0_vbias", "ch0_out_p", "ch0_out_n"]
    for channel in range(4):
        critical_nets.extend(
            f"ch{channel}_{suffix}"
            for suffix in ("input", "tail", "gm_p", "gm_n", "lop", "lon")
        )
    missing_flat = [
        name for name in critical_nets
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", flat) is None
    ]
    if missing_flat:
        errors.append(f"critical nets missing from flat extraction: {missing_flat}")

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
        f"{marker_prefix}_FLAT_SPICE=",
    ):
        if marker not in log:
            errors.append(f"Magic extraction log lacks marker {marker}")
    if log.count("exttospice finished.") < 2:
        errors.append("Magic extraction did not finish both topology views")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "checked_instance_count": len(checked),
        "checked_instance_names": checked,
        "critical_flat_net_count": len(critical_nets),
        "missing_flat_nets": missing_flat,
        "magic_log_fatal_matches": fatal,
        "magic_exttospice_completion_count": log.count("exttospice finished."),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spice", type=Path, default=Path(
        "build/v2/control_routing/quadrature_extraction/control_quadrature_hier.spice"))
    parser.add_argument("--flat", type=Path, default=Path(
        "build/v2/control_routing/quadrature_extraction/control_quadrature_flat.spice"))
    parser.add_argument("--geometry", type=Path, default=Path(
        "build/v2/control_routing/openroad_route_geometry.json"))
    parser.add_argument("--log", type=Path, default=Path(
        "build/v2/control_routing/direct/quadrature_magic_extraction.log"))
    parser.add_argument("--report", type=Path, default=Path(
        "build/v2/control_routing/quadrature_extraction/final_signal_topology_audit.json"))
    parser.add_argument("--top", default=TOP)
    parser.add_argument("--marker-prefix", default="CONTROL_QUADRATURE")
    args = parser.parse_args()
    report = audit(
        args.spice.read_text(errors="replace"), args.flat.read_text(errors="replace"),
        json.loads(args.geometry.read_text()), args.log.read_text(errors="replace"),
        args.top, args.marker_prefix,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
