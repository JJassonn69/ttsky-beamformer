#!/usr/bin/env python3
"""Run SKY130 transistor/resistor sweeps for the V2 four-bit R-2R trim DAC."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = PROJECT_ROOT / "build" / "v2" / "r2r"
MODEL_ROOT = PROJECT_ROOT / "third_party" / "sky130_fd_pr"

MEASURE_RE = re.compile(
    r"^(code_(?:[0-9]|1[0-5])|glitch_7_to_8_(?:min|max)|supply_avg)\s*=\s*"
    r"([-+0-9.eE]+)",
    re.MULTILINE,
)


def spice_deck(corner: str, supply_v: float, temperature_c: float, load_ohm: float) -> str:
    measures = "\n".join(
        f".measure tran code_{code} find v(out) at={code + 0.75:.2f}u"
        for code in range(16)
    )
    return f"""* Generated V2 R-2R PVT/load characterization.
.option scale=1e-6
.option method=gear
.temp {temperature_c}
.include \"spice/sky130/sky130_1v8_{corner}.inc\"
.include \"spice/sky130/sky130_passives_tt.inc\"
.include \"v2/spice/r2r_4bit.inc\"

.param VDD_VALUE={supply_v}
VDD vdd 0 {{VDD_VALUE}}

* Binary count 0..15 with deliberate 50 ps incremental driver skew. This
* exercises the multi-bit carry transition rather than assuming ideal simultaneity.
VB0 in0 0 pulse(0 {{VDD_VALUE}} 1u 100p 100p 1u 2u)
VB1 in1 0 pulse(0 {{VDD_VALUE}} 2.00005u 100p 100p 2u 4u)
VB2 in2 0 pulse(0 {{VDD_VALUE}} 4.00010u 100p 100p 4u 8u)
VB3 in3 0 pulse(0 {{VDD_VALUE}} 8.00015u 100p 100p 8u 16u)

XD0 in0 b0 vdd 0 v2_dac_bit_driver
XD1 in1 b1 vdd 0 v2_dac_bit_driver
XD2 in2 b2 vdd 0 v2_dac_bit_driver
XD3 in3 b3 vdd 0 v2_dac_bit_driver
XDAC b0 b1 b2 b3 out 0 v2_r2r_4bit

RLOAD out 0 {load_ohm}
CLOAD out 0 200f

.tran 2n 15.95u
{measures}
.measure tran glitch_7_to_8_min min v(out) from=7.90u to=8.30u
.measure tran glitch_7_to_8_max max v(out) from=7.90u to=8.30u
.measure tran supply_avg avg i(VDD) from=1u to=15.9u
.end
"""


def parse_measures(log_text: str) -> dict[str, float]:
    values = {name: float(value) for name, value in MEASURE_RE.findall(log_text)}
    expected = {f"code_{code}" for code in range(16)}
    missing = sorted(expected - values.keys())
    if missing:
        raise RuntimeError(f"ngspice log is missing measurements: {missing}")
    return values


def analyze_values(values: dict[str, float]) -> dict[str, Any]:
    codes = [values[f"code_{code}"] for code in range(16)]
    endpoint_lsb = (codes[-1] - codes[0]) / 15.0
    steps = [codes[index + 1] - codes[index] for index in range(15)]
    dnl = [step / endpoint_lsb - 1.0 for step in steps]
    inl = [
        (value - (codes[0] + index * endpoint_lsb)) / endpoint_lsb
        for index, value in enumerate(codes)
    ]
    lower = min(codes[7], codes[8])
    upper = max(codes[7], codes[8])
    glitch_min = values["glitch_7_to_8_min"]
    glitch_max = values["glitch_7_to_8_max"]
    glitch_outside_lsb = max(lower - glitch_min, glitch_max - upper, 0.0) / endpoint_lsb
    return {
        "code_voltages_v": codes,
        "endpoint_lsb_v": endpoint_lsb,
        "monotonic": all(step > 0.0 for step in steps),
        "dnl_lsb": dnl,
        "inl_lsb": inl,
        "max_abs_dnl_lsb": max(abs(value) for value in dnl),
        "max_abs_inl_lsb": max(abs(value) for value in inl),
        "major_carry_glitch_outside_endpoints_lsb": glitch_outside_lsb,
        "average_supply_current_a": -values["supply_avg"],
    }


def run_case(
    ngspice: str,
    corner: str,
    supply_v: float,
    temperature_c: float,
    load_ohm: float,
) -> dict[str, Any]:
    case_name = f"{corner}_{supply_v:.2f}v_{temperature_c:+.0f}c_{load_ohm:.0f}ohm"
    case_dir = BUILD_ROOT / case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    deck_path = case_dir / "r2r.spice"
    log_path = case_dir / "ngspice.log"
    deck_path.write_text(
        spice_deck(corner, supply_v, temperature_c, load_ohm),
        encoding="utf-8",
    )
    result = subprocess.run(
        [ngspice, "-b", "-o", str(log_path), str(deck_path)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ngspice failed for {case_name}:\n{result.stdout}\n{result.stderr}\n"
            f"{log_path.read_text(encoding='utf-8', errors='replace')}"
        )
    values = parse_measures(log_path.read_text(encoding="utf-8", errors="replace"))
    analysis = analyze_values(values)
    analysis.update(
        {
            "name": case_name,
            "corner": corner,
            "supply_v": supply_v,
            "temperature_c": temperature_c,
            "load_ohm": load_ohm,
        }
    )
    return analysis


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    for case in cases:
        if not case["monotonic"]:
            failures.append(f"{case['name']}: non-monotonic")
        if case["load_ohm"] >= 1.0e6 and case["max_abs_dnl_lsb"] > 0.50:
            failures.append(
                f"{case['name']}: DNL {case['max_abs_dnl_lsb']:.3f} LSB exceeds 0.50"
            )
        if case["load_ohm"] >= 1.0e6 and case["max_abs_inl_lsb"] > 0.50:
            failures.append(
                f"{case['name']}: INL {case['max_abs_inl_lsb']:.3f} LSB exceeds 0.50"
            )
    return {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "case_count": len(cases),
        "unit_resistor_nominal_ohm": 10600.0,
        "driver_skew_increment_ps": 50.0,
        "load_capacitance_f": 200.0e-15,
        "worst_abs_dnl_lsb": max(case["max_abs_dnl_lsb"] for case in cases),
        "worst_abs_inl_lsb": max(case["max_abs_inl_lsb"] for case in cases),
        "worst_major_carry_glitch_outside_endpoints_lsb": max(
            case["major_carry_glitch_outside_endpoints_lsb"] for case in cases
        ),
        "cases": cases,
    }


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

    if args.full:
        corners = ("tt", "ff", "ss")
        supplies = (1.62, 1.80, 1.98)
        temperatures = (-40.0, 27.0, 85.0)
        loads = (1.0e6, 1.0e5)
    else:
        corners = ("tt",)
        supplies = (1.80,)
        temperatures = (27.0,)
        loads = (1.0e6, 1.0e5)

    cases = [
        run_case(args.ngspice, corner, supply, temperature, load)
        for corner in corners
        for supply in supplies
        for temperature in temperatures
        for load in loads
    ]
    summary = summarize(cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
