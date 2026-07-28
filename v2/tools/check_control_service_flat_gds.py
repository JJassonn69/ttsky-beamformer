#!/usr/bin/env python3
"""Audit the flattened service-routed GDS with explicit shield ownership."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_gds_flat_rules import (  # noqa: E402
    CAPM, MET3, MET4, VIA2, VIA3, audit_rectangles, component_gap,
    connected_components, flatten_rectangles, parse_gds, rectangle_gap,
)


def component_bbox(component: list[tuple[float, float, float, float]]) -> list[float]:
    return [
        min(item[0] for item in component), min(item[1] for item in component),
        max(item[2] for item in component), max(item[3] for item in component),
    ]


def via_only_island_bboxes(rectangles: dict, components: dict) -> list[list[float]]:
    result: list[list[float]] = []
    for met3_component in components[MET3]:
        attached_via3 = [
            cut for cut in rectangles[VIA3]
            if any(rectangle_gap(cut, metal) == 0.0 for metal in met3_component)
        ]
        if not attached_via3:
            continue
        descends = any(
            any(rectangle_gap(cut, metal) == 0.0 for metal in met3_component)
            for cut in rectangles[VIA2]
        )
        touches_mim = any(
            component_gap(met3_component, capm_component) == 0.0
            for capm_component in components[CAPM]
        )
        attached_m4 = {
            index for cut in attached_via3
            for index, component in enumerate(components[MET4])
            if any(rectangle_gap(cut, metal) == 0.0 for metal in component)
        }
        if not descends and not touches_mim and len(attached_m4) <= 1:
            result.append(component_bbox(met3_component))
    return sorted(result)


def close_bbox(first: list[float], second: list[float]) -> bool:
    return all(abs(a-b) <= 1e-6 for a, b in zip(first, second))


def audit(candidate: Path, top: str, source: Path, source_top: str,
          plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    source_structures, source_dbu = parse_gds(source)
    candidate_structures, candidate_dbu = parse_gds(candidate)
    source_rectangles = flatten_rectangles(source_structures, source_top, source_dbu)
    candidate_rectangles = flatten_rectangles(candidate_structures, top, candidate_dbu)
    source_components, source_checks = audit_rectangles(source_rectangles)
    candidate_components, candidate_checks = audit_rectangles(candidate_rectangles)

    for name, values in candidate_checks.items():
        if name in ("met4 minimum width", "via-only met3 island"):
            continue
        if values:
            errors.append(f"flattened candidate has {len(values)} {name} marker(s)")
    if sorted(candidate_checks["met4 minimum width"]) != sorted(source_checks["met4 minimum width"]):
        errors.append("service routing changes the frozen source M4-width marker set")

    y0, y1 = map(float, plan["spine_y_range"])
    expected_shields = sorted([
        [float(x)-.2, y0, float(x)+.2, y1]
        for x in plan["ground_shields_x"]
    ])
    islands = via_only_island_bboxes(candidate_rectangles, candidate_components)
    unmatched = list(islands)
    for expected in expected_shields:
        match = next((item for item in unmatched if close_bbox(item, expected)), None)
        if match is None:
            errors.append(f"named grounded M3 shield is absent from island classification: {expected}")
        else:
            unmatched.remove(match)
    if unmatched:
        errors.append(f"unexpected via-only M3 island(s): {unmatched}")

    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_hash != plan["source_checkpoint"]["sha256"]:
        errors.append("service flat audit source hash differs from the route contract")
    return {
        "status": "pass" if not errors else "fail", "errors": errors,
        "candidate_gds": str(candidate),
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "source_gds": str(source), "source_sha256": source_hash,
        "source_inherited_m4_width_marker_count": len(source_checks["met4 minimum width"]),
        "candidate_m4_width_marker_count": len(candidate_checks["met4 minimum width"]),
        "intentional_grounded_m3_shield_count": len(expected_shields),
        "unexpected_via_only_m3_island_count": len(unmatched),
        "candidate_generic_marker_count_by_rule": {
            name: len(values) for name, values in candidate_checks.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=Path("build/v2/control_routing/direct/v2_control_service_routed.gds"))
    parser.add_argument("--top", default="v2_control_service_routed")
    parser.add_argument("--source", type=Path, default=Path("build/v2/control_routing/direct/v2_control_direct_routed.gds"))
    parser.add_argument("--source-top", default="v2_control_direct_routed")
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_service_route_plan.json"))
    parser.add_argument("--report", type=Path, default=Path("build/v2/control_routing/direct/service_flat_gds_audit.json"))
    args = parser.parse_args()
    report = audit(args.candidate, args.top, args.source, args.source_top,
                   json.loads(args.plan.read_text()))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
