#!/usr/bin/env python3
"""Generate the deliberately small TinyTapeout abstract LEF.

Magic's generic LEF writer exports every shape connected to a port.  That is a
useful routing abstract for some flows, but TinyTapeout's precheck requires each
template signal pin to have exactly the rectangle from the official DEF.  This
script treats that pinned DEF as the source of truth and adds the two full-height
power stripes drawn by ``generate_layout_scripts.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOP = "tt_um_jjassonn69_beamformer"
TEMPLATE_DEF = ROOT / "build/layout/tt_analog_1x2.def"
OUTPUT = ROOT / f"lef/{TOP}.lef"


@dataclass(frozen=True)
class Pin:
    name: str
    direction: str
    use: str
    layer: str
    rect_nm: tuple[int, int, int, int]


def parse_template(path: Path) -> tuple[int, int, list[Pin]]:
    text = path.read_text(encoding="utf-8")
    units_match = re.search(r"UNITS DISTANCE MICRONS (\d+) ;", text)
    die_match = re.search(
        r"DIEAREA \( 0 0 \) \( (\d+) (\d+) \) ;", text
    )
    if units_match is None or die_match is None:
        raise ValueError(f"could not parse units/die area from {path}")
    units = int(units_match.group(1))
    if units != 1000:
        raise ValueError(f"expected 1000 DEF units/um, got {units}")
    width_nm, height_nm = map(int, die_match.groups())

    pin_pattern = re.compile(
        r"^\s*- (\S+) \+ NET \S+ \+ DIRECTION (\S+) \+ USE (\S+)\s*$"
        r"\s*\+ PORT\s*$"
        r"\s*\+ LAYER (\S+) \( (-?\d+) (-?\d+) \) "
        r"\( (-?\d+) (-?\d+) \)\s*$"
        r"\s*\+ PLACED \( (-?\d+) (-?\d+) \) \S+ ;",
        re.MULTILINE,
    )
    pins: list[Pin] = []
    for match in pin_pattern.finditer(text):
        name, direction, use, layer, lx, by, rx, ty, ox, oy = match.groups()
        lx_i, by_i, rx_i, ty_i, ox_i, oy_i = map(
            int, (lx, by, rx, ty, ox, oy)
        )
        pins.append(
            Pin(
                name=name,
                direction=direction,
                use=use,
                layer=layer,
                rect_nm=(
                    ox_i + lx_i,
                    oy_i + by_i,
                    ox_i + rx_i,
                    oy_i + ty_i,
                ),
            )
        )
    count_match = re.search(r"PINS (\d+) ;", text)
    expected = int(count_match.group(1)) if count_match else -1
    if len(pins) != expected:
        raise ValueError(f"parsed {len(pins)} pins from {path}, expected {expected}")
    return width_nm, height_nm, pins


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
    width_nm, height_nm, pins = parse_template(TEMPLATE_DEF)
    names = [pin.name for pin in pins]
    if len(names) != len(set(names)):
        raise ValueError("duplicate signal pins in template DEF")

    # These match the 2 um-wide stripes drawn from y=5 to y=220.76 um.
    # Each spans to within 10 um of both edges, as TinyTapeout requires.
    power_pins = [
        Pin("VDPWR", "INOUT", "POWER", "met4", (1000, 5000, 3000, 220760)),
        Pin("VGND", "INOUT", "GROUND", "met4", (4000, 5000, 6000, 220760)),
    ]

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
    for pin in pins + power_pins:
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
    print(f"wrote {OUTPUT}: {len(pins)} template pins + {len(power_pins)} power pins")


if __name__ == "__main__":
    main()
