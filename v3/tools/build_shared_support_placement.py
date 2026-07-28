#!/usr/bin/env python3
"""Build the authoritative V3 shared-support placement constraint manifest.

The manifest fixes the nominally selected six-unit common-centroid VCM
divider, three-MIM VCM bypass, symmetric output loads, shared tail-bias
resistor, and two-MIM tail-bias bypass.  It intentionally stops before
drawing Magic geometry; exact terminal landings, DRC, topology extraction,
and distributed RC remain the next physical-pilot gate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FLOORPLAN = ROOT / "v3" / "layout" / "floorplan.json"
CATALOG = ROOT / "v3" / "layout" / "shared_support_pcell_catalog.json"
SUPPORT_SELECTION = ROOT / "v3" / "evidence" / "shared_support_candidate_selection.json"
BIAS = ROOT / "v3" / "layout" / "bias_distribution.json"
INPUT_BIAS = ROOT / "v3" / "layout" / "input_bias_distribution.json"
DEFAULT_OUTPUT = ROOT / "v3" / "layout" / "shared_support_placement.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def translate(point: list[float], center: list[float]) -> list[float]:
    return [round(center[0] + point[0], 6), round(center[1] + point[1], 6)]


def segment(
    start: list[float], stop: list[float], layer: str, width_um: float
) -> dict[str, Any]:
    if start[0] != stop[0] and start[1] != stop[1]:
        raise ValueError(f"non-Manhattan segment {start} -> {stop}")
    return {
        "from": start,
        "to": stop,
        "layer": layer,
        "width_um": width_um,
    }


def placed_component(
    name: str,
    cell_name: str,
    center: list[float],
    cells: dict[str, Any],
    nets: dict[str, str],
    role: str,
) -> dict[str, Any]:
    cell = cells[cell_name]
    bbox = cell["bbox_um"]
    return {
        "name": name,
        "role": role,
        "catalog_cell": cell_name,
        "generated_cell": cell["generated_cell"],
        "center": center,
        "orientation": "R0",
        "bbox": [
            round(center[0] + bbox[0], 6),
            round(center[1] + bbox[1], 6),
            round(center[0] + bbox[2], 6),
            round(center[1] + bbox[3], 6),
        ],
        "terminals": {
            label: [translate(port["point_um"], center) for port in ports]
            for label, ports in cell["ports"].items()
        },
        "nets": nets,
    }


def first_terminal(component: dict[str, Any], name: str) -> list[float]:
    values = component["terminals"][name]
    if len(values) != 1:
        raise ValueError(f"{component['name']}.{name} is not a single measured terminal")
    return values[0]


def build() -> dict[str, Any]:
    floorplan = json.loads(FLOORPLAN.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    selection = json.loads(SUPPORT_SELECTION.read_text(encoding="utf-8"))
    bias = json.loads(BIAS.read_text(encoding="utf-8"))
    input_bias = json.loads(INPUT_BIAS.read_text(encoding="utf-8"))
    if catalog["status"] != "pass" or selection["status"] != "pass":
        raise RuntimeError("shared-support PCell or nominal VCM selection gate is open")
    selected = selection["selected_candidate"]
    if (
        selected["divider_scale_vs_v2"] != 0.25
        or selected["vcm_mim_count"] != 3
        or selected["vcm_varactor_count"] != 0
    ):
        raise RuntimeError("VCM support selection changed; placement must be reconsidered")
    cells = catalog["cells"]

    # B-A-B / B-A-B yields identical A and B centroids at (32.5, 127).
    unit_cell = "XVCM_UNIT_SCALE_0P25"
    assignments = (
        ("RVCM_B0", "B", [22.0, 136.0], {"B": "VGND", "R1": "vcm_b2", "R2": "vcm_b1"}),
        ("RVCM_T0", "A", [32.5, 136.0], {"B": "VGND", "R1": "VDPWR", "R2": "vcm_tmid"}),
        ("RVCM_B1", "B", [43.0, 136.0], {"B": "VGND", "R1": "vcm_b2", "R2": "vcm_b3"}),
        ("RVCM_B2", "B", [22.0, 118.0], {"B": "VGND", "R1": "vcm_b1", "R2": "vcm"}),
        ("RVCM_T1", "A", [32.5, 118.0], {"B": "VGND", "R1": "vcm_tmid", "R2": "vcm"}),
        ("RVCM_B3", "B", [43.0, 118.0], {"B": "VGND", "R1": "vcm_b3", "R2": "VGND"}),
    )
    divider = [
        placed_component(name, unit_cell, center, cells, nets, f"vcm_divider_{group}")
        for name, group, center, nets in assignments
    ]
    by_name = {item["name"]: item for item in divider}
    divider_routes = [
        {"net": "vcm_tmid", "segments": [segment(
            first_terminal(by_name["RVCM_T0"], "R2"),
            first_terminal(by_name["RVCM_T1"], "R1"), "metal2", 0.50,
        )]},
        {"net": "vcm_b1", "segments": [segment(
            first_terminal(by_name["RVCM_B2"], "R1"),
            first_terminal(by_name["RVCM_B0"], "R2"), "metal2", 0.50,
        )]},
        {"net": "vcm_b2", "segments": [segment(
            first_terminal(by_name["RVCM_B0"], "R1"),
            first_terminal(by_name["RVCM_B1"], "R1"), "metal3", 0.50,
        )]},
        {"net": "vcm_b3", "segments": [segment(
            first_terminal(by_name["RVCM_B1"], "R2"),
            first_terminal(by_name["RVCM_B3"], "R1"), "metal2", 0.50,
        )]},
        {"net": "vcm", "segments": [segment(
            first_terminal(by_name["RVCM_B2"], "R2"),
            first_terminal(by_name["RVCM_T1"], "R2"), "metal2", 0.50,
        )]},
    ]

    vcm_caps = [
        placed_component(
            f"CVCM{index}", "XDECAP_MIM", [33.38, y], cells,
            {"C1": "vcm", "C2": "VGND"}, "vcm_bypass",
        )
        for index, y in enumerate((78.0, 50.0, 22.0))
    ]
    cap_top = [first_terminal(item, "C1") for item in vcm_caps]
    cap_bottom = [first_terminal(item, "C2") for item in vcm_caps]
    divider_vcm = first_terminal(by_name["RVCM_T1"], "R2")
    vcm_root = input_bias["vcm_distribution"]["root"]
    cap_top_chain = [
        segment(cap_top[index], cap_top[index + 1], "metal4", 0.50)
        for index in range(len(cap_top) - 1)
    ]
    vcm_feed = {
        "net": "vcm",
        "named_star": divider_vcm,
        "segments": [
            segment(divider_vcm, [divider_vcm[0], 94.0], "metal4", 0.50),
            segment([divider_vcm[0], 94.0], cap_top[0], "metal4", 0.50),
            *cap_top_chain,
            segment([divider_vcm[0], 94.0], [53.0, 94.0], "metal4", 0.50),
            segment([53.0, 94.0], [53.0, vcm_root[1]], "metal4", 0.50),
            segment([53.0, vcm_root[1]], vcm_root, "metal4", 0.50),
        ],
        "via_stack_at_divider_star": ["via1", "via2", "via3"],
        "via3_at_input_tree_root": True,
        "crossing_policy": "leave each MIM C1 top plate vertically, cross above the capacitor so Metal 4 never touches its C2 Via-3 landing, cross output Metal-3 trunks only on Metal 4, and remain below the Metal-4 differential sum buses",
        "direction_reversals": 0,
    }
    cap_ground_chain = [
        segment(cap_bottom[index], cap_bottom[index + 1], "metal3", 0.80)
        for index in range(len(cap_bottom) - 1)
    ]
    vcm_ground = {
        "net": "VGND",
        "segments": [
            *cap_ground_chain,
            segment(cap_bottom[-1], [cap_bottom[-1][0], 5.0], "metal3", 0.80),
        ],
        "joins_guard_and_power_ground_only_at_named_ground_strap": True,
    }

    output_pair = []
    for side in ("p", "n"):
        output_pair.append(placed_component(
            f"RLOAD_{side.upper()}",
            "XOUTPUT_LOAD",
            floorplan["output_pair"][f"load_{side}_center"],
            cells,
            {"B": "VGND", "R1": "VDPWR", "R2": f"beam_out_{side}"},
            "differential_output_load",
        ))

    tail_reference_center = bias["reference"]["center_um"]
    tail_resistor = placed_component(
        "RBIAS", "XTAIL_BIAS_RESISTOR", [210.0, 80.0], cells,
        {"B": "VGND", "R1": "VDPWR", "R2": "vbias_ref"},
        "tail_reference_bias_resistor",
    )
    tail_caps = [
        placed_component(
            f"CBIAS{index}", "XDECAP_MIM", [x, 48.0], cells,
            {"C1": "vbias_ref", "C2": "VGND"}, "tail_bias_bypass",
        )
        for index, x in enumerate((228.0, 256.0))
    ]
    tail_cap_top = [first_terminal(item, "C1") for item in tail_caps]
    tail_cap_bottom = [first_terminal(item, "C2") for item in tail_caps]
    tail_star = bias["common_route"]["start"]
    tail_support_routes = {
        "rbias_to_star": {
            "net": "vbias_ref",
            "segments": [
                segment(first_terminal(tail_resistor, "R2"), [tail_star[0], first_terminal(tail_resistor, "R2")[1]], "metal2", 0.80),
                segment([tail_star[0], first_terminal(tail_resistor, "R2")[1]], tail_star, "metal2", 0.80),
            ],
        },
        "decap_top_bus": {
            "net": "vbias_ref",
            "segments": [
                segment(tail_star, [tail_cap_top[0][0], tail_star[1]], "metal4", 0.80),
                segment([tail_cap_top[0][0], tail_star[1]], tail_cap_top[0], "metal4", 0.80),
                segment(tail_cap_top[0], tail_cap_top[1], "metal4", 0.80),
            ],
        },
        "decap_ground_bus": {
            "net": "VGND",
            "segments": [
                segment(tail_cap_bottom[0], tail_cap_bottom[1], "metal3", 0.80),
                segment(tail_cap_bottom[0], [tail_cap_bottom[0][0], 30.0], "metal3", 0.80),
            ],
        },
    }

    return {
        "schema_version": 1,
        "units": "um",
        "status": "constraint placement selected by nominal and full five-corner PVT gates; exact Magic routing, DRC, extraction topology, distributed RC, and direct-GDS checks pending",
        "provenance": {
            "generator": "v3/tools/build_shared_support_placement.py",
            "floorplan": "v3/layout/floorplan.json",
            "floorplan_sha256": sha256(FLOORPLAN),
            "pcell_catalog": "v3/layout/shared_support_pcell_catalog.json",
            "pcell_catalog_sha256": sha256(CATALOG),
            "shared_support_candidate_selection": "v3/evidence/shared_support_candidate_selection.json",
            "shared_support_candidate_selection_sha256": sha256(SUPPORT_SELECTION),
            "bias_distribution": "v3/layout/bias_distribution.json",
            "bias_distribution_sha256": sha256(BIAS),
            "input_bias_distribution": "v3/layout/input_bias_distribution.json",
            "input_bias_distribution_sha256": sha256(INPUT_BIAS),
        },
        "vcm": {
            "divider_topology": "six identical units; two series above VCM and four below",
            "common_centroid_matrix": [["B", "A", "B"], ["B", "A", "B"]],
            "divider_unit_cell": unit_cell,
            "divider_units": divider,
            "divider_internal_routes": divider_routes,
            "bypass_capacitors": vcm_caps,
            "bypass_modeled_total_pf": selected["modeled_vcm_bypass_pf"],
            "bypass_measured_pcell_nominal_total_pf": selected["measured_pcell_nominal_vcm_bypass_pf"],
            "feed": vcm_feed,
            "ground": vcm_ground,
            "varactor_count": selected["vcm_varactor_count"],
        },
        "input_bias": {
            "manifest": "v3/layout/input_bias_distribution.json",
            "resistor_count": len(input_bias["placement"]["resistors"]),
            "integration_status": "constraint-placed; exact guard merge remains one-channel pilot gate",
        },
        "output_pair": {
            "components": output_pair,
            "nominal_simulation_resistance_ohm": 2925.0,
            "pcell_nominal_value_ohm": 2910.0,
            "routing": floorplan["output_pair"]["routes"],
            "channel_taps": floorplan["output_pair"]["channel_taps"],
        },
        "tail_bias": {
            "reference_center": tail_reference_center,
            "reference_status": bias["status"],
            "bias_resistor": tail_resistor,
            "bypass_capacitors": tail_caps,
            "bypass_nominal_total_pf": 1.96,
            "routes": tail_support_routes,
            "closed_bias_tree_manifest": "v3/layout/bias_distribution.json",
        },
        "layout_invariants": {
            "metal5_used": False,
            "floating_stubs_allowed": False,
            "orphan_vias_allowed": False,
            "u_turns_or_meanders_allowed": False,
            "all_via_stacks_must_be_at_named_terminals_or_branch_points": True,
            "do_not_move_channel_pin_selector_or_closed_tail_reference_axes": True,
            "exact_common_centroid_required_for_vcm_divider": True,
        },
        "promotion_gates": [
            "selected support candidate remains bound to passing all five MOS PVT corners and gm headroom evidence",
            "Magic pilot places the exact measured PCells without overlap or keepout intrusion",
            "Magic DRC and Tiny Tapeout-compatible direct-GDS flat checks have zero markers",
            "extraction proves the 2:4 VCM divider, three VCM MIMs, two tail-bias MIMs, symmetric loads, and no unintended shorts",
            "distributed RC confirms balanced VCM leaves, output loads, and tail-bias branches",
            "startup settles before the documented enable/measurement delay",
        ],
    }


def main() -> None:
    report = build()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
