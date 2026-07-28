#!/usr/bin/env python3
"""Build the measured compact input-bias PCell catalogue."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MAG_DIR = ROOT / "build" / "v3" / "input_bias_pcell_study_r2" / "remote_mag"
PARENT = MAG_DIR / "v3_input_bias_pcell_study.mag"
DEFAULT_OUTPUT = ROOT / "v3" / "layout" / "input_bias_pcell_catalog.json"
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
VALUE_RE = re.compile(r"\bval\s+(?P<value>[\d.]+)k\b")
PARAMETERS = {
    "XIN_0P35_L17P5_G": {"width_um": 0.35, "length_um": 17.5, "guard": 1},
    "XIN_0P35_L17P5_U": {"width_um": 0.35, "length_um": 17.5, "guard": 0},
    "XIN_0P35_L5P833_G": {"width_um": 0.35, "length_um": 5.833333333, "guard": 1},
    "XIN_0P35_L5P833_U": {"width_um": 0.35, "length_um": 5.833333333, "guard": 0},
    "XIN_0P35_L17P36_G": {"width_um": 0.35, "length_um": 17.36, "guard": 1},
}
ANCHORS = {
    "XIN_0P35_L17P5_G": [0.0, 0.0],
    "XIN_0P35_L17P5_U": [10.0, 0.0],
    "XIN_0P35_L5P833_G": [20.0, 0.0],
    "XIN_0P35_L5P833_U": [30.0, 0.0],
    "XIN_0P35_L17P36_G": [40.0, 0.0],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ports(path: Path) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    text = path.read_text(encoding="utf-8")
    for match in LABEL_RE.finditer(text):
        values = [int(match.group(key)) / UNITS_PER_UM for key in ("x0", "y0", "x1", "y1")]
        output.setdefault(match.group("label"), []).append({
            "layer": match.group("layer"),
            "point_um": [(values[0] + values[2]) / 2.0, (values[1] + values[3]) / 2.0],
        })
    return output


def build() -> dict[str, Any]:
    matches = {match.group("instance"): match.groupdict() for match in USE_RE.finditer(PARENT.read_text(encoding="utf-8"))}
    if set(matches) != set(PARAMETERS):
        raise RuntimeError(f"compact input-bias PCell set changed: {sorted(matches)}")
    cells = {}
    for name, parameters in PARAMETERS.items():
        match = matches[name]
        child = MAG_DIR / f"{match['cell']}.mag"
        bbox = [int(match[key]) / UNITS_PER_UM for key in ("x0", "y0", "x1", "y1")]
        value_match = VALUE_RE.search(child.read_text(encoding="utf-8"))
        if not value_match:
            raise RuntimeError(f"missing nominal PCell value in {child}")
        cells[name] = {
            "generated_cell": match["cell"],
            "parameters": {**parameters, "model": "res_xhigh_po_0p35", "role": "input_bias"},
            "bbox_um": bbox,
            "width_um": bbox[2] - bbox[0],
            "height_um": bbox[3] - bbox[1],
            "nominal_pcell_resistance_ohm": float(value_match.group("value")) * 1000.0,
            "gencell_anchor_offset_um": [
                int(match["tx"]) / UNITS_PER_UM - ANCHORS[name][0],
                int(match["ty"]) / UNITS_PER_UM - ANCHORS[name][1],
            ],
            "ports": ports(child),
            "mag_sha256": sha256(child),
        }
    selected = cells["XIN_0P35_L17P36_G"]
    old_resistance = 100266.0
    gates = {
        "all_five_candidates_measured": len(cells) == 5,
        "all_guarded_candidates_have_body_terminal": all(
            "B" in cells[name]["ports"] for name in cells if name.endswith("_G")
        ),
        "selected_candidate_has_all_terminals": {"R1", "R2", "B"} <= set(selected["ports"]),
        "selected_candidate_fits_3p58um_pitch_gap": selected["width_um"] <= 3.58,
        "selected_candidate_is_at_least_3x_shorter": selected["height_um"] <= 76.32 / 3.0,
        "selected_nominal_resistance_matches_old_within_0p1pct": abs(selected["nominal_pcell_resistance_ohm"] - old_resistance) / old_resistance <= 0.001,
    }
    return {
        "schema_version": 1,
        "status": "pass" if all(gates.values()) else "fail",
        "scope": "measured compact input-bias PCell dimensions, terminals, and generator-reported nominal resistance",
        "selected_candidate": "XIN_0P35_L17P36_G",
        "old_reference": {
            "model": "res_xhigh_po_1p41",
            "width_um": 1.41,
            "length_um": 70.5,
            "bbox_um": [3.07, 76.32],
            "nominal_pcell_resistance_ohm": old_resistance,
        },
        "cells": cells,
        "gates": gates,
        "provenance": {
            "magic_version": "8.3.676",
            "sky130_pdk_commit": "0536d02d875c8f67dd7cca3902ac457e62f20005",
            "generator": "v3/layout/measure_input_bias_pcells.tcl",
            "generator_sha256": sha256(ROOT / "v3" / "layout" / "measure_input_bias_pcells.tcl"),
            "parent_mag_sha256": sha256(PARENT),
        },
        "next_gate": "place the selected guarded PCell under an M3 ground shield in the channel side corridor and prove exact DRC/topology",
    }


def main() -> None:
    report = build()
    DEFAULT_OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "gates": report["gates"], "selected": report["cells"][report["selected_candidate"]]}, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
