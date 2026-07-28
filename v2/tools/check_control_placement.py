#!/usr/bin/env python3
"""Audit V2 control placement geometry, topology, taps, and wire cost."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from generate_control_placement import (
    POWER_PINS,
    ROW,
    SITE,
    access_center,
    row_orientation,
    transform_point,
)


def overlap(first: list[float], second: list[float]) -> bool:
    return not (
        first[2] <= second[0] + 1e-9
        or second[2] <= first[0] + 1e-9
        or first[3] <= second[1] + 1e-9
        or second[3] <= first[1] + 1e-9
    )


def anchors(
    integration: dict[str, Any], floorplan: dict[str, Any]
) -> dict[str, tuple[float, float]]:
    result = {
        "clk": (143.98, 225.26), "rst_n": (141.22, 225.26),
        "ena": (146.74, 225.26), "beam_select[0]": (138.46, 225.26),
        "beam_select[1]": (135.70, 225.26), "manual_mode": (130.18, 225.26),
        "channel_enable[0]": (127.42, 225.26),
        "channel_enable[1]": (124.66, 225.26),
        "channel_enable[2]": (121.90, 225.26),
        "channel_enable[3]": (119.14, 225.26),
        "cfg_clk": (116.38, 225.26), "cfg_data": (113.62, 225.26),
        "cfg_latch": (110.86, 225.26), "mixers_blank": (123.28, 176.0),
    }
    root_nets = ("phase_wave[0]", "phase_wave[1]", "phase_wave[3]", "phase_wave[2]")
    for item, net in zip(integration["quadrature_root_handoffs"], root_nets):
        result[net] = tuple(map(float, item["point"]))
    for item in integration["phase_control_handoffs"]["routes"]:
        result[f"{item['signal']}[{item['channel']}]"] = (
            float(item["x"]), float(integration["phase_control_handoffs"]["transition_y"])
        )
    trim = integration["trim_control_bus"]
    for index in range(16):
        result[f"active_trim_codes[{index}]"] = (
            float(trim["source_region_x"]),
            float(trim["first_track_y"]) + index * float(trim["track_pitch"]),
        )
    return result


def net_weight(net: str, endpoint_count: int) -> float:
    if net.startswith("phase_wave") or net.startswith("phase_select") or net.startswith("phase_enable"):
        base = 8.0
    elif net.startswith("active_trim_codes"):
        base = 4.0
    elif net in {"clk", "rst_n", "cfg_clk"}:
        base = 3.0
    elif net in {"serial_phase_to_trim", "apply_config", "cfg_latch"}:
        base = 2.5
    else:
        base = 1.0
    return base / max(1.0, endpoint_count / 4.0)


def hpwl_report(
    points: dict[str, list[tuple[float, float]]],
    mapping: dict[str, Any],
    fixed: dict[str, tuple[float, float]],
) -> dict[str, Any]:
    per_net: dict[str, dict[str, float | int]] = {}
    total = 0.0
    weighted = 0.0
    for net, endpoints in mapping["nets"].items():
        net_points = list(points.get(net, []))
        if net in fixed:
            net_points.append(fixed[net])
        if len(net_points) < 2:
            continue
        length = max(p[0] for p in net_points) - min(p[0] for p in net_points)
        length += max(p[1] for p in net_points) - min(p[1] for p in net_points)
        weight = net_weight(net, len(endpoints))
        per_net[net] = {"hpwl_um": length, "weight": weight, "endpoint_count": len(net_points)}
        total += length
        weighted += length * weight
    longest = sorted(
        ({"net": net, **record} for net, record in per_net.items()),
        key=lambda item: float(item["hpwl_um"]), reverse=True,
    )[:12]
    return {"total_hpwl_um": total, "weighted_hpwl": weighted,
            "routed_net_count": len(per_net), "longest_nets": longest,
            "per_net": per_net}


def placed_net_points(placement: dict[str, Any]) -> dict[str, list[tuple[float, float]]]:
    points: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for cell in placement["placements"]:
        for access in cell["pin_access"].values():
            points[access["net"]].append(tuple(map(float, access["point_um"])))
    return points


def naive_points(
    mapping: dict[str, Any], placement: dict[str, Any]
) -> dict[str, list[tuple[float, float]]]:
    """Legal row-balanced baseline using the same regions and LEF pin access."""

    points: dict[str, list[tuple[float, float]]] = defaultdict(list)
    by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cell in mapping["cells"]:
        by_region[cell["region"]].append(cell)
    for region, cells in by_region.items():
        spec = placement["regions"][region]
        x0, y0, x1, _ = map(float, spec["bbox"])
        rows = int(spec["row_count"])
        used = [0.0] * rows
        origins: dict[str, tuple[float, int]] = {}
        for cell in sorted(cells, key=lambda item: item["instance"]):
            width = float(cell["size_um"][0])
            row = min(range(rows), key=lambda index: (used[index], index))
            x = snap = math.ceil((x0 + used[row]) / SITE - 1e-9) * SITE
            if x + width > x1 + 1e-9:
                raise ValueError(f"naive baseline overflows {region} row {row}")
            origins[cell["instance"]] = (x, row)
            used[row] = x + width + SITE - x0
        for cell in cells:
            x, row = origins[cell["instance"]]
            y = y0 + row * ROW
            orientation = row_orientation(row)
            library = mapping["library"][cell["short_cell"]]
            width, height = map(float, library["size_um"])
            for pin, net in cell["pins"].items():
                if pin in POWER_PINS:
                    continue
                px, py, _ = access_center(library, pin)
                px, py = transform_point((px, py), width, height, orientation)
                points[net].append((x + px, y + py))
    return points


def validate(
    mapping: dict[str, Any],
    placement: dict[str, Any],
    integration: dict[str, Any],
    floorplan: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    mapped = {cell["instance"]: cell for cell in mapping["cells"]}
    signal = {cell["instance"]: cell for cell in placement["placements"]}
    taps = placement["well_taps"]
    fillers = placement.get("fillers", [])
    if set(signal) != set(mapped):
        errors.append(
            f"mapped/placed instance mismatch missing={sorted(set(mapped)-set(signal))} "
            f"extra={sorted(set(signal)-set(mapped))}"
        )
    all_items = placement["placements"] + taps + fillers
    by_row: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for item in all_items:
        region = placement["regions"].get(item["region"])
        if region is None:
            errors.append(f"{item['instance']}: unknown placement region")
            continue
        x, y = map(float, item["origin_um"])
        box = list(map(float, item["bbox_um"]))
        region_box = list(map(float, region["bbox"]))
        row = int(item["row"])
        if not math.isclose(x / SITE, round(x / SITE), abs_tol=1e-7):
            errors.append(f"{item['instance']}: X is off the {SITE} um site grid")
        if not math.isclose(y, region_box[1] + row * ROW, abs_tol=1e-7):
            errors.append(f"{item['instance']}: Y is off its row grid")
        if not (region_box[0] <= box[0] and box[2] <= region_box[2]
                and region_box[1] <= box[1] and box[3] <= region_box[3]):
            errors.append(f"{item['instance']}: bbox leaves {item['region']}")
        expected = {row_orientation(row), row_orientation(row, True)}
        if item["orientation"] not in expected:
            errors.append(f"{item['instance']}: orientation breaks row power abutment")
        by_row[(item["region"], row)].append(item)
        if item["role"] != "well_tap" and item["instance"] in mapped:
            expected_width, expected_height = map(float, mapped[item["instance"]]["size_um"])
            if not math.isclose(box[2] - box[0], expected_width, abs_tol=1e-7):
                errors.append(f"{item['instance']}: width differs from LEF")
            if not math.isclose(box[3] - box[1], expected_height, abs_tol=1e-7):
                errors.append(f"{item['instance']}: height differs from LEF")
            for pin, access in item["pin_access"].items():
                if access["net"] != mapped[item["instance"]]["pins"][pin]:
                    errors.append(f"{item['instance']}.{pin}: access net mismatch")
                px, py = map(float, access["point_um"])
                if not (box[0] - 1e-9 <= px <= box[2] + 1e-9
                        and box[1] - 1e-9 <= py <= box[3] + 1e-9):
                    errors.append(f"{item['instance']}.{pin}: access leaves cell bbox")

    overlap_count = 0
    for key, items in by_row.items():
        items = sorted(items, key=lambda item: item["bbox_um"][0])
        for first, second in zip(items, items[1:]):
            if overlap(first["bbox_um"], second["bbox_um"]):
                overlap_count += 1
                errors.append(f"{key}: {first['instance']} overlaps {second['instance']}")

    utilization: dict[str, dict[str, float]] = {}
    for region_name, region in placement["regions"].items():
        width = float(region["bbox"][2]) - float(region["bbox"][0])
        row_values: dict[str, float] = {}
        for row in range(int(region["row_count"])):
            used = sum(
                float(item["bbox_um"][2]) - float(item["bbox_um"][0])
                for item in by_row[(region_name, row)]
                if item["role"] not in ("well_tap", "power_filler")
            )
            value = used / width
            row_values[str(row)] = value
            if value > float(integration["rules"]["maximum_standard_cell_utilization"]) + 1e-9:
                errors.append(f"{region_name} row {row} utilization {value:.3f} exceeds limit")
        utilization[region_name] = row_values

    tap_pitch = float(integration["rules"]["maximum_welltap_pitch"])
    tap_audit: dict[str, dict[str, float]] = {}
    for region_name, region in placement["regions"].items():
        x0, _, x1, _ = map(float, region["bbox"])
        for row in range(int(region["row_count"])):
            xs = sorted(
                float(item["origin_um"][0]) for item in taps
                if item["region"] == region_name and int(item["row"]) == row
            )
            if not xs:
                errors.append(f"{region_name} row {row} has no well taps")
                continue
            gaps = [xs[0] - x0, *(b - a for a, b in zip(xs, xs[1:])), x1 - xs[-1]]
            maximum = max(gaps)
            tap_audit[f"{region_name}:{row}"] = {"maximum_gap_um": maximum, "tap_count": len(xs)}
            if maximum > tap_pitch + 1e-9:
                errors.append(f"{region_name} row {row} tap gap {maximum:.3f} um")

    trim_q: list[tuple[int, float]] = []
    for cell in mapping["cells"]:
        if cell["role"] != "trim_active_storage" or "Q" not in cell["pins"]:
            continue
        index = int(cell["pins"]["Q"].split("[")[1].split("]")[0])
        trim_q.append((index, float(signal[cell["instance"]]["pin_access"]["Q"]["point_um"][0])))
    trim_q.sort()
    trim_pitch_min = min(second[1] - first[1] for first, second in zip(trim_q, trim_q[1:]))
    required_pitch = 0.4 + float(integration["rules"]["minimum_met3_met4_spacing"])
    if trim_pitch_min < required_pitch - 1e-9:
        errors.append(f"trim Q M3 columns have only {trim_pitch_min:.3f} um pitch")

    fixed = anchors(integration, floorplan)
    optimized = hpwl_report(placed_net_points(placement), mapping, fixed)
    naive = hpwl_report(naive_points(mapping, placement), mapping, fixed)
    improvement = 1.0 - float(optimized["weighted_hpwl"]) / float(naive["weighted_hpwl"])
    if improvement <= 0.0:
        errors.append(f"connectivity placement does not improve weighted HPWL ({improvement:.3%})")

    # The phase shift register is deliberately interleaved above the active
    # phase bank.  Guard the actual electrical result, not only the instance
    # order: every stored phase-bit net must remain local and the package
    # cfg_data handoff must not regress into an across-bank route.
    optimized_nets = optimized["per_net"]
    phase_shift_hpwl = {
        net: float(optimized_nets[net]["hpwl_um"])
        for net in sorted(optimized_nets)
        if net.startswith("phase_config/shift_bits[")
    }
    expected_shift_nets = {
        f"phase_config/shift_bits[{index}]" for index in range(1, 8)
    }
    if set(phase_shift_hpwl) != expected_shift_nets:
        errors.append(
            "phase-shift placement audit does not cover shift_bits[1:7]"
        )
    maximum_shift_hpwl = max(phase_shift_hpwl.values(), default=float("inf"))
    shift_limit = float(integration["rules"]["maximum_phase_shift_bit_hpwl_um"])
    if maximum_shift_hpwl > shift_limit + 1e-9:
        errors.append(
            f"phase shift-bit HPWL {maximum_shift_hpwl:.3f} um exceeds "
            f"{shift_limit:.3f} um"
        )
    cfg_data_hpwl = float(optimized_nets.get("cfg_data", {}).get("hpwl_um", float("inf")))
    cfg_data_limit = float(integration["rules"]["maximum_cfg_data_hpwl_um"])
    if cfg_data_hpwl > cfg_data_limit + 1e-9:
        errors.append(
            f"cfg_data HPWL {cfg_data_hpwl:.3f} um exceeds {cfg_data_limit:.3f} um"
        )

    # Every mux/FF enabled_d connection must be compact unless it is one of
    # the 16 deliberately static trim-active tradeoff nets.  That exception
    # was measured against the reversed component order: shortening those
    # links increases total HPWL by 74.423 um and weighted HPWL by 169.150,
    # principally by stretching the shift-chain and shared trim logic.
    enabled_d = {
        net: float(record["hpwl_um"])
        for net, record in optimized_nets.items()
        if net.endswith("/enabled_d")
    }
    local_pair_limit = float(integration["rules"]["maximum_local_pair_hpwl_um"])
    static_trim_limit = float(
        integration["rules"]["maximum_static_trim_enabled_hpwl_um"]
    )
    static_tradeoffs = {
        net: length for net, length in enabled_d.items()
        if length > local_pair_limit + 1e-9
    }
    expected_static_count = int(
        integration["rules"]["expected_static_trim_enabled_tradeoff_count"]
    )
    if len(static_tradeoffs) != expected_static_count:
        errors.append(
            f"expected {expected_static_count} static trim enabled_d tradeoffs, "
            f"found {len(static_tradeoffs)}"
        )
    if any(not net.startswith("trim_config/") for net in static_tradeoffs):
        errors.append("a non-trim enabled_d pair exceeds the local-pair HPWL limit")
    if any(length > static_trim_limit + 1e-9 for length in static_tradeoffs.values()):
        errors.append("a static trim enabled_d route exceeds its measured HPWL limit")

    orientation_audit = placement.get("orientation_optimization", {})
    if int(orientation_audit.get("eligible_residual_cells", 0)) != 36:
        errors.append("residual orientation audit does not cover all 36 eligible cells")
    if float(orientation_audit.get("improvement_um", 0.0)) <= 0.0:
        errors.append("residual orientation optimization has no measured improvement")

    # Filler cells must close every complete site in the reserved digital row.
    # This is a well-continuity rule, not an aesthetic density rule.
    unfilled_sites: list[str] = []
    for region_name, region in placement["regions"].items():
        x0, _, x1, _ = map(float, region["bbox"])
        for row in range(int(region["row_count"])):
            items = by_row[(region_name, row)]
            for site in range(
                math.ceil(x0 / SITE - 1e-9),
                math.floor((x1 - SITE) / SITE + 1e-9) + 1,
            ):
                x = site * SITE
                if not any(
                    x < float(item["bbox_um"][2]) - 1e-9
                    and x + SITE > float(item["bbox_um"][0]) + 1e-9
                    for item in items
                ):
                    unfilled_sites.append(f"{region_name}:{row}:{x:.2f}")
    if unfilled_sites:
        errors.append(f"unfilled standard-cell row sites: {unfilled_sites[:12]}")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "mapped_standard_cells": len(signal),
        "well_taps": len(taps),
        "fillers": len(fillers),
        "overlap_count": overlap_count,
        "row_signal_utilization": utilization,
        "tap_rows": tap_audit,
        "trim_output_columns_um": [x for _, x in trim_q],
        "minimum_trim_output_pitch_um": trim_pitch_min,
        "optimized_wire_cost": optimized,
        "naive_row_major_wire_cost": naive,
        "weighted_hpwl_improvement_fraction": improvement,
        "orientation_optimization": orientation_audit,
        "unfilled_complete_site_count": len(unfilled_sites),
        "phase_shift_chain": {
            "topology": "channel_aligned_two_row_interleave",
            "row_transition_count": 7,
            "phase_bit_hpwl_um": phase_shift_hpwl,
            "maximum_phase_bit_hpwl_um": maximum_shift_hpwl,
            "maximum_phase_bit_hpwl_limit_um": shift_limit,
            "cfg_data_hpwl_um": cfg_data_hpwl,
            "cfg_data_hpwl_limit_um": cfg_data_limit,
        },
        "paired_storage": {
            "enabled_d_net_count": len(enabled_d),
            "maximum_local_pair_hpwl_um": max(
                (length for net, length in enabled_d.items()
                 if net not in static_tradeoffs), default=0.0
            ),
            "local_pair_hpwl_limit_um": local_pair_limit,
            "static_trim_tradeoff_count": len(static_tradeoffs),
            "static_trim_tradeoff_nets": dict(sorted(static_tradeoffs.items())),
            "maximum_static_trim_enabled_hpwl_um": max(
                static_tradeoffs.values(), default=0.0
            ),
            "static_trim_enabled_hpwl_limit_um": static_trim_limit,
            "reversed_order_total_hpwl_penalty_um": 74.4225,
            "reversed_order_weighted_hpwl_penalty": 169.150192307685,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("placement", type=Path)
    parser.add_argument("integration", type=Path)
    parser.add_argument("floorplan", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate(
        json.loads(args.mapping.read_text(encoding="utf-8")),
        json.loads(args.placement.read_text(encoding="utf-8")),
        json.loads(args.integration.read_text(encoding="utf-8")),
        json.loads(args.floorplan.read_text(encoding="utf-8")),
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
