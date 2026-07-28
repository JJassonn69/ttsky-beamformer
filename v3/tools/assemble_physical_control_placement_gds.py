#!/usr/bin/env python3
"""Compose the placed V3 controller over the frozen four-channel power top."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))
import assemble_control_placement_gds as base
from normalize_foundry_cells import normalize


TOP = "v3_four_channel_control_placed"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path,
        default=Path("v3/frozen/four_channel_power_integration/v3_four_channel_power_integration.gds"),
    )
    parser.add_argument("--source-top", default="v3_four_channel_power_integration")
    parser.add_argument(
        "--placement", type=Path,
        default=Path("build/v3/control_placement/physical_control_placement.json"),
    )
    parser.add_argument(
        "--cell-dir", type=Path,
        default=Path("third_party/sky130_fd_sc_hd_cells"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("build/v3/control_placement/direct/v3_four_channel_control_placed.gds"),
    )
    parser.add_argument(
        "--report", type=Path,
        default=Path("build/v3/control_placement/direct/assembly_report.json"),
    )
    args = parser.parse_args()
    base.TOP = TOP
    output, report = base.assemble(
        args.source,
        args.source_top,
        json.loads(args.placement.read_text(encoding="utf-8")),
        args.cell_dir,
    )
    normalized, normalization = normalize(output, args.cell_dir)
    output = normalized
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    report["policy"] = {
        "frozen_source_geometry_modified": False,
        "assembly": "direct GDS hierarchy; no foundry cell polygon regeneration",
        "controller_count": 1,
        "standard_cell_master_policy": "all used cells restored from pinned foundry GDS",
    }
    report["foundry_cell_normalization"] = normalization
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
