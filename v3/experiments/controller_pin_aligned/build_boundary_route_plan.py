#!/usr/bin/env python3
"""Hash-lock the routed Candidate B TinyTapeout boundary handoffs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORK = Path("build/v3/experiments/controller_pin_aligned")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    plan_path = WORK / "physical_control_boundary_handoff_plan.json"
    source = WORK / "analog_handoffs/direct/v3_cb_four_channel_ctrl_analog_handoffs.gds"
    openroad = WORK / "boundary_handoffs/openroad"
    template = Path("v3/layout/physical_control_boundary_handoff_route_plan.json")
    generator = Path("v3/tools/generate_physical_control_boundary_handoff_inputs.py")
    checker = Path("v3/tools/check_physical_control_boundary_handoffs.py")
    audit = openroad / "route_audit.json"
    audit_data = json.loads((ROOT / audit).read_text(encoding="utf-8"))
    if audit_data.get("status") != "pass" or audit_data.get("errors"):
        raise ValueError("Candidate B boundary route audit did not pass")

    result = json.loads((ROOT / template).read_text(encoding="utf-8"))
    result["status"] = "hash-locked Candidate B TinyTapeout controller-input handoff route contract"
    result["source_checkpoint"] = {
        "gds": str(source),
        "top": "v3_cb_4ch_ctrl_analog_handoff",
        "sha256": sha256(ROOT / source),
    }
    result["route_contract"] = {
        "plan": str(plan_path),
        "plan_sha256": sha256(ROOT / plan_path),
        "generator": str(generator),
        "generator_sha256": sha256(ROOT / generator),
        "checker": str(checker),
        "checker_sha256": sha256(ROOT / checker),
    }
    checkpoints = {
        "input_def": "input.def",
        "input_summary": "input_summary.json",
        "audit": "route_audit.json",
        "routed_def": "routed.def",
        "detailed_route_drc": "detailed_route_drc.rpt",
        "openroad_log": "openroad.log",
        "wire_length": "wire_length.csv",
        "guide_coverage": "guide_coverage.csv",
        "route_guide": "route.guide",
    }
    route_checkpoint = {}
    for key, filename in checkpoints.items():
        path = openroad / filename
        route_checkpoint[key] = str(path)
        route_checkpoint[f"{key}_sha256"] = sha256(ROOT / path)
    result["route_checkpoint"] = route_checkpoint
    # GDSII structure names are limited to 32 bytes.
    result["overlay_top"] = "v3_cb_ctrl_bnd_routes"
    result["output_top"] = "v3_cb_4ch_ctrl_bnd"
    result["candidate"] = "B"

    output = ROOT / WORK / "physical_control_boundary_handoff_route_plan.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "generated",
        "candidate": "B",
        "output": str(output.relative_to(ROOT)),
        "source_sha256": result["source_checkpoint"]["sha256"],
        "route_count": audit_data["route_count"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
