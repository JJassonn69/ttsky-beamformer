#!/usr/bin/env python3
"""Render the frozen geometry under the four analog-input axes."""

from __future__ import annotations

from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "v3/frozen/controller_boundary_handoffs/v3_four_channel_ctrl_boundary_handoffs.gds"
OUTPUT = ROOT / "build/v3/analog_input_escapes/review"
TOP = "v3_four_ch_ctrl_boundary_handoff"
COLORS = {
    (69, 20): 0x3366FF,
    (69, 44): 0x7AE582,
    (70, 20): 0xF39C3D,
    (70, 44): 0xF6BD60,
    (71, 20): 0x8E5BE8,
}


def save(view: pya.LayoutView, layers: set[tuple[int, int]], name: str) -> None:
    for props in view.each_layer():
        key = (props.source_layer, props.source_datatype)
        props.visible = key in layers
        if key in COLORS:
            props.fill_color = COLORS[key]
            props.frame_color = COLORS[key]
    view.zoom_box(pya.DBox(86.0, -1.0, 161.0, 146.0))
    path = OUTPUT / name
    view.save_image(str(path), 1600, 2600)
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
    save(view, set(COLORS), "01_all_routing_layers.png")
    save(view, {(69, 20), (69, 44)}, "02_m2_and_via2.png")
    save(view, {(70, 20), (70, 44)}, "03_m3_and_via3.png")
    save(view, {(71, 20)}, "04_m4_only.png")


if __name__ == "__main__":
    main()
