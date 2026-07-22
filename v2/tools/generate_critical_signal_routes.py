#!/usr/bin/env python3
"""Generate first-pass V2 critical signal routes from measured physical ports.

This stage intentionally routes only the signal-critical one-channel topology:
input/VCM gates, GM/tail nodes, mixer outputs, and the equal-length dual-branch
LO pair.  Trim controls, power, guard rings, and global summing/tree geometry
are added in later clean-regeneration stages.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from check_route_feasibility import component_ports


DBU_UM = 0.005
M1_PAD = 0.32
M2_WIDTH = 0.32
M3_LANDING_X = 0.31
M3_LANDING_Y = 0.20
VIA2_HALF = 0.20
VIA3_HALF = 0.20


def fmt(value: float) -> str:
    return f"{value:.4f}"


def rect(layer: str, x1: float, y1: float, x2: float, y2: float) -> str:
    left, right = sorted((x1, x2))
    bottom, top = sorted((y1, y2))
    return f"paint_rect {layer} {fmt(left)} {fmt(bottom)} {fmt(right)} {fmt(top)}"


def wire_h(layer: str, x1: float, x2: float, y: float, width: float) -> str:
    if abs(x2 - x1) <= DBU_UM / 2.0:
        return f"# skipped zero-length horizontal {layer} wire"
    return rect(layer, x1, y - width / 2.0, x2, y + width / 2.0)


def wire_v(layer: str, x: float, y1: float, y2: float, width: float) -> str:
    if abs(y2 - y1) <= DBU_UM / 2.0:
        return f"# skipped zero-length vertical {layer} wire"
    return rect(layer, x - width / 2.0, y1, x + width / 2.0, y2)


def corner_pad(layer: str, x: float, y: float, width: float) -> str:
    return rect(layer, x - width / 2.0, y - width / 2.0,
                x + width / 2.0, y + width / 2.0)


def contact_stack(x: float, y: float) -> list[str]:
    """Transition an existing M1 escape to M2 at its access point."""
    return [
        rect("metal1", x - M1_PAD / 2.0, y - M1_PAD / 2.0,
             x + M1_PAD / 2.0, y + M1_PAD / 2.0),
        rect("via1", x - 0.13, y - 0.13, x + 0.13, y + 0.13),
        rect("metal2", x - M2_WIDTH / 2.0, y - M2_WIDTH / 2.0,
             x + M2_WIDTH / 2.0, y + M2_WIDTH / 2.0),
    ]


def li_to_m1_stack(x: float, y: float) -> list[str]:
    """Attach M1 to an LI terminal at the measured terminal coordinate.

    Both the analog PCell terminal labels (``ndiffc``, ``polycont``, and
    ``xpolycontact``) and the standard-cell signal pins resolve to local
    interconnect in the extracted view.  M1 overlapping LI is insulating
    unless an explicit ``viali``/mcon is present.
    """
    return [
        rect("locali", x - 0.085, y - 0.085, x + 0.085, y + 0.085),
        rect("viali", x - 0.085, y - 0.085, x + 0.085, y + 0.085),
        # Match sky130::mcon_draw for a square 0.17 um mcon: 0.06 um
        # horizontal and 0.03 um vertical M1 enclosure.
        rect("metal1", x - 0.145, y - 0.115, x + 0.145, y + 0.115),
    ]


def li_contact_stack(x: float, y: float) -> list[str]:
    """Alias documenting that a standard-cell port is LI-only."""
    return [*li_to_m1_stack(x, y), *contact_stack(x, y)]


def via2_stack(x: float, y: float) -> list[str]:
    return [
        rect("metal2", x - VIA2_HALF, y - VIA2_HALF,
             x + VIA2_HALF, y + VIA2_HALF),
        rect("via2", x - VIA2_HALF, y - VIA2_HALF,
             x + VIA2_HALF, y + VIA2_HALF),
        rect("metal3", x - M3_LANDING_X, y - M3_LANDING_Y,
             x + M3_LANDING_X, y + M3_LANDING_Y),
    ]


def via3_stack(x: float, y: float) -> list[str]:
    return [
        rect("metal3", x - M3_LANDING_X, y - M3_LANDING_Y,
             x + M3_LANDING_X, y + M3_LANDING_Y),
        rect("via3", x - VIA3_HALF, y - VIA3_HALF,
             x + VIA3_HALF, y + VIA3_HALF),
        rect("metal4", x - VIA3_HALF, y - VIA3_HALF,
             x + VIA3_HALF, y + VIA3_HALF),
    ]


def shifted(points: list[list[float]], dx: float) -> list[list[float]]:
    return [[x + dx, y] for x, y in points]


def terminal_ladder(
    component: dict[str, Any],
    terminal: str,
    channel_x: float,
    access_y: float,
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
) -> tuple[list[str], float]:
    points = shifted(
        component_ports(component, terminal, dimensions, catalog), channel_x
    )
    if terminal == "G":
        points = [min(points, key=lambda item: abs(item[0] - (channel_x + float(component["x"]))))]
    commands: list[str] = []
    for x, original_y in points:
        commands.extend(li_to_m1_stack(x, original_y))
        if abs(access_y - original_y) > DBU_UM / 2.0:
            commands.append(wire_v("metal1", x, original_y, access_y, 0.23))
        commands.extend(contact_stack(x, access_y))
    xs = [point[0] for point in points]
    if len(xs) > 1:
        commands.append(wire_h("metal2", min(xs), max(xs), access_y, M2_WIDTH))
    return commands, sum(xs) / len(xs)


def terminal_to_track(
    component: dict[str, Any],
    terminal: str,
    channel_x: float,
    access_y: float,
    track_x: float,
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
) -> list[str]:
    commands, anchor_x = terminal_ladder(
        component, terminal, channel_x, access_y, dimensions, catalog
    )
    commands.append(wire_h("metal2", anchor_x, track_x, access_y, M2_WIDTH))
    commands.extend(via2_stack(track_x, access_y))
    return commands


def terminal_to_track_m2_escape(
    component: dict[str, Any],
    terminal: str,
    channel_x: float,
    access_y: float,
    track_x: float,
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
) -> list[str]:
    """Put via1 on every measured terminal, then stagger entirely on M2.

    This is reserved for the four B-row mixer-source branches.  Their lower
    access lanes would cross internal guarded-PCell straps if reached on M1;
    the exact-terminal via1 keeps ownership unambiguous and M2 crosses the
    PCell guard without touching it.
    """
    points = shifted(
        component_ports(component, terminal, dimensions, catalog), channel_x
    )
    commands: list[str] = []
    for x, original_y in points:
        commands.extend(li_contact_stack(x, original_y))
        if abs(access_y - original_y) > DBU_UM / 2.0:
            commands.append(wire_v("metal2", x, original_y, access_y, 0.23))
            commands.append(corner_pad("metal2", x, access_y, M2_WIDTH))
    xs = [point[0] for point in points]
    if len(xs) > 1:
        commands.append(wire_h("metal2", min(xs), max(xs), access_y, M2_WIDTH))
    anchor_x = sum(xs) / len(xs)
    commands.append(wire_h("metal2", anchor_x, track_x, access_y, M2_WIDTH))
    commands.extend(via2_stack(track_x, access_y))
    return commands


def terminal_to_track_m3_direct(
    component: dict[str, Any],
    terminal: str,
    channel_x: float,
    track_x: float,
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
) -> tuple[list[str], float]:
    """Leave an exact terminal vertically, then join a nearby M3 spine.

    The trim switches have their drain between a lower M2 ground bus and an
    upper M2 bias bus.  Moving that drain along M1 can touch the gate inside
    the PCell, while moving it vertically on M2 crosses one of those buses.
    A terminal-local via1/via2 stack followed by a short M3 branch is the
    shortest unambiguous escape and lets both source buses pass underneath.
    """
    points = shifted(
        component_ports(component, terminal, dimensions, catalog), channel_x
    )
    if len(points) != 1:
        raise ValueError(
            f"M3-direct escape requires one terminal point, got {len(points)}"
        )
    terminal_x, terminal_y = points[0]
    commands = li_contact_stack(terminal_x, terminal_y)
    commands.extend(via2_stack(terminal_x, terminal_y))
    commands.append(wire_h("metal3", terminal_x, track_x, terminal_y, 0.40))
    return commands, terminal_y


def terminal_to_track_m1_outward(
    component: dict[str, Any],
    terminal: str,
    channel_x: float,
    access_y: float,
    track_x: float,
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
) -> list[str]:
    """Escape laterally from a one-finger terminal before changing Y on M1.

    In the compact trim-switch PCell, dropping M1 vertically at a diffusion
    contact captures the internal gate strap.  The diffusion terminals face
    outward, so a 0.30 um lateral M1 escape clears the PCell bounding box;
    only then does the route descend to its assigned M2 source-bus lane.
    """
    points = shifted(
        component_ports(component, terminal, dimensions, catalog), channel_x
    )
    if len(points) != 1:
        raise ValueError(
            f"M1-outward escape requires one terminal point, got {len(points)}"
        )
    terminal_x, terminal_y = points[0]
    center_x = channel_x + float(component["x"])
    direction = 1.0 if terminal_x > center_x else -1.0
    escape_x = terminal_x + direction * 0.30
    commands = li_to_m1_stack(terminal_x, terminal_y)
    commands.append(wire_h("metal1", terminal_x, escape_x, terminal_y, 0.23))
    commands.append(wire_v("metal1", escape_x, terminal_y, access_y, 0.23))
    commands.extend(contact_stack(escape_x, access_y))
    commands.append(wire_h("metal2", escape_x, track_x, access_y, M2_WIDTH))
    commands.extend(via2_stack(track_x, access_y))
    return commands


def terminal_to_track_m4_crossover(
    component: dict[str, Any],
    terminal: str,
    channel_x: float,
    access_y: float,
    track_x: float,
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
    exact_terminal_m2: bool = False,
) -> list[str]:
    """Cross one member of a differential pair on M4.

    A switching quad necessarily contains rows where the logical P/N outputs
    cross in physical X.  Keeping both crossed branches on M2 either shorts
    them or forces long detours.  The terminal fingers are collected locally
    on M2, lifted once at their centroid, crossed directly on M4, and dropped
    onto the named M3 output spine.  The complementary crossed row assigns
    this topology to the opposite polarity so aggregate P/N via count and
    conductor stack remain balanced.
    """
    points = shifted(
        component_ports(component, terminal, dimensions, catalog), channel_x
    )
    xs = [point[0] for point in points]
    if exact_terminal_m2:
        commands = []
        for x, original_y in points:
            commands.extend(li_contact_stack(x, original_y))
            if abs(access_y - original_y) > DBU_UM / 2.0:
                commands.append(wire_v("metal2", x, original_y, access_y, 0.23))
                commands.append(corner_pad("metal2", x, access_y, M2_WIDTH))
        commands.append(wire_h("metal2", min(xs), max(xs), access_y, M2_WIDTH))
    else:
        commands, _ = terminal_ladder(
            component, terminal, channel_x, access_y, dimensions, catalog
        )

    # Launch in the open corridor between the output and LO spines.  Launching
    # at the device centroid leaves only 0.215 um to the output spine; launching
    # at a terminal extreme collides with the inner LO spine.  The two fixed
    # corridor sites are mirrored about the channel's 0.92 um symmetry axis.
    symmetry_axis_x = channel_x + 0.92
    anchor_x = symmetry_axis_x - 2.95 if track_x > symmetry_axis_x else symmetry_axis_x + 2.95
    if anchor_x < min(xs) or anchor_x > max(xs):
        raise ValueError(
            f"M4 crossover launch {anchor_x:.3f} is outside terminal ladder "
            f"[{min(xs):.3f}, {max(xs):.3f}]"
        )
    commands.extend(via2_stack(anchor_x, access_y))
    commands.extend(via3_stack(anchor_x, access_y))
    commands.append(wire_h("metal4", anchor_x, track_x, access_y, 0.40))
    commands.extend(via3_stack(track_x, access_y))
    return commands


def track_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in plan["local_vertical_tracks"]}


def point_for_standard_cell(
    component: dict[str, Any],
    terminal: str,
    expected: list[float],
    channel_x: float,
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
) -> list[float]:
    candidates = shifted(
        component_ports(component, terminal, dimensions, catalog), channel_x
    )
    absolute_expected = [channel_x + float(expected[0]), float(expected[1])]
    if not any(math.dist(candidate, absolute_expected) < 1e-9 for candidate in candidates):
        raise ValueError(
            f"{component['name']}.{terminal}: expected {absolute_expected} not in {candidates}"
        )
    return absolute_expected


def generate_trim_channel(
    channel_index: int,
    channel_x: float,
    template: dict[str, Any],
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
    plan: dict[str, Any],
) -> list[str]:
    """Generate the guarded local tail bank and monotonic static controls."""
    components = {item["name"]: item for item in template["components"]}
    tracks = track_map(plan)
    commands: list[str] = []

    def net(name: str) -> str:
        if name == "vgnd_local":
            # The four guard rings share the die substrate and must therefore
            # have one intentional global name.  Per-channel ground labels
            # falsely imply isolation that does not exist in silicon.
            return "VGND"
        return f"ch{channel_index}_{name}"

    def tx(local_x: float) -> float:
        return channel_x + local_x

    def track_x(name: str) -> float:
        return tx(float(tracks[name]["x"]))

    def connect_track(
        component: str,
        terminal: str,
        net_name: str,
        access_y: float,
        x: float,
        escape_style: str = "metal1",
    ) -> None:
        commands.append(
            f"# CH{channel_index}.{component}.{terminal} -> {net(net_name)}"
        )
        if escape_style == "metal1":
            route = terminal_to_track(
                components[component], terminal, channel_x, access_y, x,
                dimensions, catalog,
            )
        elif escape_style == "terminal_m2":
            route = terminal_to_track_m2_escape(
                components[component], terminal, channel_x, access_y, x,
                dimensions, catalog,
            )
        elif escape_style == "terminal_m3_direct":
            route, actual_y = terminal_to_track_m3_direct(
                components[component], terminal, channel_x, x,
                dimensions, catalog,
            )
            if abs(actual_y - access_y) > DBU_UM / 2.0:
                raise ValueError(
                    f"{component}.{terminal}: M3-direct terminal y {actual_y} "
                    f"does not match requested access y {access_y}"
                )
        elif escape_style == "m1_outward":
            route = terminal_to_track_m1_outward(
                components[component], terminal, channel_x, access_y, x,
                dimensions, catalog,
            )
        else:
            raise ValueError(f"unsupported trim escape style {escape_style}")
        commands.extend(route)

    guard = template["guard_rings"][0]
    gx1, gy1, gx2, gy2 = map(float, guard["bbox"])
    commands.extend((
        f"# CH{channel_index}.trim_guard -> {net('vgnd_local')}",
        f"box {fmt(tx(gx1))}um {fmt(gy1)}um {fmt(tx(gx2))}um {fmt(gy2)}um",
        "sky130::subconn_guard_draw",
    ))

    ground_x = track_x("VGND_shield")
    tail_x = track_x("tail")
    vbias_x = track_x("vbias")

    # One explicit metal pickup ties the continuous LI guard to the local
    # ground/shield spine.  The PDK guard procedure itself does not add M1.
    guard_pickup_x = tx(gx1)
    guard_pickup_y = 38.75
    commands.extend(li_contact_stack(guard_pickup_x, guard_pickup_y))
    commands.append(
        wire_h("metal2", guard_pickup_x, ground_x, guard_pickup_y, M2_WIDTH)
    )
    commands.extend(via2_stack(ground_x, guard_pickup_y))

    # Fixed 42-unit bank.  Source/drain/gate lanes are monotonically ordered
    # below, at, and above each row; no alternating diffusion is collected on
    # the same M2 line before its short M1 escape.
    for name in ("TMAIN0", "TMAIN1", "TMAIN2"):
        y = float(components[name]["y"])
        connect_track(name, "S", "vgnd_local", y - 0.60, ground_x)
        connect_track(name, "D", "tail", y + 0.60, tail_x)
        connect_track(name, "G", "vbias", y + 1.30, vbias_x)

    bit_devices = {
        3: ("TTRIM8", -0.53, 42.20),
        2: ("TTRIM4", -2.99, 44.80),
        1: ("TTRIM2", 1.93, 44.80),
        0: ("TTRIM1", 4.39, 44.80),
    }
    gate_track_endpoints: dict[int, list[float]] = {}
    for bit, (name, local_gate_x, gate_y) in bit_devices.items():
        y = float(components[name]["y"])
        connect_track(name, "S", "vgnd_local", y - 0.60, ground_x)
        connect_track(name, "D", "tail", y + 0.60, tail_x)
        connect_track(name, "G", f"trim_gate{bit}", gate_y, tx(local_gate_x))
        gate_track_endpoints[bit] = [gate_y]

    # The switch drains leave locally on M3.  Two horizontal M2 source buses
    # sit below them at 0.50 um pitch: bias first, then ground.  This ordering
    # clears both the trim-gate via2 pads below and drain via2 pads above.
    for bit in (2, 3, 1, 0):
        on = f"TSW{bit}_ON"
        off = f"TSW{bit}_OFF"
        gate_x = tx(bit_devices[bit][1])
        # The switch drain sits below its gate inside this compact PCell.  An
        # M1 descent clips the internal gate strap, while an M2 descent would
        # cross the shared source buses.  Rise at D and join the nearby trim
        # spine on M3; the source buses pass underneath on M2.
        connect_track(
            on, "D", f"trim_gate{bit}", 46.50, gate_x, "terminal_m3_direct"
        )
        connect_track(
            off, "D", f"trim_gate{bit}", 46.50, gate_x, "terminal_m3_direct"
        )
        gate_track_endpoints[bit].append(46.50)
        connect_track(
            off, "S", "vgnd_local", 45.85, ground_x, "m1_outward"
        )
        connect_track(on, "S", "vbias", 45.35, vbias_x, "m1_outward")

    for bit, ys in gate_track_endpoints.items():
        commands.append(
            f"# vertical trim gate {bit} -> {net(f'trim_gate{bit}') }"
        )
        commands.append(
            wire_v("metal3", tx(bit_devices[bit][1]), min(ys), max(ys), 0.40)
        )

    # Relocating the inverter row below the guard makes every static-control
    # route a single vertical M4 column.  The local M2 hookups are disjoint in
    # physical [2,3,1,0] order and no output-crossover bridge is required.
    control_columns = {
        (2, False): -3.385, (2, True): -2.155,
        (3, False): -1.230, (3, True): -0.530,
        (1, False): 2.370, (1, True): 3.070,
        (0, False): 3.995, (0, True): 5.225,
    }
    for bit in (2, 3, 1, 0):
        inverter = components[f"TINV{bit}"]
        for complement, inverter_port, switch_name in (
            (False, "A", f"TSW{bit}_ON"),
            (True, "Y", f"TSW{bit}_OFF"),
        ):
            logical = f"trim_b{bit}{'_b' if complement else ''}"
            switch_point = shifted(
                component_ports(
                    components[switch_name], "G", dimensions, catalog
                ), channel_x,
            )[0]
            column_x = tx(control_columns[(bit, complement)])
            inverter_points = shifted(
                component_ports(inverter, inverter_port, dimensions, catalog),
                channel_x,
            )
            inverter_point = (
                max(inverter_points, key=lambda point: point[1])
                if complement else inverter_points[0]
            )
            commands.append(
                f"# CH{channel_index}.{switch_name}.G -> {net(logical)}"
            )
            commands.extend(li_contact_stack(switch_point[0], switch_point[1]))
            commands.append(
                wire_h(
                    "metal2", switch_point[0], column_x,
                    switch_point[1], M2_WIDTH,
                )
            )
            bottom_transition_y = 48.185 if complement else switch_point[1]
            if abs(bottom_transition_y - switch_point[1]) > DBU_UM / 2.0:
                commands.append(
                    wire_v(
                        "metal2", column_x, switch_point[1],
                        bottom_transition_y, 0.23,
                    )
                )
                commands.append(
                    corner_pad("metal2", column_x, bottom_transition_y, M2_WIDTH)
                )
            commands.extend(via2_stack(column_x, bottom_transition_y))
            commands.extend(via3_stack(column_x, bottom_transition_y))
            commands.append(
                wire_v(
                    "metal4", column_x, bottom_transition_y,
                    inverter_point[1], 0.40,
                )
            )
            commands.extend(li_contact_stack(inverter_point[0], inverter_point[1]))
            commands.append(
                wire_h(
                    "metal2", inverter_point[0], column_x,
                    inverter_point[1], M2_WIDTH,
                )
            )
            commands.extend(via2_stack(column_x, inverter_point[1]))
            commands.extend(via3_stack(column_x, inverter_point[1]))

    # Bridge the deliberate one-site gaps in the tapped inverter row.  These
    # are real standard-cell M1 supply rails, not signal-route detours.
    inv_height = float(dimensions["pcells"]["sc_hd_inv_1"]["height_um"])
    rail_bottom = float(components["TINV2"]["y"]) - inv_height / 2.0
    rail_top = float(components["TINV2"]["y"]) + inv_height / 2.0
    rail_left = tx(
        float(components["PTAP3"]["x"])
        - float(dimensions["pcells"]["sc_hd_tapvpwrvgnd_1"]["width_um"]) / 2.0
    )
    rail_right = tx(
        float(components["TINV0"]["x"])
        + float(dimensions["pcells"]["sc_hd_inv_1"]["width_um"]) / 2.0
    )
    commands.append(f"# local inverter VGND rail -> {net('vgnd_local')}")
    commands.append(wire_h("metal1", ground_x, rail_right, rail_bottom, 0.48))
    commands.extend(contact_stack(ground_x, rail_bottom))
    commands.extend(via2_stack(ground_x, rail_bottom))
    commands.append(f"# local inverter VPWR rail -> {net('vpwr_local')}")
    commands.append(wire_h("metal1", rail_left, rail_right, rail_top, 0.48))

    commands.append(f"# vertical ground shield -> {net('vgnd_local')}")
    commands.append(wire_v("metal3", ground_x, rail_bottom, 81.00, 0.40))
    # The centered tail spine passes between two selector pairs.  A short M4
    # bridge through the switch row is intentional: staying on M3 there would
    # touch the terminal-local M3 drain landings on both sides.  This is a
    # straight layer hop, not a lateral detour.
    tail_bridge_bottom = 45.20
    tail_bridge_top = 47.80
    commands.append(f"# tail-bank lower trunk -> {net('tail')}")
    commands.append(wire_v("metal3", tail_x, 31.60, tail_bridge_bottom, 0.50))
    commands.extend(via3_stack(tail_x, tail_bridge_bottom))
    commands.append(f"# tail-bank M4 switch-row bridge -> {net('tail')}")
    commands.append(
        wire_v("metal4", tail_x, tail_bridge_bottom, tail_bridge_top, 0.50)
    )
    commands.extend(via3_stack(tail_x, tail_bridge_top))
    commands.append(f"# tail-bank upper trunk -> {net('tail')}")
    commands.append(wire_v("metal3", tail_x, tail_bridge_top, 49.00, 0.50))
    commands.append(f"# local bias trunk -> {net('vbias')}")
    commands.append(wire_v("metal3", vbias_x, 32.30, 46.75, 0.40))

    for logical, point, layer in (
        ("vgnd_local", (ground_x, guard_pickup_y), "met3"),
        ("vbias", (vbias_x, 40.0), "met3"),
    ):
        commands.extend((
            f"# net label: {net(logical)}",
            f"box {fmt(point[0])}um {fmt(point[1])}um {fmt(point[0])}um {fmt(point[1])}um",
            f"label {{{net(logical)}}} FreeSans 0.10u -{layer}",
        ))
    return commands


def generate_channel(
    channel_index: int,
    channel_x: float,
    template: dict[str, Any],
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
    plan: dict[str, Any],
) -> tuple[list[str], dict[str, dict[str, float]]]:
    components = {item["name"]: item for item in template["components"]}
    tracks = track_map(plan)
    commands: list[str] = []
    endpoints: dict[str, list[float]] = defaultdict(list)

    def net(name: str) -> str:
        return f"ch{channel_index}_{name}"

    def x(track: str) -> float:
        return channel_x + float(tracks[track]["x"])

    def connect(component: str, terminal: str, net_name: str, access_y: float,
                track: str, escape_style: str = "metal1") -> None:
        commands.append(f"# CH{channel_index}.{component}.{terminal} -> {net(net_name)}")
        if escape_style == "metal1":
            commands.extend(
                terminal_to_track(
                    components[component], terminal, channel_x, access_y, x(track),
                    dimensions, catalog,
                )
            )
        elif escape_style == "terminal_m2":
            commands.extend(
                terminal_to_track_m2_escape(
                    components[component], terminal, channel_x, access_y, x(track),
                    dimensions, catalog,
                )
            )
        elif escape_style == "metal4_crossover":
            commands.extend(
                terminal_to_track_m4_crossover(
                    components[component], terminal, channel_x, access_y, x(track),
                    dimensions, catalog,
                )
            )
        elif escape_style == "terminal_m2_m4_crossover":
            commands.extend(
                terminal_to_track_m4_crossover(
                    components[component], terminal, channel_x, access_y, x(track),
                    dimensions, catalog, exact_terminal_m2=True,
                )
            )
        else:
            raise ValueError(f"unsupported terminal escape style {escape_style}")
        endpoints[track].append(access_y)

    # Input: the pin and bias-resistor terminal join a straight shield-adjacent
    # M3 spine; the two ABBA GM gate branches use distinct M2 rows.
    input_track = x("input")
    commands.append(f"# TinyTapeout ua[{channel_index}] boundary -> {net('input')}")
    commands.append(wire_v("metal4", channel_x, 0.50, 8.00, 0.40))
    commands.extend(via3_stack(channel_x, 8.00))
    commands.append(wire_h("metal3", channel_x, input_track, 8.00, 0.40))
    commands.append(corner_pad("metal3", input_track, 8.00, 0.40))
    endpoints["input"].append(8.00)
    connect("RINPUT", "R2", "input", 8.865, "input")
    connect("GM_SIG_A", "G", "input", 53.525, "input")
    connect("GM_SIG_B", "G", "input", 58.695, "input")

    # VCM leaves the upper resistor terminal on M4, crossing the local M3
    # collectors without vias, and descends only on its named reference spine.
    vcm_track = x("vcm")
    r1 = components["RINPUT"]
    r1_commands, r1_x = terminal_ladder(
        r1, "R1", channel_x, 83.765, dimensions, catalog
    )
    commands.append(f"# CH{channel_index}.RINPUT.R1 -> {net('vcm')}")
    commands.extend(r1_commands)
    commands.extend(via2_stack(r1_x, 83.765))
    commands.extend(via3_stack(r1_x, 83.765))
    commands.append(wire_h("metal4", r1_x, vcm_track, 83.765, 0.40))
    commands.extend(via3_stack(vcm_track, 83.765))
    endpoints["vcm"].append(83.765)
    connect("GM_REF_A", "G", "vcm", 53.525, "vcm")
    connect("GM_REF_B", "G", "vcm", 58.225, "vcm")

    # GM drain branches use mirrored 0.68 um row staggering.  In the lower
    # row P exits directly and N exits upward; the upper ABBA row reverses the
    # assignment.  This gives equal aggregate escape length while keeping
    # both M2 ladders and their terminal mcon pads disjoint.
    connect("GM_SIG_A", "D", "gm_p", 52.000, "gm_p")
    connect("GM_SIG_B", "D", "gm_p", 57.380, "gm_p")
    connect("GM_REF_A", "D", "gm_n", 52.680, "gm_n")
    connect("GM_REF_B", "D", "gm_n", 56.700, "gm_n")

    # All four GM sources meet the centered tail bus. Same-net ladders may
    # overlap intentionally; no extra layer transition is introduced.
    for component, access_y in (
        ("GM_SIG_A", 51.360), ("GM_REF_A", 51.360),
        ("GM_REF_B", 56.060), ("GM_SIG_B", 56.060),
    ):
        connect(component, "S", "tail", access_y, "tail")
    endpoints["tail"].append(49.00)

    mixer = (
        # component, source net/track/access, drain net/track/access/style,
        # LO net/track/access.  The two physical crossover rows alternate
        # which polarity uses M4, balancing the differential conductor stack.
        ("SW1_A", "gm_p", "gm_p", 64.360, "out_p", "out_p", 65.640, "metal1", "lop", "lop_outer", 66.525),
        ("SW3_A", "gm_n", "gm_n", 64.360, "out_n", "out_n", 65.640, "metal1", "lop", "lop_outer", 66.525),
        ("SW2_A", "gm_p", "gm_p", 69.060, "out_n", "out_n", 69.720, "metal4_crossover", "lon", "lon_outer", 71.225),
        ("SW4_A", "gm_n", "gm_n", 69.060, "out_p", "out_p", 70.360, "metal1", "lon", "lon_outer", 71.225),
        ("SW4_B", "gm_n", "gm_n", 72.900, "out_p", "out_p", 75.040, "metal1", "lon", "lon_inner", 76.300),
        ("SW2_B", "gm_p", "gm_p", 73.600, "out_n", "out_n", 75.040, "metal1", "lon", "lon_inner", 76.300),
        ("SW3_B", "gm_n", "gm_n", 78.300, "out_n", "out_n", 80.380, "terminal_m2", "lop", "lop_inner", 81.000),
        ("SW1_B", "gm_p", "gm_p", 77.600, "out_p", "out_p", 79.760, "terminal_m2_m4_crossover", "lop", "lop_inner", 81.000),
    )
    for item in mixer:
        (component, source_net, source_track, source_y,
         drain_net, drain_track, drain_y, drain_style,
         lo_net, lo_track, lo_y) = item
        connect(
            component, "S", source_net, source_y, source_track,
            "terminal_m2" if component.endswith("_B") else "metal1",
        )
        connect(component, "D", drain_net, drain_y, drain_track, drain_style)
        connect(component, "G", lo_net, lo_y, lo_track)

    # The two LO roots use the exact selected std-cell output access points.
    for polarity, buffer, expected, branch_tracks in (
        ("lop", "PBUF_P", [-1.20, 120.495], ("lop_outer", "lop_inner")),
        ("lon", "PBUF_N", [3.04, 120.495], ("lon_inner", "lon_outer")),
    ):
        root = point_for_standard_cell(
            components[buffer], "X", expected, channel_x, dimensions, catalog
        )
        commands.append(f"# CH{channel_index}.{buffer}.X -> {net(polarity)}")
        commands.extend(li_contact_stack(root[0], root[1]))
        commands.extend(via2_stack(root[0], root[1]))
        branch_xs = [x(name) for name in branch_tracks]
        commands.append(wire_h("metal3", root[0], max(branch_xs), root[1], 0.50))
        if min(branch_xs) < root[0]:
            commands.append(wire_h("metal3", min(branch_xs), root[0], root[1], 0.50))
        for track in branch_tracks:
            endpoints[track].append(root[1])
            commands.append(corner_pad("metal3", x(track), root[1], 0.50))

    # Paint only the useful endpoint-to-endpoint extent of each reserved bus.
    for track_name, ys in endpoints.items():
        track = tracks[track_name]
        if len(ys) < 2:
            continue
        commands.append(f"# vertical track {track_name} -> {net(track['net'])}")
        commands.append(
            wire_v("metal3", x(track_name), min(ys), max(ys), float(track["width"]))
        )

    # The local output buses terminate at real future summing-tree anchors.
    for track_name in ("out_p", "out_n"):
        commands.append(f"# output anchor {track_name} -> {net(track_name)}")
        commands.append(wire_v("metal3", x(track_name), min(endpoints[track_name]), 90.0, 0.50))
        endpoints[track_name].append(90.0)

    # Labels are placed on single-layer roots after all conductor painting.
    label_points = {
        "input": (input_track, 8.0),
        "vcm": (vcm_track, 83.765),
        "tail": (x("tail"), 49.0),
        "gm_p": (x("gm_p"), 60.0),
        "gm_n": (x("gm_n"), 60.0),
        "out_p": (x("out_p"), 90.0),
        "out_n": (x("out_n"), 90.0),
        "lop": (x("lop_outer"), 120.495),
        "lon": (x("lon_outer"), 120.495),
    }
    for logical_net, (label_x, label_y) in label_points.items():
        commands.extend(
            (
                f"# net label: {net(logical_net)}",
                f"box {fmt(label_x)}um {fmt(label_y)}um {fmt(label_x)}um {fmt(label_y)}um",
                f"label {{{net(logical_net)}}} FreeSans 0.10u -met3",
            )
        )

    metrics = {
        "lop_vertical_um": (120.495 - 66.525) + (120.495 - 80.625),
        "lon_vertical_um": (120.495 - 71.225) + (120.495 - 75.925),
        "lop_branch_pitch_um": abs(x("lop_outer") - x("lop_inner")),
        "lon_branch_pitch_um": abs(x("lon_outer") - x("lon_inner")),
    }
    return commands, metrics


def generate(
    floorplan: dict[str, Any],
    template: dict[str, Any],
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
    plan: dict[str, Any],
    channels: list[int],
    output: Path,
    selected_nets: set[str] | None = None,
    include_local_trim: bool = False,
) -> dict[str, Any]:
    all_commands: list[str] = []
    metrics: dict[str, Any] = {}
    by_index = {int(item["index"]): item for item in floorplan["channels"]}
    for channel in channels:
        commands, channel_metrics = generate_channel(
            channel, float(by_index[channel]["center_x"]), template,
            dimensions, catalog, plan,
        )
        if include_local_trim:
            commands.extend(
                generate_trim_channel(
                    channel, float(by_index[channel]["center_x"]), template,
                    dimensions, catalog, plan,
                )
            )
        if selected_nets is not None:
            commands = filter_net_commands(commands, selected_nets)
        all_commands.extend(commands)
        metrics[f"ch{channel}"] = channel_metrics

    if include_local_trim and selected_nets is None:
        tracks = track_map(plan)
        ground_offset = float(tracks["VGND_shield"]["x"])
        ground_xs = [
            float(by_index[channel]["center_x"]) + ground_offset
            for channel in channels
        ]
        ground_bus_y = 20.00
        all_commands.append("# shared analog ground bus -> VGND")
        for ground_x in ground_xs:
            all_commands.append(
                wire_v("metal3", ground_x, ground_bus_y, 22.64, 0.40)
            )
            all_commands.extend(via3_stack(ground_x, ground_bus_y))
        all_commands.append(
            wire_h(
                "metal4", min(ground_xs), max(ground_xs), ground_bus_y, 0.80
            )
        )
        label_x = min(ground_xs)
        all_commands.extend((
            "# net label: VGND",
            f"box {fmt(label_x)}um {fmt(ground_bus_y)}um "
            f"{fmt(label_x)}um {fmt(ground_bus_y)}um",
            "label {VGND} FreeSans 0.10u -met4",
        ))

    body = "\n".join(all_commands)
    top = (
        "v2_four_channel_local_routed"
        if include_local_trim else "v2_four_channel_critical_routed"
    )
    stage = "local_channel_routes" if include_local_trim else "critical_signal_routes"
    tcl = f"""# Generated by v2/tools/generate_critical_signal_routes.py; do not edit.
set PROJECT_ROOT [pwd]
set SOURCE_GDS [file join $PROJECT_ROOT build v2 four_channel_placement magic v2_four_channel_placement.gds]
set OUT_DIR [file join $PROJECT_ROOT build v2 {stage} magic]
file mkdir $OUT_DIR
if {{![file exists $SOURCE_GDS]}} {{
    error "required clean-placement GDS does not exist: $SOURCE_GDS"
}}
if {{[catch {{gds read $SOURCE_GDS}} import_error]}} {{
    error "failed to import clean-placement GDS: $import_error"
}}
if {{[lsearch -exact [cellname list all] v2_four_channel_placement] < 0}} {{
    error "clean-placement top cell was not imported"
}}
load v2_four_channel_placement
cellname rename {top}
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
puts "CRITICAL_SIGNAL_ROUTE_DRC_COUNT=$drc_count"
if {{$drc_count != 0}} {{
    feedback save [file join $OUT_DIR critical_signal_route_drc.txt]
    error "refusing critical routed artifact with $drc_count DRC errors"
}}
cd $OUT_DIR
save {top}.mag
feedback clear
gds compress 0
gds write {top}.gds
set gds_feedback [feedback count]
puts "CRITICAL_SIGNAL_ROUTE_GDS_FEEDBACK_COUNT=$gds_feedback"
if {{$gds_feedback != 0}} {{
    feedback save critical_signal_route_gds_feedback.txt
    error "refusing critical routed artifact with $gds_feedback GDS writer problems"
}}
quit -noprompt
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(tcl, encoding="utf-8")
    return metrics


def filter_net_commands(commands: list[str], selected_nets: set[str]) -> list[str]:
    """Keep complete generated command blocks for selected diagnostic nets.

    This intentionally operates after normal route construction so a
    single-net Magic/extraction probe exercises exactly the same geometry as
    the full candidate.  It is a debug/signoff aid, not a second router.
    """
    filtered: list[str] = []
    active = False
    for command in commands:
        if command.startswith("#"):
            match = re.search(r" -> (\S+)$", command)
            if match is None:
                match = re.match(r"# net label: (\S+)$", command)
            if match is not None:
                active = match.group(1) in selected_nets
        if active:
            filtered.append(command)
    return filtered


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channels", default="0", help="comma-separated channel indices")
    parser.add_argument(
        "--nets", default="",
        help="optional comma-separated exact net names for single-net extraction probes",
    )
    parser.add_argument(
        "--include-local-trim", action="store_true",
        help="also generate trim guard, tail bank, static controls, and local rails",
    )
    parser.add_argument("--output", type=Path, default=Path("build/v2/critical_signal_routes/route.tcl"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    channels = [int(item) for item in args.channels.split(",") if item]
    metrics = generate(
        json.loads((root / "v2/layout/floorplan.json").read_text()),
        json.loads((root / "v2/layout/channel_template.json").read_text()),
        json.loads((root / "v2/layout/pcell_dimensions.json").read_text()),
        json.loads((root / "v2/layout/port_catalog.json").read_text()),
        json.loads((root / "v2/layout/routing_plan.json").read_text()),
        channels,
        args.output,
        {item for item in args.nets.split(",") if item} or None,
        args.include_local_trim,
    )
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
