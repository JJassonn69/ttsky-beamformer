#!/usr/bin/env python3
"""Build the measured V3 shared-support PCell dimension catalogue."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAG_DIR = ROOT / "build" / "v3" / "shared_support_pcell_measurements" / "remote_mag"
DEFAULT_OUTPUT = ROOT / "v3" / "layout" / "shared_support_pcell_catalog.json"
PARENT = "v3_shared_support_pcell_measurement.mag"
UNITS_PER_UM = 200.0
USE_RE = re.compile(
    r"^use\s+(?P<cell>\S+)\s+(?P<instance>\S+)\n"
    r"(?:.*\n)*?transform\s+1\s+0\s+(?P<tx>-?\d+)\s+0\s+1\s+(?P<ty>-?\d+)\n"
    r"box\s+(?P<x0>-?\d+)\s+(?P<y0>-?\d+)\s+(?P<x1>-?\d+)\s+(?P<y1>-?\d+)",
    re.MULTILINE,
)
LABEL_RE = re.compile(
    r"^rlabel\s+(?P<layer>\S+)\s+"
    r"(?P<x0>-?\d+)\s+(?P<y0>-?\d+)\s+(?P<x1>-?\d+)\s+(?P<y1>-?\d+)\s+"
    r"\d+\s+(?P<label>\S+)$",
    re.MULTILINE,
)
PARAMETERS = {
    "XVCM_UNIT_SCALE_1": {"role": "vcm_divider_unit", "model": "res_xhigh_po_1p41", "width_um": 1.41, "length_um": 23.5, "guard": 1},
    "XVCM_UNIT_SCALE_0P5": {"role": "vcm_divider_unit", "model": "res_xhigh_po_1p41", "width_um": 1.41, "length_um": 11.75, "guard": 1},
    "XVCM_UNIT_SCALE_0P25": {"role": "vcm_divider_unit", "model": "res_xhigh_po_1p41", "width_um": 1.41, "length_um": 5.875, "guard": 1},
    "XVCM_HIGH_UNIT_L5P875": {"role": "vcm_divider_unit", "model": "res_high_po_1p41", "width_um": 1.41, "length_um": 5.875, "guard": 1},
    "XVCM_HIGH_UNIT_L11P75": {"role": "vcm_divider_unit", "model": "res_high_po_1p41", "width_um": 1.41, "length_um": 11.75, "guard": 1},
    "XVCM_HIGH_UNIT_L23P5": {"role": "vcm_divider_unit", "model": "res_high_po_1p41", "width_um": 1.41, "length_um": 23.5, "guard": 1},
    "XINPUT_BIAS": {"role": "input_bias", "model": "res_xhigh_po_1p41", "width_um": 1.41, "length_um": 70.5, "guard": 1},
    "XOUTPUT_LOAD": {"role": "output_load", "model": "res_high_po_1p41", "width_um": 1.41, "length_um": 11.6117, "guard": 1},
    "XTAIL_BIAS_RESISTOR": {"role": "tail_bias", "model": "res_high_po_1p41", "width_um": 1.41, "length_um": 44.9768, "guard": 1},
    "XDECAP_MIM": {"role": "decap", "model": "cap_mim_m3_1", "width_um": 22.0, "length_um": 22.0},
    "XVCM_VAR": {"role": "optional_vcm_varactor", "model": "cap_var_lvt", "width_um": 17.68, "length_um": 17.68, "guard": 1},
}
MEASUREMENT_ANCHORS_UM = {
    "XVCM_UNIT_SCALE_1": [0.0, 0.0],
    "XVCM_UNIT_SCALE_0P5": [20.0, 0.0],
    "XVCM_UNIT_SCALE_0P25": [40.0, 0.0],
    "XINPUT_BIAS": [70.0, 0.0],
    "XOUTPUT_LOAD": [100.0, 0.0],
    "XTAIL_BIAS_RESISTOR": [130.0, 0.0],
    "XDECAP_MIM": [170.0, 0.0],
    "XVCM_VAR": [210.0, 0.0],
    "XVCM_HIGH_UNIT_L5P875": [250.0, 0.0],
    "XVCM_HIGH_UNIT_L11P75": [270.0, 0.0],
    "XVCM_HIGH_UNIT_L23P5": [290.0, 0.0],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measured_ports(path: Path) -> dict[str, list[dict[str, Any]]]:
    ports: dict[str, list[dict[str, Any]]] = {}
    for match in LABEL_RE.finditer(path.read_text(encoding="utf-8")):
        x0, y0, x1, y1 = (
            int(match.group(key)) / UNITS_PER_UM
            for key in ("x0", "y0", "x1", "y1")
        )
        ports.setdefault(match.group("label"), []).append({
            "layer": match.group("layer"),
            "point_um": [(x0 + x1) / 2.0, (y0 + y1) / 2.0],
        })
    if not ports:
        raise RuntimeError(f"no measured ports in {path}")
    return ports


def build(mag_dir: Path) -> dict[str, Any]:
    parent = mag_dir / PARENT
    matches = {match.group("instance"): match.groupdict() for match in USE_RE.finditer(parent.read_text(encoding="utf-8"))}
    if set(matches) != set(PARAMETERS):
        raise RuntimeError(f"shared-support PCell catalogue changed: {sorted(matches)}")
    cells = {}
    for instance, parameters in PARAMETERS.items():
        match = matches[instance]
        bbox = [int(match[key]) / UNITS_PER_UM for key in ("x0", "y0", "x1", "y1")]
        child = mag_dir / f"{match['cell']}.mag"
        if not child.is_file():
            raise RuntimeError(f"missing generated child {child}")
        cells[instance] = {
            "generated_cell": match["cell"],
            "parameters": parameters,
            "bbox_um": bbox,
            "width_um": bbox[2] - bbox[0],
            "height_um": bbox[3] - bbox[1],
            "area_um2": (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]),
            "gencell_anchor_offset_um": [
                int(match["tx"]) / UNITS_PER_UM - MEASUREMENT_ANCHORS_UM[instance][0],
                int(match["ty"]) / UNITS_PER_UM - MEASUREMENT_ANCHORS_UM[instance][1],
            ],
            "ports": measured_ports(child),
            "mag_sha256": sha256(child),
        }
    gates = {
        "all_eleven_pcells_measured": len(cells) == 11,
        "smallest_vcm_unit_is_legal_and_nonzero": cells["XVCM_UNIT_SCALE_0P25"]["width_um"] > 0 and cells["XVCM_UNIT_SCALE_0P25"]["height_um"] > 0,
        "four_guarded_input_resistors_fit_pitch_gaps_by_width": cells["XINPUT_BIAS"]["width_um"] <= 3.58,
        "output_load_matches_v2_proven_geometry": (
            cells["XOUTPUT_LOAD"]["width_um"] == 3.07
            and cells["XOUTPUT_LOAD"]["height_um"] == 17.43
        ),
        "all_required_terminals_measured": (
            all(
                {"B", "R1", "R2"} <= set(cells[name]["ports"])
                for name in (
                    "XVCM_UNIT_SCALE_1", "XVCM_UNIT_SCALE_0P5",
                    "XVCM_UNIT_SCALE_0P25", "XVCM_HIGH_UNIT_L5P875",
                    "XVCM_HIGH_UNIT_L11P75", "XVCM_HIGH_UNIT_L23P5",
                    "XINPUT_BIAS", "XOUTPUT_LOAD",
                    "XTAIL_BIAS_RESISTOR",
                )
            )
            and {"C1", "C2"} <= set(cells["XDECAP_MIM"]["ports"])
            and {"B", "D", "G", "S"} <= set(cells["XVCM_VAR"]["ports"])
        ),
    }
    return {
        "schema_version": 1,
        "status": "pass" if all(gates.values()) else "fail",
        "scope": "measured PCell dimensions only; terminal access, placement, routing, DRC, extraction, and GDS remain separate gates",
        "provenance": {
            "magic_version": "8.3.676",
            "sky130_pdk_commit": "0536d02d875c8f67dd7cca3902ac457e62f20005",
            "generator": "v3/layout/measure_shared_support_pcells.tcl",
            "generator_sha256": sha256(ROOT / "v3" / "layout" / "measure_shared_support_pcells.tcl"),
            "parent_mag_sha256": sha256(parent),
            "coordinate_conversion": "Magic internal coordinates divided by 200 give micrometres",
        },
        "cells": cells,
        "gates": gates,
        "next_gate": "select the VCM divider scale electrically, then use only its measured PCell in the routed support pilot",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mag-dir", type=Path, default=DEFAULT_MAG_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build(args.mag_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "gates": report["gates"]}, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
