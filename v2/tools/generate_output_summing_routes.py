#!/usr/bin/env python3
"""Generate matched four-channel differential summing trees and pad routes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from generate_critical_signal_routes import (
    fmt,
    li_contact_stack,
    via2_stack,
    via3_stack,
    wire_h,
    wire_v,
)


TOP = "v2_four_channel_output_routed"
STAGE = "output_summing_routes"
LOCAL_ANCHOR_Y = 90.0
BOTTOM_TRANSITION_Y = 8.0
SUM_WIDTH = 0.80


ROUTE_ROWS = {
    "p": {"leaf": 91.0, "root": 96.0, "load": 98.4, "output": 88.0},
    "n": {"leaf": 92.2, "root": 93.6, "load": 97.2, "output": 86.8},
}


def generate(
    floorplan: dict[str, Any], routing_plan: dict[str, Any], output: Path,
) -> dict[str, Any]:
    tracks = {item["name"]: item for item in routing_plan["local_vertical_tracks"]}
    channels = sorted(
        floorplan["channels"], key=lambda item: float(item["center_x"])
    )
    commands: list[str] = []
    metrics: dict[str, Any] = {}

    for polarity in ("p", "n"):
        net = f"sum_{polarity}"
        rows = ROUTE_ROWS[polarity]
        local_offset = float(tracks[f"out_{polarity}"]["x"])
        taps = {
            int(channel["index"]): float(channel["center_x"]) + local_offset
            for channel in channels
        }
        left_channels, right_channels = channels[:2], channels[2:]
        left_pair_x = sum(taps[int(item["index"])] for item in left_channels) / 2.0
        right_pair_x = sum(taps[int(item["index"])] for item in right_channels) / 2.0
        root_x = (left_pair_x + right_pair_x) / 2.0
        load_x, load_terminal_y = map(
            float, floorplan["output_pair"][f"load_{polarity}"]
        )
        pin_name = str(floorplan["output_pair"][f"pin_{polarity}"])
        pin_x, pin_y = map(float, floorplan["analog_pins"][pin_name]["center"])

        commands.append(f"# balanced four-channel output tree -> {net}")
        source_paths: dict[str, float] = {}
        for pair_x, pair_channels in (
            (left_pair_x, left_channels),
            (right_pair_x, right_channels),
        ):
            pair_taps = [taps[int(item["index"])] for item in pair_channels]
            for channel in pair_channels:
                channel_index = int(channel["index"])
                x = taps[channel_index]
                commands.append(
                    wire_v("metal3", x, LOCAL_ANCHOR_Y, rows["leaf"], SUM_WIDTH)
                )
                commands.extend(via3_stack(x, rows["leaf"]))
                source_paths[f"ch{channel_index}_out_{polarity}"] = (
                    rows["leaf"] - LOCAL_ANCHOR_Y
                    + abs(x - pair_x)
                    + rows["root"] - rows["leaf"]
                    + abs(pair_x - root_x)
                    + rows["load"] - rows["root"]
                    + abs(root_x - load_x)
                    + load_terminal_y - rows["load"]
                )
            commands.append(
                wire_h(
                    "metal4", min(pair_taps), max(pair_taps),
                    rows["leaf"], SUM_WIDTH,
                )
            )
            commands.extend(via3_stack(pair_x, rows["leaf"]))
            commands.append(
                wire_v("metal3", pair_x, rows["leaf"], rows["root"], SUM_WIDTH)
            )
            commands.extend(via3_stack(pair_x, rows["root"]))

        commands.append(
            wire_h("metal4", left_pair_x, right_pair_x, rows["root"], SUM_WIDTH)
        )
        commands.extend(via3_stack(root_x, rows["root"]))
        commands.append(
            wire_v("metal3", root_x, rows["root"], rows["load"], SUM_WIDTH)
        )
        commands.extend(via3_stack(root_x, rows["load"]))
        commands.append(
            wire_h("metal4", root_x, load_x, rows["load"], SUM_WIDTH)
        )
        commands.extend(via3_stack(load_x, rows["load"]))

        # Exact R2 terminal access on the shared load resistor.
        commands.extend(li_contact_stack(load_x, load_terminal_y))
        commands.extend(via2_stack(load_x, load_terminal_y))
        commands.append(
            wire_v("metal3", load_x, rows["load"], load_terminal_y, SUM_WIDTH)
        )

        # A separate lower M4 row preserves the equal load-to-pad geometry;
        # it does not merge with or lengthen only one summing-tree branch.
        commands.append(
            wire_v("metal3", load_x, rows["output"], load_terminal_y, SUM_WIDTH)
        )
        commands.extend(via3_stack(load_x, rows["output"]))
        commands.append(
            wire_h("metal4", pin_x, load_x, rows["output"], SUM_WIDTH)
        )
        commands.extend(via3_stack(pin_x, rows["output"]))
        commands.append(
            wire_v("metal3", pin_x, BOTTOM_TRANSITION_Y, rows["output"], SUM_WIDTH)
        )
        commands.extend(via3_stack(pin_x, BOTTOM_TRANSITION_Y))
        commands.append(
            wire_v("metal4", pin_x, pin_y, BOTTOM_TRANSITION_Y, SUM_WIDTH)
        )
        commands.extend((
            f"# net label: {net}",
            f"box {fmt(pin_x)}um {fmt(pin_y)}um {fmt(pin_x)}um {fmt(pin_y)}um",
            f"label {{{net}}} FreeSans 0.10u -met4",
        ))

        metrics[net] = {
            "tree_root_x_um": root_x,
            "load_x_um": load_x,
            "aggregate_tree_m3_centerline_um": (
                4.0 * (rows["leaf"] - LOCAL_ANCHOR_Y)
                + 2.0 * (rows["root"] - rows["leaf"])
                + rows["load"] - rows["root"]
                + load_terminal_y - rows["load"]
            ),
            "aggregate_tree_m4_centerline_um": (
                right_pair_x - left_pair_x
                + sum(
                    max(taps[int(item["index"])] for item in pair)
                    - min(taps[int(item["index"])] for item in pair)
                    for pair in (left_channels, right_channels)
                )
                + abs(load_x - root_x)
            ),
            "source_to_load_centerline_um": source_paths,
            "load_to_pad_m3_centerline_um": (
                load_terminal_y - rows["output"]
                + rows["output"] - BOTTOM_TRANSITION_Y
            ),
            "load_to_pad_m4_centerline_um": (
                abs(load_x - pin_x) + BOTTOM_TRANSITION_Y - pin_y
            ),
            "tree_via3_sites": 11,
            "pad_route_via3_sites": 3,
        }

    body = "\n".join(commands)
    tcl = f"""# Generated by v2/tools/generate_output_summing_routes.py; do not edit.
set PROJECT_ROOT [pwd]
set SOURCE_GDS [file join $PROJECT_ROOT build v2 global_phase_tree magic v2_four_channel_phase_tree_routed.gds]
set OUT_DIR [file join $PROJECT_ROOT build v2 {STAGE} magic]
file mkdir $OUT_DIR
if {{![file exists $SOURCE_GDS]}} {{
    error "required global-phase-tree GDS does not exist: $SOURCE_GDS"
}}
gds read $SOURCE_GDS
if {{[lsearch -exact [cellname list all] v2_four_channel_phase_tree_routed] < 0}} {{
    error "global-phase-tree top cell was not imported"
}}
load v2_four_channel_phase_tree_routed
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
puts "OUTPUT_SUMMING_ROUTE_DRC_COUNT=$drc_count"
if {{$drc_count != 0}} {{
    feedback save [file join $OUT_DIR output_summing_route_drc.txt]
    error "refusing output-routed artifact with $drc_count DRC errors"
}}
cd $OUT_DIR
save {TOP}.mag
feedback clear
gds compress 0
gds write {TOP}.gds
set gds_feedback [feedback count]
puts "OUTPUT_SUMMING_ROUTE_GDS_FEEDBACK_COUNT=$gds_feedback"
if {{$gds_feedback != 0}} {{
    feedback save output_summing_route_gds_feedback.txt
    error "refusing output-routed artifact with $gds_feedback writer problems"
}}
quit -noprompt
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(tcl, encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--floorplan", type=Path, default=Path("v2/layout/floorplan.json"))
    parser.add_argument(
        "--routing-plan", type=Path, default=Path("v2/layout/routing_plan.json")
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("build/v2/output_summing_routes/route.tcl"),
    )
    args = parser.parse_args()
    metrics = generate(
        json.loads(args.floorplan.read_text(encoding="utf-8")),
        json.loads(args.routing_plan.read_text(encoding="utf-8")),
        args.output,
    )
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
