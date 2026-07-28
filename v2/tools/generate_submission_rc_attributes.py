#!/usr/bin/env python3
"""Generate final-submission extresist anchors from labels in the exact GDS.

Run under KLayout's Python interpreter.  The submission GDS is the only source
of coordinates, so RC extraction remains reproducible after intermediate route
build artifacts have been cleaned.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import pya


TOP = "tt_um_jjassonn69_beamformer"
R_LABEL = re.compile(r"R\d{3}$")
EXTERNAL_UNDRIVEN = re.compile(
    r"^(?:ch[0-3]_input|ch[0-3]_phase_sel[01]|ch[0-3]_phase_enable|"
    r"phase_(?:0|90|180|270)|vcm)$"
)
DRIVE_ONLY = re.compile(r"^ch[0-3]_lo[pn]$")
FORCE_ONLY = re.compile(r"^sum_[pn]$")
POWER = {"VDPWR", "VGND"}
MAGIC_LAYER = {
    67: "locali",
    68: "metal1",
    69: "metal2",
    70: "metal3",
    71: "metal4",
}


def flattened_texts(layout: pya.Layout, top: pya.Cell) -> list[tuple[str, float, float, str]]:
    labels: set[tuple[str, float, float, str]] = set()
    for layer_index in layout.layer_indexes():
        info = layout.get_info(layer_index)
        magic_layer = MAGIC_LAYER.get(info.layer)
        if magic_layer is None:
            continue
        iterator = top.begin_shapes_rec(layer_index)
        while not iterator.at_end():
            shape = iterator.shape()
            if shape.is_text():
                text = shape.text
                transform = iterator.trans() * text.trans
                point = transform.disp
                labels.add((
                    text.string,
                    round(point.x * layout.dbu, 6),
                    round(point.y * layout.dbu, 6),
                    magic_layer,
                ))
            iterator.next()
    return sorted(labels)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gds", type=Path,
        default=Path(os.environ.get(
            "BF_RC_GDS", "gds/tt_um_jjassonn69_beamformer.gds"
        )),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path(os.environ.get(
            "BF_RC_ATTRIBUTES", "build/v2/submission/final_rc/force_attributes.tcl"
        )),
    )
    args = parser.parse_args()

    layout = pya.Layout()
    layout.read(str(args.gds))
    top = layout.cell(TOP)
    if top is None:
        raise SystemExit(f"missing top cell {TOP}")
    labels = flattened_texts(layout, top)
    selected = [
        item for item in labels
        if R_LABEL.fullmatch(item[0])
        or EXTERNAL_UNDRIVEN.fullmatch(item[0])
        or DRIVE_ONLY.fullmatch(item[0])
        or FORCE_ONLY.fullmatch(item[0])
    ]
    # Standard cells contain thousands of local VGND labels.  Anchor each
    # supply exactly once on the intentional top-level M4 strap instead.
    for power in sorted(POWER):
        candidates = [
            item for item in labels
            if item[0] == power and item[3] == "metal4"
        ]
        if not candidates:
            raise SystemExit(f"missing top-level metal4 label for {power}")
        selected.append(sorted(candidates)[0])
    selected.sort()
    routed = {name for name, *_rest in selected if R_LABEL.fullmatch(name)}
    if len(routed) != 206:
        raise SystemExit(f"found {len(routed)} routed Rxxx labels, expected 206")

    lines = [
        "# Generated from exact final-submission GDS labels; not manufactured.",
    ]
    for name, x, y, layer in selected:
        lines.extend((
            f"# retain extracted mesh {name}",
            f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um",
        ))
        if (
            R_LABEL.fullmatch(name)
            or EXTERNAL_UNDRIVEN.fullmatch(name)
            or FORCE_ONLY.fullmatch(name)
            or name in POWER
        ):
            lines.append(f"label {{res:force@}} FreeSans 0.10u -{layer}")
        if (
            EXTERNAL_UNDRIVEN.fullmatch(name)
            or DRIVE_ONLY.fullmatch(name)
            or FORCE_ONLY.fullmatch(name)
            or name in POWER
        ):
            lines.append(f"label {{res:drive@}} FreeSans 0.10u -{layer}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n")
    print(f"{args.output}: {len(selected)} anchors, 206 routed control labels")


if __name__ == "__main__":
    main()
