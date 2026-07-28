#!/usr/bin/env python3
"""Generate the bounded OpenROAD pilot for the differential output collector.

The analog channel is treated as a fixed hard macro.  Its thirty drain taps
are the only internal access points exposed to the router; every other shape
in the exact GDS-derived LEF is an obstruction.  The two output roots sit in
the quiet top corridor so the eventual four-channel combiner does not need to
cross the phase-tree bundle again.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DBU = 1000
TOP = "v3_channel_output_route_pilot"
MACRO = "v3_channel_input_bias_pilot_output_macro"
MACRO_SIZE_UM = (19.30, 95.88)
TOP_CORRIDOR_UM = 3.40
ROOTS_UM = {
    # Coordinates are relative to the lower-left of the GDS-derived macro.
    "channel_outp": (6.74, 98.26),
    "channel_outn": (8.74, 98.26),
}


def q(value: float) -> int:
    return round(value * DBU)


def tcl_path(path: Path) -> str:
    value = str(path)
    if "{" in value or "}" in value:
        raise ValueError(f"invalid Tcl path: {value}")
    return "{" + value + "}"


def build_def() -> tuple[str, dict[str, object]]:
    die_width = MACRO_SIZE_UM[0]
    die_height = MACRO_SIZE_UM[1] + TOP_CORRIDOR_UM
    outp = [("CHANNEL", f"u{index:02d}_outp") for index in range(15)]
    outn = [("CHANNEL", f"u{index:02d}_outn") for index in range(15)]
    nets = {"channel_outp": outp, "channel_outn": outn}

    lines = [
        "VERSION 5.8 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        f"DESIGN {TOP} ;",
        "UNITS DISTANCE MICRONS 1000 ;",
        f"DIEAREA ( 0 0 ) ( {q(die_width)} {q(die_height)} ) ;",
        "TRACKS X 230 DO 42 STEP 460 LAYER li1 ;",
        "TRACKS Y 170 DO 291 STEP 340 LAYER li1 ;",
        "TRACKS X 170 DO 56 STEP 340 LAYER met1 ;",
        "TRACKS Y 170 DO 291 STEP 340 LAYER met1 ;",
        "TRACKS X 230 DO 42 STEP 460 LAYER met2 ;",
        "TRACKS Y 230 DO 216 STEP 460 LAYER met2 ;",
        "TRACKS X 340 DO 28 STEP 680 LAYER met3 ;",
        "TRACKS Y 340 DO 146 STEP 680 LAYER met3 ;",
        "TRACKS X 460 DO 21 STEP 920 LAYER met4 ;",
        "TRACKS Y 460 DO 108 STEP 920 LAYER met4 ;",
        "COMPONENTS 1 ;",
        f"- CHANNEL {MACRO} + FIXED ( 0 0 ) N ;",
        "END COMPONENTS",
        "PINS 2 ;",
    ]
    for name, (x, y) in ROOTS_UM.items():
        lines.extend(
            [
                f"- {name} + NET {name} + DIRECTION OUTPUT + USE SIGNAL",
                "  + PORT + LAYER met3 ( -150 0 ) ( 150 840 )",
                f"  + FIXED ( {q(x)} {q(y)} ) N ;",
            ]
        )
    lines.append("END PINS")
    lines.append("NETS 2 ;")
    for net, endpoints in nets.items():
        lines.append(f"- {net}")
        for instance, pin in endpoints:
            lines.append(f"  ( {instance} {pin} )")
        lines.append(f"  ( PIN {net} ) ;")
    lines.extend(("END NETS", "END DESIGN", ""))
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "generated",
        "scope": "one exact analog channel; 15 positive and 15 negative drains",
        "macro": MACRO,
        "macro_size_um": list(MACRO_SIZE_UM),
        "top_corridor_um": TOP_CORRIDOR_UM,
        "die_bbox_um": [0.0, 0.0, die_width, die_height],
        "output_roots_um": {key: list(value) for key, value in ROOTS_UM.items()},
        "net_endpoints": {
            net: [[instance, pin] for instance, pin in endpoints] + [["PIN", net]]
            for net, endpoints in nets.items()
        },
        "balance_contract": {
            "same_layer_stack": True,
            "same_nominal_width": True,
            "maximum_post_extraction_differential_leaf_resistance_delta_percent": 2.0,
            "maximum_post_extraction_p_n_total_capacitance_delta_percent": 2.0,
        },
    }
    return "\n".join(lines), report


def build_route_tcl(tech_lef: Path, macro_lef: Path, workdir: Path) -> str:
    return "\n".join(
        (
            "set_thread_count 8",
            f"read_lef {tcl_path(tech_lef)}",
            f"read_lef {tcl_path(macro_lef)}",
            f"read_def {tcl_path(workdir / 'input.def')}",
            "set_routing_layers -signal met2-met4 -clock met2-met4",
            "set_global_routing_layer_adjustment met2-met4 0.05",
            f"global_route -guide_file {tcl_path(workdir / 'route.guide')} -congestion_iterations 150 -congestion_report_file {tcl_path(workdir / 'congestion.rpt')} -verbose",
            f"detailed_route -output_drc {tcl_path(workdir / 'detailed_route_drc.rpt')} -output_guide_coverage {tcl_path(workdir / 'guide_coverage.csv')} -droute_end_iter 96 -clean_patches -verbose 1",
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
    parser.add_argument("--macro-lef", type=Path, required=True)
    parser.add_argument(
        "--workdir", type=Path, default=ROOT / "build" / "v3" / "channel_output_route"
    )
    args = parser.parse_args()
    def_text, report = build_def()
    args.workdir.mkdir(parents=True, exist_ok=True)
    (args.workdir / "input.def").write_text(def_text, encoding="utf-8")
    (args.workdir / "route.tcl").write_text(
        build_route_tcl(args.technology_lef, args.macro_lef, args.workdir), encoding="utf-8"
    )
    (args.workdir / "input_summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "generated", "nets": 2, "drain_taps": 30}, indent=2))


if __name__ == "__main__":
    main()
