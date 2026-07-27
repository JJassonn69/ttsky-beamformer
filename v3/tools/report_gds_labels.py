#!/usr/bin/env python3
"""Report recursively transformed text labels in a GDS using KLayout Python."""

from __future__ import annotations

import json
from pathlib import Path

import pya


def required(name: str) -> str:
    value = globals().get(name)
    if not value:
        raise RuntimeError(f"missing -rd {name}=...")
    return str(value)


layout = pya.Layout()
input_path = Path(required("input")).resolve()
layout.read(str(input_path))
tops = list(layout.top_cells())
if len(tops) != 1:
    raise RuntimeError(f"expected one top cell, found {len(tops)}")
top = tops[0]
records: list[dict[str, object]] = []
for layer_index in layout.layer_indices():
    info = layout.get_info(layer_index)
    iterator = top.begin_shapes_rec(layer_index)
    while not iterator.at_end():
        shape = iterator.shape()
        if shape.is_text():
            value = shape.text.transformed(iterator.trans())
            records.append({
                "text": value.string,
                "layer": [info.layer, info.datatype],
                "x_um": round(value.x * layout.dbu, 6),
                "y_um": round(value.y * layout.dbu, 6),
            })
        iterator.next()
records.sort(key=lambda item: (str(item["text"]), item["layer"], item["x_um"], item["y_um"]))
result = {
    "input": str(input_path),
    "top": top.name,
    "dbu_um": layout.dbu,
    "labels": records,
}
output_path = globals().get("output")
if output_path:
    Path(str(output_path)).resolve().write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
print(json.dumps(result, indent=2, sort_keys=True))
