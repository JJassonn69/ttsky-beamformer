#!/usr/bin/env python3
"""Generate the full 15-unit service channel with late analog promotion."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import generate_channel_architecture_service_pilot as baseline
import generate_channel_matrix_pilot as matrix_gen
import generate_vector_unit_pilot as unit_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3/layout/channel_matrix_late_promotion.json"
ARCHITECTURE = ROOT / "v3/layout/channel_routing_architecture.json"
UNIT = ROOT / "v3/layout/vector_unit_late_promotion.json"
CATALOG = ROOT / "v3/layout/channel_pcell_catalog.json"
BUILD = ROOT / "build/v3/channel_architecture_service_late_promotion"
DEFAULT_OUTPUT = BUILD / "build.tcl"
TOP = "v3_channel_architecture_service_late_promotion"
GUARD_BOTTOM_Y = 4.80
GROUND_SPINE_X = 6.98


def shifted(point: list[float]) -> list[float]:
    return unit_gen.shifted(point)


def wire_h(layer: str, x1: float, x2: float, y: float, width: float) -> str:
    first, second = shifted([x1, y]), shifted([x2, y])
    return unit_gen.wire_h(layer, first[0], second[0], first[1], width)


def wire_v(layer: str, x: float, y1: float, y2: float, width: float) -> str:
    first, second = shifted([x, y1]), shifted([x, y2])
    return unit_gen.wire_v(layer, first[0], first[1], second[1], width)


def compact_via2(point: list[float]) -> list[str]:
    return unit_gen.compact_via2_stack(*shifted(point))


def via2(point: list[float]) -> list[str]:
    return unit_gen.via2_stack(*shifted(point))


def contact(point: list[float]) -> list[str]:
    return unit_gen.contact_stack(*shifted(point))


def add_analog_routes(
    commands: list[str], by_row: dict[int, list[dict[str, Any]]],
    analog_spines: dict[str, float],
) -> None:
    for row, instances in sorted(by_row.items()):
        instances.sort(key=lambda item: item["column_left_to_right"])
        origin_y = float(instances[0]["origin"][1])
        levels = {
            "sig": round(origin_y - 1.95, 6),
            "vbias": round(origin_y - 1.25, 6),
            "ref": round(origin_y - 0.55, 6),
        }
        for role in ("sig", "vbias", "ref"):
            ports = [
                [float(value) for value in item["ports"][role]["point"]]
                for item in instances
            ]
            level = levels[role]
            spine_x = float(analog_spines[role])
            # M2 drops cross the three M1 row buses without an electrical
            # intersection.  Only one M1/Via1/M2 handoff is used at the
            # service spine; M3/M4 remain untouched.  Extending the common
            # guard to y=4.80 makes the same topology legal for the fifth row.
            for port in ports:
                commands.extend(contact(port))
                commands.append(wire_v("metal2", port[0], level, port[1], 0.23))
                commands.extend(contact([port[0], level]))
            commands.append(wire_h(
                "metal1", min(spine_x, *(point[0] for point in ports)),
                max(spine_x, *(point[0] for point in ports)), level, 0.23,
            ))
            commands.extend(contact([spine_x, level]))


def build_tcl(
    matrix: dict[str, Any], architecture: dict[str, Any], unit: dict[str, Any],
    catalog: dict[str, Any],
) -> str:
    source = matrix_gen.build_tcl(
        matrix,
        unit,
        catalog,
        ground_bus_offset_um=0.20,
        guard_bottom_y=GUARD_BOTTOM_Y,
        ground_spines_x=[GROUND_SPINE_X],
    )
    source = source.replace("channel_matrix_pilot", "channel_architecture_service_late_promotion")
    source = source.replace("v3_channel_matrix_pilot", TOP)
    source = source.replace("V3_CHANNEL_MATRIX", "V3_CHANNEL_ARCHITECTURE_SERVICE_LATE")
    source = source.replace("channel-matrix pilot", "late-promotion channel-service pilot")

    alias = re.compile(
        r"box [^\n]+\n"
        r"label u\d{2}_(?:sig|ref|vbias|outp|outn) center metal[1-4]\n"
        r"port make\nport class (?:input|output)\nport use signal\n"
        r"port connections n s e w\n?"
    )
    source, removed = alias.subn("", source)
    if removed != 75:
        raise RuntimeError(f"expected to remove 75 unit service aliases, removed {removed}")

    selected = architecture["candidates"][architecture["decision"]["selected"]]
    rows = {int(item["row_top_to_bottom"]): item for item in selected["row_track_plan"]}
    by_row: dict[int, list[dict[str, Any]]] = {}
    for item in matrix["matrix"]["instances"]:
        by_row.setdefault(int(item["row_top_to_bottom"]), []).append(item)
    output_spines = selected["service_corridors"]["output_left"]["spines"]
    analog_spines = selected["service_corridors"]["analog_right"]["spines"]
    commands: list[str] = []

    for row, instances in sorted(by_row.items()):
        instances.sort(key=lambda item: item["column_left_to_right"])
        tracks = rows[row]["tracks"]
        for polarity in ("p", "n"):
            taps = sorted(
                [item["ports"][f"out{polarity}"]["point"] for item in instances],
                key=lambda point: point[0],
            )
            bus_y = float(tracks[f"output_{polarity}_bus_m3"])
            spine_x = float(output_spines[polarity])
            for tap in taps:
                commands.extend(compact_via2(tap))
                commands.append(wire_v("metal2", tap[0], tap[1], bus_y, 0.40))
                commands.extend(via2([tap[0], bus_y]))
            commands.append(wire_h(
                "metal3", min(spine_x, taps[0][0]), max(spine_x, taps[-1][0]),
                bus_y, 0.60,
            ))
            commands.extend(via2([spine_x, bus_y]))

    add_analog_routes(commands, by_row, analog_spines)
    commands.extend([
        wire_v("metal2", float(output_spines["p"]), baseline.SPINE_BOTTOM_Y, baseline.SPINE_TOP_Y, 0.50),
        wire_v("metal2", float(output_spines["n"]), baseline.SPINE_BOTTOM_Y, baseline.SPINE_TOP_Y, 0.50),
        wire_v("metal2", float(analog_spines["sig"]), baseline.SPINE_BOTTOM_Y, baseline.SPINE_TOP_Y, 0.40),
        wire_v("metal2", float(analog_spines["vbias"]), baseline.SPINE_BOTTOM_Y, baseline.SPINE_TOP_Y, 0.40),
        wire_v("metal2", float(analog_spines["ref"]), baseline.SPINE_BOTTOM_Y, baseline.SPINE_TOP_Y, 0.30),
    ])
    labels = [
        matrix_gen.label("row_outp", [float(output_spines["p"]), baseline.SPINE_TOP_Y], "metal2", output=True),
        matrix_gen.label("row_outn", [float(output_spines["n"]), baseline.SPINE_TOP_Y], "metal2", output=True),
        matrix_gen.label("sig", [float(analog_spines["sig"]), baseline.SPINE_TOP_Y], "metal2"),
        matrix_gen.label("vbias", [float(analog_spines["vbias"]), baseline.SPINE_TOP_Y], "metal2"),
        matrix_gen.label("ref", [float(analog_spines["ref"]), baseline.SPINE_TOP_Y], "metal2"),
    ]
    insertion = "\n".join(commands + labels)
    marker = "\nsave $TOP.mag\nwriteall force\n"
    if source.count(marker) != 1:
        raise RuntimeError("late service insertion marker changed")
    source = source.replace(marker, f"\n{insertion}{marker}")

    final_marker = 'puts "V3_CHANNEL_ARCHITECTURE_SERVICE_LATE_GDS_FEEDBACK_COUNT=[feedback count]"\nquit -noprompt'
    final_replacement = """set gds_feedback [feedback count]
puts "V3_CHANNEL_ARCHITECTURE_SERVICE_LATE_GDS_FEEDBACK_COUNT=$gds_feedback"
if {$gds_feedback != 0} { feedback save [file join $WORKDIR gds_feedback.txt] }
set summary [open [file join $WORKDIR physical_markers.txt] w]
puts $summary "V3_CHANNEL_ARCHITECTURE_SERVICE_LATE_DRC_COUNT=$drc_count"
puts $summary "V3_CHANNEL_ARCHITECTURE_SERVICE_LATE_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
puts $summary "V3_CHANNEL_ARCHITECTURE_SERVICE_LATE_GDS_FEEDBACK_COUNT=$gds_feedback"
close $summary
quit -noprompt"""
    if source.count(final_marker) != 1:
        raise RuntimeError("late service final marker changed")
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
