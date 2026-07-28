#!/usr/bin/env python3
"""Audit all 14 OpenROAD routes from the V3 controller to TinyTapeout pins."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from check_physical_control_analog_handoffs import validate


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir", type=Path,
        default=ROOT / "build/v3/control_boundary_handoffs/openroad",
    )
    parser.add_argument(
        "--plan", type=Path,
        default=ROOT / "v3/layout/physical_control_boundary_handoff_plan.json",
    )
    parser.add_argument(
        "--generator", type=Path,
        default=ROOT / "v3/tools/generate_physical_control_boundary_handoff_inputs.py",
    )
    parser.add_argument(
        "--report", type=Path,
        default=ROOT / "build/v3/control_boundary_handoffs/openroad/route_audit.json",
    )
    args = parser.parse_args()
    report = validate(args.workdir, args.plan, args.generator)
    report["scope"] = "14 V3 controller inputs routed to the exact TinyTapeout 2x2 top-boundary pin rectangles"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: report[key] for key in (
        "status", "errors", "route_count", "pin_count", "route_class_counts",
        "total_centerline_wire_length_um", "total_via_count",
        "nets_using_layer", "maximum_route_layer", "maximum_detour",
        "maximum_via_count",
    )}, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
