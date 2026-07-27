#!/usr/bin/env python3
"""Generate the exact Magic build for one routed V3 vector-unit pilot."""

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
    li_to_m1_stack,
    rect,
    via2_stack,
    via3_stack,
    wire_h,
    wire_v,
)


MANIFEST = ROOT / "v3" / "layout" / "vector_unit_placement.json"
CATALOG = ROOT / "v3" / "layout" / "channel_pcell_catalog.json"
DEFAULT_OUTPUT = ROOT / "build" / "v3" / "vector_unit_pilot" / "build.tcl"
ORIGIN = [20.0, 20.0]
TOP = "v3_vector_unit_pilot"


def fmt(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def shifted(point: list[float]) -> list[float]:
    return [round(point[0] + ORIGIN[0], 6), round(point[1] + ORIGIN[1], 6)]


def route(item: dict[str, Any]) -> str:
    first = shifted(item["from"])
    second = shifted(item["to"])
    if first[0] == second[0]:
        return wire_v(item["layer"], first[0], first[1], second[1], item["width_um"])
    if first[1] == second[1]:
        # Cover both endpoint pads completely.  Without these half-width
        # extensions an L-junction/pad union leaves a narrow concave notch
        # that violates the direct-GDS M4 width rule despite being connected.
        if item["layer"] == "metal4":
            half = item["width_um"] / 2.0
            direction = 1.0 if second[0] >= first[0] else -1.0
            first = [first[0] - direction * half, first[1]]
            second = [second[0] + direction * half, second[1]]
        return wire_h(item["layer"], first[0], second[0], first[1], item["width_um"])
    raise ValueError(f"non-Manhattan route {item}")


def compact_via2_stack(x: float, y: float) -> list[str]:
    """Single-cut M2/M3 transition without an oversized M3 landing plate."""
    return [
        rect("metal2", x - 0.15, y - 0.15, x + 0.15, y + 0.15),
        # Magic needs the 0.40 um contact tile used by the PDK generator; the
        # emitted GDS cut remains the legal 0.20 um Via-2 square.
        rect("via2", x - 0.20, y - 0.20, x + 0.20, y + 0.20),
        rect("metal3", x - 0.20, y - 0.20, x + 0.20, y + 0.20),
    ]


def compact_via2_tall_stack(x: float, y: float) -> list[str]:
    """Compact-width isolated Via-2 landing meeting the 0.24 um2 M3 area."""
    return [
        rect("metal2", x - 0.15, y - 0.15, x + 0.15, y + 0.15),
        rect("via2", x - 0.20, y - 0.20, x + 0.20, y + 0.20),
        rect("metal3", x - 0.20, y - 0.30, x + 0.20, y + 0.30),
    ]


def device_contact_stack(component: dict[str, Any], name: str) -> list[str]:
    """Place legal Via-1 landings, spreading tight switch D/S pairs outward."""
    point = terminal(component, name)
    if component["name"].startswith("XSW_") and name in ("D", "S"):
        point[0] += -0.02 if point[0] < shifted(component["center"])[0] else 0.02
    return contact_stack(*point)


def pcell_command(component: dict[str, Any], catalog: dict[str, Any]) -> str:
    cell = catalog["cells"][component["cell"]]
    parameters = cell["parameters"]
    center = shifted(component["center"])
    offset = cell["gencell_anchor_offset_um"]
    anchor = [center[0] - offset[0], center[1] - offset[1]]
    command = (
        f"box {fmt(anchor[0])}um {fmt(anchor[1])}um {fmt(anchor[0])}um {fmt(anchor[1])}um\n"
        "magic::gencell sky130::sky130_fd_pr__nfet_01v8 "
        f"{component['name']} w {fmt(parameters['width_um'])} l {fmt(parameters['length_um'])} "
        "nf 1 m 1 guard 0 conn_gates 1 full_metal 1 doports 0"
    )
    if component["orientation"] == "MY":
        command += f"\nselect cell {component['name']}\nsideways\nselect clear"
    elif component["orientation"] != "R0":
        raise ValueError(f"unsupported component orientation {component['orientation']}")
    return command


def terminal(component: dict[str, Any], name: str) -> list[float]:
    values = component["terminals"][name]
    if len(values) != 1:
        raise ValueError(f"{component['name']}.{name} is not a single terminal")
    return shifted(values[0])


def build_tcl(data: dict[str, Any], catalog: dict[str, Any]) -> str:
    instances = "\n".join(pcell_command(item, catalog) for item in data["devices"])
    commands: list[str] = []
    # Every D/S terminal gets the same legal parent-level Via-1 landing.  GM
    # and tail gates promote in place.  Switch gates first escape on M1, then
    # promote outside the current trunks so neither their M2 nor M3 landing
    # plates can touch the signal path.  The four breakouts deliberately stop
    # on M3; a balanced group spine performs the one later promotion to M4.
    for item in data["devices"]:
        for terminal_name in ("D", "S"):
            commands.extend(device_contact_stack(item, terminal_name))
        if not item["name"].startswith("XSW_"):
            point = terminal(item, "G")
            commands.extend(contact_stack(*point))
            commands.extend(via2_stack(*point))
            commands.extend(via3_stack(*point))
    for promotion in data["switch_gate_promotions"]:
        point = shifted(promotion["point"])
        commands.extend(contact_stack(*point))
        commands.extend(compact_via2_tall_stack(*point))
    for segments in data["routes"].values():
        commands.extend(route(item) for item in segments)
    # Explicit layer changes exist only at named branch points.
    for point in ([1.08, 11.465], [1.78, 9.435], [2.20, 2.975]):
        commands.extend(compact_via2_stack(*shifted(point)))

    tile = data["tile_bbox"]
    guard = [
        ORIGIN[0] + tile[0] - 0.8,
        ORIGIN[1] + tile[1] - 0.8,
        ORIGIN[0] + tile[2] + 0.8,
        ORIGIN[1] + tile[3] + 0.8,
    ]
    guard_join = [ORIGIN[0] + data["boundary_ports"]["VGND"]["point"][0], guard[1]]
    ground_boundary = shifted(data["boundary_ports"]["VGND"]["point"])
    commands.append(wire_v("metal3", ground_boundary[0], guard_join[1], ground_boundary[1], 0.40))
    commands.extend(li_to_m1_stack(*guard_join))
    commands.extend(contact_stack(*guard_join))
    commands.extend(via2_stack(*guard_join))
    commands_text = "\n".join(commands)

    labels = []
    for name, port in data["boundary_ports"].items():
        point = shifted(port["point"])
        layer = port["layer"]
        labels.append(
            f"box {fmt(point[0] - 0.20)}um {fmt(point[1] - 0.20)}um "
            f"{fmt(point[0] + 0.20)}um {fmt(point[1] + 0.20)}um\n"
            f"label {name} center {layer}\nport make\n"
            f"port class {'input' if name not in ('outp', 'outn') else 'output'}\n"
            f"port use {'ground' if name == 'VGND' else 'signal'}\n"
            "port connections n s e w"
        )
    label_text = "\n".join(labels)

    return f"""# Generated by v3/tools/generate_vector_unit_pilot.py; do not edit.
set PROJECT_ROOT [file normalize [pwd]]
set WORKDIR [file join $PROJECT_ROOT build v3 vector_unit_pilot]
set SOURCE_TOP v3_vector_unit_source
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

# Pilot-only shared substrate guard.  The production channel uses one guard
# around the complete 3x5 unit matrix, never one ring per unit.
box {fmt(guard[0])}um {fmt(guard[1])}um {fmt(guard[2])}um {fmt(guard[3])}um
sky130::subconn_guard_draw

{commands_text}

# Name the substrate at the guard itself as well as the routed M3 port.
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
puts "V3_VECTOR_UNIT_DRC_COUNT=$drc_count"
if {{$drc_count != 0}} {{
    feedback save [file join $WORKDIR drc_feedback.txt]
    error "vector-unit pilot has DRC errors"
}}
extract unique notopports
extract do local
extract all
set extraction_feedback [feedback count]
puts "V3_VECTOR_UNIT_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
if {{$extraction_feedback != 0}} {{
    feedback save [file join $WORKDIR extraction_feedback.txt]
    error "vector-unit pilot extraction produced feedback"
}}
ext2spice lvs
ext2spice hierarchy off
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice -o [file join $WORKDIR ${{TOP}}_flat.spice] ${{TOP}}.ext
gds compress 0
gds write [file join $WORKDIR ${{TOP}}.gds]
puts "V3_VECTOR_UNIT_GDS_FEEDBACK_COUNT=[feedback count]"
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
