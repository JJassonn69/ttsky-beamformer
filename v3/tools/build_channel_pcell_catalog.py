#!/usr/bin/env python3
"""Build an exact terminal catalogue for the measured V3 channel MOS PCells."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "build" / "v3" / "pcell_dimensions" / "summary.json"
MAG_DIR = ROOT / "build" / "v3" / "pcell_dimensions" / "remote_mag"
MEASURE_TCL = ROOT / "v3" / "layout" / "measure_pcells.tcl"
DEFAULT_OUTPUT = ROOT / "v3" / "layout" / "channel_pcell_catalog.json"
INTERNAL_UNITS_PER_UM = 200.0
PORT_RE = re.compile(
    r"^rlabel\s+(?P<layer>\S+)\s+(?P<x>-?\d+)\s+(?P<y>-?\d+)\s+"
    r"-?\d+\s+-?\d+\s+\d+\s+(?P<name>\S+)\s*$"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ports(path: Path) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = PORT_RE.match(raw)
        if not match:
            continue
        result.setdefault(match["name"], []).append({
            "layer": match["layer"],
            "point_um": [
                int(match["x"]) / INTERNAL_UNITS_PER_UM,
                int(match["y"]) / INTERNAL_UNITS_PER_UM,
            ],
        })
    return result


def build() -> dict[str, Any]:
    study = json.loads(SUMMARY.read_text(encoding="utf-8"))
    cells: dict[str, Any] = {}
    errors: list[str] = []
    for name, measured in sorted(study["measured_pcells"].items()):
        mag = MAG_DIR / f"{measured['generated_cell']}.mag"
        observed_ports = ports(mag)
        expected_ports = {"D", "S", "G"} | ({"B"} if measured["parameters"]["guard"] else set())
        if set(observed_ports) != expected_ports:
            errors.append(f"{name} ports changed: {sorted(observed_ports)}")
        bbox = measured["bbox_um"]
        cells[name] = {
            **measured,
            "gencell_anchor": "lower_left",
            "gencell_anchor_offset_um": [
                round(-bbox[0], 6),
                round(-bbox[1], 6),
            ],
            "ports": observed_ports,
            "body_connection": (
                "PCell guard-ring B port" if measured["parameters"]["guard"]
                else "shared p-substrate guard; no isolated body port on unguarded PCell"
            ),
            "mag": str(mag.relative_to(ROOT)),
            "mag_sha256": sha256(mag),
        }
    required = {"XGM_U", "XSW_U", "XTAIL_U", "XBIAS_PASS_U", "XBIAS_PULL_U"}
    missing = sorted(required - set(cells))
    if missing:
        errors.append(f"missing required channel cells: {missing}")
    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "scope": "measured PCell boxes and exact D/S/G terminal coordinates; shared guard and parent routing remain separate geometry",
        "cells": cells,
        "provenance": {
            "magic_version": study["provenance"]["magic_version"],
            "sky130_pdk_commit": study["provenance"]["sky130_pdk_commit"],
            "dimension_summary": str(SUMMARY.relative_to(ROOT)),
            "dimension_summary_sha256": sha256(SUMMARY),
            "measurement_tcl": str(MEASURE_TCL.relative_to(ROOT)),
            "measurement_tcl_sha256": sha256(MEASURE_TCL),
            "generator": "v3/tools/build_channel_pcell_catalog.py",
            "generator_sha256": sha256(Path(__file__)),
        },
    }


def main() -> None:
    report = build()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
