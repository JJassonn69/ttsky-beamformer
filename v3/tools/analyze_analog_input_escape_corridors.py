#!/usr/bin/env python3
"""Measure exact frozen metal obstructions on the four analog-input axes."""

from __future__ import annotations

import json
from pathlib import Path

import pya


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "v3/frozen/controller_boundary_handoffs/v3_four_channel_ctrl_boundary_handoffs.gds"
OUTPUT = ROOT / "build/v3/analog_input_escapes/corridor_obstructions.json"
TOP = "v3_four_ch_ctrl_boundary_handoff"
LAYERS = {
    "met2": (69, 20),
    "via2": (69, 44),
    "met3": (70, 20),
    "via3": (70, 44),
    "met4": (71, 20),
}
AXES = {
    "channel0": 152.26,
    "channel1": 132.94,
    "channel2": 113.62,
    "channel3": 94.30,
}


def merged_intervals(intervals: list[tuple[float, float]]) -> list[list[float]]:
    result: list[list[float]] = []
    for lo, hi in sorted(intervals):
        if not result or lo > result[-1][1]:
            result.append([lo, hi])
        else:
            result[-1][1] = max(result[-1][1], hi)
    return [[round(lo, 6), round(hi, 6)] for lo, hi in result]


def main() -> None:
    layout = pya.Layout()
    layout.read(str(INPUT))
    top = layout.cell(TOP)
    if top is None:
        raise SystemExit(f"missing top cell {TOP}")
    dbu = layout.dbu
    report: dict[str, object] = {
        "schema_version": 1,
        "source_gds": str(INPUT.relative_to(ROOT)),
        "top": TOP,
        "source_sha256": "598790c7ed1358cdff93a05393aed9e245238a6712e1242d69516215c3bdc452",
        "route_extent_y_um": [0.0, 143.91],
        "prospective_wire_width_um": 0.4,
        "axes": {},
    }
    half_width = 0.2
    for channel, x in AXES.items():
        item: dict[str, object] = {
            "x_um": x,
            "tinytapeout_pin_center_um": [x, 0.5],
            "element_input_center_um": [x, 143.91],
            "layers": {},
        }
        for layer_name, layer_tuple in LAYERS.items():
            layer_index = layout.layer(*layer_tuple)
            bboxes: list[list[float]] = []
            intervals: list[tuple[float, float]] = []
            iterator = top.begin_shapes_rec(layer_index)
            while not iterator.at_end():
                bbox = iterator.shape().bbox().transformed(iterator.trans()).to_dtype(dbu)
                if (
                    bbox.right >= x - half_width
                    and bbox.left <= x + half_width
                    and bbox.top >= 0.0
                    and bbox.bottom <= 143.91
                ):
                    clipped_bottom = max(0.0, bbox.bottom)
                    clipped_top = min(143.91, bbox.top)
                    bboxes.append([
                        round(bbox.left, 6), round(bbox.bottom, 6),
                        round(bbox.right, 6), round(bbox.top, 6),
                    ])
                    intervals.append((clipped_bottom, clipped_top))
                iterator.next()
            item["layers"][layer_name] = {
                "shape_count": len(bboxes),
                "blocked_y_intervals_um": merged_intervals(intervals),
                "bboxes_um": sorted(bboxes),
            }
        report["axes"][channel] = item
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
