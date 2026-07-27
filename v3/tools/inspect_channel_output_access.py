#!/usr/bin/env python3
"""Report exact conductor geometry around every V3 output drain access."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[2]
INPUT = Path(os.environ.get(
    "V3_CHANNEL_GDS",
    ROOT / "build/v3/channel_input_bias_pilot/v3_channel_input_bias_pilot.gds",
)).resolve()
OUTPUT = Path(os.environ.get(
    "V3_OUTPUT_ACCESS_REPORT",
    ROOT / "build/v3/channel_output_route/output_access_geometry.json",
)).resolve()
TOP = os.environ.get("V3_CHANNEL_TOP", "v3_channel_input_bias_pilot")
LAYERS = {"met2": (69, 20), "via2": (69, 44), "met3": (70, 20), "via3": (70, 44), "met4": (71, 20)}
POINTS = {
    **{f"u{i:02d}_outp": point for i, point in enumerate((
        (22.32, 104.23), (27.52, 104.23), (32.72, 104.23),
        (22.32, 88.23), (27.52, 88.23), (32.72, 88.23),
        (22.32, 72.23), (27.52, 72.23), (33.42, 72.23),
        (23.02, 56.23), (28.22, 56.23), (33.42, 56.23),
        (23.02, 40.23), (28.22, 40.23), (33.42, 40.23),
    ))},
    **{f"u{i:02d}_outn": point for i, point in enumerate((
        (23.02, 104.23), (28.22, 104.23), (33.42, 104.23),
        (23.02, 88.23), (28.22, 88.23), (33.42, 88.23),
        (23.02, 72.23), (28.22, 72.23), (32.72, 72.23),
        (22.32, 56.23), (27.52, 56.23), (32.72, 56.23),
        (22.32, 40.23), (27.52, 40.23), (32.72, 40.23),
    ))},
}


def main() -> None:
    layout = pya.Layout()
    layout.read(str(INPUT))
    top = layout.cell(TOP)
    if top is None:
        raise SystemExit(f"missing top cell {TOP}")
    dbu = layout.dbu
    report: dict[str, object] = {
        "input_gds": str(INPUT), "top": TOP, "points": {}, "channel_shapes": {}
    }
    channel_window = pya.DBox(19.5, 16.8, 40.0, 114.0)
    for layer_name, layer_tuple in LAYERS.items():
        layer_index = layout.layer(*layer_tuple)
        bboxes: list[list[float]] = []
        iterator = top.begin_shapes_rec(layer_index)
        while not iterator.at_end():
            bbox = iterator.shape().bbox().transformed(iterator.trans()).to_dtype(dbu)
            if bbox.touches(channel_window):
                bboxes.append([bbox.left, bbox.bottom, bbox.right, bbox.top])
            iterator.next()
        report["channel_shapes"][layer_name] = sorted(bboxes)
    for name, (x, y) in sorted(POINTS.items()):
        window = pya.DBox(x - 0.65, y - 1.4, x + 0.65, y + 1.4)
        item: dict[str, object] = {"point_um": [x, y], "nearby": {}}
        for layer_name, layer_tuple in LAYERS.items():
            layer_index = layout.layer(*layer_tuple)
            bboxes: list[list[float]] = []
            iterator = top.begin_shapes_rec(layer_index)
            while not iterator.at_end():
                bbox = iterator.shape().bbox().transformed(iterator.trans()).to_dtype(dbu)
                if bbox.touches(window):
                    bboxes.append([bbox.left, bbox.bottom, bbox.right, bbox.top])
                iterator.next()
            item["nearby"][layer_name] = sorted(bboxes)
        report["points"][name] = item
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
