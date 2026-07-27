#!/usr/bin/env python3
"""Generate a three-unit V3 row pilot with exact local LON/LOP merges.

The centre matrix row is used because it contains both R0 and MY whole-unit
orientations.  This closes the repeated-cell abutment, mirror transform, local
diagonal crossover, and shared-substrate assumptions before all fifteen units
are replicated.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import generate_vector_unit_pilot as unit_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3" / "layout" / "channel_matrix_placement.json"
UNIT = ROOT / "v3" / "layout" / "vector_unit_placement.json"
CATALOG = ROOT / "v3" / "layout" / "channel_pcell_catalog.json"
DEFAULT_OUTPUT = ROOT / "build" / "v3" / "channel_row_pilot" / "build.tcl"
TOP = "v3_channel_row_pilot"
SELECTED_ROW = 2
ROW_Y = 40.0
UNIT_MIRROR_AXIS_X = 1.43


def fmt(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def whole_transform(
    point: list[float], instance: dict[str, Any], base_y: float = ROW_Y
) -> list[float]:
    x, y = point
    if instance["orientation"] == "MY":
        x = 2.0 * UNIT_MIRROR_AXIS_X - x
    elif instance["orientation"] != "R0":
        raise ValueError(f"unsupported whole-unit orientation {instance['orientation']}")
    return [
        round(instance["origin"][0] + x, 6),
        round(instance["origin"][1] - base_y + y, 6),
    ]


def absolute_to_row(point: list[float], base_y: float = ROW_Y) -> list[float]:
    return [round(point[0], 6), round(point[1] - base_y, 6)]


def transform_component(
    component: dict[str, Any], instance: dict[str, Any], prefix: str,
    base_y: float = ROW_Y,
) -> dict[str, Any]:
    result = copy.deepcopy(component)
    result["name"] = f"{prefix}_{component['name']}"
    result["center"] = whole_transform(component["center"], instance, base_y)
    result["terminals"] = {
        name: [whole_transform(point, instance, base_y) for point in points]
        for name, points in component["terminals"].items()
    }
    if instance["orientation"] == "MY":
        result["orientation"] = "MY" if component["orientation"] == "R0" else "R0"
    return result


def transform_segment(
    item: dict[str, Any], instance: dict[str, Any], base_y: float = ROW_Y
) -> dict[str, Any]:
    return {
        **item,
        "from": whole_transform(item["from"], instance, base_y),
        "to": whole_transform(item["to"], instance, base_y),
    }


def device_contact_stack(component: dict[str, Any], name: str) -> list[str]:
    """Retain the exact unit's 20 nm outward switch-contact staggering."""
    point = unit_gen.terminal(component, name)
    if "_XSW_" in component["name"] and name in ("D", "S"):
        centre_x = unit_gen.shifted(component["center"])[0]
        point[0] += -0.02 if point[0] < centre_x else 0.02
    return unit_gen.contact_stack(*point)


def local_route(item: dict[str, Any]) -> str:
    """Paint a local upper-metal segment with fully covered L-junctions."""
    first = unit_gen.shifted(item["from"])
    second = unit_gen.shifted(item["to"])
    width = float(item["width_um"])
    if first[0] == second[0]:
        return unit_gen.wire_v(item["layer"], first[0], first[1], second[1], width)
    if first[1] == second[1]:
        half = width / 2.0
        direction = 1.0 if second[0] >= first[0] else -1.0
        return unit_gen.wire_h(
            item["layer"], first[0] - direction * half,
            second[0] + direction * half, first[1], width,
        )
    raise ValueError(f"non-Manhattan local route {item}")


def label(name: str, point: list[float], layer: str, *, output: bool = False) -> str:
    x, y = unit_gen.shifted(point)
    return (
        f"box {fmt(x - 0.20)}um {fmt(y - 0.20)}um {fmt(x + 0.20)}um {fmt(y + 0.20)}um\n"
        f"label {name} center {layer}\nport make\n"
        f"port class {'output' if output else 'input'}\nport use signal\n"
        "port connections n s e w"
    )


def build_tcl(
    matrix: dict[str, Any], unit: dict[str, Any], catalog: dict[str, Any],
    *, guard_bottom_y: float | None = None,
) -> str:
    selected = sorted(
        (
            item for item in matrix["matrix"]["instances"]
            if item["row_top_to_bottom"] == SELECTED_ROW
        ),
        key=lambda item: item["column_left_to_right"],
    )
    if len(selected) != 3 or {item["orientation"] for item in selected} != {"R0", "MY"}:
        raise RuntimeError("centre row no longer exercises three units and both orientations")

    components: list[dict[str, Any]] = []
    commands: list[str] = []
    labels: list[str] = []
    ground_ports: list[list[float]] = []
    named_branch_points = ([1.08, 11.465], [1.78, 9.435], [2.20, 2.975])
    for index, instance in enumerate(selected):
        prefix = f"U{index}"
        placed_components = [
            transform_component(component, instance, prefix)
            for component in unit["devices"]
        ]
        components.extend(placed_components)
        for component in placed_components:
            for terminal_name in ("D", "S"):
                commands.extend(device_contact_stack(component, terminal_name))
            if (
                not component["name"].split("_", 1)[1].startswith("XSW_")
                and not unit.get("late_promotion")
            ):
                point = unit_gen.terminal(component, "G")
                commands.extend(unit_gen.contact_stack(*point))
                commands.extend(unit_gen.via2_stack(*point))
                commands.extend(unit_gen.via3_stack(*point))

        for promotion in unit["switch_gate_promotions"]:
            point = whole_transform(promotion["point"], instance)
            commands.extend(unit_gen.contact_stack(*unit_gen.shifted(point)))
            commands.extend(unit_gen.compact_via2_tall_stack(*unit_gen.shifted(point)))
        for segments in unit["routes"].values():
            commands.extend(
                unit_gen.route(transform_segment(item, instance)) for item in segments
            )
        for point in named_branch_points:
            commands.extend(
                unit_gen.compact_via2_stack(*unit_gen.shifted(whole_transform(point, instance)))
            )

        # Only LOP is promoted. LON remains on M3, so the two diagonal local
        # nets can cross without a short or a detour.
        local_routes = instance["local_lo_routes"]
        for point in local_routes["lop"]["via3_at_source_ports"]:
            commands.extend(unit_gen.via3_stack(*unit_gen.shifted(absolute_to_row(point))))
        for route in local_routes.values():
            for item in route["segments"]:
                local_item = {
                    **item,
                    "from": absolute_to_row(item["from"]),
                    "to": absolute_to_row(item["to"]),
                }
                commands.append(local_route(local_item))

        if unit.get("late_promotion"):
            ports = {
                name: {
                    "point": whole_transform(value["point"], instance),
                    "layer": value["layer"],
                }
                for name, value in unit["boundary_ports"].items()
                if name in ("sig", "ref", "vbias", "outp", "outn", "VGND")
            }
        else:
            ports = {
                name: {"point": absolute_to_row(value["point"]), "layer": value["layer"]}
                for name, value in instance["ports"].items()
            }
        ground_ports.append(ports["VGND"]["point"])
        for port_name in ("sig", "ref", "vbias", "outp", "outn"):
            labels.append(label(
                f"u{index}_{port_name}", ports[port_name]["point"], ports[port_name]["layer"],
                output=port_name in ("outp", "outn"),
            ))
        for net in ("lop", "lon"):
            root = absolute_to_row(local_routes[net]["root"])
            labels.append(label(f"u{index}_{net}", root, local_routes[net]["layer"]))

    instances_text = "\n".join(unit_gen.pcell_command(item, catalog) for item in components)

    active = matrix["active_array_bbox"]
    # Follow the same exact shared-guard boundary as the full matrix.  The
    # active-array bbox includes each unit's guard allowance, so expanding it
    # by another 0.8 um would measure the wrong channel pitch.
    row_origin_y = float(selected[0]["origin"][1]) - ROW_Y
    if any(abs((float(item["origin"][1]) - ROW_Y) - row_origin_y) > 1e-9 for item in selected):
        raise RuntimeError("selected row instances no longer share one y origin")
    guard = [
        round(active[0] + 0.05, 6),
        round(row_origin_y - 0.8 if guard_bottom_y is None else guard_bottom_y, 6),
        round(active[2] - 0.05, 6), round(row_origin_y + 14.75, 6),
    ]
    ground_bus_y = -0.45
    # Keep the complete inter-row M3 channel available to phase, output, and
    # analog branches.  Each exact M3 VGND port drops once to M2; the pilot
    # ground bus then remains below every signal spine.  The production matrix
    # uses same-y guard contacts and does not need these vertical pilot drops.
    for point in ground_ports:
        # Move the M3-to-M2 handoff 0.20 um into the existing unit ground
        # stem.  At the boundary itself its M3 landing sat only 0.15 um above
        # the adjacent REF row bus after GDS expansion.
        handoff = [point[0], round(point[1] + 0.20, 6)]
        commands.append(unit_gen.wire_v(
            "metal3", point[0] + unit_gen.ORIGIN[0], point[1] + unit_gen.ORIGIN[1],
            handoff[1] + unit_gen.ORIGIN[1], 0.40,
        ))
        commands.extend(unit_gen.compact_via2_stack(*unit_gen.shifted(handoff)))
        commands.append(unit_gen.wire_v("metal2", handoff[0] + unit_gen.ORIGIN[0], ground_bus_y + unit_gen.ORIGIN[1], handoff[1] + unit_gen.ORIGIN[1], 0.40))
    commands.append(unit_gen.wire_h(
        "metal2",
        ground_ports[0][0] + unit_gen.ORIGIN[0] - 0.20,
        ground_ports[-1][0] + unit_gen.ORIGIN[0] + 0.20,
        ground_bus_y + unit_gen.ORIGIN[1],
        0.40,
    ))
    guard_join = [ground_ports[0][0] + unit_gen.ORIGIN[0], guard[1] + unit_gen.ORIGIN[1]]
    commands.append(unit_gen.wire_v(
        "metal2", guard_join[0], guard_join[1], ground_bus_y + unit_gen.ORIGIN[1], 0.40
    ))
    commands.extend(unit_gen.li_to_m1_stack(*guard_join))
    commands.extend(unit_gen.contact_stack(*guard_join))
    labels.append(label("VGND", [ground_ports[0][0], ground_bus_y], "metal2"))

    commands_text = "\n".join(commands)
    label_text = "\n".join(labels)
    guard_abs = [
        guard[0] + unit_gen.ORIGIN[0], guard[1] + unit_gen.ORIGIN[1],
        guard[2] + unit_gen.ORIGIN[0], guard[3] + unit_gen.ORIGIN[1],
    ]
    return f"""# Generated by v3/tools/generate_channel_row_pilot.py; do not edit.
set PROJECT_ROOT [file normalize [pwd]]
set WORKDIR [file join $PROJECT_ROOT build v3 channel_row_pilot]
set SOURCE_TOP v3_channel_row_source
set TOP {TOP}
file mkdir $WORKDIR
cd $WORKDIR
foreach stale [glob -nocomplain [file join $WORKDIR ${{SOURCE_TOP}}*] [file join $WORKDIR ${{TOP}}*]] {{
    file delete -force $stale
}}
catch {{cellname delete $SOURCE_TOP}}
catch {{cellname delete $TOP}}
load $SOURCE_TOP -silent

{instances_text}

catch {{cellname delete {{(UNNAMED)}}}}
save $SOURCE_TOP.mag
writeall force
select top cell
expand
flatten $TOP
load $TOP
select top cell

proc paint_rect {{layer x1 y1 x2 y2}} {{
    box ${{x1}}um ${{y1}}um ${{x2}}um ${{y2}}um
    paint $layer
}}

# One substrate guard for the complete row, matching the production hierarchy.
box {fmt(guard_abs[0])}um {fmt(guard_abs[1])}um {fmt(guard_abs[2])}um {fmt(guard_abs[3])}um
sky130::subconn_guard_draw

{commands_text}

box {fmt(guard_join[0] - 0.08)}um {fmt(guard_join[1] - 0.08)}um {fmt(guard_join[0] + 0.08)}um {fmt(guard_join[1] + 0.08)}um
label VGND center locali

{label_text}

save $TOP.mag
writeall force
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "V3_CHANNEL_ROW_DRC_COUNT=$drc_count"
if {{$drc_count != 0}} {{
    feedback save [file join $WORKDIR drc_feedback.txt]
    error "channel-row pilot has DRC errors"
}}
extract unique notopports
extract do local
extract all
set extraction_feedback [feedback count]
puts "V3_CHANNEL_ROW_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
if {{$extraction_feedback != 0}} {{
    feedback save [file join $WORKDIR extraction_feedback.txt]
    error "channel-row pilot extraction produced feedback"
}}
ext2spice lvs
ext2spice hierarchy off
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice -o [file join $WORKDIR ${{TOP}}_flat.spice] ${{TOP}}.ext
gds compress 0
gds write [file join $WORKDIR ${{TOP}}.gds]
puts "V3_CHANNEL_ROW_GDS_FEEDBACK_COUNT=[feedback count]"
quit -noprompt
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--unit", type=Path, default=UNIT)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    unit = json.loads(args.unit.read_text(encoding="utf-8"))
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_tcl(matrix, unit, catalog), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
