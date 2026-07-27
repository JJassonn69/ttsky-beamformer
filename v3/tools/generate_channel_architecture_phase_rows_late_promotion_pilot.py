#!/usr/bin/env python3
"""Add the exact per-row phase collectors to the late-promotion service channel."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import generate_channel_architecture_phase_rows_pilot as phase_rows
import generate_channel_architecture_service_late_promotion_pilot as service_gen
import generate_channel_row_pilot as row_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3/layout/channel_matrix_late_promotion.json"
ARCHITECTURE = ROOT / "v3/layout/channel_routing_architecture.json"
UNIT = ROOT / "v3/layout/vector_unit_late_promotion.json"
CATALOG = ROOT / "v3/layout/channel_pcell_catalog.json"
BUILD = ROOT / "build/v3/channel_architecture_phase_rows_late_promotion"
DEFAULT_OUTPUT = BUILD / "build.tcl"
DEFAULT_ROOTS = BUILD / "phase_row_roots.json"
TOP = "v3_channel_architecture_phase_rows_late_promotion"


def build_tcl(
    matrix: dict[str, Any], architecture: dict[str, Any], unit: dict[str, Any],
    catalog: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    source = service_gen.build_tcl(matrix, architecture, unit, catalog)
    source = source.replace(
        "channel_architecture_service_late_promotion",
        "channel_architecture_phase_rows_late_promotion",
    )
    source = source.replace(
        "v3_channel_architecture_service_late_promotion", TOP,
    )
    source = source.replace(
        "V3_CHANNEL_ARCHITECTURE_SERVICE_LATE",
        "V3_CHANNEL_ARCHITECTURE_PHASE_ROWS_LATE",
    )
    source = source.replace(
        "late-promotion channel-service pilot",
        "late-promotion channel phase-row pilot",
    )
    local_alias = re.compile(
        r"box [^\n]+\n"
        r"label u\d{2}_(?:lop|lon) center metal[34]\n"
        r"port make\nport class input\nport use signal\n"
        r"port connections n s e w\n?"
    )
    source, removed = local_alias.subn("", source)
    if removed != 30:
        raise RuntimeError(f"expected to remove 30 unit-local phase aliases, removed {removed}")

    commands, labels, manifest = phase_rows.phase_geometry(matrix, architecture)
    manifest["status"] = "late-promotion exact per-row phase handoff candidate; global inter-row trees absent"
    manifest["late_promotion"] = {
        "service_generator": "v3/tools/generate_channel_architecture_service_late_promotion_pilot.py",
        "all_five_rows_use_m1_analog_collection": True,
        "analog_gate_use_of_m3_m4": False,
    }
    manifest["provenance"]["generator"] = (
        "v3/tools/generate_channel_architecture_phase_rows_late_promotion_pilot.py"
    )
    insertion = "\n".join(commands + labels)
    marker = "\nsave $TOP.mag\nwriteall force\n"
    if source.count(marker) != 1:
        raise RuntimeError("late phase-row insertion marker changed")
    return source.replace(marker, f"\n{insertion}{marker}"), manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--architecture", type=Path, default=ARCHITECTURE)
    parser.add_argument("--unit", type=Path, default=UNIT)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--roots-output", type=Path, default=DEFAULT_ROOTS)
    args = parser.parse_args()
    values = [json.loads(path.read_text(encoding="utf-8")) for path in (
        args.matrix, args.architecture, args.unit, args.catalog,
    )]
    source, manifest = build_tcl(*values)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source, encoding="utf-8")
    args.roots_output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    print(args.output)
    print(args.roots_output)


if __name__ == "__main__":
    main()
