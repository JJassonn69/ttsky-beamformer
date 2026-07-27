#!/usr/bin/env python3
"""Render the exact controller placement-only GDS for visual review."""

from __future__ import annotations

import os
from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[2]
INPUT = Path(os.environ.get(
    "V3_CONTROL_GDS",
    ROOT / "build/v3/control_placement/direct/v3_four_channel_control_placed.gds",
)).resolve()
OUTPUT_DIR = Path(os.environ.get(
    "V3_CONTROL_RENDER_DIR",
    ROOT / "build/v3/control_placement/review",
)).resolve()
TOP = "v3_four_channel_control_placed"

COLORS = {
    (64, 20): 0xB7D7A8,  # nwell
    (65, 20): 0xF4A261,  # diffusion
    (66, 20): 0xE63946,  # poly
    (67, 20): 0xD9A441,  # local interconnect
    (67, 44): 0xFFFFFF,  # licon/mcon family
    (68, 20): 0x35B9E9,  # metal 1
    (68, 44): 0xFF4FD8,  # via 1
    (69, 20): 0x3366FF,  # metal 2
    (69, 44): 0x7AE582,  # via 2
    (70, 20): 0x6A4CFF,  # metal 3
    (70, 44): 0xF6BD60,  # via 3
    (71, 20): 0x8E5BE8,  # metal 4
}
VIEWS = {
    "01_controller_cells": {(64, 20), (65, 20), (66, 20), (67, 20), (67, 44), (68, 20)},
    "02_controller_access": {(67, 20), (67, 44), (68, 20), (68, 44), (69, 20)},
    "03_controller_with_existing_upper_routes": set(COLORS),
}


def main() -> None:
    if not INPUT.is_file():
        raise SystemExit(f"missing input GDS: {INPUT}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    view = pya.LayoutView()
    cv_index = view.load_layout(str(INPUT))
    layout = view.cellview(cv_index).layout()
    top = layout.cell(TOP)
    if top is None:
        raise SystemExit(f"missing top cell {TOP}")
    view.select_cell(top.cell_index(), cv_index)
    view.max_hier()
    view.add_missing_layers()
    for stem, visible in VIEWS.items():
        for props in view.each_layer():
            key = (props.source_layer, props.source_datatype)
            props.visible = key in visible
            if key in COLORS:
                props.fill_color = COLORS[key]
                props.frame_color = COLORS[key]
        view.zoom_box(pya.DBox(177.0, 166.0, 323.0, 221.5))
        output = OUTPUT_DIR / f"{stem}.png"
        view.save_image(str(output), 1800, 800)
        print(output)


if __name__ == "__main__":
    main()
