#!/usr/bin/env python3
"""Render exact assembled V3 controller routes for layer-by-layer review."""

from __future__ import annotations

import os
from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[2]
INPUT = Path(os.environ.get(
    "V3_CONTROL_ROUTE_GDS",
    ROOT / "build/v3/control_routing/openroad_internal/direct/v3_four_channel_control_signal_routed.gds",
)).resolve()
OUTPUT_DIR = Path(os.environ.get(
    "V3_CONTROL_ROUTE_RENDER_DIR",
    ROOT / "build/v3/control_routing/openroad_internal/review",
)).resolve()
TOP = os.environ.get("V3_CONTROL_ROUTE_TOP", "v3_four_channel_ctrl_sig_routed")

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
VIEWS = {
    "01_m1_local_access": {(67, 20), (67, 44), (68, 20), (68, 44)},
    "02_m2_distribution": {(68, 20), (68, 44), (69, 20), (69, 44)},
    "03_m3_distribution": {(69, 20), (69, 44), (70, 20)},
    "04_all_controller_routes": set(COLORS),
}


def save_view(
    view: pya.LayoutView,
    visible: set[tuple[int, int]],
    crop: pya.DBox,
    output: Path,
    width: int,
    height: int,
) -> None:
    for props in view.each_layer():
        key = (props.source_layer, props.source_datatype)
        props.visible = key in visible
        if key in COLORS:
            props.fill_color = COLORS[key]
            props.frame_color = COLORS[key]
    view.zoom_box(crop)
    view.save_image(str(output), width, height)
    print(output)


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
    full = pya.DBox(177.0, 166.0, 323.0, 221.5)
    for stem, visible in VIEWS.items():
        save_view(view, visible, full, OUTPUT_DIR / f"{stem}.png", 2000, 900)
    save_view(
        view,
        {(69, 20), (69, 44), (70, 20)},
        pya.DBox(258.0, 167.0, 278.0, 220.0),
        OUTPUT_DIR / "05_m3_frozen_trunk_detour_closeup.png",
        900,
        1800,
    )


if __name__ == "__main__":
    main()
