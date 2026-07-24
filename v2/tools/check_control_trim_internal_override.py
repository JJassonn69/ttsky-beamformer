#!/usr/bin/env python3
"""Validate the reviewed internal trim-route override.

The override preserves a manual KLayout cleanup of the sixteen router-owned
``active_trim_codes`` routes.  It is deliberately narrow: logical labels and
top-pin rectangles must stay unchanged, while only the route polygons between
those fixed endpoints may differ from the audited OpenROAD DEF.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


CUT_LAYERS = {"mcon", "via", "via2", "via3"}
LAYER_ORDER = {
    "li1": 0,
    "mcon": 1,
    "met1": 2,
    "via": 3,
    "met2": 4,
    "via2": 5,
    "met3": 6,
    "via3": 7,
    "met4": 8,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(override: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    routes = override.get("routes", [])
    expected_nets = {f"active_trim_codes[{index}]" for index in range(16)}
    expected_labels = {f"R{index:03d}" for index in range(8, 24)}
    nets = {item.get("net") for item in routes}
    labels = {item.get("gds_label") for item in routes}
    if nets != expected_nets:
        errors.append(f"override nets differ: {sorted(nets ^ expected_nets)}")
    if labels != expected_labels:
        errors.append(f"override labels differ: {sorted(labels ^ expected_labels)}")
    if len(routes) != 16:
        errors.append(f"override has {len(routes)} routes, expected 16")

    total_shapes = 0
    total_vias = 0
    layer_counts: Counter[str] = Counter()
    for route in routes:
        shapes = route.get("shapes", [])
        total_shapes += len(shapes)
        layers = {item.get("layer") for item in shapes}
        unknown = layers - set(LAYER_ORDER)
        if unknown:
            errors.append(f"{route.get('net')}: unknown layers {sorted(unknown)}")
        if "met4" in layers:
            errors.append(f"{route.get('net')}: trim override reaches met4")
        for shape in shapes:
            bbox = list(map(float, shape.get("bbox_um", [])))
            if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
                errors.append(f"{route.get('net')}: malformed bbox {bbox}")
            layer_counts[str(shape.get("layer"))] += 1
        via_count = sum(item.get("layer") in CUT_LAYERS for item in shapes)
        total_vias += via_count
        if int(route.get("shape_count", -1)) != len(shapes):
            errors.append(f"{route.get('net')}: shape count is stale")
        if int(route.get("via_count", -1)) != via_count:
            errors.append(f"{route.get('net')}: via count is stale")
        top_pins = [item for item in shapes if item.get("kind") == "openroad_top_pin"]
        if len(top_pins) != 1:
            errors.append(f"{route.get('net')}: expected one frozen top pin")
        expected_segments = len(shapes) - 3 * via_count - 1
        if int(route.get("segment_count", -1)) != expected_segments:
            errors.append(f"{route.get('net')}: segment count is stale")
        if int(route.get("patch_count", -1)) != 0:
            errors.append(f"{route.get('net')}: unexpected patch rectangle")
        label = route.get("label", {})
        if label.get("layer") != "met3":
            errors.append(f"{route.get('net')}: label is not on met3")
        point = list(map(float, label.get("point_um", [])))
        if len(point) != 2 or not top_pins:
            continue
        x, y = point
        x0, y0, x1, y1 = map(float, top_pins[0]["bbox_um"])
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            errors.append(f"{route.get('net')}: label misses frozen top pin")

    if total_shapes != int(override.get("counts", {}).get("shapes", -1)):
        errors.append("override total shape count is stale")
    if total_vias != int(override.get("counts", {}).get("vias", -1)):
        errors.append("override total via count is stale")
    expected_layer_counts = override.get("counts", {}).get("by_layer", {})
    if dict(sorted(layer_counts.items())) != expected_layer_counts:
        errors.append("override layer counts are stale")
    if override.get("policy", {}).get("endpoints_may_change") is not False:
        errors.append("override policy does not freeze endpoints")
    if override.get("policy", {}).get("logical_mapping_may_change") is not False:
        errors.append("override policy does not freeze logical mapping")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "route_count": len(routes),
        "shape_count": total_shapes,
        "via_count": total_vias,
        "by_layer": dict(sorted(layer_counts.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--override",
        type=Path,
        default=Path("v2/layout/control_trim_internal_route_override.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("build/v2/control_routing/trim_internal_override_audit.json"),
    )
    args = parser.parse_args()
    report = validate(json.loads(args.override.read_text(encoding="utf-8")))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
