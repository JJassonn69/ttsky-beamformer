#!/usr/bin/env python3
"""Render the V3 3x5 exact-unit matrix and local LO merge hierarchy."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "v3" / "layout" / "channel_matrix_placement.json"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "channel_matrix_placement_review.svg"
SCALE = 9.0
MARGIN = 24.0


def sx(x: float) -> float:
    return MARGIN + x * SCALE


def sy(y: float, height: float) -> float:
    return MARGIN + (height - y) * SCALE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    channel = data["channel_bbox"]
    width_um, height_um = channel[2], channel[3]
    canvas_w = 2 * MARGIN + width_um * SCALE + 310
    canvas_h = 2 * MARGIN + height_um * SCALE
    colours = {1: "#f5b942", 2: "#e67e80", 4: "#6fc3df", 8: "#75c77a"}
    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:.0f}" height="{canvas_h:.0f}" viewBox="0 0 {canvas_w:.0f} {canvas_h:.0f}">',
        '<rect width="100%" height="100%" fill="#161a20"/>',
        f'<rect x="{sx(0):.2f}" y="{sy(height_um, height_um):.2f}" width="{width_um*SCALE:.2f}" height="{height_um*SCALE:.2f}" fill="#202732" stroke="#d9e2ec" stroke-width="1.5"/>',
    ]
    for gap in data["routing_reservations"]["inter_row_channels"]:
        x0, y0, x1, y1 = gap
        pieces.append(
            f'<rect x="{sx(x0):.2f}" y="{sy(y1, height_um):.2f}" width="{(x1-x0)*SCALE:.2f}" height="{(y1-y0)*SCALE:.2f}" fill="#273446" opacity="0.75"/>'
        )
    for item in data["matrix"]["instances"]:
        x0, y0, x1, y1 = item["bbox"]
        group = int(item["group_weight"])
        pieces.append(
            f'<rect x="{sx(x0):.2f}" y="{sy(y1, height_um):.2f}" width="{(x1-x0)*SCALE:.2f}" height="{(y1-y0)*SCALE:.2f}" rx="2" fill="{colours[group]}" fill-opacity="0.32" stroke="{colours[group]}" stroke-width="1.2"/>'
        )
        pieces.append(
            f'<text x="{sx((x0+x1)/2):.2f}" y="{sy((y0+y1)/2, height_um):.2f}" text-anchor="middle" dominant-baseline="middle" fill="#f3f6f9" font-family="monospace" font-size="10">G{group} {html.escape(item["orientation"])}</text>'
        )
        for net, route in item["local_lo_routes"].items():
            colour = "#3ec6ff" if net == "lon" else "#cb7cff"
            dash = "" if net == "lon" else ' stroke-dasharray="4 3"'
            for segment in route["segments"]:
                x_start, y_start = segment["from"]
                x_stop, y_stop = segment["to"]
                pieces.append(
                    f'<line x1="{sx(x_start):.2f}" y1="{sy(y_start,height_um):.2f}" x2="{sx(x_stop):.2f}" y2="{sy(y_stop,height_um):.2f}" stroke="{colour}" stroke-width="2"{dash}/>'
                )
            root = route["root"]
            pieces.append(f'<circle cx="{sx(root[0]):.2f}" cy="{sy(root[1],height_um):.2f}" r="2.8" fill="{colour}"/>')
    legend_x = sx(width_um) + 28
    pieces.extend([
        f'<text x="{legend_x:.2f}" y="42" fill="#ffffff" font-family="sans-serif" font-size="18" font-weight="bold">V3 channel matrix</text>',
        f'<text x="{legend_x:.2f}" y="68" fill="#c7d2df" font-family="sans-serif" font-size="13">15 exact vector units, common centroid</text>',
        f'<line x1="{legend_x:.2f}" y1="96" x2="{legend_x+34:.2f}" y2="96" stroke="#3ec6ff" stroke-width="3"/>',
        f'<text x="{legend_x+44:.2f}" y="101" fill="#c7d2df" font-family="sans-serif" font-size="13">LON local merge · Metal 3</text>',
        f'<line x1="{legend_x:.2f}" y1="124" x2="{legend_x+34:.2f}" y2="124" stroke="#cb7cff" stroke-width="3" stroke-dasharray="5 3"/>',
        f'<text x="{legend_x+44:.2f}" y="129" fill="#c7d2df" font-family="sans-serif" font-size="13">LOP local merge · Metal 4</text>',
        f'<text x="{legend_x:.2f}" y="164" fill="#c7d2df" font-family="sans-serif" font-size="13">Rows are top-to-bottom:</text>',
        f'<text x="{legend_x:.2f}" y="186" fill="#ffffff" font-family="monospace" font-size="13">8 8 8</text>',
        f'<text x="{legend_x:.2f}" y="206" fill="#ffffff" font-family="monospace" font-size="13">4 8 4</text>',
        f'<text x="{legend_x:.2f}" y="226" fill="#ffffff" font-family="monospace" font-size="13">2 1 2</text>',
        f'<text x="{legend_x:.2f}" y="246" fill="#ffffff" font-family="monospace" font-size="13">4 8 4</text>',
        f'<text x="{legend_x:.2f}" y="266" fill="#ffffff" font-family="monospace" font-size="13">8 8 8</text>',
        f'<text x="{legend_x:.2f}" y="306" fill="#c7d2df" font-family="sans-serif" font-size="13">Group H-trees, edge dummies, shared guard:</text>',
        f'<text x="{legend_x:.2f}" y="326" fill="#f5b942" font-family="sans-serif" font-size="13">next physical gate</text>',
        '</svg>',
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(pieces) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
