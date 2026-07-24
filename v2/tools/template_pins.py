#!/usr/bin/env python3
"""Shared parser for the pinned Tiny Tapeout 2x2 DEF pin contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


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
    die_match = re.search(r"DIEAREA \( 0 0 \) \( (\d+) (\d+) \) ;", text)
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


def submission_pins(path: Path) -> tuple[int, int, list[Pin]]:
    """Return the 51 template pins plus the required VDPWR/VGND ports."""

    width_nm, height_nm, pins = parse_template(path)
    names = [pin.name for pin in pins]
    if len(names) != len(set(names)):
        raise ValueError("duplicate signal pins in template DEF")
    pins.extend(
        (
            Pin("VDPWR", "INOUT", "POWER", "met4", (1000, 5000, 3000, 220760)),
            Pin("VGND", "INOUT", "GROUND", "met4", (4000, 5000, 6000, 220760)),
        )
    )
    return width_nm, height_nm, pins
