#!/usr/bin/env python3
"""Prove that a later GDS still contains every frozen routing polygon.

Run with KLayout's Python interpreter and ``-rd baseline=...``,
``-rd candidate=...``, and ``-rd report=...``.  Added geometry is allowed;
removed or clipped M2/Via2/M3/Via3/M4 geometry is not.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pya


LAYERS = {
    "met2": (69, 20), "via2": (69, 44),
    "met3": (70, 20), "via3": (70, 44), "met4": (71, 20),
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


def region(layout: pya.Layout, top: pya.Cell, layer: tuple[int, int]) -> pya.Region:
    index = layout.find_layer(*layer)
    return pya.Region() if index is None else pya.Region(top.begin_shapes_rec(index)).merged()


def main() -> None:
    baseline_path = Path(required("baseline")).resolve()
    candidate_path = Path(required("candidate")).resolve()
    report_path = Path(required("report")).resolve()
    baseline_layout, baseline_top = load(baseline_path)
    candidate_layout, candidate_top = load(candidate_path)
    if abs(baseline_layout.dbu - candidate_layout.dbu) > 1e-15:
        raise RuntimeError("GDS database units differ")
    dbu2 = baseline_layout.dbu * baseline_layout.dbu
    layers: dict[str, object] = {}
    for name, layer in LAYERS.items():
        before = region(baseline_layout, baseline_top, layer)
        after = region(candidate_layout, candidate_top, layer)
        missing = before - after
        layers[name] = {
            "baseline_area_um2": round(before.area() * dbu2, 9),
            "candidate_area_um2": round(after.area() * dbu2, 9),
            "missing_area_um2": round(missing.area() * dbu2, 9),
            "missing_polygons": missing.count(),
        }
    passed = all(value["missing_polygons"] == 0 for value in layers.values())
    result = {
        "schema_version": 1,
        "status": "pass" if passed else "fail",
        "scope": "frozen M2/Via2/M3/Via3/M4 routing polygon containment",
        "baseline": {"path": str(baseline_path), "top": baseline_top.name, "sha256": sha256(baseline_path)},
        "candidate": {"path": str(candidate_path), "top": candidate_top.name, "sha256": sha256(candidate_path)},
        "layers": layers,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not passed:
        raise SystemExit(1)


main()
