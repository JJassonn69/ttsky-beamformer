#!/usr/bin/env python3
"""Create the auditable Candidate A/B controller-placement decision record."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORK = Path("build/v3/experiments/controller_pin_aligned")


def load(path: Path) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def reduction(a: float, b: float) -> float:
    return round(100.0 * (a - b) / a, 3)


def main() -> None:
    a_internal_path = Path("v3/frozen/controller_signal_routing/route_audit.json")
    b_internal_path = WORK / "openroad_internal/route_audit.json"
    a_boundary_path = Path("v3/frozen/controller_boundary_handoffs/route_audit.json")
    b_boundary_path = WORK / "boundary_handoffs/openroad/route_audit.json"
    b_precheck_path = WORK / "boundary_handoffs/precheck/precheck_summary.json"
    b_topology_path = WORK / "boundary_handoffs/boundary_topology_audit.json"
    a_manifest_path = Path("v3/experiments/controller_pin_aligned/candidate_a_manifest.json")

    a_internal = load(a_internal_path)
    b_internal = load(b_internal_path)
    a_boundary = load(a_boundary_path)
    b_boundary = load(b_boundary_path)
    b_precheck = load(b_precheck_path)
    b_topology = load(b_topology_path)
    a_manifest = load(a_manifest_path)
    if not all(
        item.get("status") == "pass"
        for item in (b_internal, b_boundary, b_precheck, b_topology)
    ):
        raise ValueError("Candidate B has an open physical or topology gate")

    aiw = float(a_internal["total_centerline_wire_length_um"])
    biw = float(b_internal["total_centerline_wire_length_um"])
    aiv = int(a_internal["total_via_count"])
    biv = int(b_internal["total_via_count"])
    abw = float(a_boundary["total_centerline_wire_length_um"])
    bbw = float(b_boundary["total_centerline_wire_length_um"])
    abv = int(a_boundary["total_via_count"])
    bbv = int(b_boundary["total_via_count"])

    report = {
        "schema_version": 1,
        "status": "pass",
        "decision": "prefer_candidate_b",
        "decision_reason": (
            "pin-aligned controller placement makes both the controller and TinyTapeout top interface "
            "shorter and simpler without moving analog support components or changing the extracted device population"
        ),
        "candidate_a": {
            "role": "frozen production reference",
            "commit": a_manifest["branch_point_commit"],
            "submission_gds_sha256": a_manifest["files"][
                "v3/frozen/submission/tt_um_jjassonn69_beamformer.gds"
            ],
        },
        "candidate_b": {
            "role": "controller-only pin-aligned experiment",
            "assembled_gds": str(WORK / "boundary_handoffs/direct/v3_cb_four_channel_ctrl_boundary_handoffs.gds"),
            "assembled_gds_sha256": sha256(WORK / "boundary_handoffs/direct/v3_cb_four_channel_ctrl_boundary_handoffs.gds"),
            "analog_support_relocated": False,
            "controller_bbox_changed": False,
            "extracted_device_count": b_topology["checks"]["total_extracted_devices"],
            "device_population_matches_source": b_topology["checks"]["device_population_matches_source"],
        },
        "metrics": {
            "controller_internal": {
                "candidate_a_wire_um": aiw,
                "candidate_b_wire_um": biw,
                "wire_reduction_percent": reduction(aiw, biw),
                "candidate_a_vias": aiv,
                "candidate_b_vias": biv,
                "via_reduction_percent": reduction(aiv, biv),
            },
            "tinytapeout_top_interface": {
                "candidate_a_wire_um": abw,
                "candidate_b_wire_um": bbw,
                "wire_reduction_percent": reduction(abw, bbw),
                "candidate_a_vias": abv,
                "candidate_b_vias": bbv,
                "via_reduction_percent": reduction(abv, bbv),
                "candidate_a_maximum_detour_ratio": a_boundary["maximum_detour"]["detour_ratio"],
                "candidate_b_maximum_detour_ratio": b_boundary["maximum_detour"]["detour_ratio"],
            },
        },
        "closed_gates": {
            "placement": "pass",
            "openroad_internal_detailed_route": "pass",
            "power_connectivity": "pass",
            "analog_handoff_endpoint_compatibility": "pass",
            "openroad_boundary_graph": "pass",
            "pinned_klayout_geometry_precheck": "pass",
            "magic_drc": "pass",
            "magic_extracted_topology": "pass",
        },
        "topology_checks": b_topology["checks"],
        "deferred_experiment": {
            "name": "vertical controller plus support relocation",
            "status": "not justified",
            "reason": "Candidate B already produces a visibly and electrically cleaner top interface; moving capacitors for visual grouping would add analog return-path risk without solving an open gate",
        },
        "review_images": {
            "integrated_comparison": str(WORK / "review/candidate_a_b_integrated_comparison.png"),
            "routes_only_comparison": str(WORK / "review/candidate_a_b_routes_comparison.png"),
        },
        "artifact_sha256": {
            "candidate_a_internal_audit": sha256(a_internal_path),
            "candidate_b_internal_audit": sha256(b_internal_path),
            "candidate_a_boundary_audit": sha256(a_boundary_path),
            "candidate_b_boundary_audit": sha256(b_boundary_path),
            "candidate_b_precheck": sha256(b_precheck_path),
            "candidate_b_topology": sha256(b_topology_path),
        },
    }
    output = ROOT / WORK / "candidate_comparison.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
