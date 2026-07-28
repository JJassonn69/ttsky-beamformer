#!/usr/bin/env python3
"""Reproduce the audited 14 TinyTapeout input handoffs and attach them to GDS."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from assemble_physical_control_analog_handoffs_gds import (
    LAYER_ORDER,
    ROOT,
    attach_overlay,
    direct_gds,
    net_blocks,
    rectangle,
    route_geometry,
    sha256,
    validate_locked_sources,
)


def generate_geometry(plan: dict[str, Any]) -> dict[str, Any]:
    validate_locked_sources(plan)
    checkpoint = plan["route_checkpoint"]
    audit = json.loads((ROOT / checkpoint["audit"]).read_text(encoding="utf-8"))
    if audit.get("status") != "pass" or audit.get("errors"):
        raise ValueError("refusing to reproduce a boundary route that failed graph audit")
    if int(audit.get("route_count", -1)) != int(plan["expected_route_count"]):
        raise ValueError("audited boundary-route count differs from the frozen plan")
    if int(audit.get("pin_count", -1)) != int(plan["expected_pin_count"]):
        raise ValueError("audited boundary pin count differs from the frozen plan")
    if audit.get("maximum_route_layer") != plan["maximum_wire_layer"]:
        raise ValueError("audited maximum route layer differs from the frozen plan")

    summary = json.loads(
        (ROOT / checkpoint["input_summary"]).read_text(encoding="utf-8")
    )
    blocks = net_blocks((ROOT / checkpoint["routed_def"]).read_text(encoding="utf-8"))
    if set(blocks) != set(summary["net_ids"]):
        raise ValueError("routed DEF nets differ from the boundary input manifest")
    if int(summary["pin_count"]) != int(plan["expected_pin_count"]):
        raise ValueError("boundary endpoint count differs from the frozen plan")

    offset = summary["coordinate_offset_um"]
    shapes: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    access_pad_count = 0
    boundary_terminal_count = 0
    for pin_id, endpoint in sorted(summary["pins"].items()):
        if endpoint.get("role") == "tinytapeout_input_pin":
            net_id = f"N{int(pin_id[1:4]):03d}"
            logical = summary["net_ids"][net_id]
            shapes.append({
                "net": logical,
                "layer": endpoint["layer"],
                "bbox_um": rectangle(*map(float, endpoint["rect_um"])),
                "kind": "exact_tinytapeout_input_terminal",
            })
            boundary_terminal_count += 1
        if not endpoint.get("generated_access_pad"):
            continue
        net_id = f"N{int(pin_id[1:4]):03d}"
        logical = summary["net_ids"][net_id]
        shapes.append({
            "net": logical,
            "layer": endpoint["layer"],
            "bbox_um": rectangle(*map(float, endpoint["rect_um"])),
            "kind": "openroad_top_pin_access_pad",
        })
        access_pad_count += 1
    if access_pad_count != int(plan["expected_access_pad_count"]):
        raise ValueError("generated access-pad count differs from the boundary plan")
    if boundary_terminal_count != int(plan["expected_boundary_terminal_count"]):
        raise ValueError("TinyTapeout boundary-terminal count differs from the boundary plan")

    for index, net_id in enumerate(sorted(summary["net_ids"])):
        logical = summary["net_ids"][net_id]
        net_shapes, route = route_geometry(blocks[net_id], logical, offset, plan)
        route["net_id"] = net_id
        route["gds_label"] = f"V3B{index:03d}"
        route["shape_count"] = len(net_shapes)
        label = route.pop("label")
        label["gds_label"] = route["gds_label"]
        shapes.extend(net_shapes)
        routes.append(route)
        labels.append(label)

    if len(routes) != int(plan["expected_route_count"]):
        raise ValueError("emitted route count differs from the boundary plan")
    layers = Counter(item["layer"] for item in shapes)
    if "met5" in layers:
        raise ValueError("boundary route reproduction uses forbidden M5")
    return {
        "schema_version": 1,
        "status": "generated from hash-locked, graph-audited OpenROAD routes",
        "source_checkpoint": plan["source_checkpoint"],
        "route_contract": plan["route_contract"],
        "route_checkpoint": plan["route_checkpoint"],
        "top": plan["overlay_top"],
        "routes": routes,
        "shapes": shapes,
        "labels": labels,
        "label_net_map": {item["gds_label"]: item["net"] for item in routes},
        "counts": {
            "routes": len(routes),
            "labels": len(labels),
            "shapes": len(shapes),
            "segments": sum(item["segment_count"] for item in routes),
            "vias": sum(item["via_count"] for item in routes),
            "patches": sum(item["patch_count"] for item in routes),
            "access_pads": access_pad_count,
            "boundary_terminals": boundary_terminal_count,
            "by_layer": dict(
                sorted(layers.items(), key=lambda item: LAYER_ORDER.get(item[0], 99))
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / "build/v3/control_boundary_handoffs/direct"
    parser.add_argument(
        "--plan", type=Path,
        default=ROOT / "v3/layout/physical_control_boundary_handoff_route_plan.json",
    )
    parser.add_argument("--geometry", type=Path, default=base / "route_geometry.json")
    parser.add_argument(
        "--overlay-gds", type=Path,
        default=base / "v3_control_boundary_handoff_routes.gds",
    )
    parser.add_argument(
        "--output-gds", type=Path,
        default=base / "v3_four_channel_ctrl_boundary_handoffs.gds",
    )
    parser.add_argument("--report", type=Path, default=base / "assembly_report.json")
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
            "source_geometry_modified": False,
            "route_geometry_writer": "direct deterministic GDS boundary writer",
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
