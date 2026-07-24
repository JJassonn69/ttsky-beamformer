#!/usr/bin/env python3
"""Generate an exact DEF for one repeated V2 local selector placement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ORIENTATIONS = {"R0": "N", "MY": "FN"}


def fmt_dbu(value_um: float) -> int:
    return round(value_um * 1000.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dimensions", type=Path)
    parser.add_argument("template", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dimensions = json.loads(args.dimensions.read_text(encoding="utf-8"))["pcells"]
    template = json.loads(args.template.read_text(encoding="utf-8"))
    selector_bbox = template["regions"]["phase_selector_reserved"]
    x_origin = float(selector_bbox[0])
    y_origin = float(selector_bbox[1])
    width = float(selector_bbox[2]) - x_origin
    height = float(selector_bbox[3]) - y_origin
    components = [
        component
        for component in template["components"]
        if component.get("placement_region") == "phase_selector"
    ]

    lines = [
        "VERSION 5.8 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        "DESIGN v2_phase_selector_placement ;",
        "UNITS DISTANCE MICRONS 1000 ;",
        f"DIEAREA ( 0 0 ) ( {fmt_dbu(width)} {fmt_dbu(height)} ) ;",
        f"COMPONENTS {len(components)} ;",
    ]
    for component in components:
        cell = dimensions[component["pcell"]]
        lower_left_x = float(component["x"]) - float(cell["width_um"]) / 2.0 - x_origin
        lower_left_y = float(component["y"]) - float(cell["height_um"]) / 2.0 - y_origin
        orientation = ORIENTATIONS[component["orientation"]]
        lines.append(
            f"- {component['name']} {cell['generated_cell']} + FIXED "
            f"( {fmt_dbu(lower_left_x)} {fmt_dbu(lower_left_y)} ) {orientation} ;"
        )
    lines.extend(("END COMPONENTS", "PINS 0 ;", "END PINS", "NETS 0 ;", "END NETS", "END DESIGN"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
