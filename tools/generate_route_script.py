#!/usr/bin/env python3
"""Generate deterministic Magic routing from placed SKY130 PCell ports."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "layout" / "circuit.json"
WORK = ROOT / "build" / "layout" / "buffered"
OUTPUT = ROOT / "build" / "layout" / "route.tcl"

# Magic's SKY130 database unit is 5 nm for these generated cells.
DBU_UM = 0.005
# Match the device-access and via landing widths.  Narrow necks between two
# wider pads form sub-rule notches when Magic writes and reads GDS polygons.
M2_WIDTH = 0.32
M3_WIDTH = 0.40
M4_WIDTH = 0.40
TRACK_Y0 = 72.0
TRACK_PITCH = 2.20


@dataclass(frozen=True)
class Label:
    layer: str
    name: str
    x: float
    y: float


@dataclass
class Connection:
    device: str
    terminal: str
    net: str
    kind: str
    labels: list[Label]
    original_labels: list[Label]
    anchor_x: float
    breakout_y: float
    column_x: float = 0.0


def fmt(value: float) -> str:
    return f"{value:.4f}"


def terminal_name(label: str) -> str:
    if label.startswith("D"):
        return "D"
    if label.startswith("S"):
        return "S"
    if label.startswith("G"):
        return "G"
    return label


def parse_top_instances(top: str) -> dict[str, tuple[str, int, int]]:
    lines = (WORK / f"{top}.mag").read_text().splitlines()
    instances: dict[str, tuple[str, int, int]] = {}
    cell = instance = None
    for line in lines:
        match = re.match(r"use\s+(\S+)\s+(\S+)", line)
        if match:
            cell, instance = match.groups()
            continue
        match = re.match(r"transform\s+1\s+0\s+(-?\d+)\s+0\s+1\s+(-?\d+)", line)
        if match and cell is not None and instance is not None:
            instances[instance] = (cell, int(match.group(1)), int(match.group(2)))
            cell = instance = None
    return instances


def parse_child_labels(cell: str, tx: int, ty: int) -> list[Label]:
    labels: list[Label] = []
    for line in (WORK / f"{cell}.mag").read_text().splitlines():
        match = re.match(
            r"rlabel\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+\d+\s+(\S+)",
            line,
        )
        if match:
            layer, x1, y1, _x2, _y2, name = match.groups()
            labels.append(
                Label(
                    layer=layer,
                    name=name,
                    x=(int(x1) + tx) * DBU_UM,
                    y=(int(y1) + ty) * DBU_UM,
                )
            )
    return labels


def breakout_y(kind: str, terminal: str, labels: list[Label]) -> float:
    ys = [label.y for label in labels]
    if kind in {"nmos", "pmos"}:
        rules = {
            # Drains are joined directly on M3; sources escape downward on M2.
            # Splitting the alternating diffusion groups across layers avoids
            # a D/S short in compact multifinger cells.
            "D": max(ys),
            # Keep the M2/via2 breakout clear of the nearby guard/body tap.
            # The 0.44 um drop leaves at least 0.14 um from the body M2 pad
            # after accounting for the 0.20 um via2 landing enclosure.
            "S": min(ys) - 0.44,
            "G": max(ys) + 0.30,
            "B": min(ys) - 0.30,
        }
    elif kind.startswith("res_"):
        rules = {
            # Keep the upper resistor terminal clear of the nearest global
            # M3 track after GDS polygonization.
            "R1": max(ys) + 0.45,
            "R2": min(ys) - 0.14,
            "B": min(ys) - 0.30,
        }
    else:
        rules = {}
    if terminal not in rules:
        raise ValueError(f"no breakout rule for {kind} terminal {terminal}")
    return rules[terminal]


def available_columns(count: int) -> list[float]:
    # Clear the used TinyTapeout boundary-pin columns, which already carry M4.
    reserved = [94.30, 113.62, 132.94, 138.46, 144.00, 152.26]
    candidates: list[float] = []
    x = 8.0
    while x <= 153.0:
        if all(abs(x - pin_x) >= 0.65 for pin_x in reserved):
            candidates.append(round(x, 4))
        x += 0.72
    if len(candidates) < count:
        raise ValueError(f"need {count} M4 columns but only {len(candidates)} are available")
    indices = [round(i * (len(candidates) - 1) / (count - 1)) for i in range(count)]
    chosen = [candidates[index] for index in indices]
    if len(set(chosen)) != count:
        raise ValueError("column selection produced a duplicate")
    return chosen


def rect(layer: str, x1: float, y1: float, x2: float, y2: float) -> str:
    left, right = sorted((x1, x2))
    bottom, top = sorted((y1, y2))
    return f"paint_rect {layer} {fmt(left)} {fmt(bottom)} {fmt(right)} {fmt(top)}"


def wire_h(layer: str, x1: float, x2: float, y: float, width: float) -> str:
    return rect(layer, x1, y - width / 2, x2, y + width / 2)


def wire_v(layer: str, x: float, y1: float, y2: float, width: float) -> str:
    return rect(layer, x - width / 2, y1, x + width / 2, y2)


def contact_stack(x: float, y: float, from_bulk: bool = False) -> list[str]:
    commands: list[str] = []
    if from_bulk:
        commands.extend(
            [
                rect("locali", x - 0.22, y - 0.22, x + 0.22, y + 0.22),
                rect("viali", x - 0.085, y - 0.085, x + 0.085, y + 0.085),
                rect("metal1", x - 0.20, y - 0.20, x + 0.20, y + 0.20),
            ]
        )
    commands.extend(
        [
            # Provide explicit enclosure on both sides of every M1/M2 cut.
            # PCell terminal labels can sit on narrow terminal metal that is
            # electrically connected but too small for a newly added via.
            rect("metal1", x - 0.16, y - 0.16, x + 0.16, y + 0.16),
            # Magic contact layers describe the full cut-plus-enclosure tile,
            # not only the 0.15 um physical cut.  A cut-sized tile passes the
            # interactive DRC but is dropped by the CIF/GDS generator.
            rect("via1", x - 0.13, y - 0.13, x + 0.13, y + 0.13),
            rect("metal2", x - 0.16, y - 0.16, x + 0.16, y + 0.16),
        ]
    )
    return commands


def metal1_escape(original: Label, tap: Label) -> list[str]:
    """Join a PCell's existing M1 terminal stripe to a staggered via tap."""
    if original.x != tap.x:
        raise ValueError("terminal escape must remain on the PCell M1 stripe")
    if original.y == tap.y:
        return []
    return [wire_v("metal1", tap.x, original.y, tap.y, 0.23)]


def via2_stack(x: float, y: float) -> list[str]:
    return [
        rect("metal2", x - 0.20, y - 0.20, x + 0.20, y + 0.20),
        rect("via2", x - 0.20, y - 0.20, x + 0.20, y + 0.20),
        # A 0.40 um square is below met3.6's 0.24 um^2 minimum.  Extend
        # horizontally so even a short anchor-to-column route has enough
        # area after GDS booleanization.
        rect("metal3", x - 0.31, y - 0.20, x + 0.31, y + 0.20),
    ]


def via3_stack(x: float, y: float) -> list[str]:
    return [
        rect("metal3", x - 0.31, y - 0.20, x + 0.31, y + 0.20),
        rect("via3", x - 0.20, y - 0.20, x + 0.20, y + 0.20),
        rect("metal4", x - 0.20, y - 0.20, x + 0.20, y + 0.20),
    ]


def route_connection(connection: Connection, track_y: float) -> list[str]:
    labels = connection.labels
    commands = [f"# {connection.device}.{connection.terminal} -> {connection.net}"]
    if connection.terminal == "D":
        # Alternating multifinger drain contacts are lifted independently and
        # joined on M3.  Their interleaved source contacts remain isolated on
        # M2 and escape below the device.
        for original, label in zip(connection.original_labels, labels, strict=True):
            commands.extend(metal1_escape(original, label))
            commands.extend(contact_stack(label.x, label.y))
            commands.extend(via2_stack(label.x, label.y))
        min_x = min(label.x for label in labels)
        max_x = max(label.x for label in labels)
        commands.append(wire_h("metal3", min_x, max_x, connection.breakout_y, M3_WIDTH))
        commands.append(
            wire_h("metal3", connection.anchor_x, connection.column_x,
                   connection.breakout_y, M3_WIDTH)
        )
        commands.extend(via3_stack(connection.column_x, connection.breakout_y))
        commands.append(
            wire_v("metal4", connection.column_x, connection.breakout_y,
                   track_y, M4_WIDTH)
        )
        commands.extend(via3_stack(connection.column_x, track_y))
        return commands

    for original, label in zip(connection.original_labels, labels, strict=True):
        commands.extend(metal1_escape(original, label))
        commands.extend(
            contact_stack(label.x, label.y, from_bulk=connection.terminal == "B")
        )
        commands.append(wire_v("metal2", label.x, label.y, connection.breakout_y, M2_WIDTH))
    min_x = min(label.x for label in labels)
    max_x = max(label.x for label in labels)
    commands.append(wire_h("metal2", min_x, max_x, connection.breakout_y, M2_WIDTH))
    commands.extend(via2_stack(connection.anchor_x, connection.breakout_y))
    commands.append(
        wire_h("metal3", connection.anchor_x, connection.column_x,
               connection.breakout_y, M3_WIDTH)
    )
    commands.extend(via3_stack(connection.column_x, connection.breakout_y))
    commands.append(
        wire_v("metal4", connection.column_x, connection.breakout_y, track_y, M4_WIDTH)
    )
    commands.extend(via3_stack(connection.column_x, track_y))
    return commands


def route_capacitor(connection: Connection, track_y: float) -> list[str]:
    label = connection.labels[0]
    if connection.terminal == "C2":
        # The C2 electrode is a tall M4 strip.  A separate parallel escape
        # leaves a 20 nm spacing sliver after GDS polygonization.  Continue
        # down on the electrode itself, then jog below the capacitor body.
        escape_y = label.y - 12.0
        return [
            f"# {connection.device}.{connection.terminal} -> {connection.net}",
            rect("metal4", label.x - 0.20, label.y - 0.20,
                 label.x + 0.20, label.y + 0.20),
            wire_v("metal4", label.x, escape_y, label.y, M4_WIDTH),
            wire_h("metal4", label.x, connection.column_x, escape_y, M4_WIDTH),
            wire_v("metal4", connection.column_x, escape_y, track_y, M4_WIDTH),
            # Square off both bends; otherwise GDS booleanization leaves a
            # 0.10 um re-entrant corner that violates met4.1.
            rect("metal4", label.x - 0.30, escape_y - 0.30,
                 label.x + 0.30, escape_y + 0.30),
            rect("metal4", connection.column_x - 0.30, escape_y - 0.30,
                 connection.column_x + 0.30, escape_y + 0.30),
            *via3_stack(connection.column_x, track_y),
        ]
    return [
        f"# {connection.device}.{connection.terminal} -> {connection.net}",
        rect("metal4", label.x - 0.20, label.y - 0.20, label.x + 0.20, label.y + 0.20),
        wire_h("metal4", label.x, connection.column_x, label.y, M4_WIDTH),
        wire_v("metal4", connection.column_x, label.y, track_y, M4_WIDTH),
        *via3_stack(connection.column_x, track_y),
    ]


def boundary_route(net: str, x: float, pin_y: float, track_y: float) -> list[str]:
    commands = [
        f"# TinyTapeout boundary pin -> {net}",
        wire_v("metal4", x, pin_y, track_y, M4_WIDTH),
        *via3_stack(x, track_y),
    ]
    # The two full-height power stripes sit left of the signal-track span.
    # Bridge their via3 landings to the M3 buses explicitly.
    if x < 6.5:
        commands.append(wire_h("metal3", x, 6.5, track_y, M3_WIDTH))
    return commands


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    top = str(manifest["top"])
    instances = parse_top_instances(top)
    connections: list[Connection] = []
    for device in manifest["devices"]:
        name = str(device["name"])
        kind = str(device["kind"])
        if name not in instances:
            raise ValueError(f"placed instance {name} not found in {top}.mag")
        cell, tx, ty = instances[name]
        grouped: dict[str, list[Label]] = {}
        for label in parse_child_labels(cell, tx, ty):
            grouped.setdefault(terminal_name(label.name), []).append(label)
        for terminal, net in device["nets"].items():
            labels = grouped.get(terminal, [])
            if not labels:
                raise ValueError(f"{name}: no physical labels for terminal {terminal}")
            labels.sort(key=lambda item: (item.x, item.y))
            original_labels = labels
            if kind in {"nmos", "pmos"}:
                finger_w = float(device["total_w"]) / int(device["nf"])
                if finger_w < 0.799:
                    raise ValueError(
                        f"{name}: per-finger width {finger_w} is too small for "
                        "DRC-clean staggered M1/M2 terminal escapes"
                    )
                if terminal in {"D", "S"}:
                    # D and S contacts alternate at half the finger pitch.  A
                    # centerline via pad therefore overlaps the opposite net.
                    # Move the two rows toward opposite edges of the PCell's
                    # existing vertical M1 contact stripes.
                    direction = 1.0 if terminal == "D" else -1.0
                    offset = direction * (finger_w / 2.0 - 0.16)
                    labels = [
                        Label(label.layer, label.name, label.x, label.y + offset)
                        for label in labels
                    ]
                elif terminal == "G":
                    # conn_gates=1 creates a continuous M1 gate rail.  Tap it
                    # once, above the device, rather than placing a via on
                    # every interleaved gate label.
                    original_labels = [labels[len(labels) // 2]]
                    label = original_labels[0]
                    labels = [
                        Label(label.layer, label.name, label.x, label.y + 0.45)
                    ]
            anchor_x = labels[len(labels) // 2].x
            y = labels[0].y if kind == "cap_mim_m3" else breakout_y(kind, terminal, labels)
            y += float(device.get("route_y_offsets", {}).get(terminal, 0.0))
            connections.append(
                Connection(
                    name,
                    terminal,
                    str(net),
                    kind,
                    labels,
                    original_labels,
                    anchor_x,
                    y,
                )
            )

    connections.sort(key=lambda item: (item.anchor_x, item.breakout_y,
                                        item.device, item.terminal))
    for connection, column in zip(connections, available_columns(len(connections)), strict=True):
        connection.column_x = column

    tracks = {
        net: TRACK_Y0 + index * TRACK_PITCH
        for index, net in enumerate(manifest["track_order"])
    }
    missing_tracks = {connection.net for connection in connections} - tracks.keys()
    if missing_tracks:
        raise ValueError(f"nets without tracks: {sorted(missing_tracks)}")

    commands: list[str] = []
    for net, y in tracks.items():
        commands.extend(
            [
                f"# horizontal net track: {net}",
                wire_h("metal3", 6.5, 154.5, y, M3_WIDTH),
                f"box 80um {fmt(y)}um 80um {fmt(y)}um",
                f"label {{{net}}} FreeSans 0.10u -met3",
            ]
        )
    for connection in connections:
        router = route_capacitor if connection.kind == "cap_mim_m3" else route_connection
        commands.extend(router(connection, tracks[connection.net]))

    boundary_pins = {
        "VDPWR": (2.00, 112.88),
        "VGND": (5.00, 112.88),
        "clk": (144.00, 225.26),
        "select": (138.46, 225.26),
        "ua[0]": (152.26, 0.50),
        "ua[1]": (132.94, 0.50),
        "ua[2]": (113.62, 0.50),
        "ua[3]": (94.30, 0.50),
    }
    for net, (x, y) in boundary_pins.items():
        commands.extend(boundary_route(net, x, y, tracks[net]))

    body = "\n".join(commands)
    script = f"""# Generated by tools/generate_route_script.py; do not edit.
set PROJECT_ROOT [pwd]
set WORKDIR $PROJECT_ROOT/build/layout/buffered
cd $WORKDIR
load {top}
select top cell
expand

proc paint_rect {{layer x1 y1 x2 y2}} {{
    box ${{x1}}um ${{y1}}um ${{x2}}um ${{y2}}um
    paint $layer
}}

{body}

save {top}.mag
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "ROUTED_DRC_COUNT=$drc_count"
writeall force
quit -noprompt
"""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(script)
    print(
        f"Generated {OUTPUT} with {len(connections)} device-terminal routes "
        f"on {len(tracks)} tracks"
    )


if __name__ == "__main__":
    main()
