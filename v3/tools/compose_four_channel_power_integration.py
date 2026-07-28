"""Compose shared VDPWR/VGND routing onto the frozen output-integrated V3 top."""

import hashlib
import json
import sys
from pathlib import Path

import pya


root = Path(str(project_root)).resolve()
sys.path.insert(0, str(root / "v3/tools"))
from canonicalize_gds_timestamps import canonicalize  # noqa: E402

manifest = json.loads((root / "v3/layout/four_channel_power_integration.json").read_text())
source_path = root / manifest["source"]["gds"]
if hashlib.sha256(source_path.read_bytes()).hexdigest() != manifest["source"]["gds_sha256"]:
    raise RuntimeError("refusing power integration on a non-current frozen V3 source")

layout = pya.Layout()
layout.read(str(source_path))
source = layout.cell(manifest["source"]["top_cell"])
if source is None:
    raise RuntimeError("frozen V3 source top is missing")
top = layout.create_cell(manifest["top_cell"])
top.insert(pya.CellInstArray(source.cell_index(), pya.Trans()))

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
        box(record["layer"], x1 - half, min(y1, y2) - half, x1 + half, max(y1, y2) + half)
    elif y1 == y2:
        box(record["layer"], min(x1, x2) - half, y1 - half, max(x1, x2) + half, y1 + half)
    else:
        raise RuntimeError("non-Manhattan power route")


def via2(x, y):
    box("metal2", x - 0.20, y - 0.20, x + 0.20, y + 0.20)
    box("via2", x - 0.10, y - 0.10, x + 0.10, y + 0.10)
    box("metal3", x - 0.31, y - 0.20, x + 0.31, y + 0.20)


def via3(x, y):
    box("metal3", x - 0.31, y - 0.20, x + 0.31, y + 0.20)
    box("via3", x - 0.10, y - 0.10, x + 0.10, y + 0.10)
    box("metal4", x - 0.20, y - 0.20, x + 0.20, y + 0.20)


for pin_name, pin in manifest["external_power_pins"].items():
    box(pin["layer"], *pin["bbox_um"])
    x, y = pin["label_at_um"]
    top.shapes(layers["metal4_label"]).insert(pya.Text(pin_name, pya.Trans(round(x / dbu), round(y / dbu))))

for records in manifest["routes"].values():
    for record in records:
        route(record)
for points in manifest["via2_points_um"].values():
    for x, y in points:
        via2(x, y)
for points in manifest["via3_points_um"].values():
    for x, y in points:
        via3(x, y)

target = Path(str(output_gds)).resolve()
target.parent.mkdir(parents=True, exist_ok=True)
layout.write(str(target))
canonicalize(target)
print(target)
