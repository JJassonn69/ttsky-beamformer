#!/usr/bin/env python3
"""Render Candidate A and B top interfaces at identical scale and layer styling."""

from __future__ import annotations

from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "build/v3/experiments/controller_pin_aligned/review"
CROP = pya.DBox(96.0, 198.5, 308.0, 226.5)
COLORS = {
    (69, 20): 0x3366FF,  # M2
    (69, 44): 0x7AE582,  # via2
    (70, 20): 0xF39C3D,  # M3
    (70, 44): 0xF6BD60,  # via3
    (71, 20): 0x8E5BE8,  # M4
}


def render(path: Path, top_name: str, output_name: str) -> None:
    view = pya.LayoutView()
    cellview = view.load_layout(str(path))
    layout = view.cellview(cellview).layout()
    top = layout.cell(top_name)
    if top is None:
        raise SystemExit(f"missing top cell {top_name} in {path}")
    view.select_cell(top.cell_index(), cellview)
    view.max_hier()
    view.add_missing_layers()
    for props in view.each_layer():
        key = (props.source_layer, props.source_datatype)
        props.visible = key in COLORS
        if key in COLORS:
            props.fill_color = COLORS[key]
            props.frame_color = COLORS[key]
    view.zoom_box(CROP)
    view.save_image(str(OUTPUT / output_name), 2800, 800)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    render(
        ROOT / "v3/frozen/controller_boundary_handoffs/v3_four_channel_ctrl_boundary_handoffs.gds",
        "v3_four_ch_ctrl_boundary_handoff",
        "candidate_a_integrated_top_interface.png",
    )
    render(
        ROOT / "v3/frozen/controller_boundary_handoffs/v3_control_boundary_handoff_routes.gds",
        "v3_ctrl_boundary_handoff_routes",
        "candidate_a_boundary_routes_only.png",
    )
    render(
        ROOT / "build/v3/experiments/controller_pin_aligned/boundary_handoffs/direct/v3_cb_four_channel_ctrl_boundary_handoffs.gds",
        "v3_cb_4ch_ctrl_bnd",
        "candidate_b_integrated_top_interface.png",
    )
    render(
        ROOT / "build/v3/experiments/controller_pin_aligned/boundary_handoffs/direct/v3_cb_control_boundary_handoff_routes.gds",
        "v3_cb_ctrl_bnd_routes",
        "candidate_b_boundary_routes_only.png",
    )
    for path in sorted(OUTPUT.glob("candidate_*.png")):
        print(path)


if __name__ == "__main__":
    main()
