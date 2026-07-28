#!/usr/bin/env python3
"""Prove the final extracted ECO keeps output summing and grounds four varactors."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from assemble_vcm_varactor_eco_gds import SOURCE_SHA256 as USER_ROUTED_SOURCE_SHA256
from check_critical_extraction import top_instances


TOP = "v2_control_quadrature_routed"
VARACTOR_MODEL = "sky130_fd_pr__cap_var_lvt_88578Y"


def check(
    hierarchical: Path, flat: Path, assembly_audit: Path | None = None,
) -> dict[str, Any]:
    hierarchical_text = hierarchical.read_text(encoding="utf-8")
    flat_text = flat.read_text(encoding="utf-8")
    instances = top_instances(hierarchical_text, TOP)
    errors: list[str] = []

    expected_varactor = ["ch0_vcm", "VGND", "VGND"]
    for index in range(4):
        name = f"XCVCM_VAR{index}"
        if instances.get(name) != expected_varactor:
            errors.append(
                f"{name}: expected {' '.join(expected_varactor)}, "
                f"got {' '.join(instances.get(name, [])) or 'missing'}"
            )
    model_header = re.search(
        rf"^\.subckt\s+{re.escape(VARACTOR_MODEL)}\s+G\s+D\s+B\s*$",
        hierarchical_text,
        re.MULTILINE,
    )
    if model_header is None:
        errors.append("varactor extracted terminal order is not G D B")
    if "sky130_fd_pr__cap_var_lvt" not in flat_text:
        errors.append("flattened extraction contains no foundry varactor model")

    output_checks = 0
    for channel in range(1, 4):
        for switch in ("SW1_A", "SW1_B", "SW4_A", "SW4_B"):
            name = f"XCH{channel}_{switch}"
            nodes = instances.get(name, [])
            output_checks += 1
            if nodes.count("ch0_out_p") != 3 or f"ch{channel}_out_p" in nodes:
                errors.append(f"{name}: positive collector is not on ch0_out_p")
        for switch in ("SW2_A", "SW2_B", "SW3_A", "SW3_B"):
            name = f"XCH{channel}_{switch}"
            nodes = instances.get(name, [])
            output_checks += 1
            if nodes.count("ch0_out_n") != 3 or f"ch{channel}_out_n" in nodes:
                errors.append(f"{name}: negative collector is not on ch0_out_n")
    for name, output in (("XLOAD_P", "ch0_out_p"), ("XLOAD_N", "ch0_out_n")):
        nodes = instances.get(name, [])
        if output not in nodes or "VDPWR" not in nodes or "VGND" not in nodes:
            errors.append(f"{name}: shared output load topology changed")
    trim_preserved = False
    if assembly_audit is not None:
        audit = json.loads(assembly_audit.read_text(encoding="utf-8"))
        trim_preserved = (
            audit.get("source_sha256") == USER_ROUTED_SOURCE_SHA256
            and audit.get("source_preserves_user_trim_routes") is True
            and audit.get("varactor_reference_count_added") == 4
            and audit.get("imported_structure_count") == 1
        )
        if not trim_preserved:
            errors.append("ECO assembly does not prove preservation of the user-routed source")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "varactor_instance_count": sum(
            name.startswith("XCVCM_VAR") for name in instances
        ),
        "varactor_terminal_mapping": expected_varactor,
        "shared_output_switch_checks": output_checks,
        "shared_load_checks": 2,
        "user_trim_routes_preserved_by_source_hash": trim_preserved,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hierarchical", type=Path)
    parser.add_argument("flat", type=Path)
    parser.add_argument("--assembly-audit", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = check(args.hierarchical, args.flat, args.assembly_audit)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
