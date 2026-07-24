#!/usr/bin/env python3
"""Generate symmetric local phase-selector routing from measured cell pins."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from check_route_feasibility import component_ports
from generate_critical_signal_routes import (
    DBU_UM,
    corner_pad,
    fmt,
    li_contact_stack,
    rect,
    via2_stack,
    via3_stack,
    wire_h,
    wire_v,
)


TOP = "v2_four_channel_phase_routed"
STAGE = "phase_selector_routes"


def pick_port(
    component: dict[str, Any],
    terminal: str,
    target: tuple[float, float],
    channel_x: float,
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
) -> tuple[float, float]:
    points = component_ports(component, terminal, dimensions, catalog)
    selected = min(points, key=lambda point: math.dist(point, target))
    if math.dist(selected, target) > DBU_UM / 2.0:
        raise ValueError(
            f"{component['name']}.{terminal}: target {target} not in measured {points}"
        )
    return channel_x + selected[0], selected[1]


def m2_pin(point: tuple[float, float]) -> list[str]:
    return li_contact_stack(point[0], point[1])


def m3_pin(point: tuple[float, float]) -> list[str]:
    return [*m2_pin(point), *via2_stack(point[0], point[1])]


def m3_escape(point: tuple[float, float], column_x: float) -> list[str]:
    """Reach M3 on a nearby private column without crowding the LI pin.

    The selector output pins are closer than two conservative M3 landing pads
    plus spacing.  A short M2 escape is therefore both shorter and safer than
    forcing adjacent via2 stacks directly onto those pins.
    """
    return [
        *m2_pin(point),
        wire_h("metal2", point[0], column_x, point[1], 0.32),
        *via2_stack(column_x, point[1]),
    ]


def m3_escape_up(point: tuple[float, float], access_y: float) -> list[str]:
    """Delay an M3 transition until it clears an existing lower M3 route."""
    return [
        *m2_pin(point),
        wire_v("metal2", point[0], point[1], access_y, 0.32),
        *via2_stack(point[0], access_y),
    ]


def m2_join(first: tuple[float, float], second: tuple[float, float]) -> str:
    return rect(
        "metal2",
        min(first[0], second[0]),
        min(first[1], second[1]) - 0.16,
        max(first[0], second[0]),
        max(first[1], second[1]) + 0.16,
    )


def route_channel(
    channel: int,
    channel_x: float,
    template: dict[str, Any],
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
) -> tuple[list[str], dict[str, float]]:
    components = {item["name"]: item for item in template["components"]}
    commands: list[str] = []

    def pin(name: str, terminal: str, x: float, y: float) -> tuple[float, float]:
        return pick_port(
            components[name], terminal, (x, y), channel_x, dimensions, catalog
        )

    def start(net: str, description: str) -> None:
        commands.append(f"# {description} -> ch{channel}_{net}")

    # The two first-stage output trees are exact geometric mirrors.  The short
    # M2 pin escapes put every via2 landing on a private M3 column; direct via2
    # stacks at the two roots would miss the conservative M3 spacing target by
    # 25 nm.  Local branches stay outside the roots and only the true cross
    # branches use M4.  No M4 vertical segment or compensating meander exists.
    mux_a_root = pin("PMUX_A", "X", 0.4725, 127.98)
    mux_a_local = pin("PMUX_P", "A0", -1.3225, 124.555)
    mux_a_cross = pin("PMUX_N", "A1", 2.76, 124.655)
    mux_b_root = pin("PMUX_B", "X", 1.3675, 127.98)
    mux_b_local = pin("PMUX_N", "A0", 3.1625, 124.555)
    mux_b_cross = pin("PMUX_P", "A1", -0.92, 124.655)

    for name, root, local, cross, root_x, local_x, cross_x, transition_y in (
        ("mux_a", mux_a_root, mux_a_local, mux_a_cross, channel_x + 0.22,
         channel_x - 1.55, channel_x + 2.46, 127.20),
        ("mux_b", mux_b_root, mux_b_local, mux_b_cross, channel_x + 1.62,
         channel_x + 3.39, channel_x - 0.62, 126.30),
    ):
        start(name, f"CH{channel} first-stage mirrored tree")
        commands.extend(m3_escape(root, root_x))
        commands.extend(m3_escape(local, local_x))
        commands.extend(m3_escape(cross, cross_x))
        commands.append(wire_h("metal3", root_x, local_x, root[1], 0.40))
        commands.append(wire_v("metal3", local_x, root[1], local[1], 0.40))
        commands.append(corner_pad("metal3", local_x, root[1], 0.40))
        commands.append(wire_v("metal3", root_x, root[1], transition_y, 0.40))
        commands.extend(via3_stack(root_x, transition_y))
        commands.append(wire_h("metal4", root_x, cross_x, transition_y, 0.40))
        commands.extend(via3_stack(cross_x, transition_y))
        commands.append(wire_v("metal3", cross_x, transition_y, cross[1], 0.40))

    # Matched final-mux-to-gate routes remain on the outer sides of the row.
    for polarity, mux_name, and_name, mux_x, and_x in (
        ("p", "PMUX_P", "PAND_P", -3.2325, -4.1625),
        ("n", "PMUX_N", "PAND_N", 5.0725, 6.0025),
    ):
        root = pin(mux_name, "X", mux_x, 124.26)
        leaf = pin(and_name, "A", and_x, 121.20)
        start(f"mux_{polarity}_out", f"CH{channel} {mux_name}.X to {and_name}.A")
        commands.extend(m3_pin(root))
        leaf_access_y = 122.00
        commands.extend(m3_escape_up(leaf, leaf_access_y))
        commands.append(wire_h("metal3", root[0], leaf[0], root[1], 0.40))
        commands.append(wire_v("metal3", leaf[0], root[1], leaf_access_y, 0.40))
        commands.append(corner_pad("metal3", leaf[0], root[1], 0.40))

    # Gate-to-buffer links are adjacent mirrored M2 connections.
    for polarity, and_name, buffer_name, and_x, buffer_x in (
        ("p", "PAND_P", "PBUF_P", -2.51, -2.02),
        ("n", "PAND_N", "PBUF_N", 4.35, 3.86),
    ):
        root = pin(and_name, "X", and_x, 121.23)
        leaf = pin(buffer_name, "A", buffer_x, 121.195)
        start(f"gate_{polarity}", f"CH{channel} {and_name}.X to {buffer_name}.A")
        commands.extend(m2_pin(root))
        commands.extend(m2_pin(leaf))
        commands.append(m2_join(root, leaf))

    # Four phase leaves have identical M1/M2/M3 totals, not merely matched
    # complementary pairs.  A common via2 row sits above the mux row.  The
    # lower A0 pins use shorter horizontal and longer vertical M2 segments;
    # the upper A1 pins use the exact complementary split.  This equalizes
    # layer length without a U-turn or a non-functional stub.
    phase_access_y = 130.60
    phase_leaves = (
        ("phase_0_leaf", "PMUX_A", "A0", -1.4375, 128.275, -2.20),
        ("phase_90_leaf", "PMUX_A", "A1", -1.43, 129.14, 0.1975),
        ("phase_270_leaf", "PMUX_B", "A1", 3.27, 129.14, 1.6425),
        ("phase_180_leaf", "PMUX_B", "A0", 3.2775, 128.275, 4.04),
    )
    for net, mux_name, terminal, px, py, track_local_x in phase_leaves:
        port = pin(mux_name, terminal, px, py)
        track_x = channel_x + track_local_x
        start(net, f"CH{channel} {mux_name}.{terminal} phase leaf")
        commands.extend(m2_pin(port))
        commands.append(wire_h("metal2", port[0], track_x, port[1], 0.32))
        commands.append(wire_v("metal2", track_x, port[1], phase_access_y, 0.32))
        commands.append(corner_pad("metal2", track_x, port[1], 0.32))
        commands.extend(via2_stack(track_x, phase_access_y))
        commands.append(wire_v("metal3", track_x, phase_access_y, 151.00, 0.40))
        commands.extend((
            f"box {fmt(track_x)}um 151.0000um {fmt(track_x)}um 151.0000um",
            f"label {{ch{channel}_{net}}} FreeSans 0.10u -met3",
        ))

    # Static phase-code inputs use otherwise empty vertical corridors.  They
    # end at named anchors for the later control-core route.
    # Do not use the upper horizontal S access.  Its centre is only 0.34 um
    # below the M1 VPWR rail; a legal mcon plus M1 landing overlaps that rail.
    # The lower inward S contacts share a clear M2 corridor.  They join first,
    # then use one via2 centred in the gap between the two M3 output trees.
    phase0_a = pin("PMUX_A", "S", -0.3175, 128.60)
    phase0_b = pin("PMUX_B", "S", 2.1575, 128.60)
    phase0_x = channel_x - 3.40
    start("phase_sel0", f"CH{channel} shared first-stage select")
    commands.extend(m2_pin(phase0_a))
    commands.extend(m2_pin(phase0_b))
    commands.append(wire_h("metal2", phase0_a[0], phase0_b[0], phase0_a[1], 0.32))
    phase0_transition_x = channel_x + 0.92
    phase0_transition_y = 128.70
    commands.append(wire_v(
        "metal2", phase0_transition_x, phase0_a[1], phase0_transition_y, 0.32
    ))
    commands.extend(via2_stack(phase0_transition_x, phase0_transition_y))
    commands.append(wire_h(
        "metal3", phase0_x, phase0_transition_x, phase0_transition_y, 0.40
    ))
    commands.append(wire_v("metal3", phase0_x, phase0_transition_y, 151.00, 0.40))

    phase1_p = pin("PMUX_P", "S", -0.28, 125.255)
    phase1_n = pin("PMUX_N", "S", 2.12, 125.255)
    phase1_x = channel_x + 5.24
    start("phase_sel1", f"CH{channel} shared final-stage select")
    commands.extend(m2_pin(phase1_p))
    commands.extend(m2_pin(phase1_n))
    commands.append(wire_h("metal2", phase1_p[0], phase1_x, phase1_p[1], 0.32))
    phase1_transition_y = 125.53
    commands.append(wire_v(
        "metal2", phase1_x, phase1_p[1], phase1_transition_y, 0.32
    ))
    commands.extend(via2_stack(phase1_x, phase1_transition_y))
    commands.append(wire_v("metal3", phase1_x, phase1_transition_y, 151.00, 0.40))

    # Both blanking gates share one enable.  The pre-existing LO roots occupy
    # M3 immediately below the AND row, so rise first on M2, move away from the
    # adjacent A pins, and use a compact stacked via2/via3 transition.  The M4
    # bus crosses the LO pair without contacting it and rises at the edge.
    enable_p = pin("PAND_P", "B", -3.435, 121.20)
    enable_n = pin("PAND_N", "B", 5.275, 121.20)
    enable_y = 121.80
    enable_x = channel_x + 7.00
    start("phase_enable", f"CH{channel} symmetric blanking enable")
    enable_p_x = channel_x - 3.00
    enable_n_x = channel_x + 4.84
    for port, drop_x in ((enable_p, enable_p_x), (enable_n, enable_n_x)):
        commands.extend(m2_pin(port))
        commands.append(wire_v("metal2", port[0], port[1], enable_y, 0.32))
        commands.append(wire_h("metal2", port[0], drop_x, enable_y, 0.32))
        commands.append(corner_pad("metal2", port[0], enable_y, 0.32))
        commands.extend(via2_stack(drop_x, enable_y))
        commands.extend(via3_stack(drop_x, enable_y))
    commands.append(wire_h("metal4", enable_p_x, enable_x, enable_y, 0.40))
    commands.append(wire_v("metal4", enable_x, enable_y, 151.00, 0.40))
    commands.append(corner_pad("metal4", enable_x, enable_y, 0.40))

    for net, x, layer in (
        ("phase_sel0", phase0_x, "met3"),
        ("phase_sel1", phase1_x, "met3"),
        ("phase_enable", enable_x, "met4"),
    ):
        commands.extend((
            f"box {fmt(x)}um 151.0000um {fmt(x)}um 151.0000um",
            f"label {{ch{channel}_{net}}} FreeSans 0.10u -{layer}",
        ))

    metrics = {
        "mux_a_local_m3_um": abs((channel_x + 0.22) - (channel_x - 1.55))
        + abs(mux_a_root[1] - mux_a_local[1]),
        "mux_b_local_m3_um": abs((channel_x + 1.62) - (channel_x + 3.39))
        + abs(mux_b_root[1] - mux_b_local[1]),
        "mux_a_cross_m4_um": abs((channel_x + 0.22) - (channel_x + 2.46)),
        "mux_b_cross_m4_um": abs((channel_x + 1.62) - (channel_x - 0.62)),
        "mux_a_cross_m3_um": abs(mux_a_root[1] - mux_a_cross[1]),
        "mux_b_cross_m3_um": abs(mux_b_root[1] - mux_b_cross[1]),
        "mux_a_pin_escape_m2_um": abs(mux_a_root[0] - (channel_x + 0.22))
        + abs(mux_a_local[0] - (channel_x - 1.55))
        + abs(mux_a_cross[0] - (channel_x + 2.46)),
        "mux_b_pin_escape_m2_um": abs(mux_b_root[0] - (channel_x + 1.62))
        + abs(mux_b_local[0] - (channel_x + 3.39))
        + abs(mux_b_cross[0] - (channel_x - 0.62)),
    }
    return commands, metrics


def generate(
    floorplan: dict[str, Any],
    template: dict[str, Any],
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
    channels: list[int],
    output: Path,
) -> dict[str, Any]:
    by_index = {int(item["index"]): item for item in floorplan["channels"]}
    commands: list[str] = []
    metrics: dict[str, Any] = {}
    for channel in channels:
        channel_commands, channel_metrics = route_channel(
            channel,
            float(by_index[channel]["center_x"]),
            template,
            dimensions,
            catalog,
        )
        commands.extend(channel_commands)
        metrics[f"ch{channel}"] = channel_metrics

    body = "\n".join(commands)
    tcl = f"""# Generated by v2/tools/generate_phase_selector_routes.py; do not edit.
set PROJECT_ROOT [pwd]
set SOURCE_GDS [file join $PROJECT_ROOT build v2 local_channel_routes magic v2_four_channel_local_routed.gds]
set OUT_DIR [file join $PROJECT_ROOT build v2 {STAGE} magic]
file mkdir $OUT_DIR
if {{![file exists $SOURCE_GDS]}} {{
    error "required local-route GDS does not exist: $SOURCE_GDS"
}}
gds read $SOURCE_GDS
if {{[lsearch -exact [cellname list all] v2_four_channel_local_routed] < 0}} {{
    error "local-route top cell was not imported"
}}
load v2_four_channel_local_routed
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
puts "PHASE_SELECTOR_ROUTE_DRC_COUNT=$drc_count"
if {{$drc_count != 0}} {{
    feedback save [file join $OUT_DIR phase_selector_route_drc.txt]
    error "refusing phase-routed artifact with $drc_count DRC errors"
}}
cd $OUT_DIR
save {TOP}.mag
feedback clear
gds compress 0
gds write {TOP}.gds
set gds_feedback [feedback count]
puts "PHASE_SELECTOR_ROUTE_GDS_FEEDBACK_COUNT=$gds_feedback"
if {{$gds_feedback != 0}} {{
    feedback save phase_selector_route_gds_feedback.txt
    error "refusing phase-routed artifact with $gds_feedback GDS writer problems"
}}
quit -noprompt
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(tcl, encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--floorplan", type=Path, default=Path("v2/layout/floorplan.json"))
    parser.add_argument("--template", type=Path, default=Path("v2/layout/channel_template.json"))
    parser.add_argument("--dimensions", type=Path, default=Path("v2/layout/pcell_dimensions.json"))
    parser.add_argument("--catalog", type=Path, default=Path("v2/layout/port_catalog.json"))
    parser.add_argument("--channels", default="0,1,2,3")
    parser.add_argument("--output", type=Path, default=Path("build/v2/phase_selector_routes/route.tcl"))
    args = parser.parse_args()
    channels = [int(value) for value in args.channels.split(",") if value]
    metrics = generate(
        json.loads(args.floorplan.read_text(encoding="utf-8")),
        json.loads(args.template.read_text(encoding="utf-8")),
        json.loads(args.dimensions.read_text(encoding="utf-8")),
        json.loads(args.catalog.read_text(encoding="utf-8")),
        channels,
        args.output,
    )
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
