#!/usr/bin/env python3
"""Generate the selector route inputs aligned to the frozen late phase roots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import generate_selector_route_pilot as base


ROOT = Path(__file__).resolve().parents[2]
PLACEMENT = ROOT / "v3/layout/selector_placement.json"
TREES = ROOT / "v3/layout/group_phase_trees_late_promotion.json"
LOCAL_BUILD = ROOT / "build/v3/selector_route_late_promotion"
REMOTE_BUILD = Path("/home/jason-stone/tinytapeout-beamformer-v2-routefix/build/v3/selector_route_late_promotion")
TECH_LEF = Path("/home/jason-stone/tt-tools/reference/sky130hd-lef/sky130_fd_sc_hd.tlef")
CELL_LEF = Path("/home/jason-stone/tt-tools/reference/sky130hd-lef/sky130_fd_sc_hd_merged.lef")
NET_MAP = {
    "group0_lo_p": "g1_lop", "group0_lo_n": "g1_lon",
    "group1_lo_p": "g2_lop", "group1_lo_n": "g2_lon",
    "group2_lo_p": "g4_lop", "group2_lo_n": "g4_lon",
    "group3_lo_p": "g8_lop", "group3_lo_n": "g8_lon",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, default=LOCAL_BUILD)
    parser.add_argument("--remote-workdir", type=Path, default=REMOTE_BUILD)
    args = parser.parse_args()
    placement = json.loads(PLACEMENT.read_text(encoding="utf-8"))
    trees = json.loads(TREES.read_text(encoding="utf-8"))
    roots = {selector: float(trees["trees"][analog]["root"][0]) for selector, analog in NET_MAP.items()}
    base.OUTPUT_ROOT_X_UM = roots
    def_text, report = base.build_def(placement, row_gap_um=0.0, cell_gap_sites=0)
    report["phase_tree_manifest"] = str(TREES.relative_to(ROOT))
    report["selector_to_analog_net_map"] = NET_MAP
    report["output_root_x_um"] = roots
    report["status"] = "generated for late-promotion phase roots"
    args.workdir.mkdir(parents=True, exist_ok=True)
    (args.workdir / "input.def").write_text(def_text, encoding="utf-8")
    (args.workdir / "route.tcl").write_text(
        base.build_route_tcl(TECH_LEF, CELL_LEF, args.remote_workdir, 64), encoding="utf-8"
    )
    (args.workdir / "input_summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": report["status"], "output_root_x_um": roots}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
