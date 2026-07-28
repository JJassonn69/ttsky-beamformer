#!/usr/bin/env python3
"""Attach a deterministic physical ground tie to all unused digital outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from assemble_route_overlay_gds import assemble as attach_overlay  # noqa: E402
from generate_control_openroad_overlay import direct_gds  # noqa: E402
from template_pins import submission_pins  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_hash(path: Path, expected: str, label: str) -> None:
    observed = sha256(path)
    if observed != expected:
        raise ValueError(f"{label} hash differs: expected {expected}, got {observed}")


def generate_geometry(plan: dict[str, Any]) -> dict[str, Any]:
    source = plan["source_checkpoint"]
    require_hash(ROOT / source["gds"], source["sha256"], "analog-input source GDS")
    template = plan["template"]
    require_hash(ROOT / template["def"], template["sha256"], "TinyTapeout template DEF")
    _width, _height, pins = submission_pins(ROOT / template["def"])
    pin_map = {pin.name: pin for pin in pins}
    expected_names = set(plan["pins"])
    if len(expected_names) != len(plan["pins"]):
        raise ValueError("duplicate pin in digital-output tie plan")
    if expected_names != {
        f"{bus}[{index}]"
        for bus in ("uo_out", "uio_out", "uio_oe")
        for index in range(8)
    }:
        raise ValueError("tie-low contract must contain exactly the 24 digital outputs")

    route = plan["route_geometry"]
    net = plan["logical_net"]
    shapes = [
        {
            "net": net,
            "layer": route["layer"],
            "bbox_um": route["ground_extension_bbox"],
            "kind": "vgnd_upper_extension",
        },
        {
            "net": net,
            "layer": route["layer"],
            "bbox_um": route["horizontal_bus_bbox"],
            "kind": "static_output_tie_bus",
        },
    ]
    outputs = []
    half = float(route["drop_width"]) / 2.0
    for name in plan["pins"]:
        pin = pin_map[name]
        lx, by, rx, ty = (value / 1000.0 for value in pin.rect_nm)
        if pin.direction != "OUTPUT" or pin.use != "SIGNAL" or pin.layer != "met4":
            raise ValueError(f"{name} is not an official Metal-4 signal output")
        center_x = (lx + rx) / 2.0
        if abs((rx - lx) - float(route["drop_width"])) > 1e-9:
            raise ValueError(f"{name} width differs from the direct tie-drop width")
        bbox = [
            round(center_x - half, 6), float(route["drop_bottom_y"]),
            round(center_x + half, 6), float(route["drop_top_y"]),
        ]
        shapes.append({
            "net": net,
            "layer": route["layer"],
            "bbox_um": bbox,
            "kind": "static_low_output_drop",
            "pin": name,
        })
        outputs.append({
            "pin": name,
            "official_rect_um": [lx, by, rx, ty],
            "drop_bbox_um": bbox,
            "center_x_um": center_x,
        })

    labels = [{
        "net": net,
        "gds_label": route["label"],
        "layer": route["layer"],
        "point_um": route["label_point"],
    }]
    labels.extend(
        {
            "net": net,
            "gds_label": f"V3O{index:03d}",
            "layer": route["layer"],
            "point_um": [item["center_x_um"], 225.1],
        }
        for index, item in enumerate(outputs)
    )
    expected = plan["expected"]
    observed = {
        "pins": len(outputs),
        "ground_extensions": 1,
        "horizontal_buses": 1,
        "vertical_drops": len(outputs),
        "shapes": len(shapes),
        "labels": len(labels),
        "vias": 0,
    }
    if observed != expected:
        raise ValueError(f"tie-low geometry differs: {observed} != {expected}")
    return {
        "schema_version": 1,
        "status": "generated from hash-locked physical tie-low plan",
        "source_checkpoint": source,
        "top": plan["overlay_top"],
        "logical_net": net,
        "outputs": outputs,
        "shapes": shapes,
        "labels": labels,
        "counts": observed,
        "policy": plan["policy"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / "build/v3/digital_output_tie/direct"
    parser.add_argument("--plan", type=Path, default=ROOT / "v3/layout/digital_output_tie_plan.json")
    parser.add_argument("--geometry", type=Path, default=base / "route_geometry.json")
    parser.add_argument("--overlay-gds", type=Path, default=base / "v3_digital_output_tie_low.gds")
    parser.add_argument("--output-gds", type=Path, default=base / "v3_four_channel_output_tied.gds")
    parser.add_argument("--report", type=Path, default=base / "assembly_report.json")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    geometry = generate_geometry(plan)
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(json.dumps(geometry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    source = ROOT / plan["source_checkpoint"]["gds"]
    overlay_report = direct_gds(geometry, source, args.overlay_gds)
    output, assembly_report = attach_overlay(
        source, plan["source_checkpoint"]["top"], args.overlay_gds,
        plan["overlay_top"], plan["output_top"],
        {item["gds_label"] for item in geometry["labels"]},
    )
    args.output_gds.parent.mkdir(parents=True, exist_ok=True)
    args.output_gds.write_bytes(output)
    report = {
        "schema_version": 1,
        "status": "pass",
        "policy": plan["policy"],
        "geometry": geometry["counts"],
        "geometry_sha256": sha256(args.geometry),
        "overlay": overlay_report,
        "assembly": assembly_report,
        "output_gds": str(args.output_gds.relative_to(ROOT)),
        "output_sha256": sha256(args.output_gds),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
