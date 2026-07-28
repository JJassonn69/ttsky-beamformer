#!/usr/bin/env python3
"""Reproduce audited V3 controller DEF routes and attach them to the GDS."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))
from assemble_route_overlay_gds import assemble as attach_overlay  # noqa: E402
from check_control_openroad_routes import LAYER_ORDER, net_blocks  # noqa: E402
from generate_control_openroad_overlay import (  # noqa: E402
    direct_gds,
    rectangle,
    route_geometry,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_hash(path: Path, expected: str, name: str) -> None:
    observed = sha256(path)
    if observed != expected:
        raise ValueError(f"{name} hash differs: expected {expected}, got {observed}")


def generate_geometry(plan: dict[str, Any]) -> dict[str, Any]:
    source = ROOT / plan["source_checkpoint"]["gds"]
    require_hash(source, plan["source_checkpoint"]["sha256"], "placement GDS")
    checkpoint = plan["route_checkpoint"]
    for name, hash_name in (
        ("input_summary", "input_summary_sha256"),
        ("audit", "audit_sha256"),
        ("routed_def", "routed_def_sha256"),
        ("detailed_route_drc", "detailed_route_drc_sha256"),
        ("openroad_log", "openroad_log_sha256"),
        ("wire_length", "wire_length_sha256"),
        ("guide_coverage", "guide_coverage_sha256"),
    ):
        require_hash(ROOT / checkpoint[name], checkpoint[hash_name], name)

    audit = json.loads((ROOT / checkpoint["audit"]).read_text(encoding="utf-8"))
    if audit.get("status") != "pass" or audit.get("errors"):
        raise ValueError("refusing to reproduce a route that failed the graph audit")
    if audit.get("route_count") != int(plan["expected_route_count"]):
        raise ValueError("audited route count differs from the frozen plan")
    if audit.get("maximum_route_layer") != plan["maximum_wire_layer"]:
        raise ValueError("audited maximum route layer differs from the frozen plan")

    summary = json.loads(
        (ROOT / checkpoint["input_summary"]).read_text(encoding="utf-8")
    )
    if int(summary["pin_count"]) != int(plan["expected_boundary_pin_count"]):
        raise ValueError("boundary pin count differs from the frozen plan")
    blocks = net_blocks(
        (ROOT / checkpoint["routed_def"]).read_text(encoding="utf-8")
    )
    if set(blocks) != set(summary["net_ids"]):
        raise ValueError("routed DEF nets differ from the input manifest")

    offset = summary["coordinate_offset_um"]
    shapes: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    for index, net_id in enumerate(sorted(summary["net_ids"])):
        logical = summary["net_ids"][net_id]
        net_shapes, route = route_geometry(blocks[net_id], logical, offset, plan)
        boundary = summary["boundary_pins"].get(logical)
        if boundary is not None:
            px, py = map(float, boundary["point_um"])
            rx0, ry0, rx1, ry1 = map(float, boundary["rect_um"])
            ox, oy = map(float, offset)
            net_shapes.append({
                "net": logical,
                "layer": boundary["layer"],
                "bbox_um": rectangle(
                    ox + px + rx0,
                    oy + py + ry0,
                    ox + px + rx1,
                    oy + py + ry1,
                ),
                "kind": "openroad_boundary_pin",
            })
        route["net_id"] = net_id
        route["gds_label"] = f"V3R{index:03d}"
        route["shape_count"] = len(net_shapes)
        label = route.pop("label")
        label["gds_label"] = route["gds_label"]
        shapes.extend(net_shapes)
        routes.append(route)
        labels.append(label)

    if len(routes) != int(plan["expected_route_count"]):
        raise ValueError("emitted route count differs from the frozen plan")
    if sum(item["kind"] == "openroad_boundary_pin" for item in shapes) != int(
        plan["expected_boundary_pin_count"]
    ):
        raise ValueError("emitted boundary pin count differs from the frozen plan")
    layers = Counter(item["layer"] for item in shapes)
    forbidden = set(layers) & {"via3", "met4", "met5"}
    if forbidden:
        raise ValueError(f"route reproduction uses reserved layers {sorted(forbidden)}")
    return {
        "schema_version": 1,
        "status": "generated from hash-locked, independently audited OpenROAD routes",
        "source_checkpoint": plan["source_checkpoint"],
        "route_checkpoint": plan["route_checkpoint"],
        "top": plan["overlay_top"],
        "routes": routes,
        "shapes": shapes,
        "labels": labels,
        "label_net_map": {item["gds_label"]: item["net"] for item in routes},
        "counts": {
            "routes": len(routes),
            "labels": len(labels),
            "boundary_pins": sum(
                item["kind"] == "openroad_boundary_pin" for item in shapes
            ),
            "shapes": len(shapes),
            "segments": sum(item["segment_count"] for item in routes),
            "vias": sum(item["via_count"] for item in routes),
            "patches": sum(item["patch_count"] for item in routes),
            "by_layer": dict(
                sorted(layers.items(), key=lambda item: LAYER_ORDER.get(item[0], 99))
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", type=Path,
        default=ROOT / "v3/layout/physical_control_route_plan.json",
    )
    parser.add_argument(
        "--geometry", type=Path,
        default=ROOT / "build/v3/control_routing/openroad_internal/route_geometry.json",
    )
    parser.add_argument(
        "--overlay-gds", type=Path,
        default=ROOT / "build/v3/control_routing/openroad_internal/direct/v3_physical_control_signal_routes.gds",
    )
    parser.add_argument(
        "--output-gds", type=Path,
        default=ROOT / "build/v3/control_routing/openroad_internal/direct/v3_four_channel_control_signal_routed.gds",
    )
    parser.add_argument(
        "--report", type=Path,
        default=ROOT / "build/v3/control_routing/openroad_internal/direct/assembly_report.json",
    )
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    geometry = generate_geometry(plan)
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(
        json.dumps(geometry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

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
            "foundry_and_analog_source_geometry_modified": False,
            "route_geometry_writer": "direct deterministic GDS boundary writer",
            "placement_source_attached_hierarchically": True,
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
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": report["status"],
        "geometry": report["geometry"],
        "output_gds": report["output_gds"],
        "output_sha256": report["output_sha256"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
