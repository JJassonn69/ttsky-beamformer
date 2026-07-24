#!/usr/bin/env python3
"""Verify the production-candidate four-bit switched tail-current trim."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = PROJECT_ROOT / "build" / "v2" / "switched_tail"
MODEL_ROOT = PROJECT_ROOT / "third_party" / "sky130_fd_pr"
MEASURE_RE = re.compile(
    r"^(itail|vg[0-3])_code_([0-9]|1[0-5])\s*=\s*([-+0-9.eE]+)",
    re.MULTILINE,
)


def spice_deck(corner: str, supply_v: float, temperature_c: float) -> str:
    measures = []
    for code in range(16):
        time_us = code + 0.75
        measures.append(
            f".measure tran itail_code_{code} find i(VTAIL) at={time_us:.2f}u"
        )
        for bit in range(4):
            measures.append(
                f".measure tran vg{bit}_code_{code} find v(xtrim.g{bit}) at={time_us:.2f}u"
            )
    return f"""* Generated V2 local switched-tail PVT characterization.
.option scale=1e-6
.option method=gear
.temp {temperature_c}
.include "spice/sky130/sky130_1v8_{corner}.inc"
.include "spice/sky130/sky130_passives_tt.inc"
.include "v2/spice/r2r_4bit.inc"
.include "v2/spice/switched_tail_trim.inc"

.param VDD_VALUE={supply_v}
VDD vdd 0 {{VDD_VALUE}}
XRB vdd vbias 0 v2_r_unit
XBIASA vbias vbias 0 0 sky130_fd_pr__nfet_01v8 w=16 l=0.50
XBIASB vbias vbias 0 0 sky130_fd_pr__nfet_01v8 w=16 l=0.50

* Exercise a binary count through actual CMOS buffers and complementary
* controls.  The 50 ps incremental skew is harmless because channel updates
* are committed while the mixer is blanked, but it still stresses settling.
VB0 in0 0 pulse(0 {{VDD_VALUE}} 1u 100p 100p 1u 2u)
VB1 in1 0 pulse(0 {{VDD_VALUE}} 2.00005u 100p 100p 2u 4u)
VB2 in2 0 pulse(0 {{VDD_VALUE}} 4.00010u 100p 100p 4u 8u)
VB3 in3 0 pulse(0 {{VDD_VALUE}} 8.00015u 100p 100p 8u 16u)
XD0 in0 c0 vdd 0 v2_dac_bit_driver
XD1 in1 c1 vdd 0 v2_dac_bit_driver
XD2 in2 c2 vdd 0 v2_dac_bit_driver
XD3 in3 c3 vdd 0 v2_dac_bit_driver
XI0 c0 c0b vdd 0 v2_cmos_inv wn=1.26 wp=2.0
XI1 c1 c1b vdd 0 v2_cmos_inv wn=1.26 wp=2.0
XI2 c2 c2b vdd 0 v2_cmos_inv wn=1.26 wp=2.0
XI3 c3 c3b vdd 0 v2_cmos_inv wn=1.26 wp=2.0

XTRIM tail vbias c0 c0b c1 c1b c2 c2b c3 c3b 0 v2_switched_tail_trim
VTAIL tail 0 0.15

.tran 2n 15.95u
{chr(10).join(measures)}
.end
"""


def parse_measures(log_text: str) -> dict[str, list[float]]:
    values: dict[str, dict[int, float]] = {
        "itail": {},
        "vg0": {},
        "vg1": {},
        "vg2": {},
        "vg3": {},
    }
    for name, code_text, value_text in MEASURE_RE.findall(log_text):
        values[name][int(code_text)] = float(value_text)
    missing = {
        name: sorted(set(range(16)) - set(code_values))
        for name, code_values in values.items()
        if len(code_values) != 16
    }
    if missing:
        raise RuntimeError(f"ngspice log is missing measurements: {missing}")
    return {
        name: [code_values[code] for code in range(16)]
        for name, code_values in values.items()
    }


def analyze(values: dict[str, list[float]]) -> dict[str, Any]:
    currents = [abs(value) for value in values["itail"]]
    nominal = currents[8]
    relative = [value / nominal for value in currents]
    endpoint_lsb = (currents[-1] - currents[0]) / 15.0
    steps = [currents[index + 1] - currents[index] for index in range(15)]
    dnl = [step / endpoint_lsb - 1.0 for step in steps]
    ideal = [currents[0] + code * endpoint_lsb for code in range(16)]
    inl = [
        (currents[code] - ideal[code]) / endpoint_lsb
        for code in range(16)
    ]
    gate_error = 0.0
    for code in range(16):
        for bit in range(4):
            expected_on = bool(code & (1 << bit))
            voltage = values[f"vg{bit}"][code]
            if expected_on:
                # The selected gate should be near vbias; 0.55 V is a
                # conservative process-independent functional floor.
                gate_error = max(gate_error, max(0.55 - voltage, 0.0))
            else:
                gate_error = max(gate_error, max(voltage - 0.05, 0.0))
    return {
        "tail_current_a": currents,
        "relative_tail_current": relative,
        "code_0_relative": relative[0],
        "code_8_relative": relative[8],
        "code_15_relative": relative[15],
        "monotonic": all(step > 0.0 for step in steps),
        "max_abs_dnl_lsb": max(abs(value) for value in dnl),
        "max_abs_inl_lsb": max(abs(value) for value in inl),
        "gate_function_error_v": gate_error,
        "trim_gate_voltages_v": {
            name: values[name] for name in ("vg0", "vg1", "vg2", "vg3")
        },
    }


def run_case(
    ngspice: str,
    corner: str,
    supply_v: float,
    temperature_c: float,
) -> dict[str, Any]:
    case_name = f"{corner}_{supply_v:.2f}v_{temperature_c:+.0f}c"
    case_dir = BUILD_ROOT / case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    deck_path = case_dir / "switched_tail.spice"
    log_path = case_dir / "ngspice.log"
    deck_path.write_text(spice_deck(corner, supply_v, temperature_c), encoding="utf-8")
    result = subprocess.run(
        [ngspice, "-b", "-o", str(log_path), str(deck_path)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        log = log_path.read_text(encoding="utf-8", errors="replace")
        raise RuntimeError(
            f"ngspice failed for {case_name}:\n{result.stdout}\n{result.stderr}\n{log}"
        )
    analysis = analyze(
        parse_measures(log_path.read_text(encoding="utf-8", errors="replace"))
    )
    analysis.update(
        {
            "name": case_name,
            "corner": corner,
            "supply_v": supply_v,
            "temperature_c": temperature_c,
        }
    )
    return analysis


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--output", type=Path, default=BUILD_ROOT / "summary.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not shutil.which(args.ngspice):
        raise SystemExit(f"ngspice not found: {args.ngspice}")
    if not MODEL_ROOT.exists():
        raise SystemExit(f"SKY130 primitive models not found: {MODEL_ROOT}")

    conditions = (
        tuple(
            (corner, supply, temperature)
            for corner in ("tt", "ff", "ss")
            for supply in (1.62, 1.80, 1.98)
            for temperature in (-40.0, 27.0, 85.0)
        )
        if args.full
        else (("tt", 1.80, 27.0),)
    )
    cases = [run_case(args.ngspice, *condition) for condition in conditions]
    failures: list[str] = []
    for case in cases:
        if not case["monotonic"]:
            failures.append(f"{case['name']}: non-monotonic")
        if case["max_abs_dnl_lsb"] > 0.25:
            failures.append(
                f"{case['name']}: DNL {case['max_abs_dnl_lsb']:.3f} LSB exceeds 0.25"
            )
        if case["max_abs_inl_lsb"] > 0.25:
            failures.append(
                f"{case['name']}: INL {case['max_abs_inl_lsb']:.3f} LSB exceeds 0.25"
            )
        if case["gate_function_error_v"] > 0.0:
            failures.append(f"{case['name']}: trim gate switch did not reach a legal rail")
    summary = {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "architecture": "local four-bit binary-weighted switched tail-current trim",
        "default_code": 8,
        "nominal_relative_range": [32.0 / 40.0, 47.0 / 40.0],
        "case_count": len(cases),
        "worst_abs_dnl_lsb": max(case["max_abs_dnl_lsb"] for case in cases),
        "worst_abs_inl_lsb": max(case["max_abs_inl_lsb"] for case in cases),
        "minimum_code_0_relative": min(case["code_0_relative"] for case in cases),
        "maximum_code_15_relative": max(case["code_15_relative"] for case in cases),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
