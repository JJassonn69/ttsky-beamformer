#!/usr/bin/env python3
"""Regression gates for the first SKY130 transistor-level analog block."""

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

    values = {name: measure(text, name) for name in (
        "vin_pp", "vout_pp", "vout_cm", "gain_v", "tail_voltage",
    )}
    checks = {
        "TT path preserves a 9.5..10.1 mVpp input": 9.5e-3 < values["vin_pp"] < 10.1e-3,
        "transient voltage gain is 1..20 V/V": 1.0 < values["gain_v"] < 20.0,
        "output common-mode is 1.2..1.7 V": 1.2 < values["vout_cm"] < 1.7,
        "tail node retains >100 mV headroom": values["tail_voltage"] > 0.1,
    }

    print(
        "SKY130 transconductor: "
        f"Vin={values['vin_pp'] * 1e3:.4f} mVpp "
        f"Vout={values['vout_pp'] * 1e3:.4f} mVpp "
        f"gain={values['gain_v']:.4f} V/V "
        f"VCMout={values['vout_cm']:.4f} V "
        f"Vtail={values['tail_voltage']:.4f} V"
    )
    for label, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
