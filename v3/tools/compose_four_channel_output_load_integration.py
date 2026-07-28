"""Compose the exact output-load block and direct differential pad escapes."""

import hashlib
import json
import sys
from pathlib import Path

import pya


root = Path(str(project_root)).resolve()
sys.path.insert(0, str(root / "v3/tools"))
from canonicalize_gds_timestamps import canonicalize  # noqa: E402

manifest = json.loads((root / "v3/layout/four_channel_output_load_integration.json").read_text())
layout = pya.Layout()
source = root / manifest["source"]["gds"]
if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["source"]["gds_sha256"]:
    raise RuntimeError("refusing output integration on a non-current frozen V3 source")
layout.read(str(source))
source_top = layout.cell(manifest["source"]["top_cell"])
if source_top is None:
    raise RuntimeError("frozen V3 source top is missing")

block_record = manifest["output_load_block"]
block_path = root / block_record["gds"]
if hashlib.sha256(block_path.read_bytes()).hexdigest() != block_record["gds_sha256"]:
    raise RuntimeError("refusing changed output-load block")
layout.read(str(block_path))
block = layout.cell(block_record["top_cell"])
if block is None:
    raise RuntimeError("output-load block top is missing")

cap_record = manifest["compensation_cap_block"]
cap_path = root / cap_record["gds"]
if hashlib.sha256(cap_path.read_bytes()).hexdigest() != cap_record["gds_sha256"]:
    raise RuntimeError("refusing changed output compensation-capacitor block")
layout.read(str(cap_path))
cap_block = layout.cell(cap_record["top_cell"])
if cap_block is None:
    raise RuntimeError("output compensation-capacitor block top is missing")

top = layout.create_cell(manifest["top_cell"])
top.insert(pya.CellInstArray(source_top.cell_index(), pya.Trans()))
dx, dy = block_record["translation_um"]
top.insert(pya.CellInstArray(
    block.cell_index(),
    pya.Trans(round(dx / layout.dbu), round(dy / layout.dbu)),
))
cap_dx, cap_dy = cap_record["translation_um"]
top.insert(pya.CellInstArray(
    cap_block.cell_index(),
    pya.Trans(round(cap_dx / layout.dbu), round(cap_dy / layout.dbu)),
))

layers = {
    "metal2": layout.layer(pya.LayerInfo(69, 20)),
    "via2": layout.layer(pya.LayerInfo(69, 44)),
    "metal3": layout.layer(pya.LayerInfo(70, 20)),
    "via3": layout.layer(pya.LayerInfo(70, 44)),
    "metal4": layout.layer(pya.LayerInfo(71, 20)),
    "metal4_label": layout.layer(pya.LayerInfo(71, 5)),
}
dbu = layout.dbu


def box(layer_name, x1, y1, x2, y2):
    top.shapes(layers[layer_name]).insert(pya.Box(
        round(min(x1, x2) / dbu), round(min(y1, y2) / dbu),
        round(max(x1, x2) / dbu), round(max(y1, y2) / dbu),
    ))


def route(record):
    x1, y1 = record["from"]
    x2, y2 = record["to"]
    half = record["width_um"] / 2.0
    if x1 == x2:
        box(record["layer"], x1 - half, min(y1, y2) - half,
            x1 + half, max(y1, y2) + half)
    elif y1 == y2:
        box(record["layer"], min(x1, x2) - half, y1 - half,
            max(x1, x2) + half, y1 + half)
    else:
        raise RuntimeError("non-Manhattan output segment")


for record in manifest["routes"].values():
    for item in record["segments"]:
        route(item)
    for x, y in record["via2_points_um"]:
        box("metal2", x - 0.20, y - 0.20, x + 0.20, y + 0.20)
        box("via2", x - 0.10, y - 0.10, x + 0.10, y + 0.10)
        box("metal3", x - 0.31, y - 0.20, x + 0.31, y + 0.20)
    for x, y in record["via3_points_um"]:
        box("metal3", x - 0.31, y - 0.20, x + 0.31, y + 0.20)
        box("via3", x - 0.10, y - 0.10, x + 0.10, y + 0.10)
        box("metal4", x - 0.20, y - 0.20, x + 0.20, y + 0.20)
    pin_x, pin_y = record["analog_pin_um"]
    pin_w, pin_h = record["pad_size_um"]
    box("metal4", pin_x - pin_w / 2.0, pin_y - pin_h / 2.0,
        pin_x + pin_w / 2.0, pin_y + pin_h / 2.0)
    top.shapes(layers["metal4_label"]).insert(
        pya.Text(record["net"], pya.Trans(round(pin_x / dbu), round(pin_y / dbu)))
    )

for records in manifest["compensation_routes"].values():
    for record in records:
        route(record)

target = Path(str(output_gds)).resolve()
target.parent.mkdir(parents=True, exist_ok=True)
layout.write(str(target))
canonicalize(target)
print(target)
