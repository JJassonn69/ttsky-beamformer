#!/usr/bin/env python3
"""Map synthesized V3 physical control onto the pinned minimal SKY130 set."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from v2.tools import map_control_netlist as base


def cell_region(path: str) -> str:
    if path.startswith("config_storage/"):
        return "config_storage_bank"
    return "global_control_core"


def cell_role(path: str, q_net: str | None = None) -> str:
    if path.startswith("config_storage/"):
        if q_net and "/active_bits[" in q_net:
            return "active_vector_storage"
        if q_net and "/shift_bits[" in q_net:
            return "serial_shift_storage"
        return "configuration_logic"
    if path.startswith("quadrature_generator/"):
        return "quadrature_core"
    return "global_control_logic"


def insert_fanout_buffer_trees(
    report: dict[str, Any], cell_dir: Path, maximum_branch_loads: int = 16
) -> None:
    """Bound every physical signal branch with explicit foundry buffers.

    Yosys intentionally maps logic only; it does not perform physical clock or
    reset distribution in this flow.  A single 65-load clock and 98-load reset
    would be both difficult to route and electrically poor.  Split every net
    above the bounded load into deterministic ``buf_4`` branches before
    placement so routing, extraction, and later timing all see the real tree.
    """

    if maximum_branch_loads < 2:
        raise ValueError("maximum fanout branch must have at least two loads")
    buffer_spec = base.lef_cell_spec(cell_dir / "sky130_fd_sc_hd__buf_4.lef")
    report["library"]["buf4"] = buffer_spec
    cells = report["cells"]
    cells_by_name = {cell["instance"]: cell for cell in cells}

    def direction(endpoint: dict[str, str]) -> str:
        cell = cells_by_name[endpoint["instance"]]
        return report["library"][cell["short_cell"]]["pins"][endpoint["pin"]]["direction"]

    candidates: list[tuple[str, list[dict[str, str]]]] = []
    for net, endpoints in sorted(report["nets"].items()):
        sinks = [dict(endpoint) for endpoint in endpoints if direction(endpoint) == "input"]
        if len(sinks) > maximum_branch_loads:
            candidates.append((net, sinks))

    tree_report: list[dict[str, Any]] = []
    for net, sinks in candidates:
        # Names are stable across runs and naturally keep vector banks close.
        sinks.sort(key=lambda item: (item["instance"], item["pin"]))
        branches = [
            sinks[index:index + maximum_branch_loads]
            for index in range(0, len(sinks), maximum_branch_loads)
        ]
        for branch_index, branch in enumerate(branches):
            branch_net = f"{net}/fanout_branch[{branch_index}]"
            instance = f"physical_fanout/{net}/branch_{branch_index:02d}"
            for endpoint in branch:
                cell = cells_by_name[endpoint["instance"]]
                if cell["pins"][endpoint["pin"]] != net:
                    raise ValueError(f"{net}: fanout endpoint changed during buffering")
                cell["pins"][endpoint["pin"]] = branch_net
            buffer_cell = {
                "instance": instance,
                "cell": "sky130_fd_sc_hd__buf_4",
                "short_cell": "buf4",
                "region": "global_control_core",
                "role": "fanout_buffer",
                "source_type": "$physical_fanout_buffer",
                "pins": {
                    "A": net,
                    "X": branch_net,
                    "VGND": "VGND",
                    "VPWR": "VDPWR",
                },
                "size_um": buffer_spec["size_um"],
            }
            cells.append(buffer_cell)
            cells_by_name[instance] = buffer_cell
        tree_report.append({
            "root_net": net,
            "original_loads": len(sinks),
            "branch_count": len(branches),
            "branch_loads": [len(branch) for branch in branches],
            "maximum_branch_loads": maximum_branch_loads,
        })

    nets: dict[str, list[dict[str, str]]] = {}
    for cell in cells:
        for pin, net in cell["pins"].items():
            if pin in {"VGND", "VPWR", "VPB", "VNB"}:
                continue
            nets.setdefault(net, []).append({"instance": cell["instance"], "pin": pin})
    report["nets"] = nets
    report["fanout_buffer_trees"] = tree_report
    report["mapping_policy"].update({
        "physical_fanout_buffer": "sky130_fd_sc_hd__buf_4",
        "maximum_fanout_branch_loads": maximum_branch_loads,
        "fanout_tree_count": len(tree_report),
    })
    report["counts"] = {
        "total_cells": len(cells),
        "by_cell": dict(sorted(Counter(cell["short_cell"] for cell in cells).items())),
        "by_region": dict(sorted(Counter(cell["region"] for cell in cells).items())),
        "by_role": dict(sorted(Counter(cell["role"] for cell in cells).items())),
        "signal_nets": len(nets),
    }


def map_netlist(source: dict[str, Any], top: str, cell_dir: Path) -> dict[str, Any]:
    # Reuse the fully tested V2 generic-cell mapper, changing only physical
    # partition policy. V3 has no V2 phase/trim banks and therefore disables
    # the V2-specific decode relocation pass.
    original_region = base.cell_region
    original_role = base.cell_role
    original_partition = base.partition_phase_decode
    try:
        base.cell_region = cell_region
        base.cell_role = cell_role
        base.partition_phase_decode = lambda _physical, _specs: None
        report = base.map_netlist(source, top, cell_dir)
    finally:
        base.cell_region = original_region
        base.cell_role = original_role
        base.partition_phase_decode = original_partition
    insert_fanout_buffer_trees(report, cell_dir)
    report["mapping_policy"]["physical_partition"] = (
        "32-bit serial/active storage bank plus adjacent global controller"
    )
    report["mapping_policy"]["central_phase_selector_logic"] = "absent; selectors are frozen inside channel macros"
    return report


def render_structural_verilog(report: dict[str, Any]) -> str:
    text = base.render_structural_verilog(report)
    return (
        text.replace("Generated by v2/tools/map_control_netlist.py", "Generated by v3/tools/map_physical_control_netlist.py")
        .replace("v2_physical_control_core_mapped", "v3_physical_control_core_mapped")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "generic_json", type=Path,
        default=Path("build/v3/control_synthesis/generic_netlist.json"),
        nargs="?",
    )
    parser.add_argument(
        "cell_dir", type=Path,
        default=Path("third_party/sky130_fd_sc_hd_cells"),
        nargs="?",
    )
    parser.add_argument(
        "output", type=Path,
        default=Path("build/v3/control_mapping/physical_mapping.json"),
        nargs="?",
    )
    parser.add_argument("--top", default="v3_physical_control_core")
    parser.add_argument(
        "--verilog", type=Path,
        default=Path("build/v3/control_mapping/physical_mapping.v"),
    )
    args = parser.parse_args()
    report = map_netlist(
        json.loads(args.generic_json.read_text(encoding="utf-8")),
        args.top,
        args.cell_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.verilog.parent.mkdir(parents=True, exist_ok=True)
    args.verilog.write_text(render_structural_verilog(report), encoding="utf-8")
    print(json.dumps(report["counts"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
