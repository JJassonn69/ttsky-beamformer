#!/usr/bin/env python3
"""Compare routing-resource geometry between baseline and late-promotion rows.

Run with KLayout's Python interpreter using ``-rd baseline=...``,
``-rd candidate=...``, and ``-rd report=...``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pya


LAYERS = {
    "met1": (68, 20), "via1": (68, 44),
    "met2": (69, 20), "via2": (69, 44),
    "met3": (70, 20), "via3": (70, 44),
    "met4": (71, 20),
}


def required(name: str) -> str:
    value = globals().get(name)
    if not value:
        raise RuntimeError(f"missing -rd {name}=...")
    return str(value)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> tuple[pya.Layout, pya.Cell]:
    layout = pya.Layout()
    layout.read(str(path))
    tops = list(layout.top_cells())
    if len(tops) != 1:
        raise RuntimeError(f"{path} has {len(tops)} top cells")
    return layout, tops[0]


def layer_stats(layout: pya.Layout, top: pya.Cell, layer: tuple[int, int]) -> dict[str, object]:
    index = layout.find_layer(*layer)
    region = pya.Region() if index is None else pya.Region(top.begin_shapes_rec(index)).merged()
    polygons = list(region.each())
    return {
        "area_um2": round(region.area() * layout.dbu * layout.dbu, 9),
        "merged_polygons": len(polygons),
    }


def main() -> None:
    baseline_path = Path(required("baseline")).resolve()
    candidate_path = Path(required("candidate")).resolve()
    report_path = Path(required("report")).resolve()
    baseline_layout, baseline_top = load(baseline_path)
    candidate_layout, candidate_top = load(candidate_path)
    if abs(baseline_layout.dbu - candidate_layout.dbu) > 1e-15:
        raise RuntimeError("GDS database units differ")
    before = {
        name: layer_stats(baseline_layout, baseline_top, layer) for name, layer in LAYERS.items()
    }
    after = {
        name: layer_stats(candidate_layout, candidate_top, layer) for name, layer in LAYERS.items()
    }
    delta = {
        name: {
            "area_um2": round(after[name]["area_um2"] - before[name]["area_um2"], 9),
            "merged_polygons": after[name]["merged_polygons"] - before[name]["merged_polygons"],
        }
        for name in LAYERS
    }
    result = {
        "schema_version": 1,
        "scope": "direct flattened-GDS conductor/cut comparison; lower-layer area includes the late-row pilot's intentionally enlarged guard",
        "baseline": {"path": str(baseline_path), "top": baseline_top.name, "sha256": sha256(baseline_path)},
        "candidate": {"path": str(candidate_path), "top": candidate_top.name, "sha256": sha256(candidate_path)},
        "layers": {name: {"baseline": before[name], "candidate": after[name], "delta": delta[name]} for name in LAYERS},
        "designed_analog_route_change": {
            "baseline_m4_centerline_um": 79.275,
            "baseline_m3_centerline_um": 41.76,
            "candidate_m1_centerline_um": 119.445,
            "candidate_m2_drop_centerline_um": 11.25,
            "analog_via_delta": {"via1": 12, "via2": -12, "via3": -18},
            "note": "centerline and via figures are exact from the three-unit generators; GDS areas also contain unchanged devices, guard, output, ground, and phase geometry",
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


main()
