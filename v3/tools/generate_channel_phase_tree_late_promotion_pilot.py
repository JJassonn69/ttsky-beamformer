#!/usr/bin/env python3
"""Generate the 15-cell late-promotion service channel plus eight phase trees."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import generate_channel_architecture_service_late_promotion_pilot as service_gen
import generate_channel_matrix_pilot as matrix_gen
import generate_channel_row_pilot as row_gen
import generate_vector_unit_pilot as unit_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3/layout/channel_matrix_late_promotion.json"
ARCHITECTURE = ROOT / "v3/layout/channel_routing_architecture.json"
UNIT = ROOT / "v3/layout/vector_unit_late_promotion.json"
CATALOG = ROOT / "v3/layout/channel_pcell_catalog.json"
TREES = ROOT / "v3/layout/group_phase_trees_late_promotion.json"
BUILD = ROOT / "build/v3/channel_phase_tree_late_promotion"
DEFAULT_OUTPUT = BUILD / "build.tcl"
TOP = "v3_channel_phase_tree_late_promotion"


def unique_geometry(
    tree: dict[str, Any],
) -> tuple[
    list[dict[str, Any]], list[list[float]], list[list[float]], list[dict[str, Any]],
]:
    segments = list(tree.get("fixed_segments", []))
    vias: list[list[float]] = []
    for path in tree["paths"]:
        segments.extend(path["segments"])
        vias.extend(path.get("via3_points", []))
    unique_segments: list[dict[str, Any]] = []
    segment_keys = set()
    for item in segments:
        key = (tuple(item["from"]), tuple(item["to"]), item["layer"], float(item["width_um"]))
        reverse = (key[1], key[0], key[2], key[3])
        if key in segment_keys or reverse in segment_keys:
            continue
        segment_keys.add(key)
        unique_segments.append(item)
    unique_vias: list[list[float]] = []
    via_keys = set()
    for item in vias:
        key = tuple(item)
        if key not in via_keys:
            via_keys.add(key)
            unique_vias.append(item)
    compact = list(tree.get("compact_corridor_via3_points", []))
    compact_keys = {tuple(item) for item in compact}
    unique_vias = [item for item in unique_vias if tuple(item) not in compact_keys]
    return unique_segments, unique_vias, compact, list(tree.get("junction_fill_rectangles", []))


def compact_corridor_via3_stack(point: list[float]) -> list[str]:
    """Via-3 landing fitted between the exact G8-LON M3/M4 obstacles.

    M3 is 0.40 x 0.60 um.  M4 shares the left edge of the existing 0.40 um
    trunk and extends only 0.02 um farther right, preserving 0.30 um spacing.
    Both landing areas exceed 0.24 um2 and retain >=0.07 um cut enclosure.
    """
    x, y = unit_gen.shifted(point)
    return [
        unit_gen.rect("metal3", x - 0.20, y - 0.30, x + 0.20, y + 0.30),
        unit_gen.rect("via3", x - 0.20, y - 0.20, x + 0.20, y + 0.20),
        unit_gen.rect("metal4", x - 0.25, y - 0.30, x + 0.17, y + 0.30),
    ]


def build_tcl(
    matrix: dict[str, Any], architecture: dict[str, Any], unit: dict[str, Any],
    catalog: dict[str, Any], trees: dict[str, Any],
) -> str:
    source = service_gen.build_tcl(matrix, architecture, unit, catalog)
    source = source.replace(
        "channel_architecture_service_late_promotion",
        "channel_phase_tree_late_promotion",
    )
    source = source.replace("v3_channel_architecture_service_late_promotion", TOP)
    source = source.replace(
        "V3_CHANNEL_ARCHITECTURE_SERVICE_LATE",
        "V3_CHANNEL_PHASE_TREE_LATE",
    )
    source = source.replace(
        "late-promotion channel-service pilot",
        "late-promotion obstacle-aware phase-tree pilot",
    )

    local_alias = re.compile(
        r"box [^\n]+\n"
        r"label u\d{2}_(?:lop|lon) center metal[34]\n"
        r"port make\nport class input\nport use signal\n"
        r"port connections n s e w\n?"
    )
    source, removed = local_alias.subn("", source)
    if removed != 30:
        raise RuntimeError(f"expected to remove 30 local phase ports, removed {removed}")

    commands: list[str] = []
    labels: list[str] = []
    for name in trees["tree_order"]:
        tree = trees["trees"][name]
        segments, vias, compact_vias, fills = unique_geometry(tree)
        commands.extend(row_gen.local_route(item) for item in segments)
        for at in vias:
            commands.extend(unit_gen.via3_stack(*unit_gen.shifted(at)))
        for at in compact_vias:
            commands.extend(compact_corridor_via3_stack(at))
        for item in fills:
            x0, y0 = unit_gen.shifted(item["bbox"][:2])
            x1, y1 = unit_gen.shifted(item["bbox"][2:])
            commands.append(unit_gen.rect(item["layer"], x0, y0, x1, y1))
        labels.append(matrix_gen.label(name, tree["root"], tree["root_layer"]))

    marker = "\nsave $TOP.mag\nwriteall force\n"
    if source.count(marker) != 1:
        raise RuntimeError("late service save marker changed")
    source = source.replace(marker, "\n" + "\n".join(commands + labels) + marker)

    # Preserve the service script's fail-fast behavior while giving this gate
    # its own stable marker names and feedback files.
    source = source.replace(
        "late-promotion channel-service pilot has DRC errors",
        "late-promotion phase-tree pilot has DRC errors",
    ).replace(
        "late-promotion channel-service pilot extraction produced feedback",
        "late-promotion phase-tree pilot extraction produced feedback",
    )
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--architecture", type=Path, default=ARCHITECTURE)
    parser.add_argument("--unit", type=Path, default=UNIT)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--trees", type=Path, default=TREES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    values = [json.loads(path.read_text(encoding="utf-8")) for path in (
        args.matrix, args.architecture, args.unit, args.catalog, args.trees,
    )]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_tcl(*values), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
