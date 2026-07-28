#!/usr/bin/env python3
"""Build the authoritative placement/route contract for one V3 vector unit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "v3" / "layout" / "channel_pcell_catalog.json"
DEFAULT_OUTPUT = ROOT / "v3" / "layout" / "vector_unit_placement.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def transform(point: list[float], center: list[float], orientation: str) -> list[float]:
    x, y = point
    if orientation == "MY":
        x = -x
    elif orientation != "R0":
        raise ValueError(f"unsupported unit-device orientation {orientation}")
    return [round(center[0] + x, 6), round(center[1] + y, 6)]


def placed(
    name: str,
    cell_name: str,
    center: list[float],
    orientation: str,
    nets: dict[str, str],
    cells: dict[str, Any],
) -> dict[str, Any]:
    cell = cells[cell_name]
    x0, y0, x1, y1 = cell["bbox_um"]
    if orientation == "MY":
        x0, x1 = -x1, -x0
    return {
        "name": name,
        "cell": cell_name,
        "generated_cell": cell["generated_cell"],
        "center": center,
        "orientation": orientation,
        "bbox": [
            round(center[0] + x0, 6), round(center[1] + y0, 6),
            round(center[0] + x1, 6), round(center[1] + y1, 6),
        ],
        "terminals": {
            terminal: [transform(item["point_um"], center, orientation) for item in values]
            for terminal, values in cell["ports"].items()
        },
        "nets": {**nets, "B": "VGND"},
    }


def segment(start: list[float], stop: list[float], layer: str, width: float) -> dict[str, Any]:
    if start[0] != stop[0] and start[1] != stop[1]:
        raise ValueError(f"non-Manhattan unit segment: {start} -> {stop}")
    return {"from": start, "to": stop, "layer": layer, "width_um": width}


def terminal(component: dict[str, Any], name: str) -> list[float]:
    points = component["terminals"][name]
    if len(points) != 1:
        raise ValueError(f"{component['name']}.{name} is not a single terminal")
    return points[0]


def build() -> dict[str, Any]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if catalog["status"] != "pass":
        raise RuntimeError("channel PCell terminal catalogue is not closed")
    cells = catalog["cells"]
    devices = [
        placed("XTAIL", "XTAIL_U", [1.43, 2.975], "R0", {"D": "tail", "S": "VGND", "G": "vbias"}, cells),
        placed("XGM_P", "XGM_U", [0.59, 7.31], "R0", {"D": "gm_p", "S": "tail", "G": "sig"}, cells),
        placed("XGM_N", "XGM_U", [2.27, 7.31], "MY", {"D": "gm_n", "S": "tail", "G": "ref"}, cells),
        # Output-aligned rows avoid crossing the high-current outp/outn routes.
        placed("XSW_PP", "XSW_U", [0.815, 11.465], "MY", {"D": "outp", "S": "gm_p", "G": "lop"}, cells),
        placed("XSW_NN", "XSW_U", [2.045, 11.465], "R0", {"D": "outp", "S": "gm_n", "G": "lon"}, cells),
        placed("XSW_PN", "XSW_U", [0.815, 9.435], "MY", {"D": "outn", "S": "gm_p", "G": "lon"}, cells),
        placed("XSW_NP", "XSW_U", [2.045, 9.435], "R0", {"D": "outn", "S": "gm_n", "G": "lop"}, cells),
    ]
    by_name = {item["name"]: item for item in devices}
    tail_d = terminal(by_name["XTAIL"], "D")
    tail_s = terminal(by_name["XTAIL"], "S")
    gm_p_d = terminal(by_name["XGM_P"], "D")
    gm_p_s = terminal(by_name["XGM_P"], "S")
    gm_n_d = terminal(by_name["XGM_N"], "D")
    gm_n_s = terminal(by_name["XGM_N"], "S")
    routes = {
        "tail": [
            segment(tail_d, [tail_d[0], gm_p_s[1]], "metal2", 0.32),
            segment([tail_d[0], gm_p_s[1]], gm_n_s, "metal2", 0.32),
        ],
        "gm_p": [
            segment(gm_p_d, [0.00, gm_p_d[1]], "metal2", 0.32),
            segment([0.00, gm_p_d[1]], [0.00, terminal(by_name["XSW_PN"], "S")[1]], "metal2", 0.32),
            segment([0.00, terminal(by_name["XSW_PN"], "S")[1]], [0.00, terminal(by_name["XSW_PP"], "S")[1]], "metal2", 0.32),
            segment([0.00, terminal(by_name["XSW_PN"], "S")[1]], terminal(by_name["XSW_PN"], "S"), "metal2", 0.32),
            segment([0.00, terminal(by_name["XSW_PP"], "S")[1]], terminal(by_name["XSW_PP"], "S"), "metal2", 0.32),
        ],
        "gm_n": [
            segment(gm_n_d, [2.86, gm_n_d[1]], "metal2", 0.32),
            segment([2.86, gm_n_d[1]], [2.86, terminal(by_name["XSW_NP"], "S")[1]], "metal2", 0.32),
            segment([2.86, terminal(by_name["XSW_NP"], "S")[1]], [2.86, terminal(by_name["XSW_NN"], "S")[1]], "metal2", 0.32),
            segment([2.86, terminal(by_name["XSW_NP"], "S")[1]], terminal(by_name["XSW_NP"], "S"), "metal2", 0.32),
            segment([2.86, terminal(by_name["XSW_NN"], "S")[1]], terminal(by_name["XSW_NN"], "S"), "metal2", 0.32),
        ],
        "outp": [
            segment([1.08, terminal(by_name["XSW_PP"], "D")[1]], terminal(by_name["XSW_NN"], "D"), "metal2", 0.40),
            segment([1.08, terminal(by_name["XSW_PP"], "D")[1]], [1.08, 12.23], "metal3", 0.40),
        ],
        "outn": [
            segment(terminal(by_name["XSW_PN"], "D"), [1.78, terminal(by_name["XSW_PN"], "D")[1]], "metal2", 0.40),
            segment([1.78, terminal(by_name["XSW_PN"], "D")[1]], [1.78, 12.23], "metal3", 0.40),
        ],
        "sig": [
            segment([0.15, 0.0], [0.15, terminal(by_name["XGM_P"], "G")[1]], "metal4", 0.40),
            segment([0.15, terminal(by_name["XGM_P"], "G")[1]], terminal(by_name["XGM_P"], "G"), "metal4", 0.40),
        ],
        "ref": [
            segment([2.71, 0.0], [2.71, terminal(by_name["XGM_N"], "G")[1]], "metal4", 0.40),
            segment([2.71, terminal(by_name["XGM_N"], "G")[1]], terminal(by_name["XGM_N"], "G"), "metal4", 0.40),
        ],
        "vbias": [segment([1.43, 0.0], terminal(by_name["XTAIL"], "G"), "metal4", 0.32)],
        "VGND": [
            segment(tail_s, [2.20, tail_s[1]], "metal2", 0.40),
            segment([2.20, 0.0], [2.20, tail_s[1]], "metal3", 0.40),
        ],
        # Promote outside the high-current M2 drain trunks.  Keeping these
        # landings inside the original 2.86 um device envelope shorts the
        # Via-1/M2 landing into gm_p/gm_n even when the upper metals clear.
        "lop_left": [segment(terminal(by_name["XSW_PP"], "G"), [-0.65, terminal(by_name["XSW_PP"], "G")[1]], "metal1", 0.23)],
        "lop_right": [segment(terminal(by_name["XSW_NP"], "G"), [3.51, terminal(by_name["XSW_NP"], "G")[1]], "metal1", 0.23)],
        "lon_right": [segment(terminal(by_name["XSW_NN"], "G"), [3.51, terminal(by_name["XSW_NN"], "G")[1]], "metal1", 0.23)],
        "lon_left": [segment(terminal(by_name["XSW_PN"], "G"), [-0.65, terminal(by_name["XSW_PN"], "G")[1]], "metal1", 0.23)],
    }
    return {
        "schema_version": 1,
        "status": "placement and route contract; exact Magic pilot pending",
        "units": "um",
        # Includes the M3 landing extents of the four isolated LO breakouts.
        "tile_bbox": [-0.85, 0.0, 3.71, 12.365],
        "devices": devices,
        "routes": routes,
        "boundary_ports": {
            "sig": {"point": [0.15, 0.0], "layer": "metal4"},
            "vbias": {"point": [1.43, 0.0], "layer": "metal4"},
            "ref": {"point": [2.71, 0.0], "layer": "metal4"},
            "VGND": {"point": [2.20, 0.0], "layer": "metal3"},
            "lop_left": {"point": [-0.65, terminal(by_name["XSW_PP"], "G")[1]], "layer": "metal3"},
            "lop_right": {"point": [3.51, terminal(by_name["XSW_NP"], "G")[1]], "layer": "metal3"},
            "outp": {"point": [1.08, 12.23], "layer": "metal3"},
            "outn": {"point": [1.78, 12.23], "layer": "metal3"},
            "lon_right": {"point": [3.51, terminal(by_name["XSW_NN"], "G")[1]], "layer": "metal3"},
            "lon_left": {"point": [-0.65, terminal(by_name["XSW_PN"], "G")[1]], "layer": "metal3"},
        },
        "layout_contract": {
            "gm_sources_face_inward": True,
            "switch_sources_face_outward_toward_gm_drain_trunks": True,
            "switch_rows_grouped_by_output_to_avoid_current_route_crossing": True,
            "LO_gate_breakouts_end_on_separate_metal3_landings": True,
            "LO_pair_merging_deferred_to_balanced_group_spines": True,
            "all_device_contacts_have_equal_legal_via1_landings": True,
            "floating_stubs_allowed": False,
            "orphan_vias_allowed": False,
            "route_meanders_allowed": False,
            "body_connection": "one shared channel substrate guard, added at the full-channel gate",
        },
        "switch_gate_promotions": [
            {"device": "XSW_PP", "terminal": "G", "net": "lop", "port": "lop_left", "point": [-0.65, terminal(by_name["XSW_PP"], "G")[1]]},
            {"device": "XSW_NP", "terminal": "G", "net": "lop", "port": "lop_right", "point": [3.51, terminal(by_name["XSW_NP"], "G")[1]]},
            {"device": "XSW_NN", "terminal": "G", "net": "lon", "port": "lon_right", "point": [3.51, terminal(by_name["XSW_NN"], "G")[1]]},
            {"device": "XSW_PN", "terminal": "G", "net": "lon", "port": "lon_left", "point": [-0.65, terminal(by_name["XSW_PN"], "G")[1]]},
        ],
        "provenance": {
            "generator": "v3/tools/build_vector_unit_placement.py",
            "generator_sha256": sha256(Path(__file__)),
            "pcell_catalog": "v3/layout/channel_pcell_catalog.json",
            "pcell_catalog_sha256": sha256(CATALOG),
        },
    }


def main() -> None:
    report = build()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
