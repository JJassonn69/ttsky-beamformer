#!/usr/bin/env python3
"""Audit direct-boundary route legality against the exact source GDS."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_gds_flat_rules import MET2, MET3, flatten_rectangles, parse_gds, rectangle_gap  # noqa: E402
from check_control_phase_routes import CONDUCTORS, VIAS, distance, intersects  # noqa: E402
from build_control_pin_access_catalog import contains  # noqa: E402


def validate(
    data: dict[str, Any], plan: dict[str, Any], catalog: dict[str, Any],
    source_rectangles: dict[tuple[int, int], list[tuple[float, float, float, float]]],
    reservations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    routes, shapes = data["routes"], data["shapes"]
    expected = set(plan["routes"])
    if {item["net"] for item in routes} != expected:
        errors.append("direct-boundary route net set differs from plan")
    if len(data["labels"]) != len(expected):
        errors.append("direct-boundary label count differs from route count")
    if any(item["layer"] in ("metal4", "via3", "metal5") for item in shapes):
        errors.append("direct-boundary overlay uses forbidden upper metal")
    if any(item["direction_reversals"] != 0 for item in routes):
        errors.append("direct-boundary route contains a direction reversal")

    catalog_by_key = {(item["instance"], item["pin"]): item for item in catalog["records"]}
    access_errors = 0
    for route in routes:
        for access in route["accesses"]:
            record = catalog_by_key.get((access["instance"], access["pin"]))
            point = access["pin_um"]
            legal = record is not None and record["net"] == route["net"] and any(
                item["layer"] == "li1" and contains(item["rect_um"], point, item["required_inset_um"])
                for item in record["legal_access_rects"]
            )
            if not legal:
                access_errors += 1
                errors.append(f"{route['net']}: illegal catalog access {access['instance']}|{access['pin']}")
            if access["pin_escape_um"] > float(plan["rules"]["maximum_pin_escape_length"])+1e-9:
                errors.append(f"{route['net']}: pin escape exceeds limit at {access['instance']}|{access['pin']}")

    cuts = {layer: sum(item["layer"] == layer for item in shapes) for layer in VIAS}
    pin_count = sum(item["mapped_pin_count"] for item in routes)
    required = {"viali": pin_count, "via1": pin_count, "via2": pin_count+2*len(routes), "via3": 0}
    if cuts != required:
        errors.append(f"direct-boundary cut counts {cuts} != {required}")

    components: dict[str, int] = {}
    ownership_errors = 0
    for net in expected:
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
        unseen = set(range(len(conductors)))
        count = 0
        while unseen:
            count += 1
            queue = deque([unseen.pop()])
            while queue:
                for neighbour in edges[queue.popleft()]:
                    if neighbour in unseen:
                        unseen.remove(neighbour); queue.append(neighbour)
        components[net] = count
        if count != 1:
            errors.append(f"{net} has {count} disconnected overlay components")

    spacing = {"metal1": .14, "metal2": .14, "metal3": .30}
    signal_shapes = [item for item in shapes if item["layer"] in spacing]
    intra = 0
    for i, first in enumerate(signal_shapes):
        for second in signal_shapes[:i]:
            if first["net"] == second["net"] or first["layer"] != second["layer"]:
                continue
            if distance(first["bbox_um"], second["bbox_um"]) < spacing[first["layer"]]-1e-9:
                intra += 1
                errors.append(f"{first['id']} is too close to {second['id']}")

    source_interactions = Counter()
    for signal in signal_shapes:
        if signal["layer"] not in ("metal2", "metal3"):
            continue
        layer = MET2 if signal["layer"] == "metal2" else MET3
        for obstacle in source_rectangles[layer]:
            if rectangle_gap(tuple(signal["bbox_um"]), obstacle) < spacing[signal["layer"]]-1e-9:
                source_interactions[signal["layer"]] += 1
                errors.append(f"{signal['id']} has an unplanned source interaction with {obstacle}")

    service_access_keepout_errors = 0
    reserved_service_pin_count = 0
    if reservations is not None:
        service_shapes: list[tuple[str, str, str, str, list[float]]] = []
        for item in reservations["reservations"]:
            for reserved in item["reserved_shapes"]:
                if reserved["layer"] not in ("metal1", "metal2", "metal3"):
                    continue
                service_shapes.append((
                    item["net"], item["instance"], item["pin"],
                    reserved["layer"], list(map(float, reserved["bbox_um"])),
                ))
        reserved_service_pin_count = len(reservations["reservations"])
        for signal in [item for item in shapes if item["layer"] in ("metal1", "metal2", "metal3")]:
            clearance = float(plan["rules"][f"minimum_{signal['layer']}_clearance"])
            for net, instance, pin, layer, keepout in service_shapes:
                if signal["layer"] != layer:
                    continue
                gap = distance(signal["bbox_um"], keepout)
                if gap < clearance - 1e-9:
                    service_access_keepout_errors += 1
                    errors.append(
                        f"{signal['id']} ({signal['net']}) blocks reserved direct "
                        f"{layer} service escape {net}:{instance}|{pin} with only "
                        f"{gap:.3f} um clearance"
                    )

    spines = sorted(float(item["spine_x_um"]) for item in routes)
    minimum_pitch = min(second-first for first, second in zip(spines, spines[1:]))
    if minimum_pitch < float(plan["rules"]["minimum_spine_pitch"])-1e-9:
        errors.append(f"minimum spine pitch {minimum_pitch:.3f} um is below contract")
    return {
        "status": "pass" if not errors else "fail", "errors": errors,
        "route_count": len(routes), "mapped_pin_count": pin_count,
        "pin_access_error_count": access_errors,
        "cut_count_by_layer": cuts,
        "connected_component_count_by_net": dict(sorted(components.items())),
        "via_ownership_error_count": ownership_errors,
        "cross_net_spacing_error_count": intra,
        "source_interaction_count_by_layer": dict(sorted(source_interactions.items())),
        "reserved_service_pin_count": reserved_service_pin_count,
        "service_access_keepout_error_count": service_access_keepout_errors,
        "minimum_spine_pitch_um": round(minimum_pitch, 6),
        "total_centerline_um": data["metrics"]["total_centerline_um"],
        "maximum_pin_escape_um": data["metrics"]["maximum_pin_escape_um"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, default=Path("build/v2/control_routing/direct_boundary_geometry.json"))
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_direct_boundary_route_plan.json"))
    parser.add_argument("--catalog", type=Path, default=Path("build/v2/control_routing/control_pin_access_catalog.json"))
    parser.add_argument("--source-gds", type=Path, default=Path("build/v2/control_routing/direct/v2_control_quadrature_routed.gds"))
    parser.add_argument("--source-top", default="v2_control_quadrature_routed")
    parser.add_argument("--service-access", type=Path,
                        default=Path("build/v2/control_routing/service_pin_access_reservations.json"))
    parser.add_argument("--report", type=Path, default=Path("build/v2/control_routing/direct_boundary_route_audit.json"))
    args = parser.parse_args()
    structures, database_um = parse_gds(args.source_gds)
    source_rectangles = flatten_rectangles(structures, args.source_top, database_um)
    report = validate(
        json.loads(args.geometry.read_text()), json.loads(args.plan.read_text()),
        json.loads(args.catalog.read_text()), source_rectangles,
        json.loads(args.service_access.read_text()),
    )
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
