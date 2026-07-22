#!/usr/bin/env python3
"""Size and verify the passive R-2R-to-tail-current trim interface."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = PROJECT_ROOT / "build" / "v2" / "trim_interface"
MODEL_ROOT = PROJECT_ROOT / "third_party" / "sky130_fd_pr"

MEASURE_RE = re.compile(
    r"^(vgate|vbias|itail)_(?:code_)?([0-9]|1[0-5])\s*=\s*([-+0-9.eE]+)",
    re.MULTILINE,
)


def spice_deck(
    corner: str,
    supply_v: float,
    temperature_c: float,
    attenuation_units: int,
) -> str:
    measures = []
    for code in range(16):
        time_us = code + 0.75
        measures.extend(
            (
                f".measure tran vgate_code_{code} find v(vgate) at={time_us:.2f}u",
                f".measure tran vbias_code_{code} find v(vbias) at={time_us:.2f}u",
                f".measure tran itail_code_{code} find i(VTAIL) at={time_us:.2f}u",
            )
        )
    attenuation = "\n".join(
        f"XATT{index} att{index} att{index + 1} 0 v2_r_unit"
        for index in range(attenuation_units)
    )
    return f"""* Generated V2 tail-current trim-interface characterization.
.option scale=1e-6
.option method=gear
.temp {temperature_c}
.include "spice/sky130/sky130_1v8_{corner}.inc"
.include "spice/sky130/sky130_passives_tt.inc"
.include "v2/spice/r2r_4bit.inc"

.param VDD_VALUE={supply_v}
VDD vdd 0 {{VDD_VALUE}}

* Reuse the V1 resistor-referenced bias so the experiment measures the
* incremental trim around the inherited operating point.
XRB vdd vbias 0 v2_r_unit
XBIASA vbias vbias 0 0 sky130_fd_pr__nfet_01v8 w=16 l=0.50
XBIASB vbias vbias 0 0 sky130_fd_pr__nfet_01v8 w=16 l=0.50

* Binary count 0..15 through the real matched DAC bit drivers.
VB0 in0 0 pulse(0 {{VDD_VALUE}} 1u 100p 100p 1u 2u)
VB1 in1 0 pulse(0 {{VDD_VALUE}} 2.00005u 100p 100p 2u 4u)
VB2 in2 0 pulse(0 {{VDD_VALUE}} 4.00010u 100p 100p 4u 8u)
VB3 in3 0 pulse(0 {{VDD_VALUE}} 8.00015u 100p 100p 8u 16u)
XD0 in0 b0 vdd 0 v2_dac_bit_driver
XD1 in1 b1 vdd 0 v2_dac_bit_driver
XD2 in2 b2 vdd 0 v2_dac_bit_driver
XD3 in3 b3 vdd 0 v2_dac_bit_driver
XDAC b0 b1 b2 b3 dac_out 0 v2_r2r_4bit

* A short, well-matched resistor chain attenuates the full-supply DAC range.
* The compact bias-side resistor anchors the tail gate at the shared V1 bias.
* The DAC is static during reception, so no active analog buffer is required.
RBIAS_BLEND vbias vgate 1000
RATT_START dac_out att0 0.001
{attenuation}
RATT_END att{attenuation_units} vgate 0.001
CLOCAL vgate 0 200f

XTAIL tail vgate 0 0 sky130_fd_pr__nfet_01v8 w=38 l=0.50
VTAIL tail 0 0.15

.tran 2n 15.95u
{chr(10).join(measures)}
.end
"""


def parse_measures(log_text: str) -> dict[str, list[float]]:
    values: dict[str, dict[int, float]] = {"vgate": {}, "vbias": {}, "itail": {}}
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


def analyze(values: dict[str, list[float]], attenuation_units: int) -> dict[str, Any]:
    currents = [abs(value) for value in values["itail"]]
    nominal = currents[8]
    relative = [value / nominal for value in currents]
    steps = [relative[index + 1] - relative[index] for index in range(15)]
    target_low = 0.85
    target_high = 1.15
    endpoint_error = max(abs(relative[0] - target_low), abs(relative[-1] - target_high))
    return {
        "attenuation_units": attenuation_units,
        "attenuation_nominal_ohm": attenuation_units * 10600.0,
        "bias_anchor_nominal_ohm": 1000.0,
        "vgate_v": values["vgate"],
        "vbias_v": values["vbias"],
        "tail_current_a": currents,
        "relative_tail_current": relative,
        "monotonic": all(step > 0.0 for step in steps),
        "minimum_relative_step": min(steps),
        "code_0_relative": relative[0],
        "code_8_relative": relative[8],
        "code_15_relative": relative[15],
        "endpoint_target_error": endpoint_error,
    }


def run_case(
    ngspice: str,
    corner: str,
    supply_v: float,
    temperature_c: float,
    attenuation_units: int,
) -> dict[str, Any]:
    case_name = (
        f"u{attenuation_units}_{corner}_{supply_v:.2f}v_"
        f"{temperature_c:+.0f}c"
    )
    case_dir = BUILD_ROOT / case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    deck_path = case_dir / "trim_interface.spice"
    log_path = case_dir / "ngspice.log"
    deck_path.write_text(
        spice_deck(corner, supply_v, temperature_c, attenuation_units),
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
        log = log_path.read_text(encoding="utf-8", errors="replace")
        raise RuntimeError(
            f"ngspice failed for {case_name}:\n{result.stdout}\n{result.stderr}\n{log}"
        )
    values = parse_measures(log_path.read_text(encoding="utf-8", errors="replace"))
    analysis = analyze(values, attenuation_units)
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
    parser.add_argument("--attenuation-units", type=int)
    parser.add_argument("--output", type=Path, default=BUILD_ROOT / "summary.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not shutil.which(args.ngspice):
        raise SystemExit(f"ngspice not found: {args.ngspice}")
    if not MODEL_ROOT.exists():
        raise SystemExit(f"SKY130 primitive models not found: {MODEL_ROOT}")

    if args.attenuation_units is None:
        candidate_units = tuple(range(1, 9))
        conditions = (("tt", 1.80, 27.0),)
    elif args.full:
        candidate_units = (args.attenuation_units,)
        conditions = tuple(
            (corner, supply, temperature)
            for corner in ("tt", "ff", "ss")
            for supply in (1.62, 1.80, 1.98)
            for temperature in (-40.0, 27.0, 85.0)
        )
    else:
        candidate_units = (args.attenuation_units,)
        conditions = (("tt", 1.80, 27.0),)

    cases = [
        run_case(args.ngspice, corner, supply, temperature, units)
        for units in candidate_units
        for corner, supply, temperature in conditions
    ]
    selected_units = min(
        candidate_units,
        key=lambda units: max(
            case["endpoint_target_error"]
            for case in cases
            if case["attenuation_units"] == units
        ),
    )
    failures = [case["name"] for case in cases if not case["monotonic"]]
    summary = {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "architecture": "passive bias-anchored R-2R voltage blend",
        "selected_attenuation_units": selected_units,
        "case_count": len(cases),
        "worst_code_0_relative": min(case["code_0_relative"] for case in cases),
        "worst_code_15_relative": max(case["code_15_relative"] for case in cases),
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
