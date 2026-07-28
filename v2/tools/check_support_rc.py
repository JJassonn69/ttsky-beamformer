#!/usr/bin/env python3
"""Audit the V2 support-stage distributed-RC extraction products."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_distributed_rc import annotation_counts, rc_details, spice_elements


def required_routed_nets(*, include_output_pads: bool = False) -> set[str]:
    nets = {"VGND", "ch0_vcm", "ch0_vbias", "ch0_out_p", "ch0_out_n"}
    for channel in range(4):
        nets.update(
            f"ch{channel}_{suffix}"
            for suffix in (
                "input", "tail", "gm_p", "gm_n", "lop", "lon",
                "phase_sel0", "phase_sel1", "phase_enable",
            )
        )
    nets.update(
        f"ch0_phase_{phase}_leaf" for phase in ("0", "90", "180", "270")
    )
    if include_output_pads:
        nets.update({"sum_p", "sum_n"})
    return nets


def audit(base_path: Path, rc_path: Path, res_ext_path: Path) -> dict[str, object]:
    base = spice_elements(base_path)
    rc = spice_elements(rc_path)
    required = required_routed_nets()
    details = rc_details(rc, required)
    rnodes, annotated = annotation_counts(res_ext_path)
    emitted_ratio = details["resistors"] / annotated if annotated else 0.0
    top_ext = res_ext_path.with_name(res_ext_path.name.removesuffix(".res.ext") + ".ext")
    checks = {
        "base_is_resistance_free_reference": len(base["R"]) == 0,
        "resistance_annotation_exists": rnodes > 0 and annotated > 0,
        "resistance_annotation_is_fresh": (
            top_ext.is_file()
            and res_ext_path.stat().st_mtime_ns >= top_ext.stat().st_mtime_ns
        ),
        # ext2spice is allowed to merge equivalent annotation records while
        # rewriting the graph.  A large loss is suspicious; a small reduction
        # is expected and must not be mistaken for a failed extraction.
        "explicit_resistors_emitted": annotated > 0 and emitted_ratio >= 0.95,
        "distributed_capacitances_emitted": details["capacitors"] > len(base["C"]),
        "device_count_preserved": details["devices"] == len(base["X"]) > 0,
        "all_routed_nets_resistively_covered": not details["uncovered_manifest_nets"],
        "internal_resistor_nodes_emitted": (
            details["internal_resistor_nodes"] >= len(required)
        ),
        "resistor_records_well_formed": not details["malformed_resistors"],
        "resistor_values_positive": not details["nonpositive_resistors"],
        "no_extraction_attribute_nodes": not details[
            "attribute_like_resistor_nodes"
        ],
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "required_routed_net_count": len(required),
        "required_routed_nets": sorted(required),
        "uncovered_routed_nets": details["uncovered_manifest_nets"],
        "base": {
            "resistors": len(base["R"]),
            "capacitors": len(base["C"]),
            "devices": len(base["X"]),
        },
        "distributed_rc": details,
        "annotation": {
            "rnodes": rnodes,
            "resistors": annotated,
            "spice_to_annotation_ratio": emitted_ratio,
        },
        "sha256": {
            "base": hashlib.sha256(base_path.read_bytes()).hexdigest(),
            "distributed_rc": hashlib.sha256(rc_path.read_bytes()).hexdigest(),
            "resistance_annotation": hashlib.sha256(res_ext_path.read_bytes()).hexdigest(),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_netlist", type=Path)
    parser.add_argument("rc_netlist", type=Path)
    parser.add_argument("resistance_annotation", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = audit(args.base_netlist, args.rc_netlist, args.resistance_annotation)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    details = report["distributed_rc"]
    covered = report["required_routed_net_count"] - len(
        report["uncovered_routed_nets"]
    )
    print(
        "V2 support distributed-RC "
        + ("passed" if report["passed"] else "FAILED")
        + f": {details['resistors']} resistors, {details['capacitors']} capacitors, "
        + f"{details['devices']} devices, "
        + f"{covered}/{report['required_routed_net_count']} routed nets covered"
    )
    if not report["passed"]:
        for name, passed in report["checks"].items():
            if not passed:
                print(f"FAIL: {name}")
        if report["uncovered_routed_nets"]:
            print("Uncovered: " + ", ".join(report["uncovered_routed_nets"]))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
