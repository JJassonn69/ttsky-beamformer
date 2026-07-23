#!/usr/bin/env python3
"""Render the measured repeated V2 analog-core placement plan as SVG."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape


ROLE_COLORS = {
    "input_bias": "#4d908e",
    "trim_fixed_12": "#577590",
    "trim_binary_8": "#577590",
    "trim_binary_4": "#577590",
    "trim_binary_2": "#577590",
    "trim_binary_1": "#577590",
    "trim_gate_switch": "#277da1",
    "trim_control_inverter": "#277da1",
    "gm_signal": "#f9844a",
    "gm_reference": "#f9c74f",
    "mixer_out_p": "#4361ee",
    "mixer_out_n": "#7209b7",
    "phase_mux": "#f8961e",
    "phase_gate": "#f3722c",
    "phase_buffer": "#f94144",
    "well_tap": "#90be6d",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("floorplan", type=Path)
    parser.add_argument("dimensions", type=Path)
    parser.add_argument("template", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    floorplan = json.loads(args.floorplan.read_text(encoding="utf-8"))
    dimensions = json.loads(args.dimensions.read_text(encoding="utf-8"))["pcells"]
    template = json.loads(args.template.read_text(encoding="utf-8"))
    die = floorplan["template"]["die"]
    scale = 4.0
    margin = 34.0
    width = float(die["width"])
    height = float(die["height"])

    def sx(x: float) -> float:
        return margin + scale * x

    def sy(y: float) -> float:
        return margin + scale * (height - y)

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{2*margin+scale*width:.1f}" '
        f'height="{2*margin+scale*height:.1f}" viewBox="0 0 {2*margin+scale*width:.1f} {2*margin+scale*height:.1f}">',
        '<rect width="100%" height="100%" fill="#f7f7f5"/>',
        f'<rect x="{sx(0):.1f}" y="{sy(height):.1f}" width="{scale*width:.1f}" '
        f'height="{scale*height:.1f}" fill="#fff" stroke="#1d3557" stroke-width="2"/>',
        '<text x="34" y="22" font-family="sans-serif" font-size="15" font-weight="bold" fill="#1d3557">V2 measured analog-core placement plan</text>',
    ]

    for zone in floorplan["zones"]:
        x0, y0, x1, y1 = zone["bbox"]
        svg.append(
            f'<rect x="{sx(x0):.1f}" y="{sy(y1):.1f}" width="{scale*(x1-x0):.1f}" '
            f'height="{scale*(y1-y0):.1f}" fill="#adb5bd" fill-opacity="0.08" '
            f'stroke="#adb5bd" stroke-width="0.8" stroke-dasharray="4 3"/>'
        )

    for channel in floorplan["channels"]:
        center_x = float(channel["center_x"])
        x0, y0, x1, y1 = channel["slice_bbox"]
        svg.append(
            f'<rect x="{sx(x0):.1f}" y="{sy(y1):.1f}" width="{scale*(x1-x0):.1f}" '
            f'height="{scale*(y1-y0):.1f}" fill="none" stroke="#087f8c" stroke-width="1.5"/>'
        )
        selector = channel["phase_selector_bbox"]
        svg.append(
            f'<rect x="{sx(selector[0]):.1f}" y="{sy(selector[3]):.1f}" '
            f'width="{scale*(selector[2]-selector[0]):.1f}" height="{scale*(selector[3]-selector[1]):.1f}" '
            f'fill="#f4a261" fill-opacity="0.18" stroke="#e76f51" stroke-width="1.2"/>'
        )
        svg.append(
            f'<text x="{sx(x0)+3:.1f}" y="{sy(y1)+13:.1f}" font-family="sans-serif" '
            f'font-size="10" fill="#073b4c">CH{channel["index"]}</text>'
        )

        for ring in template["guard_rings"]:
            rx0, ry0, rx1, ry1 = ring["bbox"]
            svg.append(
                f'<rect x="{sx(center_x+rx0):.1f}" y="{sy(ry1):.1f}" '
                f'width="{scale*(rx1-rx0):.1f}" height="{scale*(ry1-ry0):.1f}" '
                f'fill="none" stroke="#2a9d8f" stroke-width="1" stroke-dasharray="2 2"/>'
            )

        for component in template["components"]:
            cell = dimensions[component["pcell"]]
            component_x = center_x + float(component["x"])
            component_y = float(component["y"])
            cell_width = float(cell["width_um"])
            cell_height = float(cell["height_um"])
            color = ROLE_COLORS[component["role"]]
            svg.append(
                f'<rect x="{sx(component_x-cell_width/2):.1f}" '
                f'y="{sy(component_y+cell_height/2):.1f}" width="{scale*cell_width:.1f}" '
                f'height="{scale*cell_height:.1f}" fill="{color}" fill-opacity="0.78" '
                f'stroke="#202020" stroke-width="0.45"/>'
            )

        pin = floorplan["analog_pins"][channel["pin"]]["center"]
        svg.append(
            f'<path d="M {sx(pin[0]):.1f} {sy(pin[1]):.1f} L {sx(center_x):.1f} {sy(8.0):.1f}" '
            f'fill="none" stroke="#0081a7" stroke-width="2.2"/>'
        )

    output = floorplan["output_pair"]
    load_cell = dimensions["output_load_resistor_guarded"]
    for side, color in (("p", "#4361ee"), ("n", "#7209b7")):
        cx, cy = output[f"load_{side}_center"]
        svg.append(
            f'<rect x="{sx(cx-load_cell["width_um"]/2):.1f}" '
            f'y="{sy(cy+load_cell["height_um"]/2):.1f}" '
            f'width="{scale*load_cell["width_um"]:.1f}" height="{scale*load_cell["height_um"]:.1f}" '
            f'fill="{color}" fill-opacity="0.7" stroke="#202020" stroke-width="0.6"/>'
        )
        route = output["routes"][side]
        commands = [f'M {sx(route[0]["from"][0]):.1f} {sy(route[0]["from"][1]):.1f}']
        commands.extend(
            f'L {sx(segment["to"][0]):.1f} {sy(segment["to"][1]):.1f}'
            for segment in route
        )
        svg.append(
            f'<path d="{" ".join(commands)}" fill="none" stroke="{color}" '
            f'stroke-width="2.2" stroke-dasharray="6 3"/>'
        )

    legend_y = sy(20.0)
    legend_x = sx(184.0)
    svg.append(
        f'<rect x="{legend_x:.1f}" y="{sy(164):.1f}" width="520" height="174" '
        f'fill="#fff" fill-opacity="0.92" stroke="#6c757d" stroke-width="1"/>'
    )
    legend = [
        ("Input bias resistor", ROLE_COLORS["input_bias"]),
        ("Equal-unit tail trim", ROLE_COLORS["trim_fixed_12"]),
        ("GM signal / reference ABBA", ROLE_COLORS["gm_signal"]),
        ("Mixer output P / N common centroid", ROLE_COLORS["mixer_out_p"]),
        ("Pinned local phase-selector cells", "#f4a261"),
    ]
    for index, (label, color) in enumerate(legend):
        y = sy(157.0) + index * 28
        svg.append(f'<rect x="{legend_x+12:.1f}" y="{y-10:.1f}" width="18" height="12" fill="{color}"/>')
        svg.append(
            f'<text x="{legend_x+38:.1f}" y="{y:.1f}" font-family="sans-serif" '
            f'font-size="12" fill="#202020">{escape(label)}</text>'
        )
    svg.append(
        f'<text x="{legend_x+12:.1f}" y="{legend_y:.1f}" font-family="sans-serif" '
        f'font-size="11" fill="#495057">Measured PCells plus pinned official standard-cell GDS; isolated selector placement passes full Magic DRC.</text>'
    )
    svg.append('</svg>')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
