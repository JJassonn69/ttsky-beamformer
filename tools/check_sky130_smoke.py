#!/usr/bin/env python3
"""Fail fast when the pinned SKY130 models or ngspice are unusable."""

from __future__ import annotations

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
    high = measure(text, "vout_high")
    low = measure(text, "vout_low")
    trip = measure(text, "vtrip")

    checks = {
        "logic high > 1.75 V": high > 1.75,
        "logic low < 50 mV": low < 0.05,
        "switching point in 0.55..1.25 V": 0.55 < trip < 1.25,
    }

    print(f"SKY130 inverter: high={high:.6f} V low={low:.6g} V trip={trip:.6f} V")
    for label, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
