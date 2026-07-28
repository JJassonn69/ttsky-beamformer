#!/usr/bin/env python3
"""Generate the exact 15-unit V3 matrix with local LO merges and one guard.

Group-level H-trees are deliberately absent.  This gate proves the complete
repetition, row spacing, R0/MY transforms, local LON/LOP routes, and symmetric
shared-substrate connection before adding the eight group phase nets.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import generate_channel_row_pilot as row_gen
import generate_vector_unit_pilot as unit_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3" / "layout" / "channel_matrix_placement.json"
UNIT = ROOT / "v3" / "layout" / "vector_unit_placement.json"
CATALOG = ROOT / "v3" / "layout" / "channel_pcell_catalog.json"
DEFAULT_OUTPUT = ROOT / "build" / "v3" / "channel_matrix_pilot" / "build.tcl"
TOP = "v3_channel_matrix_pilot"


def fmt(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


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
    *, ground_bus_offset_um: float = 0.0,
    guard_bottom_y: float = 7.20,
    ground_spines_x: list[float] | None = None,
) -> str:
    selected = sorted(
        matrix["matrix"]["instances"],
        key=lambda item: (item["row_top_to_bottom"], item["column_left_to_right"]),
    )
    if len(selected) != 15:
        raise RuntimeError("full matrix pilot requires exactly fifteen units")

    components: list[dict[str, Any]] = []
    commands: list[str] = []
    labels: list[str] = []
    ground_by_row: dict[int, list[list[float]]] = {}
    named_branch_points = ([1.08, 11.465], [1.78, 9.435], [2.20, 2.975])
    for index, instance in enumerate(selected):
        prefix = f"U{index:02d}"
        placed_components = [
            row_gen.transform_component(component, instance, prefix, 0.0)
            for component in unit["devices"]
        ]
        components.extend(placed_components)
        for component in placed_components:
            for terminal_name in ("D", "S"):
                commands.extend(row_gen.device_contact_stack(component, terminal_name))
            if (
                not component["name"].split("_", 1)[1].startswith("XSW_")
                and not unit.get("late_promotion")
            ):
                point = unit_gen.terminal(component, "G")
                commands.extend(unit_gen.contact_stack(*point))
                commands.extend(unit_gen.via2_stack(*point))
                commands.extend(unit_gen.via3_stack(*point))

        for promotion in unit["switch_gate_promotions"]:
            point = row_gen.whole_transform(promotion["point"], instance, 0.0)
            commands.extend(unit_gen.contact_stack(*unit_gen.shifted(point)))
            commands.extend(unit_gen.compact_via2_tall_stack(*unit_gen.shifted(point)))
        for segments in unit["routes"].values():
            commands.extend(
                unit_gen.route(row_gen.transform_segment(item, instance, 0.0))
                for item in segments
            )
        for point in named_branch_points:
            commands.extend(unit_gen.compact_via2_stack(
                *unit_gen.shifted(row_gen.whole_transform(point, instance, 0.0))
            ))

        local_routes = instance["local_lo_routes"]
        for point in local_routes["lop"]["via3_at_source_ports"]:
            commands.extend(unit_gen.via3_stack(*unit_gen.shifted(point)))
        for route in local_routes.values():
            for point in route.get("via2_points", []):
                commands.extend(unit_gen.via2_stack(*unit_gen.shifted(point)))
            commands.extend(row_gen.local_route(item) for item in route["segments"])

        ports = instance["ports"]
        row = int(instance["row_top_to_bottom"])
        ground_by_row.setdefault(row, []).append(ports["VGND"]["point"])
        for port_name in ("sig", "ref", "vbias", "outp", "outn"):
            labels.append(label(
                f"u{index:02d}_{port_name}", ports[port_name]["point"],
                ports[port_name]["layer"], output=port_name in ("outp", "outn"),
            ))
        for net in ("lop", "lon"):
            labels.append(label(
                f"u{index:02d}_{net}", local_routes[net]["root"],
                local_routes[net]["layer"],
            ))

    instances_text = "\n".join(unit_gen.pcell_command(item, catalog) for item in components)

    # The active-array bbox includes each unit's guard allowance.  A 50 nm
    # inset reproduces the previously closed 0.44..15.30 um shared guard and
    # also follows deliberate equal-pitch column studies without a hard-coded
    # right edge.
    active_top = max(float(item["ports"]["outp"]["point"][1]) for item in selected)
    active = matrix["active_array_bbox"]
    guard = [
        round(active[0] + 0.05, 6), round(guard_bottom_y, 6),
        round(active[2] - 0.05, 6), round(active_top + 0.80, 6),
    ]
    ground_bus_levels: list[float] = []
    for row, points in sorted(ground_by_row.items()):
        y = round(points[0][1] + ground_bus_offset_um, 6)
        ground_bus_levels.append(y)
        bus = {"from": [guard[0], y], "to": [guard[2], y], "layer": "metal3", "width_um": 0.40}
        commands.append(row_gen.local_route(bus))
        if ground_spines_x:
            for spine_x in ground_spines_x:
                commands.extend(unit_gen.via2_stack(*unit_gen.shifted([spine_x, y])))
        else:
            for point in ([guard[0], y], [guard[2], y]):
                absolute = unit_gen.shifted(point)
                commands.extend(unit_gen.li_to_m1_stack(*absolute))
                commands.extend(unit_gen.contact_stack(*absolute))
                commands.extend(unit_gen.via2_stack(*absolute))
    if ground_spines_x:
        if any(not guard[0] < spine_x < guard[2] for spine_x in ground_spines_x):
            raise RuntimeError("dedicated ground spines must lie inside the shared guard")
        top_ground_y = max(ground_bus_levels)
        for spine_x in ground_spines_x:
            lower = unit_gen.shifted([spine_x, guard[1]])
            upper = unit_gen.shifted([spine_x, top_ground_y])
            commands.append(unit_gen.wire_v("metal2", lower[0], lower[1], upper[1], 0.40))
            commands.extend(unit_gen.li_to_m1_stack(*lower))
            commands.extend(unit_gen.contact_stack(*lower))
        labels.append(label("VGND", [ground_spines_x[0], top_ground_y], "metal2"))
        guard_label_point = [ground_spines_x[0], guard[1]]
    else:
        labels.append(label("VGND", [guard[0], round(8.0 + ground_bus_offset_um, 6)], "metal3"))
        guard_label_point = [guard[2], round(8.0 + ground_bus_offset_um, 6)]

    commands_text = "\n".join(commands)
    label_text = "\n".join(labels)
    guard_abs = [
        guard[0] + unit_gen.ORIGIN[0], guard[1] + unit_gen.ORIGIN[1],
        guard[2] + unit_gen.ORIGIN[0], guard[3] + unit_gen.ORIGIN[1],
    ]
    # Keep the substrate-only label away from the exported M3 VGND port box;
    # otherwise Magic sees two labels under the cursor while assigning the
    # port attributes even though both labels belong to the same net.
    guard_label = unit_gen.shifted(guard_label_point)
    return f"""# Generated by v3/tools/generate_channel_matrix_pilot.py; do not edit.
set PROJECT_ROOT [file normalize [pwd]]
set WORKDIR [file join $PROJECT_ROOT build v3 channel_matrix_pilot]
set SOURCE_TOP v3_channel_matrix_source
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

box {fmt(guard_abs[0])}um {fmt(guard_abs[1])}um {fmt(guard_abs[2])}um {fmt(guard_abs[3])}um
sky130::subconn_guard_draw

{commands_text}

box {fmt(guard_label[0] - 0.08)}um {fmt(guard_label[1] - 0.08)}um {fmt(guard_label[0] + 0.08)}um {fmt(guard_label[1] + 0.08)}um
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
puts "V3_CHANNEL_MATRIX_DRC_COUNT=$drc_count"
if {{$drc_count != 0}} {{
    feedback save [file join $WORKDIR drc_feedback.txt]
    error "channel-matrix pilot has DRC errors"
}}
extract unique notopports
extract do local
extract all
set extraction_feedback [feedback count]
puts "V3_CHANNEL_MATRIX_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
if {{$extraction_feedback != 0}} {{
    feedback save [file join $WORKDIR extraction_feedback.txt]
    error "channel-matrix pilot extraction produced feedback"
}}
ext2spice lvs
ext2spice hierarchy off
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice -o [file join $WORKDIR ${{TOP}}_flat.spice] ${{TOP}}.ext
gds compress 0
gds write [file join $WORKDIR ${{TOP}}.gds]
puts "V3_CHANNEL_MATRIX_GDS_FEEDBACK_COUNT=[feedback count]"
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
