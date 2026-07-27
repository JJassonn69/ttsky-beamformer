#!/usr/bin/env python3
"""Generate the complete shared tail-bias reference, resistor, and decoupling block."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from generate_critical_signal_routes import (  # noqa: E402
    contact_stack,
    li_contact_stack,
    li_to_m1_stack,
    via2_stack,
    via3_stack,
    wire_h,
    wire_v,
)


BIAS = ROOT / "v3/layout/bias_distribution.json"
PLACEMENT = ROOT / "v3/layout/shared_support_placement.json"
CATALOG = ROOT / "v3/layout/shared_support_pcell_catalog.json"
DEFAULT_OUTPUT = ROOT / "build/v3/tail_bias_support_block/build.tcl"
TOP = "v3_tail_bias_support_block"


def fmt(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def paint_rect(layer: str, bbox: list[float]) -> str:
    return "paint_rect {} {} {} {} {}".format(layer, *(fmt(value) for value in bbox))


def pcell_command(component: dict[str, Any], catalog: dict[str, Any]) -> str:
    cell = catalog["cells"][component["catalog_cell"]]
    parameters = cell["parameters"]
    offset = cell["gencell_anchor_offset_um"]
    anchor = [component["center"][0] - offset[0], component["center"][1] - offset[1]]
    if parameters["model"].startswith("res_"):
        generator = f"sky130::sky130_fd_pr__{parameters['model']}"
        arguments = (
            f"w {fmt(parameters['width_um'])} l {fmt(parameters['length_um'])} "
            "m 1 guard 1 full_metal 1 doports 0"
        )
    else:
        generator = "sky130::sky130_fd_pr__cap_mim_m3_1"
        arguments = (
            f"w {fmt(parameters['width_um'])} l {fmt(parameters['length_um'])} "
            "nx 1 ny 1 doports 0"
        )
    return (
        f"box {fmt(anchor[0])}um {fmt(anchor[1])}um {fmt(anchor[0])}um {fmt(anchor[1])}um\n"
        f"magic::gencell {generator} {component['name']} {arguments}"
    )


def terminal(component: dict[str, Any], name: str) -> list[float]:
    values = component["terminals"][name]
    if len(values) != 1:
        raise ValueError(f"{component['name']}.{name} must have one terminal")
    return values[0]


def build() -> str:
    bias = json.loads(BIAS.read_text(encoding="utf-8"))
    placement = json.loads(PLACEMENT.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    reference = bias["reference"]
    tail = placement["tail_bias"]
    resistor = tail["bias_resistor"]
    capacitors = tail["bypass_capacitors"]
    parameters = reference["parameters"]
    access = reference["terminal_access"]

    commands: list[str] = []
    for access_class in (
        "drain_via1_centers_um", "gate_via1_centers_um",
        "source_via1_centers_um", "body_via1_centers_um",
    ):
        for point in access[access_class]:
            half = access["via1_box_um"][0] / 2.0
            commands.append(paint_rect("metal1", [point[0]-half, point[1]-half, point[0]+half, point[1]+half]))
            commands.append(paint_rect("via1", [point[0]-half, point[1]-half, point[0]+half, point[1]+half]))
    commands.append(paint_rect("metal2", reference["straps"]["vbias_ref"]["bbox_um"]))
    commands.append(paint_rect("metal2", reference["straps"]["VGND"]["bbox_um"]))

    vbias_root = [194.0, 52.2]
    commands.extend(via2_stack(*vbias_root))
    commands.extend(via3_stack(*vbias_root))

    r1 = terminal(resistor, "R1")
    r2 = terminal(resistor, "R2")
    body = terminal(resistor, "B")
    commands.extend(li_contact_stack(*r1))
    commands.extend(li_contact_stack(*r2))
    commands.append(wire_h("metal2", vbias_root[0], r2[0], r2[1], 0.80))
    commands.append(wire_v("metal2", vbias_root[0], vbias_root[1], r2[1], 0.80))

    body_escape_x = 213.0
    commands.extend(li_to_m1_stack(*body))
    commands.append(wire_h("metal1", body[0], body_escape_x, body[1], 0.23))
    commands.extend(contact_stack(body_escape_x, body[1]))
    commands.extend(via2_stack(body_escape_x, body[1]))

    ground_y = 30.0
    reference_ground = [194.0, 43.2]
    commands.extend(via2_stack(*reference_ground))
    commands.append(wire_v("metal3", reference_ground[0], ground_y, reference_ground[1], 0.80))
    commands.extend(via3_stack(reference_ground[0], ground_y))
    commands.append(wire_v("metal3", body_escape_x, ground_y, body[1], 0.50))
    commands.extend(via3_stack(body_escape_x, ground_y))

    # Route the two MIM top plates from an upper M4 spine.  The superseded
    # constraint sketch ran horizontally through CBIAS0.C2 at y=48 um; that
    # overlap was legal geometry but extraction correctly shorted VBIAS to
    # ground.  Independent vertical drops avoid both bottom-plate Via-3s.
    cap_top_points = [terminal(item, "C1") for item in capacitors]
    # The bottom-plate C2 contact is a vertical edge strip, not a point-sized
    # feature.  Keep the shared spine above the complete 59.2 um capacitor
    # bbox and descend only on each left-side C1 access.
    cap_spine_y = 61.0
    commands.append(wire_v("metal4", vbias_root[0], vbias_root[1], cap_spine_y, 0.80))
    commands.append(wire_h("metal4", vbias_root[0], cap_top_points[-1][0], cap_spine_y, 0.80))
    for point in cap_top_points:
        commands.append(wire_v("metal4", point[0], point[1], cap_spine_y, 0.80))
    for item in tail["routes"]["decap_ground_bus"]["segments"]:
        x0, y0 = item["from"]
        x1, y1 = item["to"]
        commands.append(wire_v(item["layer"], x0, y0, y1, item["width_um"]) if x0 == x1 else wire_h(item["layer"], x0, x1, y0, item["width_um"]))
    cap_ground_x = terminal(capacitors[0], "C2")[0]
    commands.extend(via3_stack(cap_ground_x, ground_y))
    commands.append(wire_h("metal4", reference_ground[0], terminal(capacitors[-1], "C2")[0], ground_y, 0.80))

    instances = "\n".join(pcell_command(item, catalog) for item in [resistor, *capacitors])
    command_text = "\n".join(commands)
    anchor = reference["gencell_anchor_um"]
    return f"""# Generated by v3/tools/generate_tail_bias_support_block.py; do not edit.
set PROJECT_ROOT [file normalize [pwd]]
set WORKDIR [file join $PROJECT_ROOT build v3 tail_bias_support_block]
set SOURCE_TOP v3_tail_bias_support_source
set TOP {TOP}
file mkdir $WORKDIR
cd $WORKDIR
foreach stale [glob -nocomplain [file join $WORKDIR ${{SOURCE_TOP}}*] [file join $WORKDIR ${{TOP}}*]] {{ file delete -force $stale }}
catch {{cellname delete $SOURCE_TOP}}
catch {{cellname delete $TOP}}
load $SOURCE_TOP -silent
box {fmt(anchor[0])}um {fmt(anchor[1])}um {fmt(anchor[0])}um {fmt(anchor[1])}um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 XREF \
    w {fmt(parameters['finger_width_um'])} l {fmt(parameters['length_um'])} \
    nf {parameters['fingers']} m 1 guard 1 conn_gates 1 full_metal 1 \
    viagb {parameters['body_metal_coverage_percent']} doports 0
{instances}
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
{command_text}
box 193.80um 52.00um 194.20um 52.40um
label vbias center metal3
port make
port class output
port use signal
port connections n s e w
box {fmt(r1[0]-0.20)}um {fmt(r1[1]-0.20)}um {fmt(r1[0]+0.20)}um {fmt(r1[1]+0.20)}um
label VDPWR center metal2
port make
port class input
port use power
port connections n s e w
box 193.80um 29.80um 194.20um 30.20um
label VGND center metal4
port make
port class input
port use ground
port connections n s e w
save $TOP.mag
writeall force
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "V3_TAIL_BIAS_SUPPORT_BLOCK_DRC_COUNT=$drc_count"
if {{$drc_count != 0}} {{
    feedback save [file join $WORKDIR drc_feedback.txt]
    error "tail-bias support block has DRC errors"
}}
extract unique notopports
extract do local
extract all
set extraction_feedback [feedback count]
puts "V3_TAIL_BIAS_SUPPORT_BLOCK_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
if {{$extraction_feedback != 0}} {{
    feedback save [file join $WORKDIR extraction_feedback.txt]
    error "tail-bias support block extraction produced feedback"
}}
ext2spice lvs
ext2spice hierarchy off
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice -o [file join $WORKDIR ${{TOP}}_flat.spice] ${{TOP}}.ext
gds compress 0
gds write [file join $WORKDIR ${{TOP}}.gds]
puts "V3_TAIL_BIAS_SUPPORT_BLOCK_GDS_FEEDBACK_COUNT=[feedback count]"
quit -noprompt
"""


def main() -> None:
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(build(), encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
