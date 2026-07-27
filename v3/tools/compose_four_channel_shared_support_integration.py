"""Compose the exact VCM/tail-bias blocks and their edge-routed common feeds."""

import hashlib
import json
import sys
from pathlib import Path

import pya


root = Path(str(project_root)).resolve()
sys.path.insert(0, str(root / "v3/tools"))
from canonicalize_gds_timestamps import canonicalize  # noqa: E402

manifest = json.loads((root / "v3/layout/four_channel_shared_support_integration.json").read_text())
layout = pya.Layout()
source = root / manifest["source"]["gds"]
if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["source"]["gds_sha256"]:
    raise RuntimeError("refusing support integration on a non-gated source GDS")
layout.read(str(source))
source_top = layout.cell(manifest["source"]["top_cell"])
if source_top is None:
    raise RuntimeError("support-tree source top is missing")

block_cells = {}
for name, record in manifest["blocks"].items():
    path = root / record["gds"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["gds_sha256"]:
        raise RuntimeError(f"refusing changed {name} support block")
    layout.read(str(path))
    cell = layout.cell(record["top_cell"])
    if cell is None:
        raise RuntimeError(f"missing {name} support top")
    block_cells[name] = cell

top = layout.create_cell(manifest["top_cell"])
top.insert(pya.CellInstArray(source_top.cell_index(), pya.Trans()))
for name, record in manifest["blocks"].items():
    dx, dy = record["translation_um"]
    top.insert(pya.CellInstArray(
        block_cells[name].cell_index(),
        pya.Trans(round(dx / layout.dbu), round(dy / layout.dbu)),
    ))

layers = {
    "metal3": layout.layer(pya.LayerInfo(70, 20)),
    "via3": layout.layer(pya.LayerInfo(70, 44)),
    "metal4": layout.layer(pya.LayerInfo(71, 20)),
}
dbu = layout.dbu


def box(layer_name, x1, y1, x2, y2):
    top.shapes(layers[layer_name]).insert(pya.Box(
        round(min(x1, x2) / dbu), round(min(y1, y2) / dbu),
        round(max(x1, x2) / dbu), round(max(y1, y2) / dbu),
    ))


for records in manifest["common_routes"].values():
    for record in records:
        x1, y1 = record["from"]
        x2, y2 = record["to"]
        half = record["width_um"] / 2.0
        if x1 == x2:
            box("metal3", x1 - half, min(y1, y2) - half, x1 + half, max(y1, y2) + half)
        elif y1 == y2:
            box("metal3", min(x1, x2) - half, y1 - half, max(x1, x2) + half, y1 + half)
        else:
            raise RuntimeError("non-Manhattan shared-support segment")
for x, y in manifest["via3_points_um"]:
    box("metal3", x - 0.31, y - 0.20, x + 0.31, y + 0.20)
    box("via3", x - 0.10, y - 0.10, x + 0.10, y + 0.10)
    box("metal4", x - 0.20, y - 0.20, x + 0.20, y + 0.20)

target = Path(str(output_gds)).resolve()
target.parent.mkdir(parents=True, exist_ok=True)
layout.write(str(target))
canonicalize(target)
print(target)
