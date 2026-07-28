#!/usr/bin/env python3
"""Render the exact V3 static-low digital-output bus and its 24 drops."""

from __future__ import annotations

from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "build/v3/digital_output_tie/direct"
OUTPUT = ROOT / "build/v3/digital_output_tie/final_review"
ASSEMBLED = BASE / "v3_four_channel_output_tied.gds"
OVERLAY = BASE / "v3_digital_output_tie_low.gds"
ASSEMBLED_TOP = "v3_four_ch_output_tied"
OVERLAY_TOP = "v3_digital_output_tie_low"
COLORS = {
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
    save(assembled, pya.DBox(0.0, 218.0, 100.0, 226.2), "01_integrated_output_ties.png", 2800, 650)
    save(overlay, pya.DBox(0.0, 218.0, 100.0, 226.2), "02_output_tie_overlay_only.png", 2800, 650)
    save(assembled, pya.DBox(28.0, 222.8, 97.0, 226.2), "03_exact_output_pin_drops.png", 2800, 500)


if __name__ == "__main__":
    main()
