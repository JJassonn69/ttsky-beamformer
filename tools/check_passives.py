#!/usr/bin/env python3
"""Measure the chosen layout-qualified SKY130 resistor and MIM devices."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def measure(text: str, name: str) -> float:
    match = re.search(rf"^\s*{re.escape(name)}\s*=\s*([-+0-9.eE]+)", text, re.MULTILINE)
    if not match:
        raise SystemExit(f"FAIL: missing ngspice measure {name!r}")
    return float(match.group(1))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} NGSPICE_LOG")
    text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    values = {name: measure(text, name) for name in ("iload", "ibias", "ixhigh", "cap_rise")}
    rload = 0.30 / -values["iload"]
    rbias = 1.10 / -values["ibias"]
    rxhigh = 0.90 / -values["ixhigh"]
    cap = values["cap_rise"] / (2.197224577 * 1000.0)
    checks = {
        "load resistor is 2.7..3.3 kohm": 2.7e3 < rload < 3.3e3,
        "bias resistor is 9.5..11.5 kohm": 9.5e3 < rbias < 11.5e3,
        "input-bias unit resistor is 90..110 kohm": 90e3 < rxhigh < 110e3,
        "VCM capacitor is 0.9..1.1 pF": 0.9e-12 < cap < 1.1e-12,
    }
    report = {
        "load_resistance_ohm": rload,
        "bias_resistance_ohm": rbias,
        "xhigh_resistance_ohm": rxhigh,
        "mim_capacitance_f": cap,
        "checks": checks,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
