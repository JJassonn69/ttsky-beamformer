#!/usr/bin/env python3
"""Render inspection views of the exact packaged V3 TinyTapeout GDS.

Run with KLayout's embedded Python:
  klayout -b -r v3/tools/render_submission_gds.py
"""

from pathlib import Path

import pya


ROOT = Path.cwd()
GDS = ROOT / "build/v3/submission/tt_um_jjassonn69_beamformer.gds"
OUTPUT = ROOT / "build/v3/submission/review"
TOP = "tt_um_jjassonn69_beamformer"

COLORS = {
    (235, 4): 0x7F8C9A,  # project boundary
    (64, 20): 0x2F80ED,  # nwell
    (65, 20): 0x43D17A,  # diffusion
    (65, 44): 0x79E6A0,  # tap
    (66, 20): 0xFF6B6B,  # poly
    (66, 44): 0xFFE082,  # licon
    (67, 20): 0xC8D0DC,  # local interconnect
    (67, 44): 0xF4D35E,  # mcon
    (68, 20): 0x35B8E0,  # metal1
    (68, 44): 0xA7E8F5,  # via1
    (69, 20): 0x4C6FFF,  # metal2
    (69, 44): 0x9AAEFF,  # via2
    (70, 20): 0xF39C3D,  # metal3
    (70, 44): 0xFFD166,  # via3
    (71, 20): 0x9B5DE5,  # metal4
    (71, 16): 0xF15BB5,  # official pin purpose
    (79, 20): 0xE9C46A,  # high-R poly marker
    (86, 20): 0xF4A261,  # resistor marker
    (89, 44): 0xF6BD60,  # MIM plate
    (93, 44): 0x6EA8FE,  # n+ implant
    (94, 20): 0xFF8FAB,  # p+ implant
    (95, 20): 0xF9C74F,  # NPC
    (122, 16): 0xE0AAFF, # pwell pin
}


def make_view() -> pya.LayoutView:
    view = pya.LayoutView()
    cellview = view.load_layout(str(GDS))
    layout = view.cellview(cellview).layout()
    top = layout.cell(TOP)
    if top is None:
        raise SystemExit(f"missing top cell {TOP} in {GDS}")
    view.select_cell(top.cell_index(), cellview)
    view.max_hier()
    view.add_missing_layers()
    return view


def set_layers(view: pya.LayoutView, visible: set[tuple[int, int]]) -> None:
    for props in view.each_layer():
        key = (props.source_layer, props.source_datatype)
        props.visible = key in visible
        if key in visible:
            color = COLORS.get(key, 0xB8C4D6)
            props.fill_color = color
            props.frame_color = color


def save(
    view: pya.LayoutView,
    name: str,
    crop: tuple[float, float, float, float],
    size: tuple[int, int],
    visible: set[tuple[int, int]],
) -> None:
    set_layers(view, visible)
    view.zoom_box(pya.DBox(*crop))
    output = OUTPUT / name
    view.save_image(str(output), *size)
    print(output)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    view = make_view()
    devices = {
        (64, 20), (65, 20), (65, 44), (66, 20), (66, 44),
        (67, 20), (67, 44), (68, 20), (68, 44),
        (79, 20), (86, 20), (89, 44), (93, 44), (94, 20),
        (95, 20), (122, 16),
    }
    routing = {
        (68, 20), (68, 44), (69, 20), (69, 44),
        (70, 20), (70, 44), (71, 20), (71, 16), (89, 44),
    }
    save(
        view, "01_full_packaged_layout.png", (0.0, 0.0, 334.88, 225.76),
        (3200, 2200), devices | routing | {(235, 4)},
    )
    save(
        view, "02_routing_and_pins.png", (0.0, 0.0, 334.88, 225.76),
        (3200, 2200), routing | {(235, 4)},
    )
    save(
        view, "03_four_channel_vector_core.png", (82.0, 5.0, 162.0, 195.0),
        (1800, 2600), devices | routing,
    )
    save(
        view, "04_bottom_analog_interface.png", (48.0, -0.6, 163.0, 18.0),
        (3000, 650), routing,
    )
    save(
        view, "05_top_digital_interface.png", (0.0, 217.0, 326.0, 226.3),
        (3200, 520), routing,
    )
    save(
        view, "06_outputs_loads_and_support.png", (42.0, 90.0, 184.0, 161.0),
        (2600, 1400), devices | routing,
    )
    save(
        view, "07_controller_and_handoffs.png", (158.0, 8.0, 326.0, 218.0),
        (2200, 2600), devices | routing,
    )
    save(
        view, "08_power_spines.png", (0.0, 0.0, 18.0, 225.76),
        (650, 2600), routing | {(235, 4)},
    )


main()
