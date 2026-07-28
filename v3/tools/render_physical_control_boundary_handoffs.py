#!/usr/bin/env python3
"""Render the exact V3 controller-to-TinyTapeout boundary handoffs."""

from __future__ import annotations

from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "build/v3/control_boundary_handoffs/direct"
OUTPUT = ROOT / "build/v3/control_boundary_handoffs/review"
ASSEMBLED = BASE / "v3_four_channel_ctrl_boundary_handoffs.gds"
OVERLAY = BASE / "v3_control_boundary_handoff_routes.gds"
ASSEMBLED_TOP = "v3_four_ch_ctrl_boundary_handoff"
OVERLAY_TOP = "v3_ctrl_boundary_handoff_routes"

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


def save(
    view: pya.LayoutView,
    crop: pya.DBox,
    name: str,
    width: int,
    height: int,
) -> None:
    visible = set(COLORS)
    for props in view.each_layer():
        key = (props.source_layer, props.source_datatype)
        props.visible = key in visible
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
        pya.DBox(96.0, 198.5, 308.0, 226.5),
        "01_integrated_boundary_handoffs.png",
        2800,
        800,
    )
    save(
        overlay,
        pya.DBox(96.0, 198.5, 308.0, 226.5),
        "02_boundary_overlay_only.png",
        2800,
        800,
    )
    save(
        overlay,
        pya.DBox(101.0, 218.0, 151.0, 226.2),
        "03_tinytapeout_pin_landings.png",
        2600,
        650,
    )
    save(
        overlay,
        pya.DBox(184.0, 214.5, 307.0, 226.2),
        "04_controller_input_landings.png",
        2800,
        650,
    )


if __name__ == "__main__":
    main()
