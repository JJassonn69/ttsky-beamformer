#!/usr/bin/env python3
"""Create the Candidate B TinyTapeout-boundary routing contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORK = Path("build/v3/experiments/controller_pin_aligned")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = WORK / "analog_handoffs/direct/v3_cb_four_channel_ctrl_analog_handoffs.gds"
    source_gate = WORK / "analog_handoffs/direct/assembly_report.json"
    compatibility_path = WORK / "analog_handoff_compatibility.json"
    controller_manifest = WORK / "openroad_internal/input_summary.json"
    template = Path("build/v2/tt_analog_2x2.def")
    base = Path("v3/layout/physical_control_boundary_handoff_plan.json")

    assembly = json.loads((ROOT / source_gate).read_text(encoding="utf-8"))
    if assembly.get("status") != "pass":
        raise ValueError("Candidate B analog-handoff assembly did not pass")
    compatibility = json.loads((ROOT / compatibility_path).read_text(encoding="utf-8"))
    if compatibility.get("status") != "pass":
        raise ValueError("Candidate B analog-handoff endpoint compatibility did not pass")
    closed_gate_path = WORK / "analog_handoffs/physical_gate.json"
    closed_gate = {
        "schema_version": 1,
        "status": "pass",
        "candidate": "B",
        "scope": "41 endpoint-compatible controller-to-analog handoffs attached to Candidate B",
        "gds": str(source),
        "gds_sha256": sha256(ROOT / source),
        "assembly": str(source_gate),
        "assembly_sha256": sha256(ROOT / source_gate),
        "compatibility": str(compatibility_path),
        "compatibility_sha256": sha256(ROOT / compatibility_path),
        "unchanged_analog_handoff_pin_count": compatibility["unchanged_analog_handoff_pin_count"],
    }
    (ROOT / closed_gate_path).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / closed_gate_path).write_text(
        json.dumps(closed_gate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    plan = json.loads((ROOT / base).read_text(encoding="utf-8"))
    plan["status"] = "Candidate B pre-route TinyTapeout controller-input boundary contract"
    plan["source_checkpoint"] = {
        "gds": str(source),
        "top": "v3_cb_4ch_ctrl_analog_handoff",
        "sha256": sha256(ROOT / source),
        "physical_gate": str(closed_gate_path),
        "physical_gate_sha256": sha256(ROOT / closed_gate_path),
    }
    plan["endpoint_sources"]["controller_boundary_manifest"] = str(controller_manifest)
    plan["endpoint_sources"]["controller_boundary_manifest_sha256"] = sha256(
        ROOT / controller_manifest
    )
    plan["endpoint_sources"]["tinytapeout_template_def"] = str(template)
    plan["endpoint_sources"]["tinytapeout_template_def_sha256"] = sha256(ROOT / template)
    plan["candidate"] = "B"

    output = ROOT / WORK / "physical_control_boundary_handoff_plan.json"
    output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "generated",
        "candidate": "B",
        "output": str(output.relative_to(ROOT)),
        "source_sha256": plan["source_checkpoint"]["sha256"],
        "controller_manifest_sha256": plan["endpoint_sources"]["controller_boundary_manifest_sha256"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
