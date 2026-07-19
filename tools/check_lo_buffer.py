#!/usr/bin/env python3
"""Check rail swing, edge speed and phase skew of the SKY130 LO buffer."""

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
    names = ("lop_high", "lop_low", "lon_high", "lon_low", "lop_delay", "lon_delay", "lop_rise", "lon_fall")
    values = {name: measure(text, name) for name in names}
    skew = abs(values["lon_delay"] - values["lop_delay"])
    checks = {
        "both LO highs exceed 1.75 V": min(values["lop_high"], values["lon_high"]) > 1.75,
        "both LO lows are below 50 mV": max(values["lop_low"], values["lon_low"]) < 0.05,
        "LO overshoot remains inside -0.1..1.9 V": min(values["lop_low"], values["lon_low"]) > -0.1 and max(values["lop_high"], values["lon_high"]) < 1.9,
        "both propagation delays are below 2 ns": max(values["lop_delay"], values["lon_delay"]) < 2e-9,
        "complementary path skew is below 1 ns": skew < 1e-9,
        "loaded 10-90% edges are below 2 ns": max(values["lop_rise"], values["lon_fall"]) < 2e-9,
    }
    report = {**values, "path_skew_s": skew, "checks": checks}
    print(json.dumps(report, indent=2, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
