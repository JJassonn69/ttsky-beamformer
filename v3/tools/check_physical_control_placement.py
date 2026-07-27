#!/usr/bin/env python3
"""Audit the deterministic V3 shared-controller placement contract."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SITE = 0.46
ROW = 2.72
X0 = 181.24
X1 = 319.70
Y0 = 171.36
ROW_COUNT = 17
GLOBAL_X1 = 245.18
CONFIG_X0 = 245.64
MAX_TAP_PITCH = 13.80


def close(a: float, b: float, tolerance: float = 1e-6) -> bool:
    return abs(a - b) <= tolerance


def on_grid(value: float, pitch: float) -> bool:
    return close(value / pitch, round(value / pitch))


def driver(mapping: dict[str, Any], net: str) -> tuple[str, str]:
    result: list[tuple[str, str]] = []
    for cell in mapping["cells"]:
        spec = mapping["library"][cell["short_cell"]]
        for pin, pin_net in cell["pins"].items():
            if (
                pin_net == net
                and spec["pins"].get(pin, {}).get("direction") == "output"
            ):
                result.append((cell["instance"], pin))
    if len(result) != 1:
        raise ValueError(f"{net}: expected one driver, got {result}")
    return result[0]


def validate(mapping: dict[str, Any], placement: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    functional = placement["placements"]
    taps = placement["well_taps"]
    fillers = placement["fillers"]
    all_items = functional + taps + fillers
    mapped = {cell["instance"] for cell in mapping["cells"]}
    placed = {item["instance"] for item in functional}
    if placed != mapped:
        errors.append(
            f"mapped/placed instance mismatch: missing={sorted(mapped - placed)}, "
            f"extra={sorted(placed - mapped)}"
        )
    if len(placed) != len(functional):
        errors.append("duplicate functional placement instance")

    row_items: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in all_items:
        row = int(item["row"])
        x0, y0, x1, y1 = map(float, item["bbox_um"])
        ox, oy = map(float, item["origin_um"])
        if row < 0 or row >= ROW_COUNT:
            errors.append(f"{item['instance']}: row {row} out of bounds")
        if not on_grid(ox, SITE):
            errors.append(f"{item['instance']}: X origin is off the {SITE} um site grid")
        if not close(oy, Y0 + row * ROW):
            errors.append(f"{item['instance']}: Y origin does not match row {row}")
        if x0 < X0 - 1e-6 or x1 > X1 + 1e-6 or y0 < Y0 - 1e-6:
            errors.append(f"{item['instance']}: bbox leaves shared-control region")
        if not close(x0, ox) or not close(y0, oy):
            errors.append(f"{item['instance']}: bbox lower-left differs from origin")
        if not close(y1 - y0, ROW):
            errors.append(f"{item['instance']}: height is not one standard-cell row")
        row_items[row].append(item)

    overlap_count = 0
    uncovered_sites = 0
    duplicate_sites = 0
    first_site = round(X0 / SITE)
    last_site = round(X1 / SITE)
    for row in range(ROW_COUNT):
        occupancy: Counter[int] = Counter()
        ordered = sorted(row_items[row], key=lambda item: item["bbox_um"][0])
        for left, right in zip(ordered, ordered[1:]):
            if float(left["bbox_um"][2]) > float(right["bbox_um"][0]) + 1e-9:
                overlap_count += 1
        for item in ordered:
            lo = round(float(item["bbox_um"][0]) / SITE)
            hi = round(float(item["bbox_um"][2]) / SITE)
            if not close((float(item["bbox_um"][2]) - float(item["bbox_um"][0])) / SITE, hi - lo):
                errors.append(f"{item['instance']}: width is not an integer number of sites")
            occupancy.update(range(lo, hi))
        uncovered_sites += sum(occupancy[site] == 0 for site in range(first_site, last_site))
        duplicate_sites += sum(occupancy[site] > 1 for site in range(first_site, last_site))
    if overlap_count:
        errors.append(f"{overlap_count} same-row physical overlaps")
    if uncovered_sites:
        errors.append(f"{uncovered_sites} complete sites are not filled")
    if duplicate_sites:
        errors.append(f"{duplicate_sites} complete sites are multiply occupied")

    maximum_tap_gap = 0.0
    for row in range(ROW_COUNT):
        xs = [X0] + sorted(
            float(item["origin_um"][0]) for item in taps if int(item["row"]) == row
        ) + [X1]
        if len(xs) == 2:
            errors.append(f"row {row}: no explicit well tap")
            continue
        maximum_tap_gap = max(maximum_tap_gap, max(b - a for a, b in zip(xs, xs[1:])))
    if maximum_tap_gap > MAX_TAP_PITCH + 1e-6:
        errors.append(
            f"maximum tap gap {maximum_tap_gap:.6f} exceeds {MAX_TAP_PITCH:.6f} um"
        )

    by_name = {item["instance"]: item for item in functional}
    storage_pair_max_gap = 0.0
    storage_bit_rows: dict[str, dict[int, int]] = {
        "active": {}, "shift": {}
    }
    for cell in mapping["cells"]:
        if not cell["instance"].endswith("/state_ff"):
            continue
        if cell["role"] not in ("active_vector_storage", "serial_shift_storage"):
            continue
        prefix = cell["instance"].rsplit("/", 1)[0]
        ff = by_name[cell["instance"]]
        mux = by_name.get(f"{prefix}/enable_mux")
        if mux is None:
            errors.append(f"{prefix}: paired enable mux is absent")
            continue
        if ff["row"] != mux["row"]:
            errors.append(f"{prefix}: FF and mux occupy different rows")
        boxes = sorted((ff["bbox_um"], mux["bbox_um"]), key=lambda box: box[0])
        gap = float(boxes[1][0]) - float(boxes[0][2])
        storage_pair_max_gap = max(storage_pair_max_gap, gap)
        if not close(gap, SITE):
            errors.append(f"{prefix}: local FF/mux gap is {gap:.6f}, expected {SITE}")
        q_net = cell["pins"]["Q"]
        bit = int(q_net.rsplit("[", 1)[1][:-1])
        bank = "active" if cell["role"] == "active_vector_storage" else "shift"
        storage_bit_rows[bank][bit] = int(ff["row"])
    for bank, rows in storage_bit_rows.items():
        if set(rows) != set(range(32)):
            errors.append(f"{bank}: incomplete 32-bit storage row map")
        for bit, row in rows.items():
            if row != bit // 2:
                errors.append(f"{bank} bit {bit}: row {row} != {bit // 2}")

    final_driver_errors = 0
    for bit in range(32):
        name, _ = driver(mapping, f"group_codes[{bit}]")
        if int(by_name[name]["row"]) != bit // 2:
            final_driver_errors += 1
    if final_driver_errors:
        errors.append(f"{final_driver_errors} final group drivers are not bit-row aligned")
    phase_rows = {3: 8, 2: 9, 1: 10, 0: 11}
    for phase, expected_row in phase_rows.items():
        name, _ = driver(mapping, f"phase_wave[{phase}]")
        if int(by_name[name]["row"]) != expected_row:
            errors.append(f"phase_wave[{phase}] driver is not on row {expected_row}")

    global_width = GLOBAL_X1 - X0
    config_width = X1 - CONFIG_X0
    row_utilization: dict[str, dict[str, float]] = {}
    max_global = 0.0
    max_config = 0.0
    for row in range(ROW_COUNT):
        global_used = sum(
            float(item["bbox_um"][2]) - float(item["bbox_um"][0])
            for item in functional
            if item["row"] == row and item["region"] == "global_control_core"
        )
        config_used = sum(
            float(item["bbox_um"][2]) - float(item["bbox_um"][0])
            for item in functional
            if item["row"] == row and item["region"] == "config_storage_bank"
        )
        gu = global_used / global_width
        cu = config_used / config_width
        max_global = max(max_global, gu)
        max_config = max(max_config, cu)
        row_utilization[str(row)] = {"global": gu, "configuration": cu}
    if max_global > 0.76 + 1e-9:
        errors.append(f"global row utilization {max_global:.4f} exceeds 0.76")
    if max_config > 0.74 + 1e-9:
        errors.append(f"configuration row utilization {max_config:.4f} exceeds 0.74")

    report = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "mapped_standard_cells": len(mapped),
        "placed_standard_cells": len(functional),
        "well_taps": len(taps),
        "fillers": len(fillers),
        "overlap_count": overlap_count,
        "uncovered_complete_site_count": uncovered_sites,
        "multiply_occupied_site_count": duplicate_sites,
        "maximum_tap_gap_um": maximum_tap_gap,
        "maximum_storage_pair_gap_um": storage_pair_max_gap,
        "maximum_global_row_utilization": max_global,
        "maximum_configuration_row_utilization": max_config,
        "row_signal_utilization": row_utilization,
        "placement_hpwl_um": placement["metrics"]["placement_hpwl_um"],
        "orientation_optimization": placement["metrics"]["orientation_optimization"],
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mapping", type=Path, nargs="?",
        default=Path("build/v3/control_mapping/physical_mapping.json"),
    )
    parser.add_argument(
        "placement", type=Path, nargs="?",
        default=Path("build/v3/control_placement/physical_control_placement.json"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("build/v3/control_placement/placement_audit.json"),
    )
    args = parser.parse_args()
    report = validate(
        json.loads(args.mapping.read_text(encoding="utf-8")),
        json.loads(args.placement.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
