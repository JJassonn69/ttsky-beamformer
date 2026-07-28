#!/usr/bin/env python3
"""Bind Candidate B's routed controller into the unchanged V3 power plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORK = Path("build/v3/experiments/controller_pin_aligned")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    base_path = ROOT / "v3/layout/physical_control_power_plan.json"
    plan = json.loads(base_path.read_text(encoding="utf-8"))
    source = ROOT / WORK / (
        "openroad_internal/direct/"
        "v3_candidate_b_four_channel_control_signal_routed.gds"
    )
    gate = ROOT / WORK / "openroad_internal/route_audit.json"
    for path in (source, gate):
        if not path.is_file():
            raise SystemExit(f"missing Candidate B artifact: {path}")
    if json.loads(gate.read_text(encoding="utf-8")).get("status") != "pass":
        raise SystemExit("Candidate B route audit is not passing")
    plan["status"] = "Candidate B controller-power experiment"
    plan["candidate"] = "B"
    plan["source_checkpoint"] = {
        "gds": str(source.relative_to(ROOT)),
        "top": "v3_cb_4ch_ctrl_sig_routed",
        "sha256": sha256(source),
        "physical_gate": str(gate.relative_to(ROOT)),
        "physical_gate_sha256": sha256(gate),
    }
    plan["output_top"] = "v3_cb_4ch_ctrl_powered"
    plan["policy"]["candidate_a_submission_immutable"] = True
    plan["policy"]["controller_power_geometry_unchanged_from_candidate_a"] = True
    output = ROOT / WORK / "physical_control_power_plan.json"
    output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output.relative_to(ROOT)), "source_sha256": sha256(source)}, indent=2))


if __name__ == "__main__":
    main()

