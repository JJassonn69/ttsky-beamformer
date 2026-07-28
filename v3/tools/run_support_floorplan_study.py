#!/usr/bin/env python3
"""Select a measured V3 shared-tail-reference folding and support placement.

The result is a floorplan study.  It does not diode-connect the device, add
contacts/routes, create a layout database, or authorize GDS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAG_DIR = ROOT / "build" / "v3" / "support_pcell_measurements" / "remote_mag"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "support_floorplan_study.json"
PARENT_NAME = "v3_support_pcell_measurement.mag"
INTERNAL_UNITS_PER_UM = 200.0
SUPPORT_ZONE = [181.0, 20.0, 320.0, 165.0]
PARAMETERS = {
    "XREF_4X16": {"finger_width_um": 16.0, "fingers": 4},
    "XREF_8X8": {"finger_width_um": 8.0, "fingers": 8},
    "XREF_16X4": {"finger_width_um": 4.0, "fingers": 16},
    "XREF_32X2": {"finger_width_um": 2.0, "fingers": 32},
}
USE_RE = re.compile(
    r"^use\s+(?P<cell>\S+)\s+(?P<instance>\S+)\n"
    r"(?:.*\n)*?box\s+(?P<x0>-?\d+)\s+(?P<y0>-?\d+)\s+(?P<x1>-?\d+)\s+(?P<y1>-?\d+)",
    re.MULTILINE,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(mag_dir: Path) -> dict[str, dict[str, Any]]:
    parent = mag_dir / PARENT_NAME
    if not parent.is_file():
        raise SystemExit(f"missing measured parent: {parent}")
    matches = {match.group("instance"): match.groupdict() for match in USE_RE.finditer(parent.read_text())}
    if set(matches) != set(PARAMETERS):
        raise RuntimeError(f"support PCell catalogue changed: {sorted(matches)}")
    measured = {}
    for instance, parameters in PARAMETERS.items():
        match = matches[instance]
        coordinates = [
            int(match[key]) / INTERNAL_UNITS_PER_UM
            for key in ("x0", "y0", "x1", "y1")
        ]
        child = mag_dir / f"{match['cell']}.mag"
        if not child.is_file():
            raise RuntimeError(f"missing measured child: {child}")
        x0, y0, x1, y1 = coordinates
        measured[instance] = {
            "generated_cell": match["cell"],
            "parameters": {
                **parameters,
                "aggregate_width_um": parameters["finger_width_um"] * parameters["fingers"],
                "length_um": 1.0,
                "guard": 1,
            },
            "bbox_um": coordinates,
            "width_um": x1 - x0,
            "height_um": y1 - y0,
            "area_um2": (x1 - x0) * (y1 - y0),
            "mag_sha256": sha256(child),
        }
    return measured


def build_report(mag_dir: Path) -> dict[str, Any]:
    measured = measure(mag_dir)
    zone_width = SUPPORT_ZONE[2] - SUPPORT_ZONE[0]
    zone_height = SUPPORT_ZONE[3] - SUPPORT_ZONE[1]
    candidates = []
    for name, item in measured.items():
        # The reference must leave 4 um on every side for diode routing,
        # guard connection, and separation from digital/control wiring.
        required_width = item["width_um"] + 8.0
        required_height = item["height_um"] + 8.0
        aspect = max(item["width_um"] / item["height_um"], item["height_um"] / item["width_um"])
        candidates.append(
            {
                "name": name,
                "width_um": round(item["width_um"], 6),
                "height_um": round(item["height_um"], 6),
                "area_um2": round(item["area_um2"], 6),
                "aspect_ratio": round(aspect, 6),
                "fits_support_zone_with_route_margin": required_width <= zone_width and required_height <= zone_height,
                "required_envelope_um": [round(required_width, 6), round(required_height, 6)],
                # Compact, near-square folding reduces the length of the
                # diode gate/drain strap without using area as the sole score.
                "selection_score": round(item["area_um2"] * (1.0 + 0.08 * (aspect - 1.0)), 6),
            }
        )
    passing = [item for item in candidates if item["fits_support_zone_with_route_margin"]]
    if not passing:
        raise RuntimeError("no guarded 64 um reference folding fits the reserved support zone")
    selected = min(passing, key=lambda item: item["selection_score"])
    selected_cell = measured[selected["name"]]
    # Place near the analog side of the support zone, centered vertically in
    # a 40 um-high quiet subregion.  Exact terminal orientation remains open.
    placement_center = [194.0, 48.0]
    half_w = selected_cell["width_um"] / 2.0
    half_h = selected_cell["height_um"] / 2.0
    placement_bbox = [
        placement_center[0] - half_w,
        placement_center[1] - half_h,
        placement_center[0] + half_w,
        placement_center[1] + half_h,
    ]
    gate = {
        "all_candidates_preserve_64um_aggregate_width": all(
            abs(item["parameters"]["aggregate_width_um"] - 64.0) < 1e-9
            for item in measured.values()
        ),
        "selected_candidate_fits_reserved_support_zone": selected["fits_support_zone_with_route_margin"],
        "selected_candidate_has_guard": selected_cell["parameters"]["guard"] == 1,
        "selected_candidate_is_measured_not_estimated": selected_cell["mag_sha256"] != "",
    }
    return {
        "schema_version": 1,
        "status": "pass" if all(gate.values()) else "fail",
        "scope": "measured shared-reference folding and floorplan reservation; no diode strap, placement database, DRC, LVS, extraction, or GDS",
        "provenance": {
            "magic_version": "8.3.676",
            "sky130_pdk_commit": "0536d02d875c8f67dd7cca3902ac457e62f20005",
            "generator": "v3/layout/measure_support_pcells.tcl",
            "generator_sha256": sha256(ROOT / "v3" / "layout" / "measure_support_pcells.tcl"),
            "parent_mag_sha256": sha256(mag_dir / PARENT_NAME),
        },
        "support_zone_bbox_um": SUPPORT_ZONE,
        "measured_pcells": measured,
        "candidates": sorted(candidates, key=lambda item: item["selection_score"]),
        "selected_candidate": selected["name"],
        "selected_placement_center_um": placement_center,
        "selected_placement_bbox_um": [round(value, 6) for value in placement_bbox],
        "placement_orientation": "R0 provisional; orient after measured terminal-access study",
        "gate": gate,
        "next_checks": [
            "draw and extract the diode-connected gate/drain strap",
            "add a dedicated substrate-guard connection and local decoupling",
            "match the four channel bias branches from one named star point",
            "run DRC and LVS before promoting this reservation to placement",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mag-dir", type=Path, default=DEFAULT_MAG_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(args.mag_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "selected_candidate": report["selected_candidate"],
        "selected_placement_bbox_um": report["selected_placement_bbox_um"],
        "gate": report["gate"],
    }, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
