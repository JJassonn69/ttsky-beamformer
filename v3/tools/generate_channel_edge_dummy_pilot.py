#!/usr/bin/env python3
"""Generate the eight-tree V3 channel with exact top/bottom edge dummies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import generate_channel_phase_tree_pilot as phase_gen
import generate_channel_row_pilot as row_gen
import generate_vector_unit_pilot as unit_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3" / "layout" / "channel_matrix_placement.json"
UNIT = ROOT / "v3" / "layout" / "vector_unit_placement.json"
CATALOG = ROOT / "v3" / "layout" / "channel_pcell_catalog.json"
TREES = ROOT / "v3" / "layout" / "group_phase_trees.json"
DUMMIES = ROOT / "v3" / "layout" / "channel_edge_dummies.json"
DEFAULT_OUTPUT = ROOT / "build" / "v3" / "channel_edge_dummy_pilot" / "build.tcl"
TOP = "v3_channel_edge_dummy_pilot"


def ground_dummy(component: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    points = {
        name: unit_gen.terminal(component, name)
        for name in ("D", "G", "S")
    }
    if "_TOP_" in component["name"]:
        # Use the already-proven switch access pattern: D/S Via-1 landings
        # spread outward by 20 nm and the tight gate escapes on M1 before it
        # is promoted.  Direct-GDS MR_met1.SP.1 catches a raw in-place gate
        # promotion even though Magic's native DRC does not.
        centre_x = unit_gen.shifted(component["center"])[0]
        ds_points: dict[str, list[float]] = {}
        for name in ("D", "S"):
            point = list(points[name])
            point[0] += -0.02 if point[0] < centre_x else 0.02
            ds_points[name] = point
            commands.extend(unit_gen.contact_stack(*point))
        direction = -1.0 if "_PP_" in component["name"] else 1.0
        escape = [round(points["G"][0] + direction * 1.465, 6), points["G"][1]]
        commands.append(unit_gen.wire_h(
            "metal1", points["G"][0], escape[0], points["G"][1], 0.23,
        ))
        commands.extend(unit_gen.contact_stack(*escape))
        commands.extend(unit_gen.compact_via2_tall_stack(*escape))
        near = min(ds_points.values(), key=lambda point: abs(point[0] - escape[0]))
        commands.append(unit_gen.wire_h(
            "metal2", ds_points["D"][0], ds_points["S"][0],
            ds_points["D"][1], 0.30,
        ))
        commands.append(unit_gen.wire_h(
            "metal2", near[0], escape[0], near[1], 0.30,
        ))
        commands.append(unit_gen.wire_v(
            "metal2", escape[0], near[1], escape[1], 0.30,
        ))
        commands.append(unit_gen.wire_v(
            "metal3", escape[0], near[1], escape[1], 0.40,
        ))
        return commands

    for point in points.values():
        commands.extend(unit_gen.contact_stack(*point))
    # Join the three terminals locally on M2.  The D-S bar passes through the
    # gate x coordinate; a short vertical leg reaches the gate access.
    commands.append(unit_gen.wire_h(
        "metal2", points["D"][0], points["S"][0], points["D"][1], 0.30,
    ))
    commands.append(unit_gen.wire_v(
        "metal2", points["G"][0], points["D"][1], points["G"][1], 0.30,
    ))
    commands.extend(unit_gen.compact_via2_tall_stack(points["G"][0], points["D"][1]))
    return commands


def build_tcl(
    matrix: dict[str, Any], unit: dict[str, Any], catalog: dict[str, Any],
    trees: dict[str, Any], dummies: dict[str, Any],
) -> str:
    source = phase_gen.build_tcl(matrix, unit, catalog, trees)
    source = source.replace("channel_phase_tree_pilot", "channel_edge_dummy_pilot")
    source = source.replace("v3_channel_phase_tree_pilot", TOP)
    source = source.replace("V3_CHANNEL_PHASE_TREE", "V3_CHANNEL_EDGE_DUMMY")
    source = source.replace("channel-phase-tree pilot", "channel-edge-dummy pilot")

    instances = "\n".join(unit_gen.pcell_command(item, catalog) for item in dummies["devices"])
    instance_marker = "\ncatch {cellname delete {(UNNAMED)}}\n"
    if source.count(instance_marker) != 1:
        raise RuntimeError("phase pilot instance marker changed")
    source = source.replace(instance_marker, f"\n{instances}{instance_marker}")

    # Replace the matrix-only guard with the exact dummy-inclusive guard.
    old_guard = "box 20.44um 27.2um 35.3um 105.03um\nsky130::subconn_guard_draw"
    guard = dummies["shared_guard_bbox"]
    new_guard = (
        f"box {unit_gen.fmt(guard[0] + unit_gen.ORIGIN[0])}um "
        f"{unit_gen.fmt(guard[1] + unit_gen.ORIGIN[1])}um "
        f"{unit_gen.fmt(guard[2] + unit_gen.ORIGIN[0])}um "
        f"{unit_gen.fmt(guard[3] + unit_gen.ORIGIN[1])}um\n"
        "sky130::subconn_guard_draw"
    )
    if source.count(old_guard) != 1:
        raise RuntimeError("matrix guard geometry changed")
    source = source.replace(old_guard, new_guard)

    commands: list[str] = []
    for component in dummies["devices"]:
        commands.extend(ground_dummy(component))

    bus = dummies["ground_collection"]
    x0, x1 = bus["bus_x_range_um"]
    for y in (bus["bottom_bus_y_um"], bus["top_bus_y_um"]):
        ay = y + unit_gen.ORIGIN[1]
        commands.append(unit_gen.wire_h(
            "metal3", x0 + unit_gen.ORIGIN[0], x1 + unit_gen.ORIGIN[0],
            ay, bus["width_um"],
        ))
        for x in (x0, x1):
            point = [x + unit_gen.ORIGIN[0], ay]
            commands.extend(unit_gen.li_to_m1_stack(*point))
            commands.extend(unit_gen.contact_stack(*point))
            commands.extend(unit_gen.via2_stack(*point))
    commands_text = "\n".join(commands)

    save_marker = "\nsave $TOP.mag\nwriteall force\n"
    if source.count(save_marker) != 1:
        raise RuntimeError("phase pilot save marker changed")
    source = source.replace(save_marker, f"\n{commands_text}{save_marker}")
    # An NFET whose D/G/S are intentionally the same net is no longer a
    # three-terminal device to Magic's extractor.  It emits one classified
    # "device missing 1 terminal" feedback marker per inert dummy.  Require
    # exactly that population; any additional extraction marker remains fatal.
    old_feedback_gate = '''puts "V3_CHANNEL_EDGE_DUMMY_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
if {$extraction_feedback != 0} {
    feedback save [file join $WORKDIR extraction_feedback.txt]
    error "channel-edge-dummy pilot extraction produced feedback"
}'''
    expected = len(dummies["devices"])
    new_feedback_gate = f'''puts "V3_CHANNEL_EDGE_DUMMY_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
feedback save [file join $WORKDIR extraction_feedback.txt]
if {{$extraction_feedback != {expected}}} {{
    error "channel-edge-dummy pilot extraction feedback differs from the {expected} intentional shorted-device markers"
}}
feedback clear'''
    if source.count(old_feedback_gate) != 1:
        raise RuntimeError("phase pilot extraction gate changed")
    return source.replace(old_feedback_gate, new_feedback_gate)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--unit", type=Path, default=UNIT)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--trees", type=Path, default=TREES)
    parser.add_argument("--dummies", type=Path, default=DUMMIES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    values = [json.loads(path.read_text(encoding="utf-8")) for path in (
        args.matrix, args.unit, args.catalog, args.trees, args.dummies,
    )]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_tcl(*values), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
