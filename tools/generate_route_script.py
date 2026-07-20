#!/usr/bin/env python3
"""Generate deterministic Magic routing from placed SKY130 PCell ports."""

from __future__ import annotations

import json
import os
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
TRACK_Y0 = 125.0
TRACK_PITCH = 1.85
# The standard TinyTapeout top-edge M4 pins start at y=224.76 um.  Ordinary
# generated routes must stop at least met4.2 (0.30 um) below them, including
# the 0.20 um half-width of a horizontal M4 landing.  Keeping the breakout
# center at or below 224.25 um leaves 0.31 um of physical clearance.  The
# explicit clk/select boundary routes are emitted separately and intentionally
# connect to their corresponding pins.
SIGNAL_ROUTE_TOP_Y = 224.25
BOUNDARY_M4_X = [2.00, 5.00, 94.30, 113.62, 132.94, 138.46, 144.00, 152.26]
BOUNDARY_PINS = {
    "VDPWR": (2.00, 112.88),
    "VGND": (5.00, 112.88),
    "clk": (144.00, 225.26),
    "select": (138.46, 225.26),
    "ua[0]": (152.26, 0.50),
    "ua[1]": (132.94, 0.50),
    "ua[2]": (113.62, 0.50),
    "ua[3]": (94.30, 0.50),
}


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
    access_y: float
    breakout_y: float
    escape_x: float
    column_x: float = 0.0
    escape_fixed: bool = False


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


def check_instance_overlaps(top: str) -> None:
    """Reject physical PCell body overlap that same-layer DRC can miss."""
    lines = (WORK / f"{top}.mag").read_text().splitlines()
    boxes: dict[str, tuple[float, float, float, float]] = {}
    instance: str | None = None
    tx = ty = None
    for line in lines:
        match = re.match(r"use\s+\S+\s+(\S+)", line)
        if match:
            instance = match.group(1)
            tx = ty = None
            continue
        match = re.match(r"transform\s+1\s+0\s+(-?\d+)\s+0\s+1\s+(-?\d+)", line)
        if match and instance is not None:
            tx, ty = map(int, match.groups())
            continue
        match = re.match(r"box\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)", line)
        if match and instance is not None and tx is not None and ty is not None:
            x1, y1, x2, y2 = map(int, match.groups())
            boxes[instance] = tuple(
                coordinate * DBU_UM
                for coordinate in (x1 + tx, y1 + ty, x2 + tx, y2 + ty)
            )
            instance = None
    for index, (first_name, first) in enumerate(boxes.items()):
        for second_name, second in list(boxes.items())[index + 1 :]:
            overlap_x = min(first[2], second[2]) - max(first[0], second[0])
            overlap_y = min(first[3], second[3]) - max(first[1], second[1])
            # Generated guard-ring bounding boxes can intentionally graze at
            # their edges.  Reject only a material two-dimensional intrusion,
            # such as the former 2.5 x 4.0 um XBIAS/XRBIAS overlap.
            if overlap_x > 1.0 and overlap_y > 1.0:
                raise ValueError(
                    f"physical PCell overlap: {first_name} {first} and "
                    f"{second_name} {second}"
                )


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


def local_escape_x(kind: str, terminal: str, anchor_x: float) -> float:
    """Give each terminal a distinct local M4 dogleg corridor."""
    if kind in {"nmos", "pmos"}:
        offsets = {"D": 0.0, "S": 0.80, "G": -0.80, "B": 1.60}
    elif kind.startswith("res_"):
        offsets = {"R1": -0.80, "R2": 0.80, "B": 1.60}
    else:
        # C1 is the broad M4/capm top plate; C2 reaches the M3 bottom
        # plate through the narrow via3/M4 strip at the right edge.  Exit
        # those electrodes on opposite sides and only change layer outside
        # the complete capacitor footprint.
        # Put C1's first M3 landing more than capm.11's 1.34 um away from
        # the PCell plate edge (including the 0.31 um landing overhang).
        offsets = {"C1": -13.00, "C2": 1.30}
    try:
        return anchor_x + offsets[terminal]
    except KeyError as error:
        raise ValueError(f"no local escape offset for {kind}.{terminal}") from error


def capacitor_keepouts(
    connections: list[Connection],
) -> list[tuple[float, float, float, float]]:
    grouped: dict[str, dict[str, float]] = {}
    for connection in connections:
        if connection.kind == "cap_mim_m3":
            grouped.setdefault(connection.device, {})[connection.terminal] = connection.anchor_x
    keepouts: list[tuple[float, float, float, float]] = []
    for device, terminals in grouped.items():
        if set(terminals) != {"C1", "C2"}:
            raise ValueError(f"{device}: incomplete MIM capacitor terminals")
        # These margins include the PCell's M3 bottom plate, M4/capm top
        # plate, the right-hand C2 via strip, wire half-width, and the
        # independent signoff capm.11 spacing rule.
        c1 = next(
            connection
            for connection in connections
            if connection.device == device and connection.terminal == "C1"
        )
        keepouts.append(
            (
                terminals["C1"] - 12.60,
                terminals["C2"] + 0.80,
                c1.labels[0].y - 12.60,
                c1.labels[0].y + 12.60,
            )
        )
    return keepouts


def assign_local_escape_columns(
    connections: list[Connection],
    reserved_columns: list[float],
) -> None:
    """Move local doglegs off fixed TinyTapeout M4 boundary risers."""
    grouped: dict[str, list[Connection]] = {}
    for connection in connections:
        grouped.setdefault(connection.device, []).append(connection)
    shifts = [0.0]
    for index in range(1, 200):
        shifts.extend((-0.80 * index, 0.80 * index))
    # Clock/control devices occupy two dense rows at the top of the tile and
    # their breakouts frequently span both rows.  Reserve their local M4
    # columns across the complete bank; per-device uniqueness alone allowed a
    # select-gate dogleg to overlap a channel-LO gate dogleg.
    top_bank_used: list[float] = []
    for device_connections in grouped.values():
        used: list[float] = []
        for connection in sorted(
            device_connections,
            # Fixed analog-match escapes are reserved before the remaining
            # terminals of the same PCell choose their nearest legal lane.
            key=lambda item: (
                not item.escape_fixed,
                item.terminal != "D",
                item.terminal,
            ),
        ):
            connection_shifts = [0.0] if connection.escape_fixed else shifts
            for shift in connection_shifts:
                candidate = connection.escape_x + shift
                if not 6.8 <= candidate <= 154.2:
                    continue
                if any(abs(candidate - fixed_x) < 0.75 for fixed_x in BOUNDARY_M4_X):
                    continue
                if any(
                    abs(candidate - reserved_x) < 0.75
                    for reserved_x in reserved_columns
                ):
                    continue
                reserve_top_escape = (
                    connection.terminal == "G" and connection.labels[0].y >= 180.0
                )
                regional_used = top_bank_used if reserve_top_escape else []
                if any(
                    abs(candidate - other_x) < 0.75
                    for other_x in [*used, *regional_used]
                ):
                    continue
                connection.escape_x = candidate
                used.append(candidate)
                if reserve_top_escape:
                    top_bank_used.append(candidate)
                break
            else:
                qualifier = "fixed " if connection.escape_fixed else ""
                raise ValueError(
                    f"cannot place a {qualifier}local M4 escape for "
                    f"{connection.device}.{connection.terminal}"
                )


def available_columns(
    count: int,
    forbidden: list[float],
    keepouts: list[tuple[float, float, float, float]],
) -> list[float]:
    # Clear the used TinyTapeout boundary-pin columns, which already carry M4.
    reserved = BOUNDARY_M4_X
    candidates: list[float] = []
    x = 8.0
    while x <= 153.0:
        if (
            all(abs(x - pin_x) >= 0.75 for pin_x in reserved)
            and all(abs(x - anchor_x) >= 0.75 for anchor_x in forbidden)
            and all(not left <= x <= right for left, right, _bottom, _top in keepouts)
        ):
            candidates.append(round(x, 4))
        x += 0.80
    if len(candidates) < count:
        raise ValueError(f"need {count} M4 columns but only {len(candidates)} are available")
    return candidates


def assign_net_columns(
    connections: list[Connection],
    keepouts: list[tuple[float, float, float, float]],
    tracks: dict[str, float],
    match_constraints: list[dict[str, object]],
    endpoint_constraints: list[dict[str, object]],
    column_overrides: dict[str, float],
) -> None:
    """Use one M4 riser per net, assigning matched pairs together.

    The original router consumed a separate full-height M4 column for every
    device terminal and spread those columns across the complete tile.  That
    made even local mixer nodes unnecessarily long.  A shared riser keeps each
    local net close to the devices it actually connects.  Matching-critical
    pairs are allocated before ordinary nets, using the complete pin-to-device
    Manhattan tree as the cost instead of optimizing each net independently.
    """
    anchors: dict[str, list[float]] = {}
    for connection in connections:
        anchors.setdefault(connection.net, []).append(connection.anchor_x)
    medians = {
        net: sorted(values)[len(values) // 2]
        for net, values in anchors.items()
    }
    # A drain breakout briefly runs vertically on M4 at its local PCell
    # anchor.  Keep every shared net riser away from those immutable local
    # corridors; otherwise two unrelated nets can cross even though each has
    # a unique global column.
    local_risers = [
        connection.escape_x
        for connection in connections
    ]
    candidates = available_columns(len(medians), local_risers, keepouts)
    unused = set(candidates)
    columns: dict[str, float] = {}
    for net, column in sorted(column_overrides.items()):
        if net not in medians:
            raise ValueError(f"route-column override names unknown net {net}")
        if column not in unused:
            nearest = sorted(candidates, key=lambda candidate: abs(candidate - column))[:6]
            raise ValueError(
                f"route-column override {net}={column} is unavailable; "
                f"nearest legal columns are {nearest}"
            )
        columns[net] = column
        unused.remove(column)

    def route_proxy(net: str, column: float) -> float:
        net_connections = [item for item in connections if item.net == net]
        # M3 branches from each local escape to the shared column.  Equal-y
        # branches may later merge, but summing them here intentionally avoids
        # hiding a long unmatched device branch behind a coincident segment.
        horizontal = sum(abs(item.escape_x - column) for item in net_connections)
        fixed = sum(abs(item.anchor_x - item.escape_x) for item in net_connections)
        if net in BOUNDARY_PINS:
            pin_x, pin_y = BOUNDARY_PINS[net]
            horizontal += abs(pin_x - column)
            fixed += abs(tracks[net] - pin_y)
        # The common M4 column is a union, not one independent riser per
        # terminal.  Model its complete occupied span once.  Internal nets no
        # longer extend to an arbitrary M3 track; their trunk is bounded by
        # real terminal breakouts.  Boundary nets still include their M3 bus.
        ys = [item.access_y for item in net_connections]
        if net in BOUNDARY_PINS:
            ys.append(tracks[net])
        vertical = max(ys) - min(ys)
        return horizontal + vertical + fixed

    connection_by_endpoint = {
        f"{item.device}.{item.terminal}": item for item in connections
    }

    def endpoint_proxy(endpoint: str, net: str, column: float) -> tuple[float, float]:
        connection = connection_by_endpoint[endpoint]
        if connection.net != net:
            raise ValueError(f"endpoint constraint maps {endpoint} to wrong net {net}")
        # Internal matched nets are compared from each device to their shared
        # horizontal track.  Boundary-facing analog nets additionally include
        # the fixed TinyTapeout pin leg in the placement cost.
        pin_x, pin_y = BOUNDARY_PINS.get(net, (column, tracks[net]))
        local_rail = 0.0
        if connection.terminal == "D":
            local_rail = max(label.x for label in connection.labels) - min(
                label.x for label in connection.labels
            )
        metal3 = (
            local_rail
            + abs(connection.anchor_x - connection.escape_x)
            + abs(connection.escape_x - column)
            + abs(column - pin_x)
        )
        metal4 = (
            abs(tracks[net] - connection.access_y)
            + abs(tracks[net] - pin_y)
        )
        return metal3, metal4

    paired_nets: set[str] = set()
    for constraint in match_constraints:
        first, second = map(str, constraint["nets"])
        if first not in medians or second not in medians:
            continue
        if first in columns or second in columns:
            if first not in columns or second not in columns:
                raise ValueError(
                    f"matched pair {first}/{second} requires either zero or two overrides"
                )
            paired_nets.update((first, second))
            continue
        best: tuple[tuple[float, ...], float, float] | None = None
        for first_column in sorted(unused):
            first_proxy = route_proxy(first, first_column)
            for second_column in sorted(unused - {first_column}):
                second_proxy = route_proxy(second, second_column)
                average = (first_proxy + second_proxy) / 2.0
                mismatch = abs(first_proxy - second_proxy) / max(average, 1e-12)
                total = first_proxy + second_proxy
                displacement = (
                    abs(first_column - medians[first])
                    + abs(second_column - medians[second])
                )
                endpoint_penalty = 0.0
                endpoint_worst = 0.0
                for endpoint_constraint in endpoint_constraints:
                    if list(map(str, endpoint_constraint["nets"])) != [first, second]:
                        continue
                    first_endpoint, second_endpoint = map(
                        str, endpoint_constraint["endpoints"]
                    )
                    first_m3, first_m4 = endpoint_proxy(
                        first_endpoint, first, first_column
                    )
                    second_m3, second_m4 = endpoint_proxy(
                        second_endpoint, second, second_column
                    )
                    layer_limit = float(
                        endpoint_constraint["max_layer_length_mismatch_percent"]
                    ) / 100.0
                    total_limit = float(
                        endpoint_constraint["max_total_length_mismatch_percent"]
                    ) / 100.0
                    comparisons = (
                        (first_m3, second_m3, layer_limit),
                        (first_m4, second_m4, layer_limit),
                        (first_m3 + first_m4, second_m3 + second_m4, total_limit),
                    )
                    for first_value, second_value, limit in comparisons:
                        pair_average = (first_value + second_value) / 2.0
                        pair_mismatch = abs(first_value - second_value) / max(
                            pair_average, 1e-12
                        )
                        violation = max(0.0, pair_mismatch - limit)
                        endpoint_penalty += violation
                        endpoint_worst = max(endpoint_worst, violation)
                # First satisfy the one-percent constraint when possible,
                # then minimize total wire and centroid displacement.
                score = (
                    0.0 if endpoint_penalty <= 1e-12 else 1.0,
                    endpoint_worst,
                    endpoint_penalty,
                    0.0 if mismatch <= 0.005 else mismatch,
                    total,
                    displacement,
                    first_column,
                    second_column,
                )
                if best is None or score < best[0]:
                    best = (score, first_column, second_column)
        if best is None:
            raise ValueError(f"cannot allocate matched M4 columns for {first}/{second}")
        _, first_column, second_column = best
        columns[first] = first_column
        columns[second] = second_column
        unused.remove(first_column)
        unused.remove(second_column)
        paired_nets.update((first, second))

    for net in sorted(medians, key=lambda item: (medians[item], item)):
        if net in paired_nets:
            continue
        target = medians[net]
        column = min(unused, key=lambda item: (abs(item - target), item))
        columns[net] = column
        unused.remove(column)
    for connection in connections:
        connection.column_x = columns[connection.net]


def expand_endpoint_constraints(
    constraints: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Expand compact matched endpoint groups for column cost evaluation."""
    expanded: list[dict[str, object]] = []
    for constraint in constraints:
        if "endpoints" in constraint:
            expanded.append(constraint)
            continue
        pairs = constraint.get("endpoint_pairs")
        if not isinstance(pairs, list) or not pairs:
            raise ValueError(
                f"{constraint.get('name', '<unnamed>')}: endpoint constraint "
                "requires endpoints or a non-empty endpoint_pairs list"
            )
        for index, pair in enumerate(pairs, 1):
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError(
                    f"{constraint.get('name', '<unnamed>')}: endpoint pair "
                    f"{index} must contain exactly two endpoints"
                )
            item = dict(constraint)
            item.pop("endpoint_pairs")
            item["name"] = f"{constraint['name']}_{index:02d}"
            item["endpoints"] = pair
            expanded.append(item)
    return expanded


def separate_breakout_lanes(
    connections: list[Connection],
    keepouts: list[tuple[float, float, float, float]],
    tracks: dict[str, float],
    m3_track_nets: set[str],
) -> None:
    """Stagger crossing M3 and M2 terminal escapes while preserving locality."""
    # Model the actual M3 rectangles, including each via landing's 0.31 um
    # overhang.  Comparing only centerlines missed end-to-end spacing, while
    # ignoring the global buses allowed a legal-looking lane to short a bus.
    placed_m3: list[tuple[tuple[float, float, float, float], str]] = [
        ((6.5, track_y - M3_WIDTH / 2, 154.5, track_y + M3_WIDTH / 2), net)
        for net, track_y in tracks.items()
        if net in m3_track_nets
    ]
    placed_m4: list[tuple[tuple[float, float, float, float], str]] = []
    for connection in connections:
        local_y = (
            connection.labels[0].y
            if connection.terminal == "D"
            else connection.access_y
        )
        if connection.terminal == "D":
            local_x = [label.x for label in connection.labels]
            local_x.extend((connection.anchor_x, connection.escape_x))
        elif connection.kind != "cap_mim_m3":
            local_x = [connection.anchor_x, connection.escape_x]
        else:
            continue
        placed_m3.append(
            (
                (
                    min(local_x) - 0.31,
                    local_y - M3_WIDTH / 2,
                    max(local_x) + 0.31,
                    local_y + M3_WIDTH / 2,
                ),
                connection.net,
            )
        )

    def rectangle_gap(
        first: tuple[float, float, float, float],
        second: tuple[float, float, float, float],
    ) -> float:
        dx = max(0.0, first[0] - second[2], second[0] - first[2])
        dy = max(0.0, first[1] - second[3], second[1] - first[3])
        return (dx * dx + dy * dy) ** 0.5

    step = 0.75
    offsets = [0.0]
    # The two dense LO/control banks need more candidate lanes than the analog
    # core.  Search the complete tile; the bounds below still choose the
    # nearest legal lane, while avoiding an artificial +/-30 um dead end.
    for index in range(1, 301):
        offsets.extend((index * step, -index * step))
    for connection in sorted(
        connections,
        key=lambda item: (item.breakout_y, item.anchor_x, item.net, item.device),
    ):
        left, right = sorted((connection.escape_x, connection.column_x))
        local_y = (
            connection.labels[0].y
            if connection.terminal == "D"
            else connection.access_y
        )
        for offset in offsets:
            candidate = connection.breakout_y + offset
            if not 1.0 <= candidate <= SIGNAL_ROUTE_TOP_Y:
                continue
            # The MIM PCell's broad lower electrode is Metal3.  A breakout
            # lane can therefore short C2 even when both of its Metal4
            # endpoints and risers sit safely outside the capacitor.  Reject
            # every horizontal M3 segment whose complete interval crosses the
            # capacitor footprint; the earlier test only protected the local
            # vertical dogleg.
            if any(
                keepout_bottom <= candidate <= keepout_top
                and min(right, keepout_right) >= max(left, keepout_left)
                for (
                    keepout_left,
                    keepout_right,
                    keepout_bottom,
                    keepout_top,
                ) in keepouts
            ):
                continue
            if connection.kind != "cap_mim_m3" and any(
                keepout_left <= connection.escape_x <= keepout_right
                and min(local_y, candidate) <= keepout_top
                and max(local_y, candidate) >= keepout_bottom
                for (
                    keepout_left,
                    keepout_right,
                    keepout_bottom,
                    keepout_top,
                ) in keepouts
            ):
                continue
            candidate_rect = (
                left - 0.31,
                candidate - M3_WIDTH / 2,
                right + 0.31,
                candidate + M3_WIDTH / 2,
            )
            conflict = False
            for other_rect, other_net in placed_m3:
                gap = rectangle_gap(candidate_rect, other_rect)
                # Overlapping/touching rectangles are only legal when they
                # deliberately merge branches of the same extracted net.
                if gap <= 1e-9 and other_net == connection.net:
                    continue
                if gap < 0.30 - 1e-9:
                    conflict = True
                    break
            local_m4_rect: tuple[float, float, float, float] | None = None
            if abs(candidate - local_y) > DBU_UM / 2:
                local_m4_rect = (
                    connection.escape_x - M4_WIDTH / 2,
                    min(local_y, candidate) - M4_WIDTH / 2,
                    connection.escape_x + M4_WIDTH / 2,
                    max(local_y, candidate) + M4_WIDTH / 2,
                )
                for other_rect, other_net in placed_m4:
                    gap = rectangle_gap(local_m4_rect, other_rect)
                    if gap <= 1e-9 and other_net == connection.net:
                        continue
                    if gap < 0.30 - 1e-9:
                        conflict = True
                        break
            if not conflict:
                connection.breakout_y = candidate
                placed_m3.append((candidate_rect, connection.net))
                if local_m4_rect is not None:
                    placed_m4.append((local_m4_rect, connection.net))
                break
        else:
            raise ValueError(
                f"cannot allocate a non-overlapping M3 breakout for "
                f"{connection.device}.{connection.terminal} "
                f"(net={connection.net}, escape={connection.escape_x:.3f}, "
                f"column={connection.column_x:.3f}, access={local_y:.3f})"
            )


def rect(layer: str, x1: float, y1: float, x2: float, y2: float) -> str:
    left, right = sorted((x1, x2))
    bottom, top = sorted((y1, y2))
    return f"paint_rect {layer} {fmt(left)} {fmt(bottom)} {fmt(right)} {fmt(top)}"


def wire_h(layer: str, x1: float, x2: float, y: float, width: float) -> str:
    if abs(x2 - x1) <= DBU_UM / 2:
        return f"# skipped zero-length horizontal {layer} wire"
    return rect(layer, x1, y - width / 2, x2, y + width / 2)


def wire_v(layer: str, x: float, y1: float, y2: float, width: float) -> str:
    if abs(y2 - y1) <= DBU_UM / 2:
        return f"# skipped zero-length vertical {layer} wire"
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


def route_connection(
    connection: Connection,
    junction_y: float,
    terminate_on_m3_track: bool,
) -> list[str]:
    labels = connection.labels
    commands = [f"# {connection.device}.{connection.terminal} -> {connection.net}"]
    if connection.terminal == "D":
        # Alternating multifinger drain contacts are lifted independently and
        # joined locally on M3.  A short M4 dogleg then reaches the allocated
        # breakout lane.  Keeping that dogleg off M3 prevents it from crossing
        # neighbouring power and signal escapes in the dense LO row.
        for original, label in zip(connection.original_labels, labels, strict=True):
            commands.extend(metal1_escape(original, label))
            commands.extend(contact_stack(label.x, label.y))
            commands.extend(via2_stack(label.x, label.y))
        min_x = min(label.x for label in labels)
        max_x = max(label.x for label in labels)
        local_y = labels[0].y
        commands.append(wire_h("metal3", min_x, max_x, local_y, M3_WIDTH))
        if connection.escape_x != connection.anchor_x:
            commands.append(
                wire_h("metal3", connection.anchor_x, connection.escape_x,
                       local_y, M3_WIDTH)
            )
        # Do not build a pair of via3 stacks around a zero-length M4 dogleg.
        # The old pair left an isolated 0.16 um^2 M4 landing, below met4.4a.
        if abs(connection.breakout_y - local_y) > DBU_UM / 2:
            commands.extend(via3_stack(connection.escape_x, local_y))
            commands.append(
                wire_v("metal4", connection.escape_x, local_y,
                       connection.breakout_y, M4_WIDTH)
            )
            commands.extend(via3_stack(connection.escape_x, connection.breakout_y))
        commands.append(
            wire_h("metal3", connection.escape_x, connection.column_x,
                   connection.breakout_y, M3_WIDTH)
        )
        commands.extend(via3_stack(connection.column_x, connection.breakout_y))
        commands.append(
            wire_v("metal4", connection.column_x, connection.breakout_y,
                   junction_y, M4_WIDTH)
        )
        if terminate_on_m3_track:
            commands.extend(via3_stack(connection.column_x, junction_y))
        return commands

    for original, label in zip(connection.original_labels, labels, strict=True):
        commands.extend(metal1_escape(original, label))
        commands.extend(
            contact_stack(label.x, label.y, from_bulk=connection.terminal == "B")
        )
        commands.append(wire_v("metal2", label.x, label.y, connection.access_y, M2_WIDTH))
    min_x = min(label.x for label in labels)
    max_x = max(label.x for label in labels)
    commands.append(wire_h("metal2", min_x, max_x, connection.access_y, M2_WIDTH))
    commands.extend(via2_stack(connection.anchor_x, connection.access_y))
    commands.append(
        wire_h("metal3", connection.anchor_x, connection.escape_x,
               connection.access_y, M3_WIDTH)
    )
    if abs(connection.breakout_y - connection.access_y) > DBU_UM / 2:
        commands.extend(via3_stack(connection.escape_x, connection.access_y))
        commands.append(
            wire_v("metal4", connection.escape_x, connection.access_y,
                   connection.breakout_y, M4_WIDTH)
        )
        commands.extend(via3_stack(connection.escape_x, connection.breakout_y))
    commands.append(
        wire_h("metal3", connection.escape_x, connection.column_x,
               connection.breakout_y, M3_WIDTH)
    )
    commands.extend(via3_stack(connection.column_x, connection.breakout_y))
    commands.append(
        wire_v(
            "metal4", connection.column_x, connection.breakout_y,
            junction_y, M4_WIDTH,
        )
    )
    if terminate_on_m3_track:
        commands.extend(via3_stack(connection.column_x, junction_y))
    return commands


def route_capacitor(
    connection: Connection,
    junction_y: float,
    terminate_on_m3_track: bool,
) -> list[str]:
    label = connection.labels[0]
    # Remain on M4 while leaving the physical electrode.  In particular, do
    # not place a via3 on C1: its M3 landing would directly touch C2's broad
    # bottom plate and short the capacitor.  The M4 routing keep-out ensures
    # no unrelated riser crosses either plate.
    commands = [
        f"# {connection.device}.{connection.terminal} -> {connection.net}",
        rect("metal4", label.x - 0.20, label.y - 0.20, label.x + 0.20, label.y + 0.20),
        wire_h("metal4", label.x, connection.escape_x, label.y, M4_WIDTH),
        # Extend to the lower edge of the horizontal wire.  Starting on its
        # centerline leaves a 0.20 um re-entrant leg after GDS booleanization,
        # which violates met4.1 even though the painted wires are 0.40 um.
        wire_v("metal4", connection.escape_x, label.y - M4_WIDTH / 2,
               connection.breakout_y, M4_WIDTH),
        *via3_stack(connection.escape_x, connection.breakout_y),
        wire_h("metal3", connection.escape_x, connection.column_x,
               connection.breakout_y, M3_WIDTH),
        *via3_stack(connection.column_x, connection.breakout_y),
        wire_v("metal4", connection.column_x, connection.breakout_y,
               junction_y, M4_WIDTH),
    ]
    if terminate_on_m3_track:
        commands.extend(via3_stack(connection.column_x, junction_y))
    return commands


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
    check_instance_overlaps(top)
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
                    y,
                    local_escape_x(kind, terminal, anchor_x),
                )
            )

    connections.sort(key=lambda item: (item.anchor_x, item.breakout_y,
                                        item.device, item.terminal))
    connection_by_endpoint = {
        f"{item.device}.{item.terminal}": item for item in connections
    }
    for endpoint, escape_x in manifest.get("route_escape_overrides", {}).items():
        endpoint = str(endpoint)
        if endpoint not in connection_by_endpoint:
            raise ValueError(f"route-escape override names unknown endpoint {endpoint}")
        connection = connection_by_endpoint[endpoint]
        connection.escape_x = float(escape_x)
        connection.escape_fixed = True
    keepouts = capacitor_keepouts(connections)
    column_overrides = {
        str(net): float(column)
        for net, column in manifest.get("route_column_overrides", {}).items()
    }
    assign_local_escape_columns(connections, list(column_overrides.values()))
    track_y_overrides = {
        str(net): float(y)
        for net, y in manifest.get("track_y_overrides", {}).items()
    }
    unknown_track_overrides = track_y_overrides.keys() - set(manifest["track_order"])
    if unknown_track_overrides:
        raise ValueError(
            f"track-y overrides name unknown nets: {sorted(unknown_track_overrides)}"
        )
    tracks = {
        net: track_y_overrides.get(net, TRACK_Y0 + index * TRACK_PITCH)
        for index, net in enumerate(manifest["track_order"])
    }
    endpoint_constraints = expand_endpoint_constraints(
        list(manifest.get("route_endpoint_constraints", []))
    )
    assign_net_columns(
        connections,
        keepouts,
        tracks,
        list(manifest.get("route_match_constraints", [])),
        endpoint_constraints,
        column_overrides,
    )
    # Only boundary-facing nets need an M3 distribution bus.  Every internal
    # net already uses one shared M4 column, so descending to an arbitrary M3
    # track and immediately returning to that same M4 component creates a
    # via-only stub and lengthens the trunk without adding connectivity.
    m3_track_nets = set(BOUNDARY_PINS)
    separate_breakout_lanes(connections, keepouts, tracks, m3_track_nets)
    # Apply explicit matched-path compensation only after legal breakout lanes
    # have been allocated.  Each selected branch already contains a real
    # M4 dogleg between two via3 sites, so moving its second landing changes a
    # conducting component-to-trunk path without adding a via or a dead end.
    post_breakout_offsets = {
        str(endpoint): float(offset)
        for endpoint, offset in manifest.get(
            "post_breakout_y_offsets", {}
        ).items()
    }
    unknown_post_offsets = post_breakout_offsets.keys() - connection_by_endpoint.keys()
    if unknown_post_offsets:
        raise ValueError(
            "post-breakout offsets name unknown endpoints: "
            f"{sorted(unknown_post_offsets)}"
        )
    for endpoint, offset in post_breakout_offsets.items():
        connection_by_endpoint[endpoint].breakout_y += offset

    missing_tracks = {connection.net for connection in connections} - tracks.keys()
    if missing_tracks:
        raise ValueError(f"nets without tracks: {sorted(missing_tracks)}")

    junction_y_by_net: dict[str, float] = {}
    for net in tracks:
        net_connections = [item for item in connections if item.net == net]
        if not net_connections:
            raise ValueError(f"net {net} has no routed device connection")
        if net in m3_track_nets:
            junction_y_by_net[net] = tracks[net]
            continue
        columns = {item.column_x for item in net_connections}
        if len(columns) != 1:
            raise ValueError(
                f"direct-M4 net {net} unexpectedly uses columns {sorted(columns)}"
            )
        breakout_ys = sorted(item.breakout_y for item in net_connections)
        # Pick an existing transition point so the label always lands on real
        # M4 geometry.  Connecting every branch to this median bounds the
        # shared trunk by actual endpoints rather than an artificial track.
        junction_y_by_net[net] = breakout_ys[len(breakout_ys) // 2]

    commands: list[str] = []
    for net, y in tracks.items():
        if net not in m3_track_nets:
            column_x = next(
                connection.column_x for connection in connections
                if connection.net == net
            )
            junction_y = junction_y_by_net[net]
            commands.extend(
                [
                    f"# direct M4 junction: {net}",
                    f"box {fmt(column_x)}um {fmt(junction_y)}um "
                    f"{fmt(column_x)}um {fmt(junction_y)}um",
                    f"label {{{net}}} FreeSans 0.10u -met4",
                ]
            )
            continue
        endpoints = [
            connection.column_x for connection in connections if connection.net == net
        ]
        if net in BOUNDARY_PINS:
            endpoints.append(BOUNDARY_PINS[net][0])
        if not endpoints:
            raise ValueError(f"track {net} has no physical endpoint")
        left = max(6.5, min(endpoints) - 0.40)
        right = min(154.5, max(endpoints) + 0.40)
        label_x = (left + right) / 2.0
        commands.extend(
            [
                f"# horizontal net track: {net}",
                wire_h("metal3", left, right, y, M3_WIDTH),
                f"box {fmt(label_x)}um {fmt(y)}um {fmt(label_x)}um {fmt(y)}um",
                f"label {{{net}}} FreeSans 0.10u -met3",
            ]
        )
    skipped_devices = {
        item
        for item in os.environ.get("ROUTE_SKIP_DEVICES", "").split(",")
        if item
    }
    skipped_connections = {
        item
        for item in os.environ.get("ROUTE_SKIP_CONNECTIONS", "").split(",")
        if item
    }
    for connection in connections:
        if (
            connection.device in skipped_devices
            or f"{connection.device}.{connection.terminal}" in skipped_connections
        ):
            continue
        router = route_capacitor if connection.kind == "cap_mim_m3" else route_connection
        commands.extend(
            router(
                connection,
                junction_y_by_net[connection.net],
                connection.net in m3_track_nets,
            )
        )

    for net, (x, y) in BOUNDARY_PINS.items():
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
