#!/usr/bin/env python3
"""Prove exact fixed and binary tail-bank connectivity in flat extraction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .check_critical_extraction import logical_lines
except ImportError:  # direct script execution
    from check_critical_extraction import logical_lines


NFET_MODEL = "sky130_fd_pr__nfet_01v8"
TRIM_WEIGHTS = (1, 2, 4, 8)
FIXED_FINGERS = 36


def nfet_devices(text: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for line in logical_lines(text):
        tokens = line.split()
        if len(tokens) < 6 or not tokens[0].upper().startswith("X"):
            continue
        if tokens[5] != NFET_MODEL:
            continue
        parameters = {
            key: value
            for token in tokens[6:]
            if "=" in token
            for key, value in (token.split("=", 1),)
        }
        devices.append({
            "name": tokens[0],
            "drain": tokens[1],
            "gate": tokens[2],
            "source": tokens[3],
            "body": tokens[4],
            "parameters": parameters,
        })
    return devices


def tail_pair_is_exact(device: dict[str, Any], tail: str) -> bool:
    return (
        {device["drain"], device["source"]} == {tail, "VGND"}
        and device["drain"] != device["source"]
        and device["body"] == "VGND"
        and device["parameters"].get("l") == "0.5"
    )


def audit(flat_spice: str) -> dict[str, Any]:
    devices = nfet_devices(flat_spice)
    errors: list[str] = []
    channels: list[dict[str, Any]] = []

    for channel in range(4):
        tail = f"ch{channel}_tail"
        fixed = [
            device for device in devices
            if device["gate"] == "ch0_vbias"
            and tail in (device["drain"], device["source"])
        ]
        bad_fixed = [device["name"] for device in fixed
                     if not tail_pair_is_exact(device, tail)]
        if len(fixed) != FIXED_FINGERS:
            errors.append(
                f"channel {channel}: fixed bank has {len(fixed)} physical "
                f"fingers, expected {FIXED_FINGERS}"
            )
        if bad_fixed:
            errors.append(
                f"channel {channel}: fixed-bank terminals are not exact "
                f"tail/VGND pairs: {bad_fixed}"
            )

        trim_counts: dict[str, int] = {}
        for weight in TRIM_WEIGHTS:
            gate = f"CH{channel}_TTRIM{weight}/G"
            trim = [device for device in devices if device["gate"] == gate]
            bad_trim = [device["name"] for device in trim
                        if not tail_pair_is_exact(device, tail)]
            trim_counts[str(weight)] = len(trim)
            if len(trim) != weight:
                errors.append(
                    f"channel {channel}: trim weight {weight} has "
                    f"{len(trim)} physical fingers"
                )
            if bad_trim:
                errors.append(
                    f"channel {channel}: trim weight {weight} contains "
                    f"floating or miswired terminals: {bad_trim}"
                )
        channels.append({
            "channel": channel,
            "fixed_finger_count": len(fixed),
            "trim_finger_counts": trim_counts,
            "verified_tail_finger_count": len(fixed) + sum(
                trim_counts.values()
            ),
        })

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "nfet_statement_count": len(devices),
        "channels": channels,
        "verified_fixed_finger_count": sum(
            item["fixed_finger_count"] for item in channels
        ),
        "verified_binary_trim_finger_count": sum(
            sum(item["trim_finger_counts"].values()) for item in channels
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--flat-spice", type=Path,
        default=Path(
            "build/v2/control_routing/quadrature_extraction/"
            "control_quadrature_flat.spice"
        ),
    )
    parser.add_argument(
        "--report", type=Path,
        default=Path(
            "build/v2/control_routing/quadrature_extraction/"
            "tail_bank_flat_audit.json"
        ),
    )
    args = parser.parse_args()
    report = audit(args.flat_spice.read_text(errors="replace"))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
