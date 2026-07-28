#!/usr/bin/env python3
"""Reproduce audited V3 controller/analog handoffs and attach them to GDS."""

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


def validate_locked_sources(plan: dict[str, Any]) -> None:
    source = plan["source_checkpoint"]
    require_hash(ROOT / source["gds"], source["sha256"], "powered-controller GDS")
    contract = plan["route_contract"]
    for key, hash_key, label in (
        ("plan", "plan_sha256", "handoff route contract"),
        ("generator", "generator_sha256", "handoff input generator"),
        ("checker", "checker_sha256", "handoff graph checker"),
    ):
        require_hash(ROOT / contract[key], contract[hash_key], label)
    checkpoint = plan["route_checkpoint"]
    for key, hash_key, label in (
        ("input_def", "input_def_sha256", "input DEF"),
        ("input_summary", "input_summary_sha256", "input summary"),
        ("audit", "audit_sha256", "independent route audit"),
        ("routed_def", "routed_def_sha256", "routed DEF"),
        ("detailed_route_drc", "detailed_route_drc_sha256", "detailed-route DRC"),
        ("openroad_log", "openroad_log_sha256", "OpenROAD log"),
        ("wire_length", "wire_length_sha256", "wire-length report"),
        ("guide_coverage", "guide_coverage_sha256", "guide coverage"),
        ("route_guide", "route_guide_sha256", "route guide"),
    ):
        require_hash(ROOT / checkpoint[key], checkpoint[hash_key], label)


def generate_geometry(plan: dict[str, Any]) -> dict[str, Any]:
    validate_locked_sources(plan)
    checkpoint = plan["route_checkpoint"]
    audit = json.loads((ROOT / checkpoint["audit"]).read_text(encoding="utf-8"))
    if audit.get("status") != "pass" or audit.get("errors"):
        raise ValueError("refusing to reproduce a route that failed graph audit")
    if int(audit.get("route_count", -1)) != int(plan["expected_route_count"]):
        raise ValueError("audited route count differs from the frozen plan")
    if int(audit.get("pin_count", -1)) != int(plan["expected_pin_count"]):
        raise ValueError("audited pin count differs from the frozen plan")
    if audit.get("maximum_route_layer") != plan["maximum_wire_layer"]:
        raise ValueError("audited maximum route layer differs from the frozen plan")

    summary = json.loads(
        (ROOT / checkpoint["input_summary"]).read_text(encoding="utf-8")
    )
    blocks = net_blocks(
        (ROOT / checkpoint["routed_def"]).read_text(encoding="utf-8")
    )
    if set(blocks) != set(summary["net_ids"]):
        raise ValueError("routed DEF nets differ from the input manifest")
    if int(summary["pin_count"]) != int(plan["expected_pin_count"]):
        raise ValueError("input endpoint count differs from the frozen plan")

    offset = summary["coordinate_offset_um"]
    shapes: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    access_pad_count = 0
    for pin_id, endpoint in sorted(summary["pins"].items()):
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
    if access_pad_count != 4:
        raise ValueError("the symmetric phase-terminal access-pad count is not four")
    for index, net_id in enumerate(sorted(summary["net_ids"])):
        logical = summary["net_ids"][net_id]
        net_shapes, route = route_geometry(blocks[net_id], logical, offset, plan)
        route["net_id"] = net_id
        route["gds_label"] = f"V3H{index:03d}"
        route["shape_count"] = len(net_shapes)
        label = route.pop("label")
        label["gds_label"] = route["gds_label"]
        shapes.extend(net_shapes)
        routes.append(route)
        labels.append(label)

    if len(routes) != int(plan["expected_route_count"]):
        raise ValueError("emitted route count differs from the frozen plan")
    layers = Counter(item["layer"] for item in shapes)
    if "met5" in layers:
        raise ValueError("route reproduction uses forbidden M5")
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
            "by_layer": dict(
                sorted(layers.items(), key=lambda item: LAYER_ORDER.get(item[0], 99))
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", type=Path,
        default=ROOT / "v3/layout/physical_control_analog_handoff_route_plan.json",
    )
    parser.add_argument(
        "--geometry", type=Path,
        default=ROOT / "build/v3/control_analog_handoffs/direct/route_geometry.json",
    )
    parser.add_argument(
        "--overlay-gds", type=Path,
        default=ROOT / "build/v3/control_analog_handoffs/direct/v3_control_analog_handoff_routes.gds",
    )
    parser.add_argument(
        "--output-gds", type=Path,
        default=ROOT / "build/v3/control_analog_handoffs/direct/v3_four_channel_ctrl_analog_handoffs.gds",
    )
    parser.add_argument(
        "--report", type=Path,
        default=ROOT / "build/v3/control_analog_handoffs/direct/assembly_report.json",
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
            "powered_controller_source_geometry_modified": False,
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
