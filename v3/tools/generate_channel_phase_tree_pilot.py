#!/usr/bin/env python3
"""Generate the exact 15-unit channel plus all eight group phase trees."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import generate_channel_matrix_pilot as matrix_gen
import generate_channel_row_pilot as row_gen
import generate_vector_unit_pilot as unit_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3" / "layout" / "channel_matrix_placement.json"
UNIT = ROOT / "v3" / "layout" / "vector_unit_placement.json"
CATALOG = ROOT / "v3" / "layout" / "channel_pcell_catalog.json"
TREES = ROOT / "v3" / "layout" / "group_phase_trees.json"
DEFAULT_OUTPUT = ROOT / "build" / "v3" / "channel_phase_tree_pilot" / "build.tcl"
TOP = "v3_channel_phase_tree_pilot"


def all_geometry(
    tree: dict[str, Any]
) -> tuple[
    list[dict[str, Any]], list[list[float]], list[list[float]],
    list[list[float]], list[list[float]],
]:
    segments = list(tree.get("fixed_segments", []))
    via2s: list[list[float]] = []
    via3s: list[list[float]] = []
    compact_via2s: list[list[float]] = []
    compact_via3s: list[list[float]] = []
    for path in tree["paths"]:
        segments.extend(path["segments"])
        via2s.extend(path.get("via2_points", []))
        via3s.extend(path["via3_points"])
        compact_via2s.extend(path.get("compact_via2_points", []))
        compact_via3s.extend(path.get("compact_via3_points", []))
    unique_segments: list[dict[str, Any]] = []
    seen_segments = set()
    for item in segments:
        key = (
            tuple(item["from"]), tuple(item["to"]), item["layer"],
            float(item["width_um"]),
        )
        reverse = (key[1], key[0], key[2], key[3])
        if key in seen_segments or reverse in seen_segments:
            continue
        seen_segments.add(key)
        unique_segments.append(item)
    def unique(values: list[list[float]]) -> list[list[float]]:
        output = []
        seen = set()
        for item in values:
            key = tuple(item)
            if key not in seen:
                seen.add(key)
                output.append(item)
        return output
    return (
        unique_segments, unique(via2s), unique(via3s),
        unique(compact_via2s), unique(compact_via3s),
    )


def compact_via3_tall_stack(x: float, y: float) -> list[str]:
    """Via-3 with an asymmetric 0.60 x 0.40 um connected M3 landing."""
    return [
        unit_gen.rect("metal3", x - 0.20, y - 0.20, x + 0.40, y + 0.20),
        unit_gen.rect("via3", x - 0.20, y - 0.20, x + 0.20, y + 0.20),
        unit_gen.rect("metal4", x - 0.15, y - 0.20, x + 0.15, y + 0.20),
    ]


def compact_via2_asymmetric_stack(x: float, y: float) -> list[str]:
    """Via-2 sharing the same right-extended M3 landing as compact Via-3."""
    return [
        unit_gen.rect("metal2", x - 0.15, y - 0.15, x + 0.15, y + 0.15),
        unit_gen.rect("via2", x - 0.20, y - 0.20, x + 0.20, y + 0.20),
        unit_gen.rect("metal3", x - 0.20, y - 0.20, x + 0.40, y + 0.20),
    ]


def build_tcl(
    matrix: dict[str, Any], unit: dict[str, Any], catalog: dict[str, Any],
    phase_trees: dict[str, Any],
) -> str:
    source = matrix_gen.build_tcl(matrix, unit, catalog)
    source = source.replace("channel_matrix_pilot", "channel_phase_tree_pilot")
    source = source.replace("v3_channel_matrix_pilot", TOP)
    source = source.replace("V3_CHANNEL_MATRIX", "V3_CHANNEL_PHASE_TREE")
    source = source.replace("channel-matrix pilot", "channel-phase-tree pilot")

    # Unit-local LO labels are useful in the matrix-only extraction but become
    # conflicting aliases once group trees intentionally join those leaves.
    local_label = re.compile(
        r"box [^\n]+\n"
        r"label u\d{2}_(?:lop|lon) center metal[34]\n"
        r"port make\nport class input\nport use signal\n"
        r"port connections n s e w\n?"
    )
    source, removed = local_label.subn("", source)
    if removed != 30:
        raise RuntimeError(f"expected to remove 30 unit-local LO ports, removed {removed}")

    commands: list[str] = []
    labels: list[str] = []
    for name in phase_trees["tree_order"]:
        tree = phase_trees["trees"][name]
        segments, via2s, via3s, compact_via2s, compact_via3s = all_geometry(tree)
        commands.extend(row_gen.local_route(item) for item in segments)
        for at in via2s:
            commands.extend(unit_gen.via2_stack(*unit_gen.shifted(at)))
        for at in via3s:
            commands.extend(unit_gen.via3_stack(*unit_gen.shifted(at)))
        for at in compact_via2s:
            commands.extend(compact_via2_asymmetric_stack(*unit_gen.shifted(at)))
        for at in compact_via3s:
            commands.extend(compact_via3_tall_stack(*unit_gen.shifted(at)))
        labels.append(matrix_gen.label(name, tree["root"], tree["root_layer"]))

    insertion = "\n".join(commands + labels)
    marker = "\nsave $TOP.mag\nwriteall force\n"
    if source.count(marker) != 1:
        raise RuntimeError("matrix template save marker changed")
    return source.replace(marker, f"\n{insertion}\n{marker}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--unit", type=Path, default=UNIT)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--trees", type=Path, default=TREES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    values = [json.loads(path.read_text(encoding="utf-8")) for path in (
        args.matrix, args.unit, args.catalog, args.trees,
    )]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_tcl(*values), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
