#!/usr/bin/env python3
"""Build the selected 3x5 matrix contract with late-promotion unit ports."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import build_channel_matrix_placement as matrix_builder


ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE = ROOT / "v3/layout/channel_routing_architecture.json"
UNIT = ROOT / "v3/layout/vector_unit_late_promotion.json"
UNIT_GATE = ROOT / "build/v3/vector_unit_late_promotion/topology_audit.json"
DEFAULT_OUTPUT = ROOT / "v3/layout/channel_matrix_late_promotion.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict[str, object]:
    architecture = json.loads(ARCHITECTURE.read_text(encoding="utf-8"))
    selected_name = architecture["decision"]["selected"]
    columns = architecture["candidates"][selected_name]["column_origins_um"]
    result = matrix_builder.build(
        column_origins=[float(value) for value in columns],
        unit_path=UNIT,
        unit_gate_path=UNIT_GATE,
    )
    unit = json.loads(UNIT.read_text(encoding="utf-8"))
    unit_gate = json.loads(UNIT_GATE.read_text(encoding="utf-8"))
    for instance in result["matrix"]["instances"]:
        origin = [float(value) for value in instance["origin"]]
        orientation = str(instance["orientation"])
        instance["ports"] = {
            name: {
                "point": matrix_builder.transform_point(value["point"], origin, orientation),
                "layer": value["layer"],
            }
            for name, value in unit["boundary_ports"].items()
        }
    result["status"] = "late-promotion 3x5 matrix candidate; full service gate pending"
    result["unit_reference"] = {
        "manifest": "v3/layout/vector_unit_late_promotion.json",
        "manifest_sha256": sha256(UNIT),
        "physical_gate": str(UNIT_GATE.relative_to(ROOT)),
        "physical_gate_sha256": sha256(UNIT_GATE),
        "gds": unit_gate["gds"],
        "gds_sha256": unit_gate["gds_sha256"],
        "baseline_placement_unchanged": True,
        "late_promotion_scope": ["sig", "ref", "vbias"],
        "tile_bbox": unit["tile_bbox"],
    }
    result["late_promotion"] = {
        "selected_architecture": selected_name,
        "column_origins_um": columns,
        "rows_using_m1_collection": [0, 1, 2, 3, 4],
        "shared_guard_bottom_y_um": 4.8,
        "ground_collection": "one M2 spine at x=6.98 um, five named M2/M3 row taps, one bottom guard join",
        "bottom_row_guard_safe_fallback": None,
        "reason": "the guard extends into the reserved bottom margin, so every row uses the validated M1-bus/M2-drop structure and no analog gate route consumes M3 or M4",
    }
    result["provenance"] = {
        **result.get("provenance", {}),
        "late_promotion_generator": "v3/tools/build_channel_matrix_late_promotion.py",
        "late_promotion_generator_sha256": sha256(Path(__file__)),
        "architecture_sha256": sha256(ARCHITECTURE),
    }
    return result


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
