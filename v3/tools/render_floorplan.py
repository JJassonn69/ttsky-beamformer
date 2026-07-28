#!/usr/bin/env python3
"""Render the V3 constraint-only floorplan to a dependency-free SVG."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COLORS = {
    "quiet_analog": "#7fc97f",
    "critical_analog": "#36a6a6",
    "clock": "#f2a65a",
    "digital_clock": "#e76f51",
    "quiet_mixed_signal": "#9b8ac4",
}


def render(data: dict[str, Any]) -> str:
    die = data["template"]["die"]
    width, height = float(die["width"]), float(die["height"])
    scale, margin = 3.1, 34.0
    canvas_w, canvas_h = 2 * margin + scale * width, 2 * margin + scale * height

    def sx(x: float) -> float:
        return margin + scale * x

    def sy(y: float) -> float:
        return margin + scale * (height - y)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:.1f}" height="{canvas_h:.1f}" viewBox="0 0 {canvas_w:.1f} {canvas_h:.1f}">',
        '<rect width="100%" height="100%" fill="#f6f7f9"/>',
        '<style>text{font-family:Inter,Arial,sans-serif}.small{font-size:9px}.label{font-size:10px;font-weight:600}.title{font-size:16px;font-weight:700}</style>',
        f'<rect x="{sx(0):.2f}" y="{sy(height):.2f}" width="{scale*width:.2f}" height="{scale*height:.2f}" fill="#fff" stroke="#17324d" stroke-width="2"/>',
    ]
    for zone in data["zones"]:
        x0, y0, x1, y1 = zone["bbox"]
        color = COLORS[zone["noise_class"]]
        svg.append(f'<rect x="{sx(x0):.2f}" y="{sy(y1):.2f}" width="{scale*(x1-x0):.2f}" height="{scale*(y1-y0):.2f}" fill="{color}" fill-opacity="0.18" stroke="{color}" stroke-width="1.2"/>')
        svg.append(f'<text class="small" x="{sx(x0)+4:.2f}" y="{sy(y1)+12:.2f}" fill="#28323c">{escape(zone["name"])}</text>')

    matrix = data["channel_template"]["active_matrix_top_to_bottom"]
    for channel in data["channels"]:
        x0, y0, x1, y1 = channel["macro_bbox"]
        svg.append(f'<rect x="{sx(x0):.2f}" y="{sy(y1):.2f}" width="{scale*(x1-x0):.2f}" height="{scale*(y1-y0):.2f}" fill="#118c8b" fill-opacity="0.12" stroke="#087f8c" stroke-width="1.8"/>')
        pad = 1.55
        mx0, mx1 = x0 + pad, x1 - pad
        my0, my1 = y0 + 10.0, y1 - 10.0
        cell_w, cell_h = (mx1-mx0)/3, (my1-my0)/5
        for row, values in enumerate(matrix):
            for col, value in enumerate(values):
                rx = mx0 + col * cell_w
                ry_top = my1 - row * cell_h
                opacity = {1: .35, 2: .45, 4: .58, 8: .75}[value]
                svg.append(f'<rect x="{sx(rx)+1:.2f}" y="{sy(ry_top)+1:.2f}" width="{scale*cell_w-2:.2f}" height="{scale*cell_h-2:.2f}" rx="2" fill="#006d77" fill-opacity="{opacity}"/>')
                svg.append(f'<text class="small" x="{sx(rx+cell_w/2)-3:.2f}" y="{sy(ry_top-cell_h/2)+3:.2f}" fill="#fff">{value}</text>')
        sel = channel["selector_bbox"]
        svg.append(f'<rect x="{sx(sel[0]):.2f}" y="{sy(sel[3]):.2f}" width="{scale*(sel[2]-sel[0]):.2f}" height="{scale*(sel[3]-sel[1]):.2f}" fill="#f2a65a" fill-opacity="0.25" stroke="#d17b21" stroke-width="1.4"/>')
        svg.append(f'<text class="label" x="{sx(channel["center_x"])-10:.2f}" y="{sy(96):.2f}" fill="#053c5e">CH{channel["index"]}</text>')
        pin = data["analog_pins"][channel["pin"]]["center"]
        entry = channel["input_entry"]
        svg.append(f'<path d="M {sx(pin[0]):.2f} {sy(pin[1]):.2f} L {sx(entry[0]):.2f} {sy(entry[1]):.2f}" stroke="#0077b6" stroke-width="2.5" fill="none"/>')

    output = data["output_pair"]
    for side, color in (("p", "#3154b8"), ("n", "#5b2a86")):
        for item in output["routes"][side] + [output["sum_bus_extensions"][side]]:
            svg.append(f'<path d="M {sx(item["from"][0]):.2f} {sy(item["from"][1]):.2f} L {sx(item["to"][0]):.2f} {sy(item["to"][1]):.2f}" stroke="{color}" stroke-width="2.8" fill="none"/>')
        for tap in output["channel_taps"][side]:
            item = tap["route"]
            svg.append(f'<path d="M {sx(item["from"][0]):.2f} {sy(item["from"][1]):.2f} L {sx(item["to"][0]):.2f} {sy(item["to"][1]):.2f}" stroke="{color}" stroke-width="2.0" fill="none"/>')
            svg.append(f'<circle cx="{sx(item["to"][0]):.2f}" cy="{sy(item["to"][1]):.2f}" r="2.6" fill="{color}"/>')
        bbox = output[f"load_{side}_bbox"]
        svg.append(f'<rect x="{sx(bbox[0]):.2f}" y="{sy(bbox[3]):.2f}" width="{scale*(bbox[2]-bbox[0]):.2f}" height="{scale*(bbox[3]-bbox[1]):.2f}" fill="{color}" fill-opacity="0.35" stroke="{color}"/>')

    tree = data["phase_tree"]
    root = tree["root"]
    for branch_name, branch in tree["pair_branches"].items():
        svg.append(f'<path d="M {sx(root[0]):.2f} {sy(root[1]):.2f} L {sx(branch[0]):.2f} {sy(root[1]):.2f} L {sx(branch[0]):.2f} {sy(branch[1]):.2f}" stroke="#cf5c36" stroke-width="4" fill="none" opacity=".75"/>')
        for leaf in tree["leaves"]:
            if leaf["branch"] == branch_name:
                point = leaf["point"]
                svg.append(f'<path d="M {sx(branch[0]):.2f} {sy(branch[1]):.2f} L {sx(point[0]):.2f} {sy(branch[1]):.2f} L {sx(point[0]):.2f} {sy(point[1]):.2f}" stroke="#cf5c36" stroke-width="4" fill="none" opacity=".75"/>')

    for name, pin in data["analog_pins"].items():
        x, y = pin["center"]
        svg.append(f'<rect x="{sx(x)-3:.2f}" y="{sy(y)-3:.2f}" width="6" height="6" fill="#17324d"/>')
        svg.append(f'<text class="small" x="{sx(x)-13:.2f}" y="{sy(y)+16:.2f}" fill="#17324d">{escape(name)}</text>')

    reference = data["shared_support"]["tail_reference_bbox"]
    svg.append(f'<rect x="{sx(reference[0]):.2f}" y="{sy(reference[3]):.2f}" width="{scale*(reference[2]-reference[0]):.2f}" height="{scale*(reference[3]-reference[1]):.2f}" fill="#6f5aa8" fill-opacity="0.48" stroke="#4d3d7a" stroke-width="1.5"/>')
    svg.append(f'<text class="small" x="{sx(reference[0])+3:.2f}" y="{sy(reference[3])+12:.2f}" fill="#34275a">64um bias ref</text>')

    svg.append(f'<text class="title" x="{margin:.2f}" y="21" fill="#17324d">V3A four-channel floorplan — constraint review, not GDS</text>')
    svg.append(f'<text class="small" x="{canvas_w-415:.2f}" y="21" fill="#4b5966">15.74 µm channels · 3.58 µm guard gaps · matched output pin paths · balanced phase tree</text>')
    svg.append('</svg>')
    return "\n".join(svg) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?", default=PROJECT_ROOT / "v3" / "layout" / "floorplan.json")
    parser.add_argument("output", type=Path, nargs="?", default=PROJECT_ROOT / "v3" / "evidence" / "floorplan_review.svg")
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(data), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
