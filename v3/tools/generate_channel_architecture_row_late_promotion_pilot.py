#!/usr/bin/env python3
"""Generate a three-unit all-net row using late M1 analog-gate promotion."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import generate_channel_architecture_row_routing_pilot as baseline
import generate_channel_row_pilot as row_gen
import generate_vector_unit_pilot as unit_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "build/v3/channel_architecture_feasibility/channel_matrix_placement.json"
ARCHITECTURE = ROOT / "v3/layout/channel_routing_architecture.json"
UNIT = ROOT / "v3/layout/vector_unit_late_promotion.json"
CATALOG = ROOT / "v3/layout/channel_pcell_catalog.json"
BUILD = ROOT / "build/v3/channel_architecture_row_late_promotion"
DEFAULT_OUTPUT = BUILD / "build.tcl"
TOP = "v3_channel_architecture_row_late_promotion"


def late_port(
    instance: dict[str, Any], unit: dict[str, Any], role: str,
) -> list[float]:
    return row_gen.whole_transform(unit["boundary_ports"][role]["point"], instance)


def add_late_analog_routes(
    commands: list[str], selected: list[dict[str, Any]], unit: dict[str, Any],
    tracks: dict[str, float], analog_spines: dict[str, float],
) -> None:
    # These tracks lie in the empty lower inter-row band of the centre-row
    # pilot.  The pilot guard is extended below them; in the complete channel
    # they are naturally internal to the one shared matrix guard.
    for role in ("sig", "vbias", "ref"):
        ports = sorted(
            [late_port(instance, unit, role) for instance in selected],
            key=lambda point: point[0],
        )
        level = float(tracks[f"next_row_{role}_m3"]) - 60.0
        if not (5.5 < level < baseline.ROW_LOCAL_ORIGIN_Y):
            raise RuntimeError(f"{role} M1 row level is outside the reserved gap: {level}")
        for port in ports:
            # Three M1 vertical drops would cross the other two horizontal M1
            # buses.  Promote only in the empty inter-row band, descend on M2,
            # and return to M1 at the assigned row level.  This uses no M3/M4
            # and makes every layer transition explicit and electrically used.
            commands.extend(unit_gen.contact_stack(*baseline.shifted(port)))
            commands.append(baseline.wire_v("metal2", port[0], level, port[1], 0.23))
            commands.extend(unit_gen.contact_stack(*baseline.shifted([port[0], level])))
        spine_x = float(analog_spines[role])
        commands.append(baseline.wire_h(
            "metal1", min(spine_x, ports[0][0]), max(spine_x, ports[-1][0]),
            level, 0.23,
        ))
        commands.extend(unit_gen.contact_stack(*baseline.shifted([spine_x, level])))
        spine_width = 0.30 if role == "ref" else 0.40
        commands.append(baseline.wire_v(
            "metal2", spine_x, baseline.SPINE_BOTTOM_Y, baseline.SPINE_TOP_Y,
            spine_width,
        ))


def build_tcl(
    matrix: dict[str, Any], architecture: dict[str, Any], unit: dict[str, Any],
    catalog: dict[str, Any],
) -> str:
    if not unit.get("late_promotion"):
        raise RuntimeError("late-promotion row requires the alternate unit manifest")
    source = row_gen.build_tcl(
        matrix, unit, catalog, guard_bottom_y=4.80,
    )
    source = source.replace("channel_row_pilot", "channel_architecture_row_late_promotion")
    source = source.replace("v3_channel_row_pilot", TOP)
    source = source.replace("V3_CHANNEL_ROW", "V3_CHANNEL_ARCHITECTURE_ROW_LATE")
    source = source.replace(
        "channel-row pilot", "channel-architecture late-promotion row pilot",
    )

    alias = re.compile(
        r"box [^\n]+\n"
        r"label u[0-2]_(?:sig|ref|vbias|outp|outn|lop|lon) center metal[1-4]\n"
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
    track_record = next(
        item for item in candidate["row_track_plan"] if item["row_top_to_bottom"] == 2
    )
    tracks = track_record["tracks"]
    output_spines = candidate["service_corridors"]["output_left"]["spines"]
    analog_spines = candidate["service_corridors"]["analog_right"]["spines"]
    phase = candidate["phase_distribution"]
    commands: list[str] = []
    baseline.add_output_routes(commands, selected, tracks, output_spines)
    add_late_analog_routes(commands, selected, unit, tracks, analog_spines)
    phase_roots = baseline.add_phase_routes(commands, selected, tracks, phase)

    labels = [
        row_gen.label("row_outp", [output_spines["p"], baseline.SPINE_TOP_Y], "metal2", output=True),
        row_gen.label("row_outn", [output_spines["n"], baseline.SPINE_TOP_Y], "metal2", output=True),
        row_gen.label("sig", [analog_spines["sig"], baseline.SPINE_TOP_Y], "metal2"),
        row_gen.label("vbias", [analog_spines["vbias"], baseline.SPINE_TOP_Y], "metal2"),
        row_gen.label("ref", [analog_spines["ref"], baseline.SPINE_TOP_Y], "metal2"),
    ]
    labels.extend(row_gen.label(name, point, "metal4") for name, point in phase_roots.items())
    insertion = "\n".join(commands + labels)
    marker = "\nsave $TOP.mag\nwriteall force\n"
    if source.count(marker) != 1:
        raise RuntimeError("late-promotion row save marker changed")
    source = source.replace(marker, f"\n{insertion}{marker}")

    final_marker = (
        'puts "V3_CHANNEL_ARCHITECTURE_ROW_LATE_GDS_FEEDBACK_COUNT=[feedback count]"\n'
        "quit -noprompt"
    )
    final_replacement = """set gds_feedback [feedback count]
puts "V3_CHANNEL_ARCHITECTURE_ROW_LATE_GDS_FEEDBACK_COUNT=$gds_feedback"
if {$gds_feedback != 0} {
    feedback save [file join $WORKDIR gds_feedback.txt]
}
set summary [open [file join $WORKDIR physical_markers.txt] w]
puts $summary "V3_CHANNEL_ARCHITECTURE_ROW_LATE_DRC_COUNT=$drc_count"
puts $summary "V3_CHANNEL_ARCHITECTURE_ROW_LATE_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
puts $summary "V3_CHANNEL_ARCHITECTURE_ROW_LATE_GDS_FEEDBACK_COUNT=$gds_feedback"
close $summary
quit -noprompt"""
    if source.count(final_marker) != 1:
        raise RuntimeError("late-promotion row final marker changed")
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
