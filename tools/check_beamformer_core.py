#!/usr/bin/env python3
"""Release gates for the integrated nominal SKY130 beamformer core."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


def measure(text: str, name: str) -> float:
    match = re.search(rf"^\s*{re.escape(name)}\s*=\s*([-+0-9.eE]+)", text, re.MULTILINE)
    if not match:
        raise SystemExit(f"FAIL: missing ngspice measure {name!r}")
    return float(match.group(1))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check the integrated beamformer transient measurements."
    )
    parser.add_argument("ngspice_log", type=Path)
    parser.add_argument(
        "--null-min-db",
        type=float,
        default=40.0,
        help="minimum null depth for this detector (default: 40 dB)",
    )
    args = parser.parse_args()
    text = args.ngspice_log.read_text(encoding="utf-8", errors="replace")
    names = ("sum_rms", "null_rms", "sum_cm", "null_cm", "sum_supply", "null_supply")
    values = {name: measure(text, name) for name in names}
    null_db = -20.0 * math.log10(max(values["null_rms"], 1e-30) / values["sum_rms"])
    sum_current = -values["sum_supply"]
    null_current = -values["null_supply"]
    checks = {
        "integrated constructive output exceeds 1 mVrms": values["sum_rms"] > 1e-3,
        f"on-chip LO-select null exceeds {args.null_min_db:g} dB": (
            null_db > args.null_min_db
        ),
        "both output common modes are 1.2..1.7 V": 1.2 < min(values["sum_cm"], values["null_cm"]) and max(values["sum_cm"], values["null_cm"]) < 1.7,
        "each active core draws below 1 mA": max(sum_current, null_current) < 1e-3,
        "mode current mismatch is below 10%": abs(sum_current / null_current - 1.0) < 0.10,
    }
    report = {
        **values,
        "sum_supply_current_a": sum_current,
        "null_supply_current_a": null_current,
        "integrated_null_db": null_db,
        "checks": checks,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
