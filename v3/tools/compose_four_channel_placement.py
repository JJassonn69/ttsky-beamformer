"""Compose four immutable copies of the frozen channel using KLayout Python."""

import hashlib
import json
from pathlib import Path

import pya


root = Path(str(project_root)).resolve()
manifest_path = root / "v3/layout/four_channel_placement.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
source = root / manifest["frozen_macro"]["gds"]
observed = hashlib.sha256(source.read_bytes()).hexdigest()
if observed != manifest["frozen_macro"]["gds_sha256"]:
    raise RuntimeError("refusing to compose a non-current channel macro")

layout = pya.Layout()
layout.read(str(source))
macro = layout.cell(manifest["frozen_macro"]["top_cell"])
if macro is None:
    raise RuntimeError("frozen channel top cell is missing")
top = layout.create_cell(manifest["top_cell"])
for instance in manifest["instances"]:
    if instance["orientation"] != "R0":
        raise RuntimeError("only the reviewed R0 four-column placement is allowed")
    x, y = instance["translation_um"]
    top.insert(
        pya.CellInstArray(
            macro.cell_index(),
            pya.Trans(round(x / layout.dbu), round(y / layout.dbu)),
        )
    )

target = Path(str(output_gds)).resolve()
target.parent.mkdir(parents=True, exist_ok=True)
layout.write(str(target))
print(target)
