#!/usr/bin/env python3
"""Render reproducible close-ups from the exact submitted GDS.

Run with KLayout's Python interpreter, for example:

    BF_GDS_INPUT=gds/tt_um_jjassonn69_beamformer.gds \
    BF_RENDER_DIR=build/v2/submission/review \
      klayout -zz -r v2/tools/render_submission_closeups.py

The view is expanded to maximum hierarchy, so every visible rectangle is the
actual flattened fabrication geometry rather than a schematic approximation.
"""

from __future__ import annotations

import os
from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[2]
INPUT = Path(os.environ.get(
    "BF_GDS_INPUT",
    ROOT / "gds/tt_um_jjassonn69_beamformer.gds",
)).resolve()
OUTPUT_DIR = Path(os.environ.get(
    "BF_RENDER_DIR",
    ROOT / "build/v2/submission/review",
)).resolve()
TOP = "tt_um_jjassonn69_beamformer"

# Layer colors match the legend written beside each image.
LAYERS = {
    (67, 20): ("LI1", 0xB8C4CE),
    (68, 20): ("M1", 0xF4A261),
    (68, 44): ("VIA1", 0xE63946),
    (69, 20): ("M2", 0x35B9E9),
    (69, 44): ("VIA2", 0xFF4FD8),
    (70, 20): ("M3", 0x3366FF),
    (70, 44): ("VIA3", 0x7AE582),
    (71, 20): ("M4", 0x6A4CFF),
    (89, 44): ("CAPM", 0xFFD166),
}

CLOSEUPS = {
    "01_mixer_m2_m3_transitions": (88.0, 71.0, 160.0, 80.5),
    "02_trim_control_routes": (88.0, 43.5, 160.0, 49.5),
    "03_fixed_tail_gate_landings": (88.0, 30.5, 160.0, 40.5),
    "04_m4_output_and_common_mode": (88.0, 84.0, 160.0, 100.5),
    "05_channel2_mixer_transition_detail": (110.5, 71.5, 117.5, 79.8),
    "06_channel2_trim_route_detail": (110.5, 43.8, 117.5, 49.2),
    "07_channel2_tail_landing_detail": (110.5, 30.8, 117.5, 40.2),
}


def configure_layers(view: pya.LayoutView) -> None:
    view.add_missing_layers()
    for properties in view.each_layer():
        key = (properties.source_layer, properties.source_datatype)
        properties.visible = key in LAYERS
        if key in LAYERS:
            _name, color = LAYERS[key]
            properties.fill_color = color
            properties.frame_color = color


def main() -> None:
    if not INPUT.is_file():
        raise SystemExit(f"missing input GDS: {INPUT}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    view = pya.LayoutView()
    cellview_index = view.load_layout(str(INPUT))
    layout = view.cellview(cellview_index).layout()
    top = layout.cell(TOP)
    if top is None:
        raise SystemExit(f"missing top cell {TOP}")
    view.select_cell(top.cell_index(), cellview_index)
    view.max_hier()
    configure_layers(view)

    for stem, bounds in CLOSEUPS.items():
        left, bottom, right, top_y = bounds
        view.zoom_box(pya.DBox(left, bottom, right, top_y))
        destination = OUTPUT_DIR / f"{stem}.png"
        view.save_image(str(destination), 2200, 900)
        print(destination)

    legend = OUTPUT_DIR / "layer_legend.txt"
    legend.write_text("\n".join(
        f"{name}: GDS {layer}/{datatype}, #{color:06X}"
        for (layer, datatype), (name, color) in LAYERS.items()
    ) + "\n")
    print(legend)


if __name__ == "__main__":
    main()
