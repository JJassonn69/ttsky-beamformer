#!/usr/bin/env python3
"""Run a bounded TT two-tone linearity pilot on the V3 one-channel MOS cell."""

from __future__ import annotations

import concurrent.futures
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

import run_one_channel_vector_sweep as vector_sweep  # noqa: E402


BUILD = ROOT / "build/v3/twotone_pilot"
FREQUENCIES_MHZ = {
    "im3_low": 0.7,
    "fund_low": 0.9,
    "fund_high": 1.1,
    "im3_high": 1.3,
}
MEASURE_RE = re.compile(r"^([a-z0-9_]+)\s*=\s*([-+0-9.eE]+)", re.MULTILINE)


def twotone_deck(per_tone_peak_v: float) -> str:
    text = vector_sweep.deck(
        8, "mos", "tt", 1.8, 27.0, 1.2, 0.65,
        max(per_tone_peak_v, 1e-12), 10.0,
    )
    old_source = "VSIG sig 0 sin({VCM} {VINPK} {FIN})"
    new_source = (
        "BSIG sig 0 v={VCM+VINTONE*(sin(2*pi*F1*time)+sin(2*pi*F2*time))}"
    )
    if text.count(old_source) != 1:
        raise ValueError("one-channel source marker changed")
    text = text.replace(old_source, new_source)
    marker = ".param VDD=1.8 VCM=1.2 FIN=5meg FLO=4meg FOUT=1meg"
    parameter_lines = [line for line in text.splitlines() if line.startswith(marker)]
    if len(parameter_lines) != 1:
        raise ValueError("one-channel parameter marker changed")
    extended = parameter_lines[0] + (
        f" F1=4.9meg F2=5.1meg VINTONE={per_tone_peak_v:.12g}"
    )
    text = text.replace(parameter_lines[0], extended)

    demodulators: list[str] = []
    measures: list[str] = []
    for name, frequency_mhz in FREQUENCIES_MHZ.items():
        demodulators.extend((
            f"B{name.upper()}I {name}_i 0 v=v(differential)*cos(2*pi*{frequency_mhz:g}meg*time)",
            f"B{name.upper()}Q {name}_q 0 v=v(differential)*sin(2*pi*{frequency_mhz:g}meg*time)",
        ))
        measures.extend((
            f".measure tran {name}_i_avg avg v({name}_i) from=10u to=20u",
            f".measure tran {name}_q_avg avg v({name}_q) from=10u to=20u",
        ))
    if text.count(".tran 2n 20u 10u") != 1 or text.count("\n.end") != 1:
        raise ValueError("one-channel transient markers changed")
    text = text.replace(
        ".tran 2n 20u 10u",
        "\n".join(demodulators) + "\n.tran 2n 20u 10u",
    )
    text = text.replace("\n.end", "\n" + "\n".join(measures) + "\n.end")
    return text


def label(amplitude: float) -> str:
    return "background" if amplitude == 0.0 else f"tone_{round(amplitude * 1e3):d}mvpk"


def run_case(amplitude: float) -> dict[str, Any]:
    work = BUILD / label(amplitude)
    work.mkdir(parents=True, exist_ok=True)
    deck_path = work / "twotone.spice"
    log_path = work / "ngspice.log"
    deck_path.write_text(twotone_deck(amplitude))
    completed = subprocess.run(
        ["ngspice", "-b", "-o", str(log_path), str(deck_path)],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=180, check=False,
    )
    log = log_path.read_text(errors="replace") if log_path.exists() else completed.stdout
    values = {name: float(value) for name, value in MEASURE_RE.findall(log)}
    required = {
        f"{name}_{component}_avg"
        for name in FREQUENCIES_MHZ
        for component in ("i", "q")
    }
    if completed.returncode != 0 or not required.issubset(values):
        raise RuntimeError(
            f"two-tone case {label(amplitude)} failed\n"
            + "\n".join(log.splitlines()[-40:])
        )
    return {
        "per_tone_peak_v": amplitude,
        "measurements": {name: values[name] for name in sorted(required)},
        "deck": str(deck_path.relative_to(ROOT)),
        "log": str(log_path.relative_to(ROOT)),
    }


def complex_component(case: dict[str, Any], name: str) -> complex:
    values = case["measurements"]
    return complex(values[f"{name}_i_avg"], values[f"{name}_q_avg"])


def corrected_rms(case: dict[str, Any], background: dict[str, Any], name: str) -> float:
    return math.sqrt(2.0) * abs(
        complex_component(case, name) - complex_component(background, name)
    )


def analyze(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_amplitude = {case["per_tone_peak_v"]: case for case in cases}
    background = by_amplitude[0.0]
    points: dict[str, Any] = {}
    for amplitude in (0.010, 0.030):
        case = by_amplitude[amplitude]
        components = {
            name: corrected_rms(case, background, name)
            for name in FREQUENCIES_MHZ
        }
        fundamental = math.sqrt(components["fund_low"] * components["fund_high"])
        worst_im3 = max(components["im3_low"], components["im3_high"])
        separation_db = 20.0 * math.log10(fundamental / worst_im3)
        input_rms_dbv = 20.0 * math.log10(amplitude / math.sqrt(2.0))
        points[label(amplitude)] = {
            "components_rms_v": components,
            "fundamental_to_worst_im3_db": separation_db,
            "input_iip3_dbv_rms_per_tone": input_rms_dbv + separation_db / 2.0,
        }
    iip3_values = [point["input_iip3_dbv_rms_per_tone"] for point in points.values()]
    gate = {
        "fundamental_to_im3_at_least_20_db": min(
            point["fundamental_to_worst_im3_db"] for point in points.values()
        ) >= 20.0,
        "iip3_estimate_spread_at_most_6_db": max(iip3_values) - min(iip3_values) <= 6.0,
    }
    return {
        "schema_version": 1,
        "status": "pass" if all(gate.values()) else "fail",
        "scope": "bounded TT one-channel two-tone pilot; not extracted signoff",
        "input_tones_mhz": [4.9, 5.1],
        "output_fundamentals_mhz": [0.9, 1.1],
        "output_im3_mhz": [0.7, 1.3],
        "vector_word": 8,
        "gate": gate,
        "points": points,
        "cases": cases,
    }


def main() -> None:
    amplitudes = (0.0, 0.010, 0.030)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        cases = list(pool.map(run_case, amplitudes))
    report = analyze(cases)
    BUILD.mkdir(parents=True, exist_ok=True)
    output = BUILD / "summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "gate": report["gate"], "points": report["points"]}, indent=2, sort_keys=True))
    print(f"report={output.relative_to(ROOT)}")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
