#!/usr/bin/env python3
"""Render the exact four-channel analog-input escape candidate."""

from __future__ import annotations

from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "build/v3/analog_input_escapes/direct"
OUTPUT = ROOT / "build/v3/analog_input_escapes/final_review"
ASSEMBLED = BASE / "v3_four_channel_analog_inputs.gds"
OVERLAY = BASE / "v3_analog_input_escape_routes.gds"
ASSEMBLED_TOP = "v3_four_ch_analog_inputs"
OVERLAY_TOP = "v3_analog_input_escape_routes"
COLORS = {
    (69, 20): 0x3366FF,
    (69, 44): 0x7AE582,
    (70, 20): 0xF39C3D,
    (70, 44): 0xF6BD60,
    (71, 20): 0x8E5BE8,
}


def make_view(path: Path, top_name: str) -> pya.LayoutView:
    view = pya.LayoutView()
    cellview = view.load_layout(str(path))
    layout = view.cellview(cellview).layout()
    top = layout.cell(top_name)
    if top is None:
        raise SystemExit(f"missing top cell {top_name} in {path}")
    view.select_cell(top.cell_index(), cellview)
    view.max_hier()
    view.add_missing_layers()
    return view


def save(view: pya.LayoutView, crop: pya.DBox, name: str, width: int, height: int) -> None:
    for props in view.each_layer():
        key = (props.source_layer, props.source_datatype)
        props.visible = key in COLORS
        if key in COLORS:
            props.fill_color = COLORS[key]
            props.frame_color = COLORS[key]
    view.zoom_box(crop)
    path = OUTPUT / name
    view.save_image(str(path), width, height)
    print(path)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    assembled = make_view(ASSEMBLED, ASSEMBLED_TOP)
    overlay = make_view(OVERLAY, OVERLAY_TOP)
    save(
        assembled,
        pya.DBox(86.0, -1.0, 161.0, 15.0),
        "01_integrated_input_escapes.png",
        2600,
        650,
    )
    save(
        overlay,
        pya.DBox(86.0, -1.0, 161.0, 15.0),
        "02_input_escape_overlay_only.png",
        2600,
        650,
    )
    save(
        assembled,
        pya.DBox(91.5, 7.5, 155.0, 12.0),
        "03_m2_input_landings.png",
        2800,
        600,
    )
    save(
        assembled,
        pya.DBox(91.5, -0.5, 155.0, 2.0),
        "04_tinytapeout_analog_pads.png",
        2800,
        500,
    )


if __name__ == "__main__":
    main()
