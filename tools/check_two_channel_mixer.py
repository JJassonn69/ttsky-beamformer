#!/usr/bin/env python3
"""Check nominal combining and binary phase cancellation of the SKY130 mixer."""

from __future__ import annotations

import json
import math
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
    values = {name: measure(text, name) for name in (
        "sum_rms", "null_rms", "error_rms", "output_cm",
    )}
    ideal_null_db = -20.0 * math.log10(max(values["null_rms"], 1e-30) / values["sum_rms"])
    error_null_db = -20.0 * math.log10(values["error_rms"] / values["sum_rms"])
    checks = {
        "constructive 1 MHz output exceeds 1 mVrms": values["sum_rms"] > 1e-3,
        "matched binary phase inversion null exceeds 40 dB": ideal_null_db > 40.0,
        "1 dB / 8 degree error still meets 20 dB null": error_null_db >= 20.0,
        "differential output common-mode is 1.2..1.7 V": 1.2 < values["output_cm"] < 1.7,
    }
    report = {
        **values,
        "ideal_null_db": ideal_null_db,
        "error_envelope_null_db": error_null_db,
        "checks": checks,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
