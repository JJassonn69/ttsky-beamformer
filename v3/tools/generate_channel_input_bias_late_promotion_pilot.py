#!/usr/bin/env python3
"""Connect the compact bias resistor to the late-promotion sig/ref spines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import generate_channel_edge_dummy_late_promotion_pilot as edge_gen
import generate_channel_input_bias_pilot as legacy_bias_gen
import generate_channel_architecture_service_late_promotion_pilot as service_gen
import generate_vector_unit_pilot as unit_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3/layout/channel_matrix_late_promotion.json"
ARCHITECTURE = ROOT / "v3/layout/channel_routing_architecture.json"
UNIT = ROOT / "v3/layout/vector_unit_late_promotion.json"
CATALOG = ROOT / "v3/layout/channel_pcell_catalog.json"
TREES = ROOT / "v3/layout/group_phase_trees_late_promotion.json"
DUMMIES = ROOT / "v3/layout/channel_edge_dummies_late_promotion.json"
BIAS_CATALOG = ROOT / "v3/layout/input_bias_pcell_catalog.json"
BIAS = ROOT / "v3/layout/compact_input_bias_late_promotion.json"
BUILD = ROOT / "build/v3/channel_input_bias_late_promotion"
DEFAULT_OUTPUT = BUILD / "build.tcl"
TOP = "v3_channel_input_bias_late_promotion"


def build_tcl(
    matrix: dict[str, Any], architecture: dict[str, Any], unit: dict[str, Any],
    channel_catalog: dict[str, Any], trees: dict[str, Any], dummies: dict[str, Any],
    bias_catalog: dict[str, Any], bias: dict[str, Any],
) -> str:
    source = edge_gen.build_tcl(matrix, architecture, unit, channel_catalog, trees, dummies)
    source = source.replace("channel_edge_dummy_late_promotion", "channel_input_bias_late_promotion")
    source = source.replace("v3_channel_edge_dummy_late_promotion", TOP)
    source = source.replace("V3_CHANNEL_EDGE_DUMMY_LATE", "V3_CHANNEL_INPUT_BIAS_LATE")
    source = source.replace("late-promotion edge-dummy pilot", "late-promotion connected input-bias pilot")

    instance_marker = "\ncatch {cellname delete {(UNNAMED)}}\n"
    if source.count(instance_marker) != 1:
        raise RuntimeError("edge pilot instance marker changed")
    resistor = legacy_bias_gen.resistor_pcell(bias["resistor"], bias_catalog)
    source = source.replace(instance_marker, f"\n{resistor}{instance_marker}")

    old_guard = dummies["shared_guard_bbox"]
    new_guard = bias["shared_guard_bbox"]
    old_guard_text = (
        f"box {unit_gen.fmt(old_guard[0] + unit_gen.ORIGIN[0])}um "
        f"{unit_gen.fmt(old_guard[1] + unit_gen.ORIGIN[1])}um "
        f"{unit_gen.fmt(old_guard[2] + unit_gen.ORIGIN[0])}um "
        f"{unit_gen.fmt(old_guard[3] + unit_gen.ORIGIN[1])}um\n"
        "sky130::subconn_guard_draw"
    )
    new_guard_text = (
        f"box {unit_gen.fmt(new_guard[0] + unit_gen.ORIGIN[0])}um "
        f"{unit_gen.fmt(new_guard[1] + unit_gen.ORIGIN[1])}um "
        f"{unit_gen.fmt(new_guard[2] + unit_gen.ORIGIN[0])}um "
        f"{unit_gen.fmt(new_guard[3] + unit_gen.ORIGIN[1])}um\n"
        "sky130::subconn_guard_draw"
    )
    if source.count(old_guard_text) != 1:
        raise RuntimeError("edge pilot guard changed")
    source = source.replace(old_guard_text, new_guard_text)

    old_ground = unit_gen.shifted([6.98, float(old_guard[1])])
    new_ground = unit_gen.shifted([6.98, float(new_guard[1])])
    old_stack = "\n".join(unit_gen.li_to_m1_stack(*old_ground) + unit_gen.contact_stack(*old_ground))
    new_stack = "\n".join(unit_gen.li_to_m1_stack(*new_ground) + unit_gen.contact_stack(*new_ground))
    if source.count(old_stack) != 1:
        raise RuntimeError("edge guard contact changed")
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
        raise RuntimeError("edge guard label changed")
    source = source.replace(old_label, new_label)

    # Once connected through the resistor, the former internal `sig` spine is
    # the actual external element input.  Rename the one existing port rather
    # than create two shorted port aliases on the same conductor.
    if source.count("label sig center metal2") != 1:
        raise RuntimeError("shared sig spine label changed")
    source = source.replace("label sig center metal2", "label element_input center metal2")

    commands: list[str] = []
    for terminal in bias["resistor"]["terminals"].values():
        point = unit_gen.shifted(terminal)
        commands.extend(unit_gen.li_to_m1_stack(*point))
        commands.extend(unit_gen.contact_stack(*point))
    for routes in bias["routes"].values():
        for item in routes:
            start = unit_gen.shifted(item["from"])
            end = unit_gen.shifted(item["to"])
            if start[0] == end[0]:
                commands.append(unit_gen.wire_v(item["layer"], start[0], start[1], end[1], item["width_um"]))
            elif start[1] == end[1]:
                commands.append(unit_gen.wire_h(item["layer"], start[0], end[0], start[1], item["width_um"]))
            else:
                raise RuntimeError(f"non-Manhattan bias route: {item}")

    save_marker = "\nsave $TOP.mag\nwriteall force\n"
    if source.count(save_marker) != 1:
        raise RuntimeError("edge pilot save marker changed")
    source = source.replace(save_marker, "\n" + "\n".join(commands) + save_marker)
    old_gds = "gds write [file join $WORKDIR ${TOP}.gds]"
    new_gds = "gds write [file join $WORKDIR ${TOP}_magic.gds]"
    if source.count(old_gds) != 1:
        raise RuntimeError("edge pilot GDS write marker changed")
    return source.replace(old_gds, new_gds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    paths = (MATRIX, ARCHITECTURE, UNIT, CATALOG, TREES, DUMMIES, BIAS_CATALOG, BIAS)
    values = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_tcl(*values), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
