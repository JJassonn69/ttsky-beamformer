#!/usr/bin/env python3
"""Generate the exact Tiny Tapeout V2 2x2 abstract LEF.

Magic's generic LEF writer exports every shape connected to a port.  That is a
useful routing abstract for some flows, but TinyTapeout's precheck requires each
template signal pin to have exactly the rectangle from the official DEF.  This
script treats that pinned DEF as the source of truth and adds the two full-height
power ports present in the frozen V2 candidate.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "v2/tools"))

from template_pins import Pin, submission_pins  # noqa: E402


TOP = "tt_um_jjassonn69_beamformer"
TEMPLATE_DEF = ROOT / "build/v2/tt_analog_2x2.def"
OUTPUT = ROOT / f"lef/{TOP}.lef"


def um(value_nm: int) -> str:
    return f"{value_nm / 1000:.3f}"


def pin_block(pin: Pin) -> list[str]:
    lx, by, rx, ty = pin.rect_nm
    return [
        f"  PIN {pin.name}",
        f"    DIRECTION {pin.direction} ;",
        f"    USE {pin.use} ;",
        "    PORT",
        f"      LAYER {pin.layer} ;",
        f"        RECT {um(lx)} {um(by)} {um(rx)} {um(ty)} ;",
        "    END",
        f"  END {pin.name}",
    ]


def main() -> None:
    width_nm, height_nm, pins = submission_pins(TEMPLATE_DEF)

    lines = [
        "VERSION 5.8 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        "UNITS",
        "  DATABASE MICRONS 1000 ;",
        "END UNITS",
        f"MACRO {TOP}",
        "  CLASS BLOCK ;",
        f"  FOREIGN {TOP} 0.000 0.000 ;",
        "  ORIGIN 0.000 0.000 ;",
        f"  SIZE {um(width_nm)} BY {um(height_nm)} ;",
    ]
    for pin in pins:
        lines.extend(pin_block(pin))

    # Keep top-level routing away from the analog core.  Boundary pins remain
    # available on met4; lower layers are entirely internal to this macro.
    lines.extend(
        [
            "  OBS",
            "    LAYER li1 ;",
            f"      RECT 0.000 0.000 {um(width_nm)} {um(height_nm)} ;",
            "    LAYER met1 ;",
            f"      RECT 0.000 0.000 {um(width_nm)} {um(height_nm)} ;",
            "    LAYER met2 ;",
            f"      RECT 0.000 0.000 {um(width_nm)} {um(height_nm)} ;",
            "    LAYER met3 ;",
            f"      RECT 0.000 0.000 {um(width_nm)} {um(height_nm)} ;",
            "  END",
            f"END {TOP}",
            "END LIBRARY",
        ]
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}: {len(pins) - 2} template pins + 2 power pins")


if __name__ == "__main__":
    main()
