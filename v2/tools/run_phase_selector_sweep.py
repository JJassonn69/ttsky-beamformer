#!/usr/bin/env python3
"""Characterize the symmetric standard-cell V2 four-phase selector."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = PROJECT_ROOT / "build" / "v2" / "phase_selector"
MODEL_ROOT = PROJECT_ROOT / "third_party" / "sky130_fd_pr"
MEASURE_RE = re.compile(r"^([a-z][a-z0-9_]*)\s*=\s*([-+0-9.eE]+)", re.MULTILINE)


def phase_source(name: str, node: str, delay_s: float, period_s: float) -> str:
    rise_s = min(500.0e-12, period_s / 100.0)
    high_s = period_s / 2.0 - rise_s
    return (
        f"V{name} {node} 0 pulse(0 {{VDD_VALUE}} {delay_s} "
        f"{rise_s} {rise_s} {high_s} {period_s})"
    )


def spice_deck(
    corner: str,
    supply_v: float,
    temperature_c: float,
    frequency_hz: float,
) -> str:
    period_s = 1.0 / frequency_hz
    window_s = 8.0 * period_s
    stop_s = 32.0 * period_s
    half = supply_v / 2.0
    sources = "\n".join(
        (
            phase_source("LO0", "lo0", 0.0, period_s),
            phase_source("LO90", "lo90", period_s / 4.0, period_s),
            phase_source("LO180", "lo180", period_s / 2.0, period_s),
            phase_source("LO270", "lo270", 3.0 * period_s / 4.0, period_s),
        )
    )
    phase_nodes = ("lo0", "lo90", "lo180", "lo270")
    measures: list[str] = []
    for code in range(4):
        start_s = code * window_s + 2.0 * period_s
        end_s = start_s + 2.0 * period_s
        pnode = phase_nodes[code]
        nnode = phase_nodes[(code + 2) % 4]
        measures.extend(
            (
                f".measure tran p_rise_delay_{code} trig v({pnode}) val={half} rise=1 td={start_s} targ v(lop) val={half} rise=1 td={start_s}",
                f".measure tran n_rise_delay_{code} trig v({nnode}) val={half} rise=1 td={start_s} targ v(lon) val={half} rise=1 td={start_s}",
                f".measure tran p_fall_delay_{code} trig v({pnode}) val={half} fall=1 td={start_s} targ v(lop) val={half} fall=1 td={start_s}",
                f".measure tran n_fall_delay_{code} trig v({nnode}) val={half} fall=1 td={start_s} targ v(lon) val={half} fall=1 td={start_s}",
                f".measure tran p_high_{code} trig v(lop) val={half} rise=1 td={start_s} targ v(lop) val={half} fall=1 td={start_s}",
                f".measure tran p_period_{code} trig v(lop) val={half} rise=1 td={start_s} targ v(lop) val={half} rise=2 td={start_s}",
                f".measure tran n_high_{code} trig v(lon) val={half} rise=1 td={start_s} targ v(lon) val={half} fall=1 td={start_s}",
                f".measure tran n_period_{code} trig v(lon) val={half} rise=1 td={start_s} targ v(lon) val={half} rise=2 td={start_s}",
                f".measure tran overlap_time_{code} integ v(overlap) from={start_s} to={end_s}",
                f".measure tran dead_time_{code} integ v(dead) from={start_s} to={end_s}",
                f".measure tran lop_min_{code} min v(lop) from={start_s} to={end_s}",
                f".measure tran lop_max_{code} max v(lop) from={start_s} to={end_s}",
                f".measure tran lon_min_{code} min v(lon) from={start_s} to={end_s}",
                f".measure tran lon_max_{code} max v(lon) from={start_s} to={end_s}",
            )
        )
    return f"""* Generated V2 four-phase-selector characterization.
.option scale=1e-6
.option method=gear
.temp {temperature_c}
.include "spice/sky130/sky130_1v8_{corner}.inc"
.include "third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__{corner}.corner.spice"
.include "third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__mismatch.corner.spice"
.include "v2/spice/phase_selector.inc"

.param VDD_VALUE={supply_v}
VDD vdd 0 {{VDD_VALUE}}
{sources}

* Binary phase-code sequence 00, 01, 10, 11; eight LO cycles per code.
VPH0 phase0 0 pulse(0 {{VDD_VALUE}} {window_s} 100p 100p {window_s} {2.0*window_s})
VPH1 phase1 0 pulse(0 {{VDD_VALUE}} {2.0*window_s} 100p 100p {2.0*window_s} {4.0*window_s})
VEN enable 0 {{VDD_VALUE}}

XSELECT lo0 lo90 lo180 lo270 phase0 phase1 enable lop lon vdd 0 v2_phase_selector

* Each output drives four representative 8 um mixer-gate loads plus local
* routed capacitance.  Drain/source are grounded only to expose gate loading.
XLP0 0 lop 0 0 sky130_fd_pr__nfet_01v8 w=8 l=0.15
XLP1 0 lop 0 0 sky130_fd_pr__nfet_01v8 w=8 l=0.15
XLP2 0 lop 0 0 sky130_fd_pr__nfet_01v8 w=8 l=0.15
XLP3 0 lop 0 0 sky130_fd_pr__nfet_01v8 w=8 l=0.15
XLN0 0 lon 0 0 sky130_fd_pr__nfet_01v8 w=8 l=0.15
XLN1 0 lon 0 0 sky130_fd_pr__nfet_01v8 w=8 l=0.15
XLN2 0 lon 0 0 sky130_fd_pr__nfet_01v8 w=8 l=0.15
XLN3 0 lon 0 0 sky130_fd_pr__nfet_01v8 w=8 l=0.15
CROUTE_P lop 0 100f
CROUTE_N lon 0 100f

BOVER overlap 0 v={{u(v(lop)-{half})*u(v(lon)-{half})}}
BDEAD dead 0 v={{u({half}-v(lop))*u({half}-v(lon))}}

.tran {period_s/500.0} {stop_s}
{chr(10).join(measures)}
.end
"""


def parse_measures(log_text: str) -> dict[str, float]:
    return {name: float(value) for name, value in MEASURE_RE.findall(log_text)}


def analyze(values: dict[str, float], frequency_hz: float) -> dict[str, Any]:
    period_s = 1.0 / frequency_hz
    codes: list[dict[str, Any]] = []
    for code in range(4):
        required = [
            f"{prefix}_{code}"
            for prefix in (
                "p_rise_delay", "n_rise_delay", "p_fall_delay", "n_fall_delay",
                "p_high", "p_period", "n_high", "n_period", "overlap_time",
                "dead_time", "lop_min", "lop_max", "lon_min", "lon_max",
            )
        ]
        missing = [name for name in required if name not in values]
        if missing:
            raise RuntimeError(f"ngspice log is missing measurements: {missing}")
        p_rise = values[f"p_rise_delay_{code}"]
        n_rise = values[f"n_rise_delay_{code}"]
        p_fall = values[f"p_fall_delay_{code}"]
        n_fall = values[f"n_fall_delay_{code}"]
        p_duty = values[f"p_high_{code}"] / values[f"p_period_{code}"]
        n_duty = values[f"n_high_{code}"] / values[f"n_period_{code}"]
        # If the analysis window opens while a complementary output is high,
        # ngspice can report the first fall before the subsequently counted
        # rise as a negative interval.  Add one measured period to recover the
        # physical high time without changing the underlying edge data.
        if p_duty < 0.0:
            p_duty += 1.0
        if n_duty < 0.0:
            n_duty += 1.0
        codes.append(
            {
                "code": code,
                "p_rise_delay_s": p_rise,
                "n_rise_delay_s": n_rise,
                "p_fall_delay_s": p_fall,
                "n_fall_delay_s": n_fall,
                "rise_skew_s": abs(p_rise - n_rise),
                "fall_skew_s": abs(p_fall - n_fall),
                "p_duty_cycle": p_duty,
                "n_duty_cycle": n_duty,
                "duty_mismatch": abs(p_duty - n_duty),
                "overlap_fraction": values[f"overlap_time_{code}"] / (2.0 * period_s),
                "dead_fraction": values[f"dead_time_{code}"] / (2.0 * period_s),
                "lop_min_v": values[f"lop_min_{code}"],
                "lop_max_v": values[f"lop_max_{code}"],
                "lon_min_v": values[f"lon_min_{code}"],
                "lon_max_v": values[f"lon_max_{code}"],
            }
        )
    return {"codes": codes}


def run_case(
    ngspice: str,
    corner: str,
    supply_v: float,
    temperature_c: float,
    frequency_hz: float,
) -> dict[str, Any]:
    case_name = f"{corner}_{supply_v:.2f}v_{temperature_c:+.0f}c_{frequency_hz/1e6:.0f}mhz"
    case_dir = BUILD_ROOT / case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    deck_path = case_dir / "phase_selector.spice"
    log_path = case_dir / "ngspice.log"
    deck_path.write_text(
        spice_deck(corner, supply_v, temperature_c, frequency_hz), encoding="utf-8"
    )
    result = subprocess.run(
        [ngspice, "-b", "-o", str(log_path), str(deck_path)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        log = log_path.read_text(encoding="utf-8", errors="replace")
        raise RuntimeError(
            f"ngspice failed for {case_name}:\n{result.stdout}\n{result.stderr}\n{log}"
        )
    analysis = analyze(
        parse_measures(log_path.read_text(encoding="utf-8", errors="replace")),
        frequency_hz,
    )
    analysis.update(
        {
            "name": case_name,
            "corner": corner,
            "supply_v": supply_v,
            "temperature_c": temperature_c,
            "frequency_hz": frequency_hz,
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

    if args.full:
        conditions = tuple(
            (corner, supply, temperature, frequency)
            for corner in ("tt", "ff", "ss", "fs", "sf")
            for supply, temperature in ((1.62, 85.0), (1.80, 27.0), (1.98, -40.0))
            for frequency in (4.0e6, 30.0e6)
        )
    else:
        conditions = (
            ("tt", 1.80, 27.0, 4.0e6),
            ("tt", 1.80, 27.0, 30.0e6),
        )
    cases = [run_case(args.ngspice, *condition) for condition in conditions]
    code_results = [code for case in cases for code in case["codes"]]
    failures: list[str] = []
    for case in cases:
        period_s = 1.0 / case["frequency_hz"]
        for code in case["codes"]:
            label = f"{case['name']}/code{code['code']}"
            if max(code["rise_skew_s"], code["fall_skew_s"]) > 100.0e-12:
                failures.append(f"{label}: P/N skew exceeds 100 ps")
            if max(abs(code["p_duty_cycle"] - 0.5), abs(code["n_duty_cycle"] - 0.5)) > 0.03:
                failures.append(f"{label}: duty cycle error exceeds 3%")
            if code["overlap_fraction"] > max(0.03, 1.0e-9 / period_s):
                failures.append(f"{label}: simultaneous-high overlap is excessive")
            if min(code["lop_max_v"], code["lon_max_v"]) < 0.8 * case["supply_v"]:
                failures.append(f"{label}: output high level is too low")
            if max(code["lop_min_v"], code["lon_min_v"]) > 0.2 * case["supply_v"]:
                failures.append(f"{label}: output low level is too high")
    summary = {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "architecture": "shared-first-stage symmetric dual 4:1 mux plus matched gate/buffer",
        "case_count": len(cases),
        "worst_rise_skew_ps": 1.0e12 * max(code["rise_skew_s"] for code in code_results),
        "worst_fall_skew_ps": 1.0e12 * max(code["fall_skew_s"] for code in code_results),
        "worst_duty_mismatch_percent": 100.0 * max(code["duty_mismatch"] for code in code_results),
        "worst_overlap_percent": 100.0 * max(code["overlap_fraction"] for code in code_results),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
