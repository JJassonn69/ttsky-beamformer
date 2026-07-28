#!/usr/bin/env python3
"""Render the V3 shared-support constraint placement to SVG."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "v3" / "layout" / "shared_support_placement.json"
DEFAULT_FLOORPLAN = ROOT / "v3" / "layout" / "floorplan.json"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "shared_support_placement_review.svg"
ROLE_COLORS = {
    "vcm_divider_A": "#2a9d8f",
    "vcm_divider_B": "#52b788",
    "vcm_bypass": "#0077b6",
    "differential_output_load": "#5a189a",
    "tail_reference_bias_resistor": "#e76f51",
    "tail_bias_bypass": "#f4a261",
}


def render(data: dict, floorplan: dict) -> str:
    die = floorplan["template"]["die"]
    width, height = die["width"], die["height"]
    scale, margin = 3.1, 34.0
    canvas_w = 2 * margin + scale * width
    canvas_h = 2 * margin + scale * height

    def sx(x: float) -> float:
        return margin + scale * x

    def sy(y: float) -> float:
        return margin + scale * (height - y)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:.1f}" height="{canvas_h:.1f}" viewBox="0 0 {canvas_w:.1f} {canvas_h:.1f}">',
        '<rect width="100%" height="100%" fill="#f6f7f9"/>',
        '<style>text{font-family:Inter,Arial,sans-serif}.small{font-size:8px}.label{font-size:9px;font-weight:600}.title{font-size:16px;font-weight:700}</style>',
        f'<rect x="{sx(0):.2f}" y="{sy(height):.2f}" width="{scale*width:.2f}" height="{scale*height:.2f}" fill="#fff" stroke="#17324d" stroke-width="2"/>',
    ]
    for zone in floorplan["zones"]:
        x0, y0, x1, y1 = zone["bbox"]
        svg.append(
            f'<rect x="{sx(x0):.2f}" y="{sy(y1):.2f}" width="{scale*(x1-x0):.2f}" height="{scale*(y1-y0):.2f}" fill="#9fb3c8" fill-opacity="0.08" stroke="#9fb3c8" stroke-width="0.8"/>'
        )
    for channel in floorplan["channels"]:
        x0, y0, x1, y1 = channel["macro_bbox"]
        svg.append(
            f'<rect x="{sx(x0):.2f}" y="{sy(y1):.2f}" width="{scale*(x1-x0):.2f}" height="{scale*(y1-y0):.2f}" fill="#118c8b" fill-opacity="0.05" stroke="#118c8b" stroke-width="1"/>'
        )
        svg.append(
            f'<text class="small" x="{sx(channel["center_x"])-8:.2f}" y="{sy(96):.2f}" fill="#087f8c">CH{channel["index"]}</text>'
        )

    route_groups = []
    for item in data["vcm"]["divider_internal_routes"]:
        route_groups.append((item["segments"], "#2a9d8f", 1.8))
    route_groups.extend((
        (data["vcm"]["feed"]["segments"], "#0077b6", 2.5),
        (data["vcm"]["ground"]["segments"], "#4b5966", 2.5),
    ))
    for item in data["tail_bias"]["routes"].values():
        route_groups.append((item["segments"], "#d56b30", 2.2))
    for segments, color, stroke in route_groups:
        for item in segments:
            svg.append(
                f'<path d="M {sx(item["from"][0]):.2f} {sy(item["from"][1]):.2f} L {sx(item["to"][0]):.2f} {sy(item["to"][1]):.2f}" stroke="{color}" stroke-width="{stroke}" fill="none"/>'
            )

    components = (
        data["vcm"]["divider_units"]
        + data["vcm"]["bypass_capacitors"]
        + data["output_pair"]["components"]
        + [data["tail_bias"]["bias_resistor"]]
        + data["tail_bias"]["bypass_capacitors"]
    )
    for item in components:
        x0, y0, x1, y1 = item["bbox"]
        color = ROLE_COLORS[item["role"]]
        svg.append(
            f'<rect x="{sx(x0):.2f}" y="{sy(y1):.2f}" width="{scale*(x1-x0):.2f}" height="{scale*(y1-y0):.2f}" fill="{color}" fill-opacity="0.45" stroke="{color}" stroke-width="1.4"/>'
        )
        svg.append(
            f'<text class="label" x="{sx(x0)+2:.2f}" y="{sy(y1)+10:.2f}" fill="#17202a">{escape(item["name"])}</text>'
        )

    ref = floorplan["shared_support"]["tail_reference_bbox"]
    svg.append(
        f'<rect x="{sx(ref[0]):.2f}" y="{sy(ref[3]):.2f}" width="{scale*(ref[2]-ref[0]):.2f}" height="{scale*(ref[3]-ref[1]):.2f}" fill="#6f5aa8" fill-opacity="0.55" stroke="#4d3d7a" stroke-width="1.5"/>'
    )
    svg.append(
        f'<text class="label" x="{sx(ref[0])+2:.2f}" y="{sy(ref[3])+10:.2f}" fill="#34275a">XREF</text>'
    )
    svg.append(
        f'<text class="title" x="{margin:.2f}" y="21" fill="#17324d">V3 shared-support placement — PVT-selected three-MIM VCM</text>'
    )
    svg.append(
        f'<text class="small" x="{canvas_w-470:.2f}" y="21" fill="#4b5966">6-unit exact centroid · 3× VCM MIM · symmetric 2.91 kΩ loads · shared tail reference/RBIAS/2× MIM</text>'
    )
    svg.append("</svg>")
    return "\n".join(svg) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?", default=DEFAULT_MANIFEST)
    parser.add_argument("output", type=Path, nargs="?", default=DEFAULT_OUTPUT)
    parser.add_argument("--floorplan", type=Path, default=DEFAULT_FLOORPLAN)
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    floorplan = json.loads(args.floorplan.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(data, floorplan), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
