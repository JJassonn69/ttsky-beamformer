"""Draw the matched four-phase distribution using KLayout Python."""

import hashlib
import json
from pathlib import Path

import pya


root = Path(str(project_root)).resolve()
manifest = json.loads((root / "v3/layout/four_channel_phase_distribution.json").read_text())
source = root / manifest["source"]["gds"]
if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["source"]["gds_sha256"]:
    raise RuntimeError("refusing phase composition on a non-gated source GDS")

layout = pya.Layout()
layout.read(str(source))
source_top = layout.cell(manifest["source"]["top_cell"])
if source_top is None:
    raise RuntimeError("output-collector source top is missing")
top = layout.create_cell(manifest["top_cell"])
top.insert(pya.CellInstArray(source_top.cell_index(), pya.Trans()))
layers = {
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
    if x1 != x2 and y1 != y2:
        raise RuntimeError("non-Manhattan phase segment")
    box(record["layer"], x1 - half, y1 - half, x2 + half, y2 + half)


for tree in manifest["trees"].values():
    for record in tree["segments"]:
        route(record)
    for x, y in tree["via3_points_um"]:
        box("metal3", x - 0.31, y - 0.20, x + 0.31, y + 0.20)
        box("via3", x - 0.10, y - 0.10, x + 0.10, y + 0.10)
        box("metal4", x - 0.20, y - 0.20, x + 0.20, y + 0.20)
    root_x, root_y = tree["root_um"]
    top.shapes(layers["metal4_label"]).insert(
        pya.Text(tree["net"], pya.Trans(round(root_x / dbu), round(root_y / dbu)))
    )

target = Path(str(output_gds)).resolve()
target.parent.mkdir(parents=True, exist_ok=True)
layout.write(str(target))
print(target)
