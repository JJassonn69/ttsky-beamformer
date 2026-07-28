#!/usr/bin/env python3
"""Render the exact V3 controller-power candidate for visual review."""

from __future__ import annotations

from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "build/v3/control_power/direct/v3_four_channel_ctrl_powered.gds"
OUTPUT = ROOT / "build/v3/control_power/review"
TOP = "v3_four_channel_ctrl_powered"

COLORS = {
    (64, 20): 0xB7D7A8,
    (65, 20): 0xF4A261,
    (66, 20): 0xE63946,
    (67, 20): 0xD9A441,
    (67, 44): 0xFFFFFF,
    (68, 20): 0x35B9E9,
    (68, 44): 0xFF4FD8,
    (69, 20): 0x3366FF,
    (69, 44): 0x7AE582,
    (70, 20): 0xF39C3D,
    (70, 44): 0xF6BD60,
    (71, 20): 0x8E5BE8,
}


def save(
    view: pya.LayoutView,
    layers: set[tuple[int, int]],
    crop: pya.DBox,
    name: str,
    width: int,
    height: int,
) -> None:
    for props in view.each_layer():
        key = (props.source_layer, props.source_datatype)
        props.visible = key in layers
        if key in COLORS:
            props.fill_color = COLORS[key]
            props.frame_color = COLORS[key]
    view.zoom_box(crop)
    path = OUTPUT / name
    view.save_image(str(path), width, height)
    print(path)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    view = pya.LayoutView()
    cellview = view.load_layout(str(INPUT))
    layout = view.cellview(cellview).layout()
    top = layout.cell(TOP)
    if top is None:
        raise SystemExit(f"missing top cell {TOP}")
    view.select_cell(top.cell_index(), cellview)
    view.max_hier()
    view.add_missing_layers()
    metals = {(68, 20), (69, 20), (70, 20), (71, 20)}
    cuts = {(68, 44), (69, 44), (70, 44)}
    save(
        view,
        metals | cuts,
        pya.DBox(178.0, 168.0, 331.5, 220.0),
        "01_controller_power_all_metals.png",
        2200,
        850,
    )
    save(
        view,
        {(68, 20), (68, 44), (69, 20), (69, 44), (70, 20), (70, 44), (71, 20)},
        pya.DBox(210.0, 168.0, 291.0, 220.0),
        "02_distributed_row_contact_columns.png",
        1800,
        1100,
    )
    save(
        view,
        {(70, 20), (70, 44), (71, 20)},
        pya.DBox(175.0, 204.0, 221.0, 219.0),
        "03_vgnd_left_spine_bridge.png",
        1800,
        750,
    )
    save(
        view,
        {(70, 20), (70, 44), (71, 20)},
        pya.DBox(267.0, 200.0, 277.0, 216.0),
        "04_vgnd_under_vdpwr_spine.png",
        900,
        1400,
    )
    save(
        view,
        {(68, 20), (68, 44), (69, 20), (69, 44), (70, 20), (70, 44), (71, 20)},
        pya.DBox(281.0, 168.0, 329.0, 220.0),
        "05_right_contact_column_and_vdpwr_spine.png",
        1100,
        1200,
    )


if __name__ == "__main__":
    main()
