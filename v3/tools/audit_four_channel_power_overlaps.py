#!/usr/bin/env python3
"""List every old/new same-metal overlap in the V3 shared-power candidate."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_gds_flat_rules import (  # noqa: E402
    MET2,
    MET3,
    MET4,
    flatten_orthogonal_rectangles,
    parse_gds,
)


LAYER = {"metal2": MET2, "metal3": MET3, "metal4": MET4}


def route_bbox(record: dict[str, Any]) -> list[float]:
    x1, y1 = record["from"]
    x2, y2 = record["to"]
    half = record["width_um"] / 2.0
    return [min(x1, x2) - half, min(y1, y2) - half, max(x1, x2) + half, max(y1, y2) + half]


def touches(first: list[float], second: tuple[float, float, float, float]) -> bool:
    return not (
        first[2] < second[0] or second[2] < first[0]
        or first[3] < second[1] or second[3] < first[1]
    )


def main() -> None:
    manifest_path = ROOT / "v3/layout/four_channel_power_integration.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_path = ROOT / manifest["source"]["gds"]
    structures, database_um = parse_gds(source_path)
    old = flatten_orthogonal_rectangles(
        structures, manifest["source"]["top_cell"], database_um, {MET2, MET3, MET4}
    )

    added: list[dict[str, Any]] = []
    for net, records in manifest["routes"].items():
        for record in records:
            added.append({
                "net": net,
                "owner": record["role"],
                "layer": record["layer"],
                "bbox_um": route_bbox(record),
            })
    for net, points in manifest["via2_points_um"].items():
        for index, (x, y) in enumerate(points):
            added.extend([
                {"net": net, "owner": f"via2_{index}_m2_landing", "layer": "metal2", "bbox_um": [x - 0.20, y - 0.20, x + 0.20, y + 0.20]},
                {"net": net, "owner": f"via2_{index}_m3_landing", "layer": "metal3", "bbox_um": [x - 0.31, y - 0.20, x + 0.31, y + 0.20]},
            ])
    for net, points in manifest["via3_points_um"].items():
        for index, (x, y) in enumerate(points):
            added.extend([
                {"net": net, "owner": f"via3_{index}_m3_landing", "layer": "metal3", "bbox_um": [x - 0.31, y - 0.20, x + 0.31, y + 0.20]},
                {"net": net, "owner": f"via3_{index}_m4_landing", "layer": "metal4", "bbox_um": [x - 0.20, y - 0.20, x + 0.20, y + 0.20]},
            ])
    for net, pin in manifest["external_power_pins"].items():
        added.append({"net": net, "owner": "external_pin", "layer": pin["layer"], "bbox_um": pin["bbox_um"]})

    report = []
    for item in added:
        overlaps = [list(rectangle) for rectangle in old[LAYER[item["layer"]]] if touches(item["bbox_um"], rectangle)]
        if overlaps:
            report.append({**item, "old_overlap_count": len(overlaps), "old_overlaps_um": overlaps})
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
