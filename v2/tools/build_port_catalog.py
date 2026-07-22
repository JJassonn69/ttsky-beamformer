#!/usr/bin/env python3
"""Build a route-planner port catalog from Magic MAG labels and LEF ports."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


MAG_LABEL_RE = re.compile(
    r"^rlabel\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+\d+\s+(\S+)"
)
PIN_RE = re.compile(r"^\s*PIN\s+(\S+)")
LAYER_RE = re.compile(r"^\s*LAYER\s+(\S+)\s*;")
RECT_RE = re.compile(
    r"^\s*RECT\s+([-+0-9.]+)\s+([-+0-9.]+)\s+([-+0-9.]+)\s+([-+0-9.]+)\s*;"
)


def logical_terminal(label: str) -> str:
    # Multi-finger MOS labels D0/S1/... describe repeated contacts on one
    # logical terminal.  Passive labels R1/R2 and C1/C2 are distinct ends and
    # must never be collapsed by the route planner.
    if re.fullmatch(r"[DS]\d+", label):
        return label[0]
    return label


def mag_ports(path: Path, database_units_per_um: float = 200.0) -> dict[str, Any]:
    ports: dict[str, list[dict[str, Any]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = MAG_LABEL_RE.match(line)
        if not match:
            continue
        layer, x0, y0, x1, y1, label = match.groups()
        point = [
            (int(x0) + int(x1)) / (2.0 * database_units_per_um),
            (int(y0) + int(y1)) / (2.0 * database_units_per_um),
        ]
        ports.setdefault(logical_terminal(label), []).append(
            {"label": label, "layer": layer, "point_um": point}
        )
    return {"source": str(path), "ports": ports}


def lef_ports(path: Path) -> dict[str, Any]:
    ports: dict[str, list[dict[str, Any]]] = {}
    pin: str | None = None
    layer: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        pin_match = PIN_RE.match(line)
        if pin_match:
            pin = pin_match.group(1)
            layer = None
            ports.setdefault(pin, [])
            continue
        if pin is None:
            continue
        layer_match = LAYER_RE.match(line)
        if layer_match:
            layer = layer_match.group(1)
            continue
        rect_match = RECT_RE.match(line)
        if rect_match and layer is not None:
            x0, y0, x1, y1 = map(float, rect_match.groups())
            ports[pin].append(
                {
                    "layer": layer,
                    "rect_um": [x0, y0, x1, y1],
                    "center_um": [(x0 + x1) / 2.0, (y0 + y1) / 2.0],
                }
            )
            continue
        if line.strip().startswith("END ") and line.strip() == f"END {pin}":
            pin = None
            layer = None
    return {"source": str(path), "ports": ports}


def build_catalog(
    dimensions: dict[str, Any], mag_dir: Path, cell_dir: Path
) -> dict[str, Any]:
    analog: dict[str, Any] = {}
    standard_cells: dict[str, Any] = {}
    errors: list[str] = []
    for name, cell in dimensions["pcells"].items():
        generated = cell["generated_cell"]
        if name.startswith("sc_hd_"):
            lef = cell_dir / f"{generated}.lef"
            if lef.exists():
                standard_cells[name] = lef_ports(lef)
            elif name != "sc_hd_tapvpwrvgnd_1":
                errors.append(f"{name}: missing LEF {lef}")
            continue
        mag = mag_dir / f"{generated}.mag"
        if not mag.exists():
            errors.append(f"{name}: missing MAG {mag}")
            continue
        analog[name] = mag_ports(mag)
    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "coordinate_contract": {
            "analog": "micrometres relative to the generated PCell origin",
            "standard_cells": "micrometres relative to the LEF ORIGIN",
            "orientation_transform": {
                "R0": "(x,y)",
                "MY": "(-x,y) for centred analog PCells; (width-x,y) for LEF cells",
            },
        },
        "analog_pcells": analog,
        "standard_cells": standard_cells,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dimensions", type=Path)
    parser.add_argument("mag_dir", type=Path)
    parser.add_argument("cell_dir", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_catalog(
        json.loads(args.dimensions.read_text(encoding="utf-8")),
        args.mag_dir,
        args.cell_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        f"{args.output}: {len(report['analog_pcells'])} analog PCells, "
        f"{len(report['standard_cells'])} standard cells"
    )
    if report["status"] != "pass":
        raise SystemExit("\n".join(report["errors"]))


if __name__ == "__main__":
    main()
