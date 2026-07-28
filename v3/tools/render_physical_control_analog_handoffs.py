#!/usr/bin/env python3
"""Render the exact V3 controller-to-analog handoff candidate."""

from __future__ import annotations

from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "build/v3/control_analog_handoffs/direct"
OUTPUT = ROOT / "build/v3/control_analog_handoffs/review"
ASSEMBLED = BASE / "v3_four_channel_ctrl_analog_handoffs.gds"
OVERLAY = BASE / "v3_control_analog_handoff_routes.gds"
ASSEMBLED_TOP = "v3_four_ch_ctrl_analog_handoff"
OVERLAY_TOP = "v3_ctrl_analog_handoff_routes"

COLORS = {
    (68, 20): 0x35B9E9,
    (68, 44): 0xFF4FD8,
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
    all_layers = {
        (68, 20), (68, 44), (69, 20), (69, 44),
        (70, 20), (70, 44), (71, 20),
    }
    assembled = make_view(ASSEMBLED, ASSEMBLED_TOP)
    overlay = make_view(OVERLAY, OVERLAY_TOP)
    save(
        assembled,
        all_layers,
        pya.DBox(74.0, 167.0, 184.0, 207.5),
        "01_integrated_handoffs_all_metals.png",
        2400,
        900,
    )
    save(
        overlay,
        all_layers,
        pya.DBox(74.0, 167.0, 184.0, 207.5),
        "02_handoff_overlay_only.png",
        2400,
        900,
    )
    save(
        overlay,
        {(69, 20), (69, 44), (70, 20), (70, 44), (71, 20)},
        pya.DBox(133.0, 194.0, 183.0, 206.0),
        "03_four_phase_handoffs.png",
        2200,
        700,
    )
    save(
        overlay,
        all_layers,
        pya.DBox(94.0, 168.0, 183.0, 193.0),
        "04_group_code_handoffs.png",
        2400,
        800,
    )
    save(
        overlay,
        all_layers,
        pya.DBox(94.0, 174.0, 183.0, 201.0),
        "05_enable_and_blanking_handoffs.png",
        2400,
        850,
    )


if __name__ == "__main__":
    main()
