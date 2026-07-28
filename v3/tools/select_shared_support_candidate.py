#!/usr/bin/env python3
"""Consolidate the V3 shared-support electrical selection evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CAP_SCREEN = ROOT / "v3" / "evidence" / "vcm_cap_tradeoff.json"
RESISTOR_SCREEN = ROOT / "v3" / "evidence" / "vcm_resistor_type_tradeoff.json"
PVT_REJECTED = ROOT / "v3" / "evidence" / "four_channel_support_pvt_mim2_rejected.json"
PVT_SELECTED = ROOT / "v3" / "evidence" / "four_channel_support_pvt.json"
MIM3_DIAGNOSTIC = ROOT / "v3" / "evidence" / "support_pvt_mim3_fs.json"
MIM4_DIAGNOSTIC = ROOT / "v3" / "evidence" / "support_pvt_mim4_fs.json"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "shared_support_candidate_selection.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def maximum_ripple(report: dict[str, Any]) -> float:
    return max(case["vcm_peak_to_peak_v"] for case in report["cases"])


def build() -> dict[str, Any]:
    cap = json.loads(CAP_SCREEN.read_text(encoding="utf-8"))
    resistor = json.loads(RESISTOR_SCREEN.read_text(encoding="utf-8"))
    rejected = json.loads(PVT_REJECTED.read_text(encoding="utf-8"))
    selected = json.loads(PVT_SELECTED.read_text(encoding="utf-8"))
    mim3 = json.loads(MIM3_DIAGNOSTIC.read_text(encoding="utf-8"))
    mim4 = json.loads(MIM4_DIAGNOSTIC.read_text(encoding="utf-8"))
    selected_candidate = selected["selected_candidate"]
    gates = {
        "nominal_cap_screen_passed": cap["status"] == "pass",
        "lower_resistance_only_rejected": resistor["status"] == "fail",
        "two_mim_candidate_rejected_at_pvt": (
            rejected["status"] == "fail"
            and rejected["selected_candidate"]["mim_count"] == 2
            and not rejected["gates"]["vcm_peak_to_peak_at_most_15mv"]
        ),
        "three_mim_worst_corner_diagnostic_passed": (
            mim3["status"] == "diagnostic_subset"
            and maximum_ripple(mim3) <= 0.015
        ),
        "selected_three_mim_full_pvt_passed": (
            selected["status"] == "pass"
            and selected_candidate["mim_count"] == 3
            and selected_candidate["varactor_count"] == 0
            and selected_candidate["divider_scale_vs_v2"] == 0.25
        ),
        "four_mim_is_unnecessary_for_gate": (
            maximum_ripple(mim4) < maximum_ripple(mim3)
            and maximum_ripple(mim3) <= 0.015
        ),
    }
    return {
        "schema_version": 1,
        "status": "pass" if all(gates.values()) else "fail",
        "scope": "hierarchical schematic-level selection of shared VCM divider, bypass count, and output load before exact physical routing",
        "selected_candidate": {
            "divider_topology": "six identical xhigh-poly units in exact B-A-B / B-A-B common-centroid assignment",
            "divider_scale_vs_v2": 0.25,
            "divider_unit_cell": "XVCM_UNIT_SCALE_0P25",
            "divider_unit_length_um": 5.875,
            "divider_unit_count": 6,
            "vcm_mim_count": 3,
            "modeled_vcm_bypass_pf": 2.94,
            "measured_pcell_nominal_vcm_bypass_pf": 2.95416,
            "vcm_varactor_count": 0,
            "output_load_pcell": "XOUTPUT_LOAD",
            "output_load_pcell_nominal_ohm": 2910.0,
            "output_load_simulation_ohm": 2925.0,
        },
        "selection_reason": "two MIMs are nominally sufficient but miss the FS PVT ripple limit; three are the minimum PVT-clean choice; lower divider resistance alone does not close the gate and four MIMs add area without being required",
        "rejected_or_unselected": {
            "two_mim_maximum_pvt_ripple_v": maximum_ripple(rejected),
            "three_mim_worst_fs_diagnostic_ripple_v": maximum_ripple(mim3),
            "four_mim_worst_fs_diagnostic_ripple_v": maximum_ripple(mim4),
            "lower_resistance_best_ripple_v": min(
                item["maximum_vcm_peak_to_peak_v"]
                for item in resistor["candidates"]
            ),
        },
        "gates": gates,
        "provenance": {
            "generator": "v3/tools/select_shared_support_candidate.py",
            "generator_sha256": sha256(Path(__file__)),
            "inputs": {
                str(path.relative_to(ROOT)): sha256(path)
                for path in (
                    CAP_SCREEN, RESISTOR_SCREEN, PVT_REJECTED, PVT_SELECTED,
                    MIM3_DIAGNOSTIC, MIM4_DIAGNOSTIC,
                )
            },
        },
        "next_gate": "regenerate the three-MIM support placement, then run exact Magic DRC, topology extraction, direct-GDS flat checks, and distributed RC before the complete-channel pilot",
    }


def main() -> None:
    report = build()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": report["status"], "gates": report["gates"]}, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
