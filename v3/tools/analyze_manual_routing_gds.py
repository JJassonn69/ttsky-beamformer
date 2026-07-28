#!/usr/bin/env python3
"""Report exact geometry added to a manually edited V3 routing canvas.

Run this script with KLayout's embedded Python interpreter, for example::

    klayout -b -r v3/tools/analyze_manual_routing_gds.py \
      -rd base=clean.gds -rd edited=manual.gds -rd report=report.json

The report deliberately compares flattened conductor/cut geometry while also
listing direct top-cell text labels.  It does not claim electrical correctness;
the resulting geometry is consumed by the independent topology checks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pya


LAYER_NAMES = {
    (65, 20): "diff",
    (66, 20): "poly",
    (66, 44): "licon",
    (67, 20): "li1",
    (67, 44): "mcon",
    (68, 20): "met1",
    (68, 44): "via1",
    (69, 20): "met2",
    (69, 44): "via2",
    (70, 20): "met3",
    (70, 44): "via3",
    (71, 20): "met4",
}

CONDUCTOR_STACK = ("li1", "met1", "met2", "met3", "met4")
VIA_STACK = (
    ("mcon", "li1", "met1"),
    ("via1", "met1", "met2"),
    ("via2", "met2", "met3"),
    ("via3", "met3", "met4"),
)
NAME_TO_LAYER = {name: layer for layer, name in LAYER_NAMES.items()}


def require_variable(name: str) -> str:
    value = globals().get(name)
    if not value:
        raise RuntimeError(f"missing -rd {name}=...")
    return str(value)


def load(path: str) -> tuple[pya.Layout, pya.Cell]:
    layout = pya.Layout()
    layout.read(path)
    tops = list(layout.top_cells())
    if len(tops) != 1:
        raise RuntimeError(f"{path}: expected one top cell, found {[c.name for c in tops]}")
    return layout, tops[0]


def region_for(layout: pya.Layout, top: pya.Cell, layer: tuple[int, int]) -> pya.Region:
    index = layout.find_layer(layer[0], layer[1])
    if index is None:
        return pya.Region()
    return pya.Region(top.begin_shapes_rec(index))


def polygon_record(polygon: pya.Polygon, dbu: float) -> dict[str, object]:
    box = polygon.bbox()
    return {
        "bbox_um": [round(value * dbu, 6) for value in (box.left, box.bottom, box.right, box.top)],
        "area_um2": round(polygon.area() * dbu * dbu, 9),
        "vertices": polygon.num_points_hull(),
    }


def region_records(region: pya.Region, dbu: float) -> list[dict[str, object]]:
    return sorted(
        (polygon_record(polygon, dbu) for polygon in region.each_merged()),
        key=lambda item: tuple(item["bbox_um"]),
    )


def direct_texts(layout: pya.Layout, top: pya.Cell) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for info in layout.layer_infos():
        index = layout.find_layer(info.layer, info.datatype)
        if index is None:
            continue
        for shape in top.shapes(index).each():
            if not shape.is_text():
                continue
            text = shape.text
            result.append({
                "text": text.string,
                "layer": [info.layer, info.datatype],
                "layer_name": LAYER_NAMES.get((info.layer, info.datatype), "other"),
                "origin_um": [round(text.x * layout.dbu, 6), round(text.y * layout.dbu, 6)],
            })
    return sorted(result, key=lambda item: (item["origin_um"][1], item["origin_um"][0], item["text"]))


def connectivity_groups(
    layout: pya.Layout,
    top: pya.Cell,
    reference_labels: list[dict[str, object]],
) -> dict[str, object]:
    """Map reference label locations onto flattened edited conductors.

    The clean-canvas labels are used as immutable electrical access points, so
    moving a text object during manual editing cannot make a broken route look
    connected.  Results group labels that are physically joined through the
    LI1-to-M4 stack.
    """

    polygons: dict[str, list[pya.Polygon]] = {}
    for name in CONDUCTOR_STACK:
        polygons[name] = list(
            region_for(layout, top, NAME_TO_LAYER[name]).merged().each()
        )

    nodes: list[tuple[str, int]] = [
        (name, index)
        for name in CONDUCTOR_STACK
        for index in range(len(polygons[name]))
    ]
    node_index = {node: index for index, node in enumerate(nodes)}
    parent = list(range(len(nodes)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = root(first), root(second)
        if first_root != second_root:
            parent[second_root] = first_root

    for via_name, lower_name, upper_name in VIA_STACK:
        via_region = region_for(layout, top, NAME_TO_LAYER[via_name])
        for via_polygon in via_region.each():
            via_box = via_polygon.bbox()
            lower_hits = [
                index for index, polygon in enumerate(polygons[lower_name])
                if polygon.bbox().overlaps(via_box)
                and not (pya.Region(polygon) & pya.Region(via_polygon)).is_empty()
            ]
            upper_hits = [
                index for index, polygon in enumerate(polygons[upper_name])
                if polygon.bbox().overlaps(via_box)
                and not (pya.Region(polygon) & pya.Region(via_polygon)).is_empty()
            ]
            for lower_index in lower_hits:
                for upper_index in upper_hits:
                    union(
                        node_index[(lower_name, lower_index)],
                        node_index[(upper_name, upper_index)],
                    )

    labels_by_root: dict[int, list[str]] = {}
    unmapped: list[str] = []
    tolerance = 2  # database units; tolerates text-origin rounding only
    for label in reference_labels:
        layer_number = int(label["layer"][0])
        conductor = {
            67: "li1", 68: "met1", 69: "met2", 70: "met3", 71: "met4",
        }.get(layer_number)
        if conductor is None:
            continue
        x = round(float(label["origin_um"][0]) / layout.dbu)
        y = round(float(label["origin_um"][1]) / layout.dbu)
        probe = pya.Box(x - tolerance, y - tolerance, x + tolerance, y + tolerance)
        hits = [
            index for index, polygon in enumerate(polygons[conductor])
            if polygon.bbox().overlaps(probe)
            and not (pya.Region(polygon) & pya.Region(probe)).is_empty()
        ]
        if len(hits) != 1:
            unmapped.append(str(label["text"]))
            continue
        component_root = root(node_index[(conductor, hits[0])])
        labels_by_root.setdefault(component_root, []).append(str(label["text"]))

    group_records: list[dict[str, object]] = []
    for component_root, names in labels_by_root.items():
        metal_bboxes: dict[str, list[list[float]]] = {}
        for (conductor, polygon_index), index in node_index.items():
            if root(index) != component_root:
                continue
            box = polygons[conductor][polygon_index].bbox()
            metal_bboxes.setdefault(conductor, []).append([
                round(value * layout.dbu, 6)
                for value in (box.left, box.bottom, box.right, box.top)
            ])
        group_records.append({
            "labels": sorted(names),
            "metal_bboxes_um": metal_bboxes,
        })
    group_records.sort(key=lambda entry: (entry["labels"][0], len(entry["labels"])))
    return {
        "groups": [entry["labels"] for entry in group_records],
        "group_details": group_records,
        "unmapped_reference_labels": sorted(unmapped),
        "conductor_component_counts": {
            name: len(polygons[name]) for name in CONDUCTOR_STACK
        },
    }


def main() -> None:
    base_path = require_variable("base")
    edited_path = require_variable("edited")
    report_path = Path(require_variable("report"))
    base_layout, base_top = load(base_path)
    edited_layout, edited_top = load(edited_path)
    if abs(base_layout.dbu - edited_layout.dbu) > 1e-15:
        raise RuntimeError("base and edited layouts use different database units")

    changes: dict[str, object] = {}
    for layer, name in LAYER_NAMES.items():
        base_region = region_for(base_layout, base_top, layer)
        edited_region = region_for(edited_layout, edited_top, layer)
        added = edited_region - base_region
        removed = base_region - edited_region
        if added.is_empty() and removed.is_empty():
            continue
        changes[name] = {
            "layer": list(layer),
            "added": region_records(added, edited_layout.dbu),
            "removed": region_records(removed, edited_layout.dbu),
            "added_area_um2": round(added.area() * edited_layout.dbu**2, 9),
            "removed_area_um2": round(removed.area() * edited_layout.dbu**2, 9),
        }

    base_texts = direct_texts(base_layout, base_top)
    edited_texts = direct_texts(edited_layout, edited_top)
    result = {
        "base": str(Path(base_path).resolve()),
        "edited": str(Path(edited_path).resolve()),
        "top": edited_top.name,
        "dbu_um": edited_layout.dbu,
        "changes": changes,
        "base_top_texts": base_texts,
        "edited_top_texts": edited_texts,
        "edited_connectivity_at_base_labels": connectivity_groups(
            edited_layout, edited_top, base_texts
        ),
        "edited_connectivity_at_edited_labels": connectivity_groups(
            edited_layout, edited_top, edited_texts
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "top": result["top"],
        "changed_layers": list(changes),
        "change_summary": {
            name: {
                "added_polygons": len(entry["added"]),
                "removed_polygons": len(entry["removed"]),
                "added_area_um2": entry["added_area_um2"],
                "removed_area_um2": entry["removed_area_um2"],
            }
            for name, entry in changes.items()
        },
        "report": str(report_path),
    }, indent=2))


main()
