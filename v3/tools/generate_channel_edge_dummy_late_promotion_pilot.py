#!/usr/bin/env python3
"""Add edge dummies and the enlarged guard to the frozen phase-tree channel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import generate_channel_phase_tree_late_promotion_pilot as phase_gen
import generate_vector_unit_pilot as unit_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3/layout/channel_matrix_late_promotion.json"
ARCHITECTURE = ROOT / "v3/layout/channel_routing_architecture.json"
UNIT = ROOT / "v3/layout/vector_unit_late_promotion.json"
CATALOG = ROOT / "v3/layout/channel_pcell_catalog.json"
TREES = ROOT / "v3/layout/group_phase_trees_late_promotion.json"
DUMMIES = ROOT / "v3/layout/channel_edge_dummies_late_promotion.json"
BUILD = ROOT / "build/v3/channel_edge_dummy_late_promotion"
DEFAULT_OUTPUT = BUILD / "build.tcl"
TOP = "v3_channel_edge_dummy_late_promotion"


def ground_dummy(component: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    points = {name: unit_gen.terminal(component, name) for name in ("D", "G", "S")}
    if "_TOP_" in component["name"]:
        centre_x = unit_gen.shifted(component["center"])[0]
        ds_points: dict[str, list[float]] = {}
        for name in ("D", "S"):
            point = list(points[name])
            point[0] += -0.02 if point[0] < centre_x else 0.02
            ds_points[name] = point
            commands.extend(unit_gen.contact_stack(*point))
        direction = -1.0 if "_PP_" in component["name"] else 1.0
        escape = [round(points["G"][0] + direction * 1.465, 6), points["G"][1]]
        commands.append(unit_gen.wire_h("metal1", points["G"][0], escape[0], points["G"][1], 0.23))
        commands.extend(unit_gen.contact_stack(*escape))
        commands.extend(unit_gen.compact_via2_tall_stack(*escape))
        near = min(ds_points.values(), key=lambda point: abs(point[0] - escape[0]))
        commands.append(unit_gen.wire_h("metal2", ds_points["D"][0], ds_points["S"][0], ds_points["D"][1], 0.30))
        commands.append(unit_gen.wire_h("metal2", near[0], escape[0], near[1], 0.30))
        commands.append(unit_gen.wire_v("metal2", escape[0], near[1], escape[1], 0.30))
        commands.append(unit_gen.wire_v("metal3", escape[0], near[1], escape[1], 0.40))
        return commands

    for point in points.values():
        commands.extend(unit_gen.contact_stack(*point))
    commands.append(unit_gen.wire_h("metal2", points["D"][0], points["S"][0], points["D"][1], 0.30))
    commands.append(unit_gen.wire_v("metal2", points["G"][0], points["D"][1], points["G"][1], 0.30))
    commands.extend(unit_gen.compact_via2_tall_stack(points["G"][0], points["D"][1]))
    return commands


def build_tcl(
    matrix: dict[str, Any], architecture: dict[str, Any], unit: dict[str, Any],
    catalog: dict[str, Any], trees: dict[str, Any], dummies: dict[str, Any],
) -> str:
    source = phase_gen.build_tcl(matrix, architecture, unit, catalog, trees)
    source = source.replace("channel_phase_tree_late_promotion", "channel_edge_dummy_late_promotion")
    source = source.replace("v3_channel_phase_tree_late_promotion", TOP)
    source = source.replace("V3_CHANNEL_PHASE_TREE_LATE", "V3_CHANNEL_EDGE_DUMMY_LATE")
    source = source.replace("late-promotion obstacle-aware phase-tree pilot", "late-promotion edge-dummy pilot")

    instances = "\n".join(unit_gen.pcell_command(item, catalog) for item in dummies["devices"])
    instance_marker = "\ncatch {cellname delete {(UNNAMED)}}\n"
    if source.count(instance_marker) != 1:
        raise RuntimeError("phase pilot instance marker changed")
    source = source.replace(instance_marker, f"\n{instances}{instance_marker}")

    active = matrix["active_array_bbox"]
    old_guard = [float(active[0]) + 0.05, 4.8, float(active[2]) - 0.05, 101.03]
    old_guard_text = (
        f"box {unit_gen.fmt(old_guard[0] + unit_gen.ORIGIN[0])}um "
        f"{unit_gen.fmt(old_guard[1] + unit_gen.ORIGIN[1])}um "
        f"{unit_gen.fmt(old_guard[2] + unit_gen.ORIGIN[0])}um "
        f"{unit_gen.fmt(old_guard[3] + unit_gen.ORIGIN[1])}um\n"
        "sky130::subconn_guard_draw"
    )
    guard = dummies["shared_guard_bbox"]
    new_guard_text = (
        f"box {unit_gen.fmt(guard[0] + unit_gen.ORIGIN[0])}um "
        f"{unit_gen.fmt(guard[1] + unit_gen.ORIGIN[1])}um "
        f"{unit_gen.fmt(guard[2] + unit_gen.ORIGIN[0])}um "
        f"{unit_gen.fmt(guard[3] + unit_gen.ORIGIN[1])}um\n"
        "sky130::subconn_guard_draw"
    )
    if source.count(old_guard_text) != 1:
        raise RuntimeError("frozen phase pilot guard geometry changed")
    source = source.replace(old_guard_text, new_guard_text)

    # The base channel places its substrate-contact stack and locali VGND
    # label on the old y=4.8 guard boundary.  Once the guard is enlarged that
    # tiny locali square would be floating (and violates the direct li-area
    # rule), so relocate the complete stack and label to the new boundary.
    old_ground = unit_gen.shifted([6.98, 4.8])
    new_ground = unit_gen.shifted([6.98, float(guard[1])])
    old_stack = "\n".join(
        unit_gen.li_to_m1_stack(*old_ground) + unit_gen.contact_stack(*old_ground)
    )
    new_stack = "\n".join(
        unit_gen.li_to_m1_stack(*new_ground) + unit_gen.contact_stack(*new_ground)
    )
    if source.count(old_stack) != 1:
        raise RuntimeError("base ground-boundary contact stack changed")
    source = source.replace(old_stack, new_stack)
    old_label = (
        f"box {unit_gen.fmt(old_ground[0] - 0.08)}um {unit_gen.fmt(old_ground[1] - 0.08)}um "
        f"{unit_gen.fmt(old_ground[0] + 0.08)}um {unit_gen.fmt(old_ground[1] + 0.08)}um\n"
        "label VGND center locali"
    )
    new_label = (
        f"box {unit_gen.fmt(new_ground[0] - 0.08)}um {unit_gen.fmt(new_ground[1] - 0.08)}um "
        f"{unit_gen.fmt(new_ground[0] + 0.08)}um {unit_gen.fmt(new_ground[1] + 0.08)}um\n"
        "label VGND center locali"
    )
    if source.count(old_label) != 1:
        raise RuntimeError("base ground-boundary label changed")
    source = source.replace(old_label, new_label)

    commands: list[str] = []
    for component in dummies["devices"]:
        commands.extend(ground_dummy(component))
    bus = dummies["ground_collection"]
    x0, x1 = (float(value) for value in bus["bus_x_range_um"])
    spine_x = float(bus["ground_spine_x_um"])
    for y in (float(bus["bottom_bus_y_um"]), float(bus["top_bus_y_um"])):
        ay = y + unit_gen.ORIGIN[1]
        commands.append(unit_gen.wire_h("metal3", x0 + unit_gen.ORIGIN[0], x1 + unit_gen.ORIGIN[0], ay, float(bus["width_um"])))
        for x in (x0, x1):
            point = [x + unit_gen.ORIGIN[0], ay]
            commands.extend(unit_gen.li_to_m1_stack(*point))
            commands.extend(unit_gen.contact_stack(*point))
            commands.extend(unit_gen.via2_stack(*point))
        commands.extend(unit_gen.via2_stack(*unit_gen.shifted([spine_x, y])))
    # Join the enlarged guard boundary and bottom bus to the already-proven
    # M2 ground spine.  The phase/service geometry above y=4.8 is untouched.
    commands.append(unit_gen.wire_v(
        "metal2", spine_x + unit_gen.ORIGIN[0],
        float(guard[1]) + unit_gen.ORIGIN[1], 4.8 + unit_gen.ORIGIN[1], 0.40,
    ))

    save_marker = "\nsave $TOP.mag\nwriteall force\n"
    if source.count(save_marker) != 1:
        raise RuntimeError("phase pilot save marker changed")
    source = source.replace(save_marker, "\n" + "\n".join(commands) + save_marker)

    old_feedback = '''puts "V3_CHANNEL_EDGE_DUMMY_LATE_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
if {$extraction_feedback != 0} {
    feedback save [file join $WORKDIR extraction_feedback.txt]
    error "late-promotion edge-dummy pilot extraction produced feedback"
}'''
    expected = len(dummies["devices"])
    new_feedback = f'''puts "V3_CHANNEL_EDGE_DUMMY_LATE_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
feedback save [file join $WORKDIR extraction_feedback.txt]
if {{$extraction_feedback != {expected}}} {{
    error "late-promotion edge-dummy extraction feedback differs from the {expected} intentional shorted-device markers"
}}
feedback clear'''
    if source.count(old_feedback) != 1:
        raise RuntimeError("phase pilot extraction feedback gate changed")
    return source.replace(old_feedback, new_feedback)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    paths = (MATRIX, ARCHITECTURE, UNIT, CATALOG, TREES, DUMMIES)
    values = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_tcl(*values), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
