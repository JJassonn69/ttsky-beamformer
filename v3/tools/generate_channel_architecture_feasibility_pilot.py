#!/usr/bin/env python3
"""Generate an exact matrix pilot for the selected routing architecture.

The authoritative channel manifests are intentionally untouched.  A passing
pilot is required before the selected column pitch can be promoted into them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import build_channel_matrix_placement as placement_gen
import generate_channel_matrix_pilot as matrix_gen


ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE = ROOT / "v3/layout/channel_routing_architecture.json"
UNIT = ROOT / "v3/layout/vector_unit_placement.json"
CATALOG = ROOT / "v3/layout/channel_pcell_catalog.json"
BUILD = ROOT / "build/v3/channel_architecture_feasibility"
DEFAULT_MATRIX = BUILD / "channel_matrix_placement.json"
DEFAULT_TCL = BUILD / "build.tcl"
TOP = "v3_channel_architecture_feasibility"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", type=Path, default=ARCHITECTURE)
    parser.add_argument("--matrix-output", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--tcl-output", type=Path, default=DEFAULT_TCL)
    args = parser.parse_args()

    architecture = json.loads(args.architecture.read_text(encoding="utf-8"))
    selected_name = architecture["decision"]["selected"]
    selected = architecture["candidates"][selected_name]
    if selected["geometry_status"] != "pass":
        raise RuntimeError(f"selected architecture {selected_name} did not pass geometry")

    matrix = placement_gen.build(column_origins=selected["column_origins_um"])
    matrix["status"] = "architecture feasibility only; not authoritative"
    matrix["architecture_feasibility"] = {
        "architecture": selected_name,
        "source": "v3/layout/channel_routing_architecture.json",
        "projected_interchannel_active_gap_um": selected["guard_and_power"]["projected_interchannel_active_gap_um"],
        "promotion_authorized": False,
    }
    args.matrix_output.parent.mkdir(parents=True, exist_ok=True)
    args.matrix_output.write_text(
        json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    unit = json.loads(UNIT.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    source = matrix_gen.build_tcl(matrix, unit, catalog)
    source = source.replace("channel_matrix_pilot", "channel_architecture_feasibility")
    source = source.replace("v3_channel_matrix_pilot", TOP)
    source = source.replace("V3_CHANNEL_MATRIX", "V3_CHANNEL_ARCHITECTURE")
    source = source.replace("channel-matrix pilot", "channel-architecture feasibility pilot")
    marker = "puts \"V3_CHANNEL_ARCHITECTURE_GDS_FEEDBACK_COUNT=[feedback count]\"\nquit -noprompt"
    replacement = """set gds_feedback [feedback count]
puts \"V3_CHANNEL_ARCHITECTURE_GDS_FEEDBACK_COUNT=$gds_feedback\"
set summary [open [file join $WORKDIR physical_markers.txt] w]
puts $summary \"V3_CHANNEL_ARCHITECTURE_DRC_COUNT=$drc_count\"
puts $summary \"V3_CHANNEL_ARCHITECTURE_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback\"
puts $summary \"V3_CHANNEL_ARCHITECTURE_GDS_FEEDBACK_COUNT=$gds_feedback\"
close $summary
quit -noprompt"""
    if source.count(marker) != 1:
        raise RuntimeError("architecture feasibility marker block changed")
    source = source.replace(marker, replacement)
    args.tcl_output.parent.mkdir(parents=True, exist_ok=True)
    args.tcl_output.write_text(source, encoding="utf-8")
    print(args.matrix_output)
    print(args.tcl_output)
    print(f"selected={selected_name}")
    print(f"active_bbox={matrix['active_array_bbox']}")


if __name__ == "__main__":
    main()
