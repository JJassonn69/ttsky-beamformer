#!/usr/bin/env python3
"""Generate a bounded OpenROAD route pilot for one V3 local selector."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLACEMENT = ROOT / "v3" / "layout" / "selector_placement.json"
DBU = 1000
ROUTING_PITCH_UM = 0.34
CELL_SITE_WIDTH_UM = 0.46
MACROS = {
    "mux2": "sky130_fd_sc_hd__mux2_1",
    "and2": "sky130_fd_sc_hd__and2_1",
    "and2b": "sky130_fd_sc_hd__and2b_1",
    "tap": "sky130_fd_sc_hd__tapvpwrvgnd_1",
    "fill": "sky130_fd_sc_hd__fill_1",
}
ORIENTATIONS = {"R0": "N", "MX": "FS"}


def q(value: float) -> int:
    return round(value * DBU)


def tcl_path(path: Path) -> str:
    value = str(path)
    if "{" in value or "}" in value:
        raise ValueError(f"invalid Tcl path: {value}")
    return "{" + value + "}"


def boundary_pins() -> dict[str, dict[str, Any]]:
    pins: dict[str, dict[str, Any]] = {}
    for index, name in enumerate(("phase_0", "phase_90", "phase_180", "phase_270")):
        pins[name] = {
            "direction": "INPUT", "layer": "met3", "fixed": [0.0, 33.0 - 0.8 * index],
            "rect": [0.0, -0.15, 0.84, 0.15],
        }
    for index, name in enumerate(f"group{group}_bit{bit}" for group in range(4) for bit in range(2)):
        pins[name] = {
            "direction": "INPUT", "layer": "met3", "fixed": [15.74, 28.8 - 0.8 * index],
            "rect": [-0.84, -0.15, 0.0, 0.15],
        }
    for index, name in enumerate(("channel_enable", "mixers_blank")):
        pins[name] = {
            "direction": "INPUT", "layer": "met3", "fixed": [15.74, 21.6 - 0.8 * index],
            "rect": [-0.84, -0.15, 0.0, 0.15],
        }
    for index, name in enumerate(f"group{group}_lo_{side}" for group in range(4) for side in ("p", "n")):
        pins[name] = {
            "direction": "OUTPUT", "layer": "met2", "fixed": [3.8 + 1.4 * index, 0.0],
            "rect": [-0.15, 0.0, 0.15, 0.84],
        }
    return pins


def build_def(
    data: dict[str, Any], row_gap_um: float = 0.0, cell_gap_sites: int = 0
) -> tuple[str, dict[str, Any]]:
    template = data["channel_template"]
    instances = template["instances"]
    pins = boundary_pins()
    nets: dict[str, list[tuple[str, str]]] = {}
    row_order: dict[str, int] = {}
    for row in range(template["row_count"]):
        row_instances = sorted(
            (item for item in instances if item["row"] == row), key=lambda item: item["bbox"][0]
        )
        row_order.update({item["name"]: index for index, item in enumerate(row_instances)})
    for item in instances:
        for pin, net in item["connections"].items():
            nets.setdefault(net, []).append((item["name"], pin))
    for name in pins:
        nets.setdefault(name, []).append(("PIN", name))

    lines = [
        "VERSION 5.8 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        "DESIGN v3_selector_route_pilot ;",
        "UNITS DISTANCE MICRONS 1000 ;",
        "DIEAREA ( 0 0 ) ( 15740 34000 ) ;",
        "TRACKS X 230 DO 34 STEP 460 LAYER li1 ;",
        "TRACKS Y 170 DO 100 STEP 340 LAYER li1 ;",
        "TRACKS X 170 DO 46 STEP 340 LAYER met1 ;",
        "TRACKS Y 170 DO 100 STEP 340 LAYER met1 ;",
        "TRACKS X 230 DO 34 STEP 460 LAYER met2 ;",
        "TRACKS Y 230 DO 74 STEP 460 LAYER met2 ;",
        "TRACKS X 340 DO 23 STEP 680 LAYER met3 ;",
        "TRACKS Y 340 DO 50 STEP 680 LAYER met3 ;",
        "TRACKS X 460 DO 17 STEP 920 LAYER met4 ;",
        "TRACKS Y 460 DO 37 STEP 920 LAYER met4 ;",
        f"COMPONENTS {len(instances)} ;",
    ]
    for item in instances:
        x0, y0, _, _ = item["bbox"]
        x0 += row_order[item["name"]] * cell_gap_sites * CELL_SITE_WIDTH_UM
        if row_gap_um:
            occupied_height = template["row_count"] * template["row_height_um"] + (template["row_count"] - 1) * row_gap_um
            lower_margin = (template["bbox"][3] - occupied_height) / 2.0
            y0 = lower_margin + item["row"] * (template["row_height_um"] + row_gap_um)
        lines.append(
            f"- {item['name']} {MACROS[item['cell_role']]} + FIXED "
            f"( {q(x0)} {q(y0)} ) {ORIENTATIONS[item['orientation']]} ;"
        )
    lines.append("END COMPONENTS")
    lines.append(f"PINS {len(pins)} ;")
    for name, pin in pins.items():
        x, y = pin["fixed"]
        x0, y0, x1, y1 = pin["rect"]
        lines.extend(
            [
                f"- {name} + NET {name} + DIRECTION {pin['direction']} + USE SIGNAL",
                f"  + PORT + LAYER {pin['layer']} ( {q(x0)} {q(y0)} ) ( {q(x1)} {q(y1)} )",
                f"  + FIXED ( {q(x)} {q(y)} ) N ;",
            ]
        )
    lines.append("END PINS")
    lines.append(f"NETS {len(nets)} ;")
    for net, endpoints in sorted(nets.items()):
        lines.append(f"- {net}")
        for instance, pin in endpoints:
            lines.append(f"  ( {instance} {pin} )")
        lines[-1] += " ;"
    lines.extend(("END NETS", "END DESIGN", ""))
    report = {
        "schema_version": 1,
        "status": "generated",
        "scope": "one-channel signal-route pilot; power and analog-core routes excluded",
        "component_count": len(instances),
        "pin_count": len(pins),
        "net_count": len(nets),
        "row_gap_um": row_gap_um,
        "cell_gap_sites": cell_gap_sites,
        "cell_gap_um": cell_gap_sites * CELL_SITE_WIDTH_UM,
        "pins": pins,
        "net_endpoints": {net: [[instance, pin] for instance, pin in endpoints] for net, endpoints in sorted(nets.items())},
    }
    return "\n".join(lines), report


def build_route_tcl(tech_lef: Path, cell_lef: Path, workdir: Path, droute_end_iter: int) -> str:
    return "\n".join(
        (
            "set_thread_count 4",
            f"read_lef {tcl_path(tech_lef)}",
            f"read_lef {tcl_path(cell_lef)}",
            f"read_def {tcl_path(workdir / 'input.def')}",
            "set_routing_layers -signal met1-met4 -clock met1-met4",
            "set_global_routing_layer_adjustment met1 0.20",
            "set_global_routing_layer_adjustment met2-met4 0.10",
            f"global_route -guide_file {tcl_path(workdir / 'route.guide')} -congestion_iterations 100 -congestion_report_file {tcl_path(workdir / 'congestion.rpt')} -verbose",
            f"detailed_route -output_drc {tcl_path(workdir / 'detailed_route_drc.rpt')} -output_guide_coverage {tcl_path(workdir / 'guide_coverage.csv')} -droute_end_iter {droute_end_iter} -clean_patches -verbose 1",
            f"report_wire_length -net * -global_route -detailed_route -verbose -file {tcl_path(workdir / 'wire_length.csv')}",
            f"write_def {tcl_path(workdir / 'routed.def')}",
            f"write_db {tcl_path(workdir / 'routed.odb')}",
            "exit",
            "",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--technology-lef", type=Path, required=True)
    parser.add_argument("--cell-lef", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, default=ROOT / "build" / "v3" / "selector_route_pilot")
    parser.add_argument("--row-gap", type=float, default=0.0)
    parser.add_argument("--cell-gap-sites", type=int, default=0)
    parser.add_argument("--droute-end-iter", type=int, default=64)
    args = parser.parse_args()
    placement = json.loads(PLACEMENT.read_text(encoding="utf-8"))
    if args.row_gap < 0 or args.row_gap > 1.02:
        raise SystemExit("--row-gap must be between 0 and 1.02 um")
    gap_tracks = args.row_gap / ROUTING_PITCH_UM
    if not math.isclose(gap_tracks, round(gap_tracks), abs_tol=1e-9):
        raise SystemExit("--row-gap must be an integer multiple of the 0.34 um routing pitch")
    if args.droute_end_iter < 1 or args.droute_end_iter > 128:
        raise SystemExit("--droute-end-iter must be between 1 and 128")
    if args.cell_gap_sites < 0 or args.cell_gap_sites > 3:
        raise SystemExit("--cell-gap-sites must be between 0 and 3")
    def_text, report = build_def(placement, args.row_gap, args.cell_gap_sites)
    args.workdir.mkdir(parents=True, exist_ok=True)
    (args.workdir / "input.def").write_text(def_text, encoding="utf-8")
    (args.workdir / "route.tcl").write_text(
        build_route_tcl(args.technology_lef, args.cell_lef, args.workdir, args.droute_end_iter), encoding="utf-8"
    )
    report["droute_end_iter"] = args.droute_end_iter
    report["row_gap_tracks"] = round(gap_tracks)
    (args.workdir / "input_summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "component_count", "pin_count", "net_count")}, indent=2))


if __name__ == "__main__":
    main()
