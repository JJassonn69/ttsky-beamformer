#!/usr/bin/env python3
"""Check measured PCell dimensions against the constrained V2 zones."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate_cell_fit(floorplan: dict[str, Any], dimensions: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    cells = dimensions["pcells"]
    assumptions = dimensions["placement_assumptions"]
    gap = float(assumptions["minimum_device_gap_um"])

    slice_widths = [channel["slice_bbox"][2] - channel["slice_bbox"][0] for channel in floorplan["channels"]]
    slice_heights = [channel["slice_bbox"][3] - channel["slice_bbox"][1] for channel in floorplan["channels"]]
    if max(slice_widths) - min(slice_widths) > 1e-9:
        errors.append(f"channel slices have unequal widths: {slice_widths}")
    if max(slice_heights) - min(slice_heights) > 1e-9:
        errors.append(f"channel slices have unequal heights: {slice_heights}")

    slice_width = min(slice_widths)
    slice_height = min(slice_heights)
    gm_row_width = 2.0 * cells["gm_nfet_guarded"]["width_um"] + gap
    mixer_row_width = 2.0 * cells["mixer_nfet_guarded"]["width_um"] + gap
    trim_row_width = cells["trim_main_third_nfet_shared_guard"]["width_um"]
    active_core_width = max(gm_row_width, mixer_row_width, trim_row_width)
    input_resistor_width = cells["input_bias_resistor_guarded"]["width_um"]
    required_width = (
        input_resistor_width
        + float(assumptions["input_resistor_and_device_gap_um"])
        + active_core_width
    )
    if required_width > slice_width:
        errors.append(
            f"measured channel row needs {required_width:.3f} um but slice provides {slice_width:.3f} um"
        )

    gm_rows_height = 2.0 * cells["gm_nfet_guarded"]["height_um"] + gap
    mixer_rows_height = 4.0 * cells["mixer_nfet_guarded"]["height_um"] + 3.0 * gap
    trim_rows_height = (
        assumptions["trim_rows_per_channel"]
        * cells["trim_main_third_nfet_shared_guard"]["height_um"]
        + (assumptions["trim_rows_per_channel"] - 1) * gap
    )
    local_route_allowance = 8.0
    interblock_gaps = 3.0 * gap
    required_height = (
        gm_rows_height
        + mixer_rows_height
        + trim_rows_height
        + local_route_allowance
        + interblock_gaps
    )
    if required_height > slice_height:
        errors.append(
            f"measured channel stack needs {required_height:.3f} um but slice provides {slice_height:.3f} um"
        )

    input_resistor_height = cells["input_bias_resistor_guarded"]["height_um"]
    if input_resistor_height > slice_height:
        errors.append(
            f"input resistor needs {input_resistor_height:.3f} um height but slice provides {slice_height:.3f} um"
        )

    selector_heights = [
        channel["phase_selector_bbox"][3] - channel["phase_selector_bbox"][1]
        for channel in floorplan["channels"]
    ]
    if max(selector_heights) - min(selector_heights) > 1e-9:
        errors.append(f"phase-selector slices have unequal heights: {selector_heights}")
    reserved_phase_selector_height = 28.0
    if reserved_phase_selector_height > min(selector_heights):
        errors.append(
            f"phase selector needs {reserved_phase_selector_height:.3f} um but zone provides {min(selector_heights):.3f} um"
        )

    load_zone = next(zone for zone in floorplan["zones"] if zone["name"] == "differential_load_pair")
    load_bbox = load_zone["bbox"]
    load = cells["output_load_resistor_guarded"]
    load_pair_width = (
        floorplan["output_pair"]["load_p_center"][0]
        - floorplan["output_pair"]["load_n_center"][0]
        + load["width_um"]
    )
    load_pair_height = load["height_um"]
    if load_pair_width > load_bbox[2] - load_bbox[0]:
        errors.append("measured differential load pair does not fit its reserved width")
    if load_pair_height > load_bbox[3] - load_bbox[1]:
        errors.append("measured differential load pair does not fit its reserved height")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "channel_slice_width_um": slice_width,
        "channel_required_row_width_um": required_width,
        "channel_width_margin_um": slice_width - required_width,
        "channel_slice_height_um": slice_height,
        "channel_required_stack_height_um": required_height,
        "channel_height_margin_um": slice_height - required_height,
        "input_resistor_height_um": input_resistor_height,
        "phase_selector_reserved_height_um": reserved_phase_selector_height,
        "phase_selector_zone_height_um": min(selector_heights),
        "differential_load_pair_width_um": load_pair_width,
        "differential_load_pair_height_um": load_pair_height,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("floorplan", type=Path)
    parser.add_argument("dimensions", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    floorplan = json.loads(args.floorplan.read_text(encoding="utf-8"))
    dimensions = json.loads(args.dimensions.read_text(encoding="utf-8"))
    report = validate_cell_fit(floorplan, dimensions)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
