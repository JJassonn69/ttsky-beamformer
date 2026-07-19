#!/usr/bin/env python3
"""Check the nominal SKY130 shared bias reference and low-headroom sink."""

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
    values = {name: measure(text, name) for name in ("vbias_dc", "iref_dc", "itail_dc")}

    # ngspice reports currents into voltage-source positive terminals. Convert
    # the two supply/sink measurements to positive consumed/sunk magnitudes.
    iref = -values["iref_dc"]
    itail = -values["itail_dc"]
    mirror_error = abs(itail / iref - 1.0)
    checks = {
        "bias voltage is inside 0.6..0.9 V": 0.6 < values["vbias_dc"] < 0.9,
        "reference current is 80..120 uA": 80e-6 < iref < 120e-6,
        "tail current at 150 mV is 70..120 uA": 70e-6 < itail < 120e-6,
        "nominal low-headroom mirror error is below 5%": mirror_error < 0.05,
    }
    report = {
        "vbias_v": values["vbias_dc"],
        "iref_a": iref,
        "itail_at_150mv_a": itail,
        "mirror_error_fraction": mirror_error,
        "checks": checks,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
