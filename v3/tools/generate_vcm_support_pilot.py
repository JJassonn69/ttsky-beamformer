#!/usr/bin/env python3
"""Generate the exact Magic build script for the V3 VCM support pilot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2" / "tools"))

from generate_critical_signal_routes import (  # noqa: E402
    contact_stack,
    li_contact_stack,
    li_to_m1_stack,
    via2_stack,
    via3_stack,
    wire_h,
    wire_v,
)


MANIFEST = ROOT / "v3" / "layout" / "shared_support_placement.json"
CATALOG = ROOT / "v3" / "layout" / "shared_support_pcell_catalog.json"
DEFAULT_OUTPUT = ROOT / "build" / "v3" / "vcm_support_pilot" / "build.tcl"
TOP = "v3_vcm_support_pilot"
GENERATORS = {
    "res_xhigh_po_1p41": "sky130::sky130_fd_pr__res_xhigh_po_1p41",
    "cap_mim_m3_1": "sky130::sky130_fd_pr__cap_mim_m3_1",
}


def fmt(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def route_rect(item: dict[str, Any]) -> str:
    x0, y0 = item["from"]
    x1, y1 = item["to"]
    half = item["width_um"] / 2.0
    if x0 == x1:
        bbox = [x0 - half, min(y0, y1) - half, x0 + half, max(y0, y1) + half]
    elif y0 == y1:
        bbox = [min(x0, x1) - half, y0 - half, max(x0, x1) + half, y0 + half]
    else:
        raise ValueError(f"non-Manhattan segment {item}")
    return "paint_rect {} {} {} {} {}".format(
        item["layer"], *(fmt(value) for value in bbox)
    )


def terminal(component: dict[str, Any], name: str) -> list[float]:
    values = component["terminals"][name]
    if len(values) != 1:
        raise ValueError(f"{component['name']}.{name} must have one terminal")
    return values[0]


def pcell_command(component: dict[str, Any], catalog: dict[str, Any]) -> str:
    cell = catalog["cells"][component["catalog_cell"]]
    parameters = cell["parameters"]
    offset = cell["gencell_anchor_offset_um"]
    anchor = [
        component["center"][0] - offset[0],
        component["center"][1] - offset[1],
    ]
    generator = GENERATORS[parameters["model"]]
    if parameters["model"].startswith("res_"):
        args = (
            f"w {fmt(parameters['width_um'])} l {fmt(parameters['length_um'])} "
            "m 1 guard 1 full_metal 1 doports 0"
        )
    else:
        args = (
            f"w {fmt(parameters['width_um'])} l {fmt(parameters['length_um'])} "
            "nx 1 ny 1 doports 0"
        )
    return (
        f"box {fmt(anchor[0])}um {fmt(anchor[1])}um "
        f"{fmt(anchor[0])}um {fmt(anchor[1])}um\n"
        f"magic::gencell {generator} {component['name']} {args}"
    )


def build_tcl(data: dict[str, Any], catalog: dict[str, Any]) -> str:
    divider = data["vcm"]["divider_units"]
    capacitors = data["vcm"]["bypass_capacitors"]
    components = divider + capacitors
    instances = "\n".join(pcell_command(item, catalog) for item in components)
    commands: list[str] = []
    contacted_m2: set[tuple[float, float]] = set()
    contacted_m3: set[tuple[float, float]] = set()

    def contact_terminal(point: list[float], layer: str) -> None:
        key = (point[0], point[1])
        if key not in contacted_m2:
            commands.extend(li_contact_stack(*point))
            contacted_m2.add(key)
        if layer == "metal3" and key not in contacted_m3:
            commands.extend(via2_stack(*point))
            contacted_m3.add(key)

    for route in data["vcm"]["divider_internal_routes"]:
        for item in route["segments"]:
            contact_terminal(item["from"], item["layer"])
            contact_terminal(item["to"], item["layer"])
            commands.append(route_rect(item))

    feed = data["vcm"]["feed"]
    divider_star = feed["named_star"]
    contact_terminal(divider_star, "metal3")
    commands.extend(via3_stack(*divider_star))
    for item in feed["segments"]:
        commands.append(route_rect(item))

    # The bottom-plate C2 terminals are already exposed through the PCell's
    # via strip.  The manifest ground route remains on M3 until a single,
    # explicit transition to the local pilot ground bus.
    for item in data["vcm"]["ground"]["segments"]:
        commands.append(route_rect(item))

    by_name = {item["name"]: item for item in divider}
    vdd = terminal(by_name["RVCM_T0"], "R1")
    contact_terminal(vdd, "metal2")

    cap_ground_x = terminal(capacitors[0], "C2")[0]
    cap_ground_ys = [terminal(item, "C2")[1] for item in capacitors]
    divider_ground = terminal(by_name["RVCM_B3"], "R2")
    ground_y = 5.0
    commands.append(wire_v(
        "metal3", cap_ground_x, ground_y,
        max([divider_ground[1], *cap_ground_ys]), 0.80,
    ))
    commands.extend(via3_stack(cap_ground_x, ground_y))

    contact_terminal(divider_ground, "metal3")
    commands.append(wire_h("metal3", divider_ground[0], cap_ground_x, divider_ground[1], 0.80))

    # Ground every guarded resistor body without introducing a route through
    # another terminal landing.  Same-column body escapes intentionally share
    # a vertical M3 ground drop.
    ground_tracks: dict[float, list[float]] = {}
    for item in divider:
        body = terminal(item, "B")
        center_x = item["center"][0]
        if center_x < 30.0:
            # Keep the left-column body-ground drop outside the MIM CAPM
            # keepout.  At center_x - 2.0 the 0.50-um M3 drop left only
            # 1.11 um to the CAPM edge and produced one MR_capm.SP.2 marker
            # beside each of the three capacitors.
            escape_x = center_x - 3.5
        elif center_x > 40.0:
            escape_x = center_x + 3.5
        else:
            escape_x = center_x - 3.0
        commands.extend(li_to_m1_stack(*body))
        commands.append(wire_h("metal1", body[0], escape_x, body[1], 0.23))
        commands.extend(contact_stack(escape_x, body[1]))
        commands.extend(via2_stack(escape_x, body[1]))
        ground_tracks.setdefault(escape_x, []).append(body[1])
    for x, ys in ground_tracks.items():
        commands.append(wire_v("metal3", x, ground_y, max(ys), 0.50))
        commands.extend(via3_stack(x, ground_y))

    commands.append(wire_h("metal4", 15.0, 50.0, ground_y, 0.80))
    command_text = "\n".join(commands)
    root = feed["segments"][-1]["to"]

    return f"""# Generated by v3/tools/generate_vcm_support_pilot.py; do not edit.
set PROJECT_ROOT [file normalize [pwd]]
set WORKDIR [file join $PROJECT_ROOT build v3 vcm_support_pilot]
set SOURCE_TOP v3_vcm_support_source
set TOP {TOP}
file mkdir $WORKDIR
cd $WORKDIR

foreach stale [glob -nocomplain [file join $WORKDIR ${{SOURCE_TOP}}*] [file join $WORKDIR ${{TOP}}*]] {{
    file delete -force $stale
}}
catch {{cellname delete $SOURCE_TOP}}
catch {{cellname delete $TOP}}
load $SOURCE_TOP -silent

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

box {fmt(vdd[0]-0.20)}um {fmt(vdd[1]-0.20)}um {fmt(vdd[0]+0.20)}um {fmt(vdd[1]+0.20)}um
label VDPWR center metal2
port make
port class input
port use power
port connections n s e w
box 14.80um 4.80um 15.20um 5.20um
label VGND center metal4
port make
port class input
port use ground
port connections n s e w
box {fmt(root[0]-0.20)}um {fmt(root[1]-0.20)}um {fmt(root[0]+0.20)}um {fmt(root[1]+0.20)}um
label vcm center metal4
port make
port class output
port use signal
port connections n s e w

save $TOP.mag
writeall force
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "V3_VCM_SUPPORT_DRC_COUNT=$drc_count"
if {{$drc_count != 0}} {{
    feedback save [file join $WORKDIR drc_feedback.txt]
    error "VCM support pilot has DRC errors"
}}

extract unique notopports
extract do local
extract all
set extraction_feedback [feedback count]
puts "V3_VCM_SUPPORT_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
if {{$extraction_feedback != 0}} {{
    feedback save [file join $WORKDIR extraction_feedback.txt]
    error "VCM support pilot extraction produced feedback"
}}
ext2spice lvs
ext2spice hierarchy off
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice -o [file join $WORKDIR ${{TOP}}_flat.spice] ${{TOP}}.ext
gds compress 0
gds write [file join $WORKDIR ${{TOP}}.gds]
puts "V3_VCM_SUPPORT_GDS_FEEDBACK_COUNT=[feedback count]"
quit -noprompt
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_tcl(data, catalog), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
