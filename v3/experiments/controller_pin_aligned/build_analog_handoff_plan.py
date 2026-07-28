#!/usr/bin/env python3
"""Bind Candidate B to the frozen, endpoint-compatible analog handoff routes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORK = Path("build/v3/experiments/controller_pin_aligned")
INPUT_NAMES = {
    "clk",
    "rst_n",
    "ena",
    "beam_select[0]",
    "beam_select[1]",
    "beam_select[2]",
    "raw_mode",
    "channel_enable[0]",
    "channel_enable[1]",
    "channel_enable[2]",
    "channel_enable[3]",
    "cfg_clk",
    "cfg_data",
    "cfg_latch",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    candidate_source = WORK / "control_power/direct/v3_cb_four_channel_ctrl_powered.gds"
    candidate_summary = WORK / "openroad_internal/input_summary.json"
    frozen_summary = Path("v3/frozen/controller_signal_routing/input_summary.json")
    route_template = Path("v3/layout/physical_control_analog_handoff_route_plan.json")

    a_pins = json.loads((ROOT / frozen_summary).read_text(encoding="utf-8"))["boundary_pins"]
    b_pins = json.loads((ROOT / candidate_summary).read_text(encoding="utf-8"))["boundary_pins"]
    if set(a_pins) != set(b_pins):
        raise ValueError("Candidate A/B controller boundary-pin names differ")
    changed = sorted(name for name in a_pins if a_pins[name] != b_pins[name])
    if set(changed) != INPUT_NAMES:
        raise ValueError(f"only the 14 north input pins may move; changed={changed}")
    unchanged = sorted(set(a_pins) - INPUT_NAMES)
    if len(unchanged) != 41:
        raise ValueError(f"expected 41 unchanged analog handoff pins, found {len(unchanged)}")

    plan = json.loads((ROOT / route_template).read_text(encoding="utf-8"))
    plan["status"] = "Candidate B route contract using frozen endpoint-compatible analog handoffs"
    plan["source_checkpoint"] = {
        "gds": str(candidate_source),
        "top": "v3_cb_4ch_ctrl_powered",
        "sha256": sha256(ROOT / candidate_source),
    }
    plan["overlay_top"] = "v3_cb_ctrl_analog_handoff_routes"
    plan["output_top"] = "v3_cb_4ch_ctrl_analog_handoff"
    plan["candidate_b_compatibility"] = {
        "candidate_a_manifest": str(frozen_summary),
        "candidate_a_manifest_sha256": sha256(ROOT / frozen_summary),
        "candidate_b_manifest": str(candidate_summary),
        "candidate_b_manifest_sha256": sha256(ROOT / candidate_summary),
        "unchanged_analog_handoff_pin_count": len(unchanged),
        "moved_top_input_pin_count": len(changed),
        "moved_top_input_pins": changed,
    }

    output = ROOT / WORK / "physical_control_analog_handoff_route_plan.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    compatibility = {
        "schema_version": 1,
        "status": "pass",
        "candidate": "B",
        "unchanged_analog_handoff_pin_count": len(unchanged),
        "moved_top_input_pin_count": len(changed),
        "unchanged_analog_handoff_pins": unchanged,
        "moved_top_input_pins": changed,
        "route_reuse_policy": "reuse is allowed only because every one of the 41 analog-facing controller terminals is bit-exact",
        "plan": str(output.relative_to(ROOT)),
        "plan_sha256": sha256(output),
    }
    report = ROOT / WORK / "analog_handoff_compatibility.json"
    report.write_text(json.dumps(compatibility, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(compatibility, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
