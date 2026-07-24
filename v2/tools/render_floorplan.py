#!/usr/bin/env python3
"""Render the constrained V2 floorplan as a review SVG."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape


COLORS = {
    "quiet_analog": "#a7d8a5",
    "critical_analog": "#72b7b2",
    "clock": "#f4a261",
    "digital_clock": "#e76f51",
    "quiet_mixed_signal": "#b8a1d9",
    "static_digital": "#d8b4a0",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    die = data["template"]["die"]
    width = float(die["width"])
    height = float(die["height"])
    scale = 3.0
    margin = 28.0

    def sx(x: float) -> float:
        return margin + scale * x

    def sy(y: float) -> float:
        return margin + scale * (height - y)

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{2*margin+scale*width:.1f}" '
        f'height="{2*margin+scale*height:.1f}" viewBox="0 0 {2*margin+scale*width:.1f} {2*margin+scale*height:.1f}">',
        '<rect width="100%" height="100%" fill="#f7f7f5"/>',
        f'<rect x="{sx(0):.1f}" y="{sy(height):.1f}" width="{scale*width:.1f}" '
        f'height="{scale*height:.1f}" fill="#ffffff" stroke="#1d3557" stroke-width="2"/>',
    ]

    for zone in data["zones"]:
        x0, y0, x1, y1 = zone["bbox"]
        color = COLORS[zone["noise_class"]]
        svg.append(
            f'<rect x="{sx(x0):.1f}" y="{sy(y1):.1f}" width="{scale*(x1-x0):.1f}" '
            f'height="{scale*(y1-y0):.1f}" fill="{color}" fill-opacity="0.34" '
            f'stroke="{color}" stroke-width="1.5"/>'
        )
        svg.append(
            f'<text x="{sx(x0)+5:.1f}" y="{sy(y1)+15:.1f}" font-family="sans-serif" '
            f'font-size="11" fill="#202020">{escape(zone["name"])}</text>'
        )

    for channel in data["channels"]:
        x0, y0, x1, y1 = channel["slice_bbox"]
        svg.append(
            f'<rect x="{sx(x0):.1f}" y="{sy(y1):.1f}" width="{scale*(x1-x0):.1f}" '
            f'height="{scale*(y1-y0):.1f}" fill="#2a9d8f" fill-opacity="0.16" '
            f'stroke="#087f8c" stroke-width="1.5"/>'
        )
        svg.append(
            f'<text x="{sx(channel["center_x"])-11:.1f}" y="{sy(62):.1f}" '
            f'font-family="sans-serif" font-size="11" fill="#073b4c">CH{channel["index"]}</text>'
        )
        pin = data["analog_pins"][channel["pin"]]["center"]
        entry = channel["input_entry"]
        svg.append(
            f'<path d="M {sx(pin[0]):.1f} {sy(pin[1]):.1f} L {sx(entry[0]):.1f} {sy(entry[1]):.1f}" '
            f'fill="none" stroke="#0081a7" stroke-width="2.5"/>'
        )

    for keepout in data["keepouts"]:
        x0, y0, x1, y1 = keepout["bbox"]
        svg.append(
            f'<rect x="{sx(x0):.1f}" y="{sy(y1):.1f}" width="{scale*(x1-x0):.1f}" '
            f'height="{scale*(y1-y0):.1f}" fill="none" stroke="#6c757d" '
            f'stroke-width="1" stroke-dasharray="3 3"/>'
        )

    for name, pin in data["analog_pins"].items():
        x, y = pin["center"]
        svg.append(
            f'<rect x="{sx(x)-3:.1f}" y="{sy(y)-3:.1f}" width="6" height="6" fill="#1d3557"/>'
        )
        svg.append(
            f'<text x="{sx(x)-14:.1f}" y="{sy(y)+17:.1f}" font-family="sans-serif" '
            f'font-size="10" fill="#1d3557">{escape(name)}</text>'
        )

    tree = data["clock_tree"]
    root = tree["root"]
    for branch_name, branch in tree["pair_branches"].items():
        svg.append(
            f'<path d="M {sx(root[0]):.1f} {sy(root[1]):.1f} L {sx(branch[0]):.1f} {sy(root[1]):.1f} '
            f'L {sx(branch[0]):.1f} {sy(branch[1]):.1f}" fill="none" stroke="#d1495b" stroke-width="3"/>'
        )
        for leaf in tree["leaves"]:
            if leaf["branch"] != branch_name:
                continue
            point = leaf["point"]
            svg.append(
                f'<path d="M {sx(branch[0]):.1f} {sy(branch[1]):.1f} L {sx(point[0]):.1f} {sy(branch[1]):.1f} '
                f'L {sx(point[0]):.1f} {sy(point[1]):.1f}" fill="none" stroke="#d1495b" stroke-width="3"/>'
            )

    output = data["output_pair"]
    for net_name, color in (("p", "#4361ee"), ("n", "#3a0ca3")):
        load = output[f"load_{net_name}"]
        route = output["routes"][net_name]
        path_parts = [f'M {sx(route[0]["from"][0]):.1f} {sy(route[0]["from"][1]):.1f}']
        for segment in route:
            point = segment["to"]
            path_parts.append(f'L {sx(point[0]):.1f} {sy(point[1]):.1f}')
        svg.append(
            f'<path d="{" ".join(path_parts)}" fill="none" stroke="{color}" '
            f'stroke-width="2.5" stroke-dasharray="7 4"/>'
        )
        svg.append(
            f'<circle cx="{sx(load[0]):.1f}" cy="{sy(load[1]):.1f}" r="4" fill="{color}"/>'
        )

    svg.extend(
        [
            f'<text x="{margin:.1f}" y="18" font-family="sans-serif" font-size="15" '
            f'font-weight="bold" fill="#1d3557">V2 constrained floorplan — pre-placement skeleton</text>',
            '</svg>',
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
