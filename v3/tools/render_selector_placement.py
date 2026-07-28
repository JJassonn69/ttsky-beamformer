#!/usr/bin/env python3
"""Render an enlarged review drawing of the V3 local selector template."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[2]
COLORS = {
    "mux2": "#e9a03b",
    "and2": "#3b8bc2",
    "and2b": "#7656a6",
    "tap": "#5f6b73",
    "fill": "#aab4bc",
}


def render(data: dict[str, Any]) -> str:
    template = data["channel_template"]
    scale = 22.0
    margin_x, margin_y = 70.0, 78.0
    width = 2 * margin_x + scale * template["bbox"][2] + 350.0
    height = 2 * margin_y + scale * template["bbox"][3]

    def sx(x: float) -> float:
        return margin_x + scale * x

    def sy(y: float) -> float:
        return height - margin_y - scale * y

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.1f}" height="{height:.1f}" viewBox="0 0 {width:.1f} {height:.1f}">',
        '<rect width="100%" height="100%" fill="#f7f8fa"/>',
        '<style>text{font-family:Inter,Arial,sans-serif}.title{font-size:18px;font-weight:700}.label{font-size:11px;font-weight:600}.small{font-size:10px}</style>',
        f'<rect x="{sx(0):.2f}" y="{sy(34):.2f}" width="{scale*15.74:.2f}" height="{scale*34:.2f}" fill="#fff" stroke="#25384a" stroke-width="2"/>',
    ]
    phase = template["route_reservations"]["phase_spine"]["bbox"]
    static = template["route_reservations"]["static_code_entry"]["bbox"]
    svg.append(f'<rect x="{sx(phase[0]):.2f}" y="{sy(phase[3]):.2f}" width="{scale*(phase[2]-phase[0]):.2f}" height="{scale*(phase[3]-phase[1]):.2f}" fill="#d95f4f" fill-opacity=".13" stroke="#d95f4f" stroke-dasharray="5 3"/>')
    svg.append(f'<rect x="{sx(static[0]):.2f}" y="{sy(static[3]):.2f}" width="{scale*(static[2]-static[0]):.2f}" height="{scale*(static[3]-static[1]):.2f}" fill="#4b79b8" fill-opacity=".10" stroke="#4b79b8" stroke-dasharray="5 3"/>')

    for item in template["instances"]:
        x0, y0, x1, y1 = item["bbox"]
        color = COLORS[item["cell_role"]]
        svg.append(f'<rect x="{sx(x0):.2f}" y="{sy(y1):.2f}" width="{scale*(x1-x0):.2f}" height="{scale*(y1-y0):.2f}" rx="2" fill="{color}" fill-opacity=".78" stroke="#263238" stroke-width=".7"/>')
        label = item["name"].replace("_ANDNOT", "_AN").replace("_AND", "_A").replace("_MUX_", "_M_")
        svg.append(f'<text class="small" x="{sx(x0)+3:.2f}" y="{sy((y0+y1)/2)+3:.2f}" fill="#fff">{escape(label)}</text>')

    info_x = sx(15.74) + 45
    row_widths = []
    for row in range(template["row_count"]):
        row_items = [item for item in template["instances"] if item["row"] == row]
        row_widths.append(max(item["bbox"][2] for item in row_items) - min(item["bbox"][0] for item in row_items))
    row_description = (
        "Nine contiguous alternating R0/MX rows"
        if template["row_gap_um"] == 0
        else f"Nine alternating R0/MX rows; {template['row_gap_um']:.2f} um gaps"
    )
    svg.append(f'<text class="title" x="{margin_x:.2f}" y="32">V3 route-proven per-channel selector placement</text>')
    lines = [
        "Reservation: 15.74 x 34.00 um",
        f"Raw cell utilization: {template['raw_cell_utilization_percent']:.2f}%",
        row_description,
        "12 mux2 + 4 and2 + 5 and2b + 5 taps + 17 fillers",
        f"Maximum occupied row width: {max(row_widths):.2f} um",
        "One 0.46 um filler site at every signal-cell boundary",
        "Left: four-phase Metal 3 spine",
        "Right: eight static-code Metal 2 entries",
        "All four channels use this identical copy",
        "",
        "Still open:",
        "- route and compare all four selector copies",
        "- power straps, antenna repair and tap-rule signoff",
        "- extracted RC timing and channel-to-channel skew",
        "- integrated top-level DEF/GDS and official precheck",
    ]
    for index, line in enumerate(lines):
        css = "label" if line == "Still open:" else "small"
        svg.append(f'<text class="{css}" x="{info_x:.2f}" y="{80 + index*25:.2f}" fill="#273746">{escape(line)}</text>')
    for index, (role, color) in enumerate(COLORS.items()):
        y = height - 120 + index * 22
        svg.append(f'<rect x="{info_x:.2f}" y="{y-11:.2f}" width="16" height="12" fill="{color}"/>')
        svg.append(f'<text class="small" x="{info_x+23:.2f}" y="{y:.2f}" fill="#273746">{role}</text>')
    svg.append('</svg>')
    return "\n".join(svg) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?", default=ROOT / "v3" / "layout" / "selector_placement.json")
    parser.add_argument("output", type=Path, nargs="?", default=ROOT / "v3" / "evidence" / "selector_placement_review.svg")
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(data), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
