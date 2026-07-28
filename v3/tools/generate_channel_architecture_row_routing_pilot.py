#!/usr/bin/env python3
"""Generate the exact centre-row pilot with every reserved routing net class."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import generate_channel_row_pilot as row_gen
import generate_vector_unit_pilot as unit_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "build/v3/channel_architecture_feasibility/channel_matrix_placement.json"
ARCHITECTURE = ROOT / "v3/layout/channel_routing_architecture.json"
UNIT = ROOT / "v3/layout/vector_unit_placement.json"
CATALOG = ROOT / "v3/layout/channel_pcell_catalog.json"
BUILD = ROOT / "build/v3/channel_architecture_row_routing"
DEFAULT_OUTPUT = BUILD / "build.tcl"
TOP = "v3_channel_architecture_row_routing"
ROW_LOCAL_ORIGIN_Y = 8.0
SPINE_BOTTOM_Y = 5.60
SPINE_TOP_Y = 26.10


def shifted(point: list[float]) -> list[float]:
    return unit_gen.shifted(point)


def wire_h(layer: str, x1: float, x2: float, y: float, width: float) -> str:
    first = shifted([x1, y])
    second = shifted([x2, y])
    return unit_gen.wire_h(layer, first[0], second[0], first[1], width)


def wire_v(layer: str, x: float, y1: float, y2: float, width: float) -> str:
    first = shifted([x, y1])
    second = shifted([x, y2])
    return unit_gen.wire_v(layer, first[0], first[1], second[1], width)


def via2(point: list[float]) -> list[str]:
    return unit_gen.via2_stack(*shifted(point))


def compact_via2(point: list[float]) -> list[str]:
    return unit_gen.compact_via2_stack(*shifted(point))


def via3(point: list[float]) -> list[str]:
    return unit_gen.via3_stack(*shifted(point))


def add_output_routes(
    commands: list[str], selected: list[dict[str, Any]], tracks: dict[str, float],
    output_spines: dict[str, float],
) -> None:
    for polarity in ("p", "n"):
        taps = sorted(
            [row_gen.absolute_to_row(item["ports"][f"out{polarity}"]["point"]) for item in selected],
            key=lambda point: point[0],
        )
        bus_y = tracks[f"output_{polarity}_bus_m3"] - 40.0
        spine_x = output_spines[polarity]
        for tap in taps:
            # The two differential taps are only 0.70 um apart.  A generic
            # 0.62 um-wide M3 Via-2 landing leaves 0.08 um between them even
            # though the native Magic DRC does not report it.  The compact
            # landing is already closed in the vector-unit pilot and retains
            # the legal 0.30 um differential spacing here.
            commands.extend(compact_via2(tap))
            commands.append(wire_v("metal2", tap[0], tap[1], bus_y, 0.40))
            commands.extend(via2([tap[0], bus_y]))
        commands.append(wire_h(
            "metal3", min(spine_x, taps[0][0]), max(spine_x, taps[-1][0]), bus_y, 0.60
        ))
        commands.extend(via2([spine_x, bus_y]))
        commands.append(wire_v("metal2", spine_x, SPINE_BOTTOM_Y, SPINE_TOP_Y, 0.50))


def add_analog_routes(
    commands: list[str], selected: list[dict[str, Any]], tracks: dict[str, float],
    analog_spines: dict[str, float], widths: dict[str, float],
) -> None:
    for role in ("sig", "vbias", "ref"):
        ports = sorted(
            [row_gen.absolute_to_row(item["ports"][role]["point"]) for item in selected],
            key=lambda point: point[0],
        )
        level = tracks[f"next_row_{role}_m3"] - 60.0
        # The centre-row gap is the gap above the row below in the architecture
        # manifest.  Subtracting 60 um maps it to 6.05/6.75/7.45 locally.
        if not (5.5 < level < ROW_LOCAL_ORIGIN_Y):
            raise RuntimeError(f"{role} branch level mapped outside the lower row gap: {level}")
        for port in ports:
            commands.append(wire_v("metal4", port[0], level, port[1], widths[role]))
            commands.extend(via3([port[0], level]))
        spine_x = analog_spines[role]
        commands.append(wire_h(
            "metal3", min(spine_x, ports[0][0]), max(spine_x, ports[-1][0]), level,
            widths[role],
        ))
        commands.extend(via2([spine_x, level]))
        commands.append(wire_v("metal2", spine_x, SPINE_BOTTOM_Y, SPINE_TOP_Y, widths[role]))


def add_phase_routes(
    commands: list[str], selected: list[dict[str, Any]], tracks: dict[str, float],
    phase: dict[str, Any],
) -> dict[str, list[float]]:
    by_group: dict[int, list[dict[str, Any]]] = {}
    for item in selected:
        by_group.setdefault(int(item["group_weight"]), []).append(item)
    if sorted(by_group) != [1, 2] or len(by_group[1]) != 1 or len(by_group[2]) != 2:
        raise RuntimeError("centre row must remain one G1 centre and two G2 outer units")

    roots: dict[str, list[float]] = {}
    internal = phase["internal_g1_trunks_x_um"]
    side = phase["side_bank_trunks_x_um"]
    trunk_x = {"g1_lon": internal[0], "g1_lop": internal[1], "g2_lon": side[0], "g2_lop": side[1]}

    # Centre G1 routes stay on their local-root tracks and make only one short
    # lateral move.  This avoids every outer-root vertical escape.
    centre = by_group[1][0]
    for polarity in ("lon", "lop"):
        local_root = row_gen.absolute_to_row(centre["local_lo_routes"][polarity]["root"])
        track_y = tracks[f"phase_centre_{polarity}_m3"] - 40.0
        if polarity == "lop":
            # The G1 LOP local merge is already M4 and its horizontal root
            # segment crosses the selected trunk x.  A former M3 bridge plus
            # two Via-3 cuts merely hung below that same M4 component.
            horizontal = [
                item for item in centre["local_lo_routes"][polarity]["segments"]
                if item["layer"] == "metal4"
                and item["from"][1] == item["to"][1] == centre["local_lo_routes"][polarity]["root"][1]
            ]
            trunk_absolute_x = trunk_x[f"g1_{polarity}"]
            if not any(
                min(item["from"][0], item["to"][0]) - 0.20 <= trunk_absolute_x
                <= max(item["from"][0], item["to"][0]) + 0.20
                for item in horizontal
            ):
                raise RuntimeError("G1 LOP trunk no longer lands on its local M4 merge")
        else:
            if local_root[1] != track_y:
                commands.append(wire_v("metal3", local_root[0], local_root[1], track_y, 0.40))
            commands.append(wire_h("metal3", local_root[0], trunk_x[f"g1_{polarity}"], track_y, 0.40))
            commands.extend(via3([trunk_x[f"g1_{polarity}"], track_y]))
        commands.append(wire_v("metal4", trunk_x[f"g1_{polarity}"], track_y, SPINE_TOP_Y, 0.40))
        roots[f"g1_{polarity}"] = [trunk_x[f"g1_{polarity}"], SPINE_TOP_Y]

    # Outer G2 roots escape vertically on their original layer before their
    # common M3 bus.  The two G1 routes are confined between x=8.96..10.36,
    # so these escapes cannot intersect them on M3.
    for polarity in ("lon", "lop"):
        local_roots = sorted(
            [row_gen.absolute_to_row(item["local_lo_routes"][polarity]["root"]) for item in by_group[2]],
            key=lambda point: point[0],
        )
        track_y = tracks[f"phase_outer_{polarity}_m3"] - 40.0
        for local_root in local_roots:
            if polarity == "lon":
                commands.append(wire_v("metal3", local_root[0], local_root[1], track_y, 0.40))
            else:
                commands.append(wire_v("metal4", local_root[0], local_root[1], track_y, 0.40))
                commands.extend(via3([local_root[0], track_y]))
        x_value = trunk_x[f"g2_{polarity}"]
        bus_left = min(local_roots[0][0], x_value)
        bus_right = max(local_roots[-1][0], x_value)
        # Fully cover both endpoint verticals.  Merely meeting their centre
        # lines creates a narrow concave corner in flattened GDS.
        commands.append(wire_h("metal3", bus_left - 0.20, bus_right + 0.20, track_y, 0.40))
        commands.extend(via3([x_value, track_y]))
        if polarity == "lop":
            # The right local LOP escape and the side-bank trunk are only
            # 0.67 um centre-to-centre.  Join the same-net M4 conductors at
            # the row track instead of leaving an illegal 0.27 um slot.
            nearest = min(local_roots, key=lambda point: abs(point[0] - x_value))
            commands.append(wire_h("metal4", nearest[0], x_value, track_y, 0.40))
        commands.append(wire_v("metal4", x_value, track_y, SPINE_TOP_Y, 0.40))
        roots[f"g2_{polarity}"] = [x_value, SPINE_TOP_Y]
    return roots


def build_tcl(
    matrix: dict[str, Any], architecture: dict[str, Any], unit: dict[str, Any],
    catalog: dict[str, Any],
) -> str:
    source = row_gen.build_tcl(matrix, unit, catalog)
    source = source.replace("channel_row_pilot", "channel_architecture_row_routing")
    source = source.replace("v3_channel_row_pilot", TOP)
    source = source.replace("V3_CHANNEL_ROW", "V3_CHANNEL_ARCHITECTURE_ROW")
    source = source.replace("channel-row pilot", "channel-architecture row-routing pilot")

    alias = re.compile(
        r"box [^\n]+\n"
        r"label u[0-2]_(?:sig|ref|vbias|outp|outn|lop|lon) center (?:metal2|metal3|metal4)\n"
        r"port make\nport class (?:input|output)\nport use signal\n"
        r"port connections n s e w\n?"
    )
    source, removed = alias.subn("", source)
    if removed != 21:
        raise RuntimeError(f"expected to remove 21 unit boundary aliases, removed {removed}")

    selected = sorted(
        (item for item in matrix["matrix"]["instances"] if item["row_top_to_bottom"] == 2),
        key=lambda item: item["column_left_to_right"],
    )
    candidate = architecture["candidates"][architecture["decision"]["selected"]]
    track_record = next(item for item in candidate["row_track_plan"] if item["row_top_to_bottom"] == 2)
    tracks = track_record["tracks"]
    output_spines = candidate["service_corridors"]["output_left"]["spines"]
    analog_spines = candidate["service_corridors"]["analog_right"]["spines"]
    phase = candidate["phase_distribution"]
    commands: list[str] = []
    add_output_routes(commands, selected, tracks, output_spines)
    add_analog_routes(
        commands, selected, tracks, analog_spines,
        {"sig": 0.40, "vbias": 0.40, "ref": 0.30},
    )
    phase_roots = add_phase_routes(commands, selected, tracks, phase)

    labels = [
        row_gen.label("row_outp", [output_spines["p"], SPINE_TOP_Y], "metal2", output=True),
        row_gen.label("row_outn", [output_spines["n"], SPINE_TOP_Y], "metal2", output=True),
        row_gen.label("sig", [analog_spines["sig"], SPINE_TOP_Y], "metal2"),
        row_gen.label("vbias", [analog_spines["vbias"], SPINE_TOP_Y], "metal2"),
        row_gen.label("ref", [analog_spines["ref"], SPINE_TOP_Y], "metal2"),
    ]
    labels.extend(row_gen.label(name, point, "metal4") for name, point in phase_roots.items())
    insertion = "\n".join(commands + labels)
    marker = "\nsave $TOP.mag\nwriteall force\n"
    if source.count(marker) != 1:
        raise RuntimeError("row-pilot save marker changed")
    source = source.replace(marker, f"\n{insertion}{marker}")

    final_marker = "puts \"V3_CHANNEL_ARCHITECTURE_ROW_GDS_FEEDBACK_COUNT=[feedback count]\"\nquit -noprompt"
    final_replacement = """set gds_feedback [feedback count]
puts \"V3_CHANNEL_ARCHITECTURE_ROW_GDS_FEEDBACK_COUNT=$gds_feedback\"
if {$gds_feedback != 0} {
    feedback save [file join $WORKDIR gds_feedback.txt]
}
set summary [open [file join $WORKDIR physical_markers.txt] w]
puts $summary \"V3_CHANNEL_ARCHITECTURE_ROW_DRC_COUNT=$drc_count\"
puts $summary \"V3_CHANNEL_ARCHITECTURE_ROW_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback\"
puts $summary \"V3_CHANNEL_ARCHITECTURE_ROW_GDS_FEEDBACK_COUNT=$gds_feedback\"
close $summary
quit -noprompt"""
    if source.count(final_marker) != 1:
        raise RuntimeError("row-pilot final marker changed")
    return source.replace(final_marker, final_replacement)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--architecture", type=Path, default=ARCHITECTURE)
    parser.add_argument("--unit", type=Path, default=UNIT)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    values = [json.loads(path.read_text(encoding="utf-8")) for path in (
        args.matrix, args.architecture, args.unit, args.catalog,
    )]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_tcl(*values), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
