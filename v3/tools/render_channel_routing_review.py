#!/usr/bin/env python3
"""Render exact V3 channel routing layers for placement/routing review."""

from __future__ import annotations

import os
from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[2]
INPUT = Path(os.environ.get(
    "V3_CHANNEL_GDS",
    ROOT / "build/v3/channel_input_bias_pilot/v3_channel_input_bias_pilot.gds",
)).resolve()
OUTPUT_DIR = Path(os.environ.get(
    "V3_CHANNEL_RENDER_DIR",
    ROOT / "build/v3/channel_output_route/review",
)).resolve()
TOP = os.environ.get("V3_CHANNEL_TOP", "v3_channel_input_bias_pilot")

COLORS = {
    (68, 20): 0xF4A261,
    (68, 44): 0xE63946,
    (69, 20): 0x35B9E9,
    (69, 44): 0xFF4FD8,
    (70, 20): 0x3366FF,
    (70, 44): 0x7AE582,
    (71, 20): 0x6A4CFF,
}
VIEWS = {
    "01_m2_only": {(69, 20), (69, 44)},
    "02_m3_only": {(70, 20), (69, 44), (70, 44)},
    "03_m4_only": {(71, 20), (70, 44)},
    "04_m2_m3_m4": set(COLORS),
}
SELECTED_VIEW = os.environ.get("V3_CHANNEL_VIEW")
SELECTED_BOX = os.environ.get("V3_CHANNEL_BOX", "19.5,16.8,40.0,114.0")
IMAGE_WIDTH = int(os.environ.get("V3_CHANNEL_RENDER_WIDTH", "1200"))
IMAGE_HEIGHT = int(os.environ.get("V3_CHANNEL_RENDER_HEIGHT", "2400"))


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
    selected = VIEWS.items()
    if SELECTED_VIEW:
        if SELECTED_VIEW not in VIEWS:
            raise SystemExit(f"unknown V3_CHANNEL_VIEW: {SELECTED_VIEW}")
        selected = ((SELECTED_VIEW, VIEWS[SELECTED_VIEW]),)
    coordinates = [float(value) for value in SELECTED_BOX.split(",")]
    if len(coordinates) != 4 or coordinates[2] <= coordinates[0] or coordinates[3] <= coordinates[1]:
        raise SystemExit("V3_CHANNEL_BOX must be x1,y1,x2,y2 with a positive area")
    for stem, visible in selected:
        for props in view.each_layer():
            key = (props.source_layer, props.source_datatype)
            props.visible = key in visible
            if key in COLORS:
                props.fill_color = COLORS[key]
                props.frame_color = COLORS[key]
        view.zoom_box(pya.DBox(*coordinates))
        destination = OUTPUT_DIR / f"{stem}.png"
        view.save_image(str(destination), IMAGE_WIDTH, IMAGE_HEIGHT)
        print(destination)


if __name__ == "__main__":
    main()
