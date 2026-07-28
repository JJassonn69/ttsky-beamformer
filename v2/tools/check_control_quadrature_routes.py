#!/usr/bin/env python3
"""Audit quadrature route connectivity, spacing, and source interactions."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_gds_flat_rules import MET2, MET3, flatten_rectangles, parse_gds, rectangle_gap  # noqa: E402
from check_control_phase_routes import CONDUCTORS, VIAS, distance, intersects  # noqa: E402
from check_route_cut_geometry import cut_geometry_errors  # noqa: E402


def validate(data: dict[str, Any], plan: dict[str, Any], power: dict[str, Any],
             trim: dict[str, Any], phase: dict[str, Any],
             source_rectangles: dict[tuple[int, int], list[tuple[float, float, float, float]]] | None = None,
             ) -> dict[str, Any]:
    errors: list[str] = []
    routes, shapes = data["routes"], data["shapes"]
    expected = {f"phase_wave[{index}]" for index in range(4)}
    if {item["net"] for item in routes} != expected:
        errors.append("quadrature route net set differs from four-net contract")
    if len(data["labels"]) != 4:
        errors.append("quadrature route label count is not four")
    if any(item["layer"] in ("metal4", "metal5") for item in shapes):
        errors.append("quadrature overlay uses forbidden upper metal")
    maximum_reversals = int(plan["policy"]["maximum_direction_reversals"])
    if any(item["direction_reversals"] > maximum_reversals for item in routes):
        errors.append("quadrature route exceeds the direction-reversal contract")

    cuts = {layer: sum(item["layer"] == layer for item in shapes) for layer in VIAS}
    expected_pin_count = sum(item["mapped_pin_count"] for item in routes)
    required = {"viali": 0, "via1": 0,
                "via2": len(plan.get("manual_boundary_via_nets", [])), "via3": 0}
    if cuts != required:
        errors.append(f"quadrature cut counts {cuts} != {required}")
    errors.extend(cut_geometry_errors(shapes))

    components: dict[str, int] = {}
    ownership_errors = 0
    for net in expected:
        conductors = [s for s in shapes if s["net"] == net and s["layer"] in CONDUCTORS]
        edges: dict[int, set[int]] = defaultdict(set)
        for i, first in enumerate(conductors):
            for j, second in enumerate(conductors[:i]):
                if first["layer"] == second["layer"] and intersects(first["bbox_um"], second["bbox_um"]):
                    edges[i].add(j); edges[j].add(i)
        for via in [s for s in shapes if s["net"] == net and s["layer"] in VIAS]:
            lower, upper = VIAS[via["layer"]]
            lo = [i for i,s in enumerate(conductors) if s["layer"] == lower and intersects(s["bbox_um"], via["bbox_um"])]
            hi = [i for i,s in enumerate(conductors) if s["layer"] == upper and intersects(s["bbox_um"], via["bbox_um"])]
            if not lo or not hi:
                ownership_errors += 1; errors.append(f"{via['id']} lacks two-sided ownership")
            for i in lo:
                for j in hi: edges[i].add(j); edges[j].add(i)
        unseen = set(range(len(conductors))); count = 0
        while unseen:
            count += 1; queue = deque([unseen.pop()])
            while queue:
                for neighbour in edges[queue.popleft()]:
                    if neighbour in unseen: unseen.remove(neighbour); queue.append(neighbour)
        components[net] = count
        if count != 1: errors.append(f"{net} has {count} overlay components")

    spacing = {"metal1": .14, "metal2": .14, "metal3": .30}
    signal_shapes = [s for s in shapes if s["layer"] in spacing]
    intra = 0
    for i, first in enumerate(signal_shapes):
        for second in signal_shapes[:i]:
            if first["net"] == second["net"] or first["layer"] != second["layer"]: continue
            if distance(first["bbox_um"], second["bbox_um"]) < spacing[first["layer"]]-1e-9:
                intra += 1; errors.append(f"{first['id']} is too close to {second['id']}")

    cross = Counter()
    for stage_name, stage in (("power", power), ("trim", trim), ("phase", phase)):
        for signal in signal_shapes:
            for obstacle in [s for s in stage["shapes"] if s["layer"] == signal["layer"]]:
                if distance(signal["bbox_um"], obstacle["bbox_um"]) < spacing[signal["layer"]]-1e-9:
                    cross[stage_name] += 1
                    errors.append(f"{signal['id']} is too close to {stage_name} shape {obstacle['id']}")

    planned_source = 0
    unexpected_source = 0
    if source_rectangles is not None:
        root_by_net = {item["net"]: item["root_um"] for item in routes}
        boundary_by_net = {item["net"]: item["router_boundary_access_um"] for item in routes}
        boundary_bbox_by_net = {item["net"]: item["router_top_pin_bbox_um"] for item in routes}
        for signal in signal_shapes:
            if signal["layer"] not in ("metal2", "metal3"): continue
            layer = MET2 if signal["layer"] == "metal2" else MET3
            for obstacle in source_rectangles[layer]:
                gap = rectangle_gap(tuple(signal["bbox_um"]), obstacle)
                if gap >= spacing[signal["layer"]]-1e-9: continue
                root_x, root_y = root_by_net[signal["net"]]
                boundary_x, boundary_y = boundary_by_net[signal["net"]]
                boundary_bbox = boundary_bbox_by_net[signal["net"]]
                intended_root = signal["kind"] in ("root_column", "root_jog") and signal["layer"] == "metal2" and (
                    obstacle[0]-1e-9 <= root_x <= obstacle[2]+1e-9
                    and obstacle[1]-1e-9 <= root_y <= obstacle[3]+1e-9
                )
                intended_boundary = signal["kind"] in ("root_column", "boundary_drop") and signal["layer"] == "metal2" and (
                    obstacle[0]-1e-9 <= boundary_x <= obstacle[2]+1e-9
                    and obstacle[1]-1e-9 <= boundary_y <= obstacle[3]+1e-9
                )
                intended_manual_boundary = signal["kind"] == "manual_boundary_m3" and signal["layer"] == "metal3" and (
                    (obstacle[0]-1e-9 <= boundary_x <= obstacle[2]+1e-9
                     and obstacle[1]-1e-9 <= boundary_y <= obstacle[3]+1e-9)
                    or intersects(list(obstacle), boundary_bbox)
                    or rectangle_gap(tuple(boundary_bbox), obstacle)
                       < spacing["metal3"]-1e-9
                )
                intended = intended_root or intended_boundary or intended_manual_boundary
                if intended:
                    planned_source += 1
                else:
                    unexpected_source += 1
                    errors.append(f"{signal['id']} has an unplanned source interaction with {obstacle}")

    paths = {item["net"]: item["analog_drop_centerline_um"] for item in routes}
    spread = max(paths.values())-min(paths.values())
    if spread > 12.0+1e-9:
        errors.append(f"quadrature analog-drop spread {spread:.3f} um exceeds 12 um")
    return {
        "status": "pass" if not errors else "fail", "errors": errors,
        "route_count": len(routes), "mapped_pin_count": expected_pin_count,
        "cut_count_by_layer": cuts,
        "connected_component_count_by_net": dict(sorted(components.items())),
        "via_ownership_error_count": ownership_errors,
        "cross_net_spacing_error_count": intra,
        "cross_stage_spacing_error_count": dict(sorted(cross.items())),
        "planned_source_root_and_boundary_join_count": planned_source,
        "unexpected_source_interaction_count": unexpected_source,
        "analog_drop_centerline_um": dict(sorted(paths.items())),
        "analog_drop_spread_um": round(spread, 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, default=Path("build/v2/control_routing/quadrature_geometry.json"))
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_quadrature_route_plan.json"))
    parser.add_argument("--power", type=Path, default=Path("build/v2/control_power/control_power_geometry.json"))
    parser.add_argument("--trim", type=Path, default=Path("build/v2/control_routing/trim_geometry.json"))
    parser.add_argument("--phase", type=Path, default=Path("build/v2/control_routing/phase_geometry.json"))
    parser.add_argument("--source-gds", type=Path, default=Path("build/v2/control_routing/direct/v2_control_phase_routed.gds"))
    parser.add_argument("--source-top", default="v2_control_phase_routed")
    parser.add_argument("--report", type=Path, default=Path("build/v2/control_routing/quadrature_route_audit.json"))
    args = parser.parse_args()
    structures, database_um = parse_gds(args.source_gds)
    source_rectangles = flatten_rectangles(structures, args.source_top, database_um)
    report = validate(json.loads(args.geometry.read_text()), json.loads(args.plan.read_text()),
                      json.loads(args.power.read_text()), json.loads(args.trim.read_text()),
                      json.loads(args.phase.read_text()), source_rectangles)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass": raise SystemExit(1)


if __name__ == "__main__":
    main()
