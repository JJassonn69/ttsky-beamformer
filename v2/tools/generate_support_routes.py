#!/usr/bin/env python3
"""Route the matched VCM and bias support network without entering keepouts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from check_route_feasibility import component_ports
from generate_critical_signal_routes import (
    contact_stack,
    fmt,
    li_contact_stack,
    li_to_m1_stack,
    rect,
    via2_stack,
    via3_stack,
    wire_h,
    wire_v,
)


TOP = "v2_four_channel_support_routed"
STAGE = "support_routes"
SOURCE_TOP = "v2_four_channel_support_placed"
SOURCE_GDS = "build/v2/support_placement/magic/v2_four_channel_support_placed.gds"
M2_WIDTH = 0.32
M3_WIDTH = 0.40
M4_WIDTH = 0.40


def placed_component(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": record["name"],
        "pcell": record["pcell"],
        "x": record["center"][0],
        "y": record["center"][1],
        "orientation": record["orientation"],
    }


def generate(
    plan: dict[str, Any], dimensions: dict[str, Any], catalog: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    components = {
        item["name"]: placed_component(item)
        for item in plan["analog_support_components"]
    }

    def ports(name: str, terminal: str) -> list[list[float]]:
        return component_ports(
            components[name], terminal, dimensions, catalog
        )

    commands: list[str] = []

    # VCM divider midpoint.  The two terminal contacts face one another across
    # the measured 1.18 um PCell gap; the only upper-layer branch leaves from
    # the centre of that gap.
    bottom_r1 = ports("RVCM_BOTTOM", "R1")[0]
    top_r2 = ports("RVCM_TOP", "R2")[0]
    vcm_junction_y = (bottom_r1[1] + top_r2[1]) / 2.0
    commands.append("# RVCM_BOTTOM.R1 + RVCM_TOP.R2 -> vcm")
    for point in (bottom_r1, top_r2):
        commands.extend(li_contact_stack(point[0], point[1]))
    commands.append(wire_v("metal2", 25.0, bottom_r1[1], top_r2[1], M2_WIDTH))
    commands.extend(via2_stack(25.0, vcm_junction_y))
    commands.extend(via3_stack(25.0, vcm_junction_y))
    commands.append(wire_h("metal4", 25.0, 53.88, vcm_junction_y, M4_WIDTH))

    # C1 is the broad M4/capm top plate.  Leave it on M4 through the plate and
    # descend at x=53.88, where the first M3 landing retains 1.49 um clearance
    # to the complete capacitor bbox.  This also keeps the visible riser off
    # the plate centre.
    c1 = ports("CVCM", "C1")[0]
    commands.append("# CVCM.C1 -> vcm")
    commands.append(rect("metal4", c1[0] - 0.20, c1[1] - 0.20,
                         c1[0] + 0.20, c1[1] + 0.20))
    commands.append(wire_h("metal4", c1[0], 53.88, c1[1], M4_WIDTH))
    commands.append(rect("metal4", 53.68, 83.565, 54.08, 130.20))
    commands.append(wire_h("metal4", 53.88, 160.60, 83.765, M4_WIDTH))
    commands.extend((
        "# net label: vcm",
        "box 53.88um 83.765um 53.88um 83.765um",
        "label {vcm} FreeSans 0.10u -met4",
    ))

    # C2 reaches the M3 bottom plate through the PCell's own via strip.  Stay
    # on M4 until below the capacitor, then transition once at y=116.5 um.
    c2 = ports("CVCM", "C2")[0]
    commands.append("# CVCM.C2 -> VGND")
    commands.append(rect("metal4", c2[0] - 0.20, c2[1] - 0.20,
                         c2[0] + 0.20, c2[1] + 0.20))
    commands.append(wire_v("metal4", c2[0], 116.50, c2[1], M4_WIDTH))
    commands.extend(via3_stack(c2[0], 116.50))
    commands.append(wire_v("metal3", c2[0], 20.0, 116.50, M3_WIDTH))
    commands.extend(via3_stack(c2[0], 20.0))

    # Both resistor guard contacts, plus the grounded lower divider end, use
    # the x=22 um grounded shield.  It is separated from the resistor bboxes
    # and joins the same M4 ground spine at one named point.
    bottom_r2 = ports("RVCM_BOTTOM", "R2")[0]
    bottom_body = ports("RVCM_BOTTOM", "B")[0]
    top_body = ports("RVCM_TOP", "B")[0]
    commands.append("# VCM resistor bodies and lower divider end -> VGND")
    commands.extend(li_contact_stack(bottom_r2[0], bottom_r2[1]))
    commands.append(wire_h("metal2", 22.0, bottom_r2[0], bottom_r2[1], M2_WIDTH))
    commands.extend(via2_stack(22.0, bottom_r2[1]))
    for point in (bottom_body, top_body):
        body_escape_x = 24.50
        commands.extend(li_to_m1_stack(point[0], point[1]))
        commands.append(wire_h("metal1", point[0], body_escape_x, point[1], 0.23))
        commands.extend(contact_stack(body_escape_x, point[1]))
        commands.append(wire_h("metal2", 22.0, body_escape_x, point[1], M2_WIDTH))
        commands.extend(via2_stack(22.0, point[1]))
    commands.append(wire_v("metal3", 22.0, bottom_body[1], top_body[1], M3_WIDTH))
    commands.extend(via3_stack(22.0, 20.0))

    # Diode-connected bias pair.  The drain and source rows are staggered in
    # opposite directions within the existing wide M1 stripes, exactly as in
    # the verified V1 bias generator.  Only one internally strapped gate tap
    # is needed per device.
    finger_width = float(
        dimensions["pcells"]["bias_diode_nfet_guarded"]["parameters"][
            "finger_width"
        ]
    )
    terminal_offset = finger_width / 2.0 - 0.16
    drain_centres: list[float] = []
    source_centres: list[float] = []
    drain_y = 96.5 + terminal_offset
    source_y = 96.5 - terminal_offset
    gate_y = 96.5 + 1.165 + 0.45
    for name in ("BIAS_DIODE_A", "BIAS_DIODE_B"):
        drain_points = ports(name, "D")
        source_points = ports(name, "S")
        gate_points = ports(name, "G")
        body = ports(name, "B")[0]
        drain_centre = sum(point[0] for point in drain_points) / len(drain_points)
        source_centre = sum(point[0] for point in source_points) / len(source_points)
        drain_centres.append(drain_centre)
        source_centres.append(source_centre)

        commands.append(f"# {name}.D + {name}.G -> vbias")
        for point in drain_points:
            commands.extend(li_to_m1_stack(point[0], point[1]))
            commands.append(wire_v("metal1", point[0], point[1], drain_y, 0.23))
            commands.extend(contact_stack(point[0], drain_y))
        commands.append(wire_h(
            "metal2", min(point[0] for point in drain_points),
            max(point[0] for point in drain_points), drain_y, M2_WIDTH,
        ))
        gate = gate_points[len(gate_points) // 2]
        commands.extend(li_to_m1_stack(gate[0], gate[1]))
        commands.append(wire_v("metal1", gate[0], gate[1], gate_y, 0.23))
        commands.extend(contact_stack(gate[0], gate_y))
        commands.append(wire_v("metal2", gate[0], drain_y, gate_y, M2_WIDTH))
        commands.extend(via2_stack(drain_centre, drain_y))

        commands.append(f"# {name}.S + {name}.B -> VGND")
        for point in source_points:
            commands.extend(li_to_m1_stack(point[0], point[1]))
            commands.append(wire_v("metal1", point[0], point[1], source_y, 0.23))
            commands.extend(contact_stack(point[0], source_y))
        commands.append(wire_h(
            "metal2", min(point[0] for point in source_points),
            max(point[0] for point in source_points), source_y, M2_WIDTH,
        ))
        commands.extend(li_contact_stack(body[0], body[1]))
        commands.append(wire_v("metal2", body[0], body[1], source_y, M2_WIDTH))
        commands.extend(via2_stack(source_centre, source_y))
        commands.extend(via3_stack(source_centre, source_y))

    vbias_axis = sum(drain_centres) / 2.0
    ground_axis = 173.0
    commands.append("# symmetric bias-pair drain tree -> vbias")
    commands.append(wire_h(
        "metal3", min(drain_centres), max(drain_centres), drain_y, M3_WIDTH
    ))
    vbias_bus_y = 50.0
    commands.append(wire_v("metal3", vbias_axis, vbias_bus_y, 105.605, M3_WIDTH))
    commands.extend(via3_stack(vbias_axis, vbias_bus_y))
    commands.append(wire_h("metal4", 100.60, vbias_axis, vbias_bus_y, M4_WIDTH))
    commands.append("# four local channel bias handoffs -> vbias")
    for channel_vbias_x in (100.60, 119.92, 139.24, 158.56):
        commands.append(wire_v("metal3", channel_vbias_x, 46.75, vbias_bus_y, M3_WIDTH))
        commands.extend(via3_stack(channel_vbias_x, vbias_bus_y))
    commands.extend((
        "# net label: vbias",
        f"box {fmt(vbias_axis)}um 50um {fmt(vbias_axis)}um 50um",
        "label {vbias} FreeSans 0.10u -met4",
    ))

    commands.append("# symmetric bias-pair source tree -> VGND")
    commands.append(wire_h(
        "metal4", min(source_centres), max(source_centres), source_y, M4_WIDTH
    ))
    commands.extend(via3_stack(ground_axis, source_y))
    commands.append(wire_v("metal3", ground_axis, 20.0, source_y, M3_WIDTH))
    commands.extend(via3_stack(ground_axis, 20.0))

    # Bias resistor lower terminal joins the exact drain-tree symmetry axis.
    # Its body exits on M4 so it can cross the M3 vbias tree without contact.
    rbias_r2 = ports("RBIAS", "R2")[0]
    rbias_body = ports("RBIAS", "B")[0]
    commands.append("# RBIAS.R2 -> vbias")
    commands.extend(li_contact_stack(rbias_r2[0], rbias_r2[1]))
    commands.append(wire_h("metal2", vbias_axis, rbias_r2[0], rbias_r2[1], M2_WIDTH))
    commands.extend(via2_stack(vbias_axis, rbias_r2[1]))
    commands.append("# RBIAS.B -> VGND")
    commands.extend(li_contact_stack(rbias_body[0], rbias_body[1]))
    commands.append(wire_h("metal2", rbias_body[0], 175.0, rbias_body[1], M2_WIDTH))
    commands.extend(via2_stack(175.0, rbias_body[1]))
    commands.extend(via3_stack(175.0, rbias_body[1]))
    commands.append(wire_v("metal4", 175.0, source_y, rbias_body[1], M4_WIDTH))

    # One continuous M4 ground bus extends the already verified channel-guard
    # bus to the future full-height TinyTapeout ground pin at x=5 um.
    commands.append("# support and channel ground bus -> VGND")
    commands.append(wire_h("metal4", 5.0, ground_axis, 20.0, M4_WIDTH))
    commands.extend((
        "# net label: VGND",
        "box 5um 20um 5um 20um",
        "label {VGND} FreeSans 0.10u -met4",
    ))

    body = "\n".join(commands)
    tcl = f"""# Generated by v2/tools/generate_support_routes.py; do not edit.
set PROJECT_ROOT [pwd]
set SOURCE_GDS [file join $PROJECT_ROOT {SOURCE_GDS}]
set OUT_DIR [file join $PROJECT_ROOT build v2 {STAGE} magic]
file mkdir $OUT_DIR
if {{![file exists $SOURCE_GDS]}} {{
    error "required support-placement GDS does not exist: $SOURCE_GDS"
}}
gds read $SOURCE_GDS
if {{[lsearch -exact [cellname list all] {SOURCE_TOP}] < 0}} {{
    error "support-placement top cell was not imported"
}}
load {SOURCE_TOP}
cellname rename {TOP}
select top cell
expand

proc paint_rect {{layer x1 y1 x2 y2}} {{
    box ${{x1}}um ${{y1}}um ${{x2}}um ${{y2}}um
    paint $layer
}}

{body}

select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "SUPPORT_ROUTE_DRC_COUNT=$drc_count"
if {{$drc_count != 0}} {{
    feedback save [file join $OUT_DIR support_route_drc.txt]
    error "refusing support routes with $drc_count DRC errors"
}}
cd $OUT_DIR
save {TOP}.mag
feedback clear
gds compress 0
gds write {TOP}.gds
set gds_feedback [feedback count]
puts "SUPPORT_ROUTE_GDS_FEEDBACK_COUNT=$gds_feedback"
if {{$gds_feedback != 0}} {{
    feedback save support_route_gds_feedback.txt
    error "refusing support routes with $gds_feedback GDS writer problems"
}}
quit -noprompt
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(tcl, encoding="utf-8")
    return {
        "vcm_divider_junction": [25.0, vcm_junction_y],
        "vcm_capacitor_clear_edge_x": 53.88,
        "vbias_symmetry_axis_x": vbias_axis,
        "ground_symmetry_axis_x": ground_axis,
        "bias_drain_y": drain_y,
        "bias_source_y": source_y,
        "c2_external_transition": [c2[0], 116.50],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/integration_plan.json"))
    parser.add_argument("--dimensions", type=Path, default=Path("v2/layout/pcell_dimensions.json"))
    parser.add_argument("--catalog", type=Path, default=Path("v2/layout/port_catalog.json"))
    parser.add_argument("--output", type=Path, default=Path("build/v2/support_routes/route.tcl"))
    args = parser.parse_args()
    metrics = generate(
        json.loads(args.plan.read_text(encoding="utf-8")),
        json.loads(args.dimensions.read_text(encoding="utf-8")),
        json.loads(args.catalog.read_text(encoding="utf-8")),
        args.output,
    )
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
