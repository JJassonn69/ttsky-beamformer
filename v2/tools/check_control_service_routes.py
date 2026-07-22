#!/usr/bin/env python3
"""Audit service-tree connectivity, shielding, spacing, and source clearance."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_gds_flat_rules import MET2, MET3, MET4, flatten_rectangles, parse_gds, rectangle_gap  # noqa: E402
from check_control_phase_routes import CONDUCTORS, VIAS, distance, intersects  # noqa: E402
from build_control_pin_access_catalog import contains  # noqa: E402


def validate(data: dict[str, Any], plan: dict[str, Any], catalog: dict[str, Any], source: dict) -> dict[str, Any]:
    errors: list[str] = []
    routes, shapes = data["routes"], data["shapes"]
    expected = set(plan["spines"])
    if {item["net"] for item in routes} != expected:
        errors.append("service route set differs from plan")
    if len(data["labels"]) != 6:
        errors.append("service label count is not six")
    if any(item["layer"] == "metal5" for item in shapes):
        errors.append("service overlay uses forbidden metal5")

    catalog_by_key = {(item["instance"], item["pin"]): item for item in catalog["records"]}
    access_errors = 0
    for route in routes:
        for access in route["mapped_accesses"]:
            record = catalog_by_key.get((access["instance"], access["pin"]))
            legal = record is not None and record["net"] == route["net"] and any(
                item["layer"] == access["pin_layer"]
                and contains(item["rect_um"], access["pin_um"], item["required_inset_um"])
                for item in record["legal_access_rects"]
            )
            if not legal:
                access_errors += 1
                errors.append(f"{route['net']}: illegal pin access {access['instance']}|{access['pin']}")

    mapped = sum(item["mapped_pin_count"] for item in routes)
    li = sum(access["pin_layer"] == "li1" for route in routes for access in route["mapped_accesses"])
    external = sum(item["external_pin_count"] for item in routes)
    branch_count = sum(len(item["branches"]) for item in routes)
    accesses = [access for route in routes for access in route["mapped_accesses"]]
    max_m1_escape = max(float(item["m1_escape_manhattan_um"]) for item in accesses)
    max_m2_escape = max(float(item["m2_leaf_escape_um"]) for item in accesses)
    wrong_way = [
        abs(float(item["branch_track_y_um"]) - float(item["lift_um"][1]))
        for item in accesses if item["leaf_topology"].startswith("metal2_vertical")
    ]
    max_wrong_way = max(wrong_way, default=0.0)
    if max_m1_escape > float(plan["rules"]["maximum_m1_escape_manhattan"]) + 1e-9:
        errors.append("M1 pin escape exceeds the contracted local limit")
    if max_m2_escape > float(plan["rules"]["maximum_m2_leaf_escape"]) + 1e-9:
        errors.append("M2 pin-to-leaf escape exceeds the contracted local limit")
    if max_wrong_way > float(plan["rules"]["maximum_wrong_way_m2_vertical"]) + 1e-9:
        errors.append("obstacle-forced wrong-way M2 segment exceeds the contracted limit")
    exchange_x = float(plan["power_moat_bridge"]["left_transition_x_um"])
    moat_errors = 0
    for route in routes:
        for branch in route["branches"]:
            if (abs(float(branch["x_span_um"][1]) - exchange_x) > 1e-9
                    or branch.get("power_moat_bridge_um") != [exchange_x, float(route["spine_x_um"])]):
                moat_errors += 1
                errors.append(f"{route['net']} {branch['group']} bypasses the M2 power-moat crossing")
    cuts = {layer: sum(item["layer"] == layer for item in shapes) for layer in VIAS}
    required = {
        "viali": li,
        "via1": mapped,
        "via2": mapped + 2*branch_count,
        "via3": mapped + branch_count + 3*external + 2,
    }
    if cuts != required:
        errors.append(f"service cut counts {cuts} != {required}")

    components: dict[str, int] = {}
    ownership_errors = 0
    for net in expected | {"VGND"}:
        conductors = [item for item in shapes if item["net"] == net and item["layer"] in CONDUCTORS]
        edges: dict[int, set[int]] = defaultdict(set)
        for i, first in enumerate(conductors):
            for j, second in enumerate(conductors[:i]):
                if first["layer"] == second["layer"] and intersects(first["bbox_um"], second["bbox_um"]):
                    edges[i].add(j); edges[j].add(i)
        for via in [item for item in shapes if item["net"] == net and item["layer"] in VIAS]:
            lower, upper = VIAS[via["layer"]]
            lo = [i for i, item in enumerate(conductors) if item["layer"] == lower and intersects(item["bbox_um"], via["bbox_um"])]
            hi = [i for i, item in enumerate(conductors) if item["layer"] == upper and intersects(item["bbox_um"], via["bbox_um"])]
            if not lo or not hi:
                ownership_errors += 1
                errors.append(f"{via['id']} lacks two-sided same-net ownership")
            for i in lo:
                for j in hi:
                    edges[i].add(j); edges[j].add(i)
        unseen = set(range(len(conductors))); count = 0
        while unseen:
            count += 1; queue = deque([unseen.pop()])
            while queue:
                for neighbour in edges[queue.popleft()]:
                    if neighbour in unseen:
                        unseen.remove(neighbour); queue.append(neighbour)
        components[net] = count
        if count != 1:
            errors.append(f"{net} has {count} overlay components")

    spacing = {"metal1": .14, "metal2": .14, "metal3": .30, "metal4": .30}
    signal_shapes = [item for item in shapes if item["layer"] in spacing]
    intra = 0
    for i, first in enumerate(signal_shapes):
        for second in signal_shapes[:i]:
            if first["net"] == second["net"] or first["layer"] != second["layer"]:
                continue
            if distance(first["bbox_um"], second["bbox_um"]) < spacing[first["layer"]]-1e-9:
                intra += 1
                errors.append(f"{first['id']} is too close to {second['id']}")

    source_interactions = Counter(); planned_ground_joins = 0
    source_x = float(plan["ground_bridge"]["source_m3_x_um"])
    bridge_y = float(plan["ground_bridge"]["y_um"])
    for signal in signal_shapes:
        if signal["layer"] not in ("metal2", "metal3", "metal4"):
            continue
        layer = {"metal2": MET2, "metal3": MET3, "metal4": MET4}[signal["layer"]]
        for obstacle in source[layer]:
            if rectangle_gap(tuple(signal["bbox_um"]), obstacle) >= spacing[signal["layer"]]-1e-9:
                continue
            intended = (
                signal["net"] == "VGND" and signal["layer"] in ("metal3", "metal4")
                and obstacle[0]-1e-9 <= source_x <= obstacle[2]+1e-9
                and obstacle[1]-1e-9 <= bridge_y <= obstacle[3]+1e-9
            )
            if intended:
                planned_ground_joins += 1
            else:
                source_interactions[signal["layer"]] += 1
                errors.append(f"{signal['id']} has unplanned source interaction with {obstacle}")

    shield_shapes = [item for item in shapes if item["kind"] == "ground_shield"]
    if len(shield_shapes) != 2 or {round((item["bbox_um"][0]+item["bbox_um"][2])/2, 3) for item in shield_shapes} != set(plan["ground_shields_x"]):
        errors.append("two contracted ground shields are not present")
    return {
        "status": "pass" if not errors else "fail", "errors": errors,
        "route_count": len(routes), "mapped_pin_count": mapped, "external_pin_count": external,
        "branch_count": branch_count, "pin_access_error_count": access_errors,
        "maximum_m1_escape_manhattan_um": max_m1_escape,
        "maximum_m2_leaf_escape_um": max_m2_escape,
        "wrong_way_m2_vertical_count": len(wrong_way),
        "maximum_wrong_way_m2_vertical_um": max_wrong_way,
        "power_moat_bridge_error_count": moat_errors,
        "cut_count_by_layer": cuts, "connected_component_count_by_net": dict(sorted(components.items())),
        "via_ownership_error_count": ownership_errors,
        "cross_net_spacing_error_count": intra,
        "unplanned_source_interaction_count_by_layer": dict(sorted(source_interactions.items())),
        "planned_ground_source_join_count": planned_ground_joins,
        "ground_shield_count": len(shield_shapes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, default=Path("build/v2/control_routing/service_geometry.json"))
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_service_route_plan.json"))
    parser.add_argument("--catalog", type=Path, default=Path("build/v2/control_routing/control_pin_access_catalog.json"))
    parser.add_argument("--source-gds", type=Path, default=Path("build/v2/control_routing/direct/v2_control_direct_routed.gds"))
    parser.add_argument("--source-top", default="v2_control_direct_routed")
    parser.add_argument("--report", type=Path, default=Path("build/v2/control_routing/service_route_audit.json"))
    args = parser.parse_args()
    structures, database_um = parse_gds(args.source_gds)
    source = flatten_rectangles(structures, args.source_top, database_um)
    report = validate(json.loads(args.geometry.read_text()), json.loads(args.plan.read_text()), json.loads(args.catalog.read_text()), source)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
