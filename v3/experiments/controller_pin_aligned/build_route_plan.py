#!/usr/bin/env python3
"""Bind Candidate B placement and OpenROAD artifacts into a route plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORK = Path("build/v3/experiments/controller_pin_aligned")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> None:
    source = ROOT / WORK / "control_placement/direct/v3_four_channel_control_placed.gds"
    route = ROOT / WORK / "openroad_internal"
    paths = {
        "input_summary": route / "input_summary.json",
        "audit": route / "route_audit.json",
        "routed_def": route / "routed.def",
        "detailed_route_drc": route / "detailed_route_drc.rpt",
        "openroad_log": route / "openroad.log",
        "wire_length": route / "wire_length.csv",
        "guide_coverage": route / "guide_coverage.csv",
    }
    for path in [source, *paths.values()]:
        if not path.is_file():
            raise SystemExit(f"missing Candidate B artifact: {path}")
    audit = json.loads(paths["audit"].read_text(encoding="utf-8"))
    summary = json.loads(paths["input_summary"].read_text(encoding="utf-8"))
    if audit.get("status") != "pass" or audit.get("errors"):
        raise SystemExit("Candidate B route audit is not passing")
    if paths["detailed_route_drc"].read_bytes():
        raise SystemExit("Candidate B detailed-route DRC report is not empty")

    plan = {
        "schema_version": 1,
        "units": "um",
        "status": "Candidate B hash-locked controller route experiment",
        "candidate": "B",
        "source_checkpoint": {
            "gds": rel(source),
            "top": "v3_four_channel_control_placed",
            "sha256": sha256(source),
        },
        "route_checkpoint": {
            name: rel(path)
            for name, path in paths.items()
        },
        "overlay_top": "v3_cb_ctrl_sig_routes",
        "output_top": "v3_cb_4ch_ctrl_sig_routed",
        "expected_route_count": int(summary["net_count"]),
        "expected_boundary_pin_count": int(summary["pin_count"]),
        "maximum_wire_layer": audit["maximum_route_layer"],
        "wire_widths": {
            "li1": 0.17,
            "met1": 0.14,
            "met2": 0.14,
            "met3": 0.30,
        },
        "via_geometries": {
            "L1M1": [
                ["li1", [-0.085, -0.085, 0.085, 0.085]],
                ["mcon", [-0.085, -0.085, 0.085, 0.085]],
                ["met1", [-0.145, -0.115, 0.145, 0.115]],
            ],
            "M1M2": [
                ["met1", [-0.16, -0.13, 0.16, 0.13]],
                ["via", [-0.075, -0.075, 0.075, 0.075]],
                ["met2", [-0.13, -0.16, 0.13, 0.16]],
            ],
            "M2M3": [
                ["met2", [-0.14, -0.185, 0.14, 0.185]],
                ["via2", [-0.10, -0.10, 0.10, 0.10]],
                ["met3", [-0.165, -0.165, 0.165, 0.165]],
            ],
        },
        "policy": {
            "candidate_a_submission_immutable": True,
            "placement_is_fixed": True,
            "all_internal_signal_nets_are_router_owned": True,
            "metal4_is_reserved_for_analog_and_top_level_handoffs": True,
            "power_routing_is_not_promoted_by_this_experiment": True,
            "top_level_handoff_routing_is_not_promoted_by_this_experiment": True,
        },
    }
    for name, path in paths.items():
        plan["route_checkpoint"][f"{name}_sha256"] = sha256(path)

    output = ROOT / WORK / "physical_control_route_plan.json"
    output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": rel(output), "source_sha256": sha256(source)}, indent=2))


if __name__ == "__main__":
    main()
