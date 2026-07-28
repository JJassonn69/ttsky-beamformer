#!/usr/bin/env python3
"""Generate four exact translated analog-input escapes and attach them to V3."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from assemble_physical_control_analog_handoffs_gds import attach_overlay, direct_gds


ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_hash(path: Path, expected: str, name: str) -> None:
    observed = sha256(path)
    if observed != expected:
        raise ValueError(f"{name} hash differs: expected {expected}, got {observed}")


def translated_bbox(x: float, bbox: list[float]) -> list[float]:
    return [round(x + bbox[0], 6), bbox[1], round(x + bbox[2], 6), bbox[3]]


def generate_geometry(plan: dict[str, Any]) -> dict[str, Any]:
    source = plan["source_checkpoint"]
    require_hash(ROOT / source["gds"], source["sha256"], "boundary-handoff source GDS")
    require_hash(
        ROOT / source["physical_gate"], source["physical_gate_sha256"],
        "boundary-handoff physical gate",
    )
    endpoints = plan["endpoint_sources"]
    for path_key, hash_key, name in (
        ("tinytapeout_template_def", "tinytapeout_template_def_sha256", "TinyTapeout template"),
        ("corridor_audit", "corridor_audit_sha256", "input-corridor audit"),
        ("corridor_auditor", "corridor_auditor_sha256", "input-corridor auditor"),
    ):
        require_hash(ROOT / endpoints[path_key], endpoints[hash_key], name)

    route = plan["route_geometry"]
    shapes: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    for channel in plan["channels"]:
        index = int(channel["channel"])
        x = float(channel["x"])
        net = channel["net"]
        route_shapes = [
            {"net": net, "layer": "met4", "bbox_um": channel["pin_rect"], "kind": "exact_tinytapeout_analog_terminal"},
            {"net": net, "layer": "via3", "bbox_um": translated_bbox(x, route["via3_bbox_relative_to_x"]), "kind": "input_m3_m4_via"},
            {"net": net, "layer": "met3", "bbox_um": translated_bbox(x, route["m3_bbox_relative_to_x"]), "kind": "straight_input_trunk"},
            {"net": net, "layer": "via2", "bbox_um": translated_bbox(x, route["via2_bbox_relative_to_x"]), "kind": "input_m2_m3_via"},
            {"net": net, "layer": "met2", "bbox_um": translated_bbox(x, route["m2_landing_bbox_relative_to_x"]), "kind": "element_input_access_landing"},
        ]
        label = f"V3I{index:03d}"
        shapes.extend(route_shapes)
        labels.append({
            "net": net,
            "gds_label": label,
            "layer": route["label_layer"],
            "point_um": [x, route["label_y"]],
        })
        routes.append({
            "channel": index,
            "net": net,
            "pin": channel["pin"],
            "gds_label": label,
            "layers": ["met2", "met3", "met4"],
            "shape_count": len(route_shapes),
            "via_count": route["vias_per_route"],
            "direction_reversals": route["direction_reversals_per_route"],
            "m3_centerline_length_um": route["m3_centerline_length"],
        })

    counts = Counter(item["layer"] for item in shapes)
    expected = plan["expected"]
    observed = {
        "routes": len(routes),
        "labels": len(labels),
        "vias": sum(item["via_count"] for item in routes),
        "shapes": len(shapes),
        "m4_terminals": counts["met4"],
        "m3_trunks": counts["met3"],
        "m2_landings": counts["met2"],
        "total_m3_centerline_length": round(
            sum(item["m3_centerline_length_um"] for item in routes), 6
        ),
    }
    if observed != expected:
        raise ValueError(f"input-escape geometry differs from plan: {observed} != {expected}")
    if len({tuple(item["layers"]) for item in routes}) != 1:
        raise ValueError("analog-input layer sequences are asymmetric")
    if len({item["via_count"] for item in routes}) != 1:
        raise ValueError("analog-input via counts are asymmetric")
    if len({item["m3_centerline_length_um"] for item in routes}) != 1:
        raise ValueError("analog-input centerline lengths are asymmetric")
    return {
        "schema_version": 1,
        "status": "generated from hash-locked, exact-translation analog-input plan",
        "source_checkpoint": source,
        "top": plan["overlay_top"],
        "routes": routes,
        "shapes": shapes,
        "labels": labels,
        "label_net_map": {item["gds_label"]: item["net"] for item in routes},
        "counts": {**observed, "by_layer": dict(sorted(counts.items()))},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / "build/v3/analog_input_escapes/direct"
    parser.add_argument("--plan", type=Path, default=ROOT / "v3/layout/analog_input_escape_plan.json")
    parser.add_argument("--geometry", type=Path, default=base / "route_geometry.json")
    parser.add_argument("--overlay-gds", type=Path, default=base / "v3_analog_input_escape_routes.gds")
    parser.add_argument("--output-gds", type=Path, default=base / "v3_four_channel_analog_inputs.gds")
    parser.add_argument("--report", type=Path, default=base / "assembly_report.json")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    geometry = generate_geometry(plan)
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(json.dumps(geometry, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    source = ROOT / plan["source_checkpoint"]["gds"]
    overlay_report = direct_gds(geometry, source, args.overlay_gds)
    output, assembly_report = attach_overlay(
        source,
        plan["source_checkpoint"]["top"],
        args.overlay_gds,
        plan["overlay_top"],
        plan["output_top"],
        set(geometry["label_net_map"]),
    )
    args.output_gds.parent.mkdir(parents=True, exist_ok=True)
    args.output_gds.write_bytes(output)
    report = {
        "schema_version": 1,
        "status": "pass",
        "policy": {
            "source_geometry_modified": False,
            "route_geometry_writer": "direct deterministic matched-input writer",
            "source_checkpoint_attached_hierarchically": True,
            "magic_is_not_the_route_geometry_writer": True,
        },
        "geometry": geometry["counts"],
        "geometry_sha256": sha256(args.geometry),
        "overlay": overlay_report,
        "assembly": assembly_report,
        "output_gds": str(args.output_gds.relative_to(ROOT)),
        "output_sha256": sha256(args.output_gds),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "geometry": report["geometry"],
        "output_gds": report["output_gds"],
        "output_sha256": report["output_sha256"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
