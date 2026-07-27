#!/usr/bin/env python3
"""Generate the exact V3 channel with edge dummies and compact input bias."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import generate_channel_edge_dummy_pilot as edge_gen
import generate_vector_unit_pilot as unit_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3" / "layout" / "channel_matrix_placement.json"
UNIT = ROOT / "v3" / "layout" / "vector_unit_placement.json"
CHANNEL_CATALOG = ROOT / "v3" / "layout" / "channel_pcell_catalog.json"
TREES = ROOT / "v3" / "layout" / "group_phase_trees.json"
DUMMIES = ROOT / "v3" / "layout" / "channel_edge_dummies.json"
BIAS_CATALOG = ROOT / "v3" / "layout" / "input_bias_pcell_catalog.json"
BIAS = ROOT / "v3" / "layout" / "compact_input_bias_placement.json"
DEFAULT_OUTPUT = ROOT / "build" / "v3" / "channel_input_bias_pilot" / "build.tcl"
TOP = "v3_channel_input_bias_pilot"


def resistor_pcell(component: dict[str, Any], catalog: dict[str, Any]) -> str:
    cell = catalog["cells"][component["catalog_cell"]]
    offset = cell["gencell_anchor_offset_um"]
    center = unit_gen.shifted(component["center"])
    anchor = [center[0] - offset[0], center[1] - offset[1]]
    return (
        f"box {unit_gen.fmt(anchor[0])}um {unit_gen.fmt(anchor[1])}um "
        f"{unit_gen.fmt(anchor[0])}um {unit_gen.fmt(anchor[1])}um\n"
        "magic::gencell sky130::sky130_fd_pr__res_xhigh_po_0p35 "
        f"{component['name']} w 0.35 l {unit_gen.fmt(component['length_um'])} "
        "m 1 guard 1 full_metal 1 doports 0"
    )


def port(name: str, point: list[float], layer: str) -> str:
    x, y = unit_gen.shifted(point)
    half = 0.10
    return (
        f"box {unit_gen.fmt(x - half)}um {unit_gen.fmt(y - half)}um "
        f"{unit_gen.fmt(x + half)}um {unit_gen.fmt(y + half)}um\n"
        f"label {name} center {layer}\nport make\nport class input\n"
        "port use signal\nport connections n s e w"
    )


def build_tcl(
    matrix: dict[str, Any], unit: dict[str, Any], channel_catalog: dict[str, Any],
    trees: dict[str, Any], dummies: dict[str, Any], bias_catalog: dict[str, Any],
    bias: dict[str, Any],
) -> str:
    source = edge_gen.build_tcl(matrix, unit, channel_catalog, trees, dummies)
    source = source.replace("channel_edge_dummy_pilot", "channel_input_bias_pilot")
    source = source.replace("v3_channel_edge_dummy_pilot", TOP)
    source = source.replace("V3_CHANNEL_EDGE_DUMMY", "V3_CHANNEL_INPUT_BIAS")
    source = source.replace("channel-edge-dummy pilot", "channel-input-bias pilot")

    instance_marker = "\ncatch {cellname delete {(UNNAMED)}}\n"
    if source.count(instance_marker) != 1:
        raise RuntimeError("edge pilot instance marker changed")
    source = source.replace(
        instance_marker,
        f"\n{resistor_pcell(bias['resistor'], bias_catalog)}{instance_marker}",
    )

    commands: list[str] = []
    shield = bias["ground_shield"]["bbox"]
    commands.append(unit_gen.rect(
        "metal3",
        shield[0] + unit_gen.ORIGIN[0], shield[1] + unit_gen.ORIGIN[1],
        shield[2] + unit_gen.ORIGIN[0], shield[3] + unit_gen.ORIGIN[1],
    ))
    commands.append(unit_gen.wire_h(
        "metal3", 15.30 + unit_gen.ORIGIN[0], shield[0] + unit_gen.ORIGIN[0],
        3.775 + unit_gen.ORIGIN[1], 0.40,
    ))
    for item in bias["terminal_routes"]:
        first = unit_gen.shifted(item["from"])
        second = unit_gen.shifted(item["to"])
        commands.extend(unit_gen.li_to_m1_stack(*first))
        commands.extend(unit_gen.contact_stack(*first))
        commands.append(unit_gen.wire_h(
            item["layer"], first[0], second[0], first[1], item["width_um"],
        ))

    body = unit_gen.shifted(bias["resistor"]["terminals"]["B"])
    body_escape = unit_gen.shifted([15.82, bias["resistor"]["terminals"]["B"][1]])
    commands.extend(unit_gen.li_to_m1_stack(*body))
    commands.append(unit_gen.wire_h("metal1", body[0], body_escape[0], body[1], 0.23))
    commands.extend(unit_gen.contact_stack(*body_escape))
    commands.extend(unit_gen.via2_stack(*body_escape))

    labels = "\n".join(
        port(name, value["point"], value["layer"])
        for name, value in bias["ports"].items()
        if name != "VGND"
    )
    save_marker = "\nsave $TOP.mag\nwriteall force\n"
    if source.count(save_marker) != 1:
        raise RuntimeError("edge pilot save marker changed")
    source = source.replace(save_marker, f"\n{'\n'.join(commands)}\n{labels}{save_marker}")
    old_gds = "gds write [file join $WORKDIR ${TOP}.gds]"
    new_gds = "gds write [file join $WORKDIR ${TOP}_magic.gds]"
    if source.count(old_gds) != 1:
        raise RuntimeError("edge pilot GDS write marker changed")
    return source.replace(old_gds, new_gds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    paths = (MATRIX, UNIT, CHANNEL_CATALOG, TREES, DUMMIES, BIAS_CATALOG, BIAS)
    values = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_tcl(*values), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
