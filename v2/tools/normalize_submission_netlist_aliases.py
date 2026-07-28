#!/usr/bin/env python3
"""Normalize submission-wrapper net aliases for the V2 simulation harness.

The submitted Tiny Tapeout wrapper labels the differential outputs ``sum_p``
and ``sum_n`` and its ground anchor ``VGND``.  The V2 simulation harness
predates the wrapper and names the same physical nets ``ch0_out_p``,
``ch0_out_n``, and the standard-cell tap node below.  This tool performs only
those token-bounded substitutions and records their counts, avoiding any
topology or device changes to the extracted netlist.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ALIASES = {
    "sum_p": "ch0_out_p",
    "sum_n": "ch0_out_n",
    "VGND": "sky130_fd_sc_hd__fill_1_2190.VNB",
}


def replace_token(text: str, old: str, new: str) -> tuple[str, int]:
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])")
    return pattern.subn(new, text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    source = args.input.read_text(encoding="utf-8", errors="strict")
    normalized = source
    counts: dict[str, int] = {}
    for old, new in ALIASES.items():
        normalized, count = replace_token(normalized, old, new)
        counts[f"{old}->{new}"] = count
        if count == 0:
            raise SystemExit(f"required submission net alias is absent: {old}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(normalized, encoding="utf-8")
    for alias, count in counts.items():
        print(f"{alias} replacements={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
