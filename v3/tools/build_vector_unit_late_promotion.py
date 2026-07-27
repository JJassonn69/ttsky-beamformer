#!/usr/bin/env python3
"""Build a V3 vector-unit variant with late analog-gate promotion.

The accepted vector-unit placement is preserved.  Only the low-current
``sig``, ``ref``, and ``vbias`` gate access changes: each gate escapes on M1
to a clear perimeter track and remains on M1 at the unit boundary.  The row
generator owns the single later M1-to-M2 promotion into the analog service
corridor.  Current-carrying source/drain routes and the LO/output topology are
deliberately unchanged.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import build_vector_unit_placement as baseline


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "v3/layout/vector_unit_late_promotion.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def segment(
    first: list[float], second: list[float], layer: str, width_um: float,
) -> dict[str, Any]:
    return {
        "from": [round(value, 6) for value in first],
        "to": [round(value, 6) for value in second],
        "layer": layer,
        "width_um": width_um,
    }


def terminal(data: dict[str, Any], device_name: str, terminal_name: str) -> list[float]:
    device = next(item for item in data["devices"] if item["name"] == device_name)
    points = device["terminals"][terminal_name]
    if len(points) != 1:
        raise RuntimeError(f"{device_name}.{terminal_name} is not a single access point")
    return [float(value) for value in points[0]]


def build() -> dict[str, Any]:
    data = copy.deepcopy(baseline.build())

    sig_gate = terminal(data, "XGM_P", "G")
    ref_gate = terminal(data, "XGM_N", "G")
    vbias_gate = terminal(data, "XTAIL", "G")

    # SIG and REF are exact mirrors about x=1.43 um.  VBIAS uses a separate
    # right-side M1 track below the GM devices; whole-unit MY placement mirrors
    # that track automatically in alternating matrix positions.
    sig_escape = [-0.65, sig_gate[1]]
    ref_escape = [3.51, ref_gate[1]]
    vbias_escape = [3.05, vbias_gate[1]]
    boundary_y = 0.0

    data["routes"]["sig"] = [
        segment(sig_gate, sig_escape, "metal1", 0.23),
        segment(sig_escape, [sig_escape[0], boundary_y], "metal1", 0.23),
    ]
    data["routes"]["ref"] = [
        segment(ref_gate, ref_escape, "metal1", 0.23),
        segment(ref_escape, [ref_escape[0], boundary_y], "metal1", 0.23),
    ]
    data["routes"]["vbias"] = [
        segment(vbias_gate, vbias_escape, "metal1", 0.23),
        segment(vbias_escape, [vbias_escape[0], boundary_y], "metal1", 0.23),
    ]

    for name, point in {
        "sig": [sig_escape[0], boundary_y],
        "ref": [ref_escape[0], boundary_y],
        "vbias": [vbias_escape[0], boundary_y],
    }.items():
        data["boundary_ports"][name] = {"point": point, "layer": "metal1"}

    sig_length = abs(sig_gate[0] - sig_escape[0]) + abs(sig_escape[1] - boundary_y)
    ref_length = abs(ref_gate[0] - ref_escape[0]) + abs(ref_escape[1] - boundary_y)
    if abs(sig_length - ref_length) > 1e-9:
        raise RuntimeError("late-promotion SIG/REF M1 paths are not length matched")

    data["status"] = "late-promotion access candidate; exact unit and row gates pending"
    data["late_promotion"] = {
        "scope": ["sig", "ref", "vbias"],
        "device_placement_changed": False,
        "source_drain_routing_changed": False,
        "output_routing_changed": False,
        "phase_routing_changed": False,
        "unit_boundary_layer": "metal1",
        "row_collection_layer": "metal1",
        "service_spine_layer": "metal2",
        "sig_ref_unit_path_length_um": round(sig_length, 6),
        "vbias_unit_path_length_um": round(
            abs(vbias_gate[0] - vbias_escape[0]) + abs(vbias_escape[1] - boundary_y), 6
        ),
        "constraints": {
            "sig_ref_exact_mirror": True,
            "one_m1_to_m2_promotion_per_row_net": True,
            "no_analog_gate_use_of_m3_or_m4_inside_unit": True,
            "do_not_move_current_paths_to_m1": True,
        },
    }
    data["provenance"] = {
        **data.get("provenance", {}),
        "late_promotion_generator": "v3/tools/build_vector_unit_late_promotion.py",
        "late_promotion_generator_sha256": sha256(Path(__file__)),
        "baseline_manifest": "v3/layout/vector_unit_placement.json",
        "baseline_manifest_sha256": sha256(ROOT / "v3/layout/vector_unit_placement.json"),
    }
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
