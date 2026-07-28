#!/usr/bin/env python3
"""Measure every ordered blanked V3 phase-code transition on the SKY130 MOS cell.

The analog cell and bias pass/pulldown pair are transistor-level.  Group
selection and the voltages driving the real bias switch are deliberately
behavioral controls in this pre-layout gate, so the result bounds analog
recovery after the digital controller has generated valid, non-overlapping
controls; it does not include selector-cell or route RC.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/model"))

from beamformer_v3 import phase_table, unpack_group_codes  # noqa: E402


BUILD = ROOT / "build/v3/transition_settling"
AXIS_LO_PAIR = {
    0: ("lo0", "lo180"),
    1: ("lo90", "lo270"),
    2: ("lo180", "lo0"),
    3: ("lo270", "lo90"),
}
BLANK_START_US = 20.0
UPDATE_US = 20.25
SELECTOR_EDGE_NS = 5.0
EDGE_END_US = UPDATE_US + SELECTOR_EDGE_NS / 1000.0
STOP_US = 25.25
WINDOWS_US = (
    ("pre", 18.0, 20.0),
    ("post_1us", 20.25, 21.25),
    ("post_2us", 21.25, 22.25),
    ("post_3us", 22.25, 23.25),
    ("final", 23.25, 25.25),
)
MEASURE_RE = re.compile(r"^([a-z0-9_]+)\s*=\s*([-+0-9.eE]+)", re.MULTILINE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wrapped_phase_error_deg(actual: float, target: float) -> float:
    return (actual - target + 180.0) % 360.0 - 180.0


def switched_node(group: int, side: str, old_word: int, new_word: int) -> str:
    index = 0 if side == "p" else 1
    old = AXIS_LO_PAIR[unpack_group_codes(old_word)[group]][index]
    new = AXIS_LO_PAIR[unpack_group_codes(new_word)[group]][index]
    return (
        f"BG{group}{side.upper()} g{group}{side} 0 "
        f"v=(time<{BLANK_START_US:g}u?v({old}):"
        f"(time<{UPDATE_US:g}u?0:(time<{EDGE_END_US:g}u?"
        f"v({new})*(time-{UPDATE_US:g}u)/{SELECTOR_EDGE_NS:g}n:v({new}))))"
    )


def deck(old_word: int, new_word: int) -> str:
    controls = "\n".join(
        switched_node(group, side, old_word, new_word)
        for group in range(4)
        for side in ("p", "n")
    )
    measures: list[str] = []
    for name, start, stop in WINDOWS_US:
        measures.extend((
            f".measure tran tone_i_{name} avg v(tone_i) from={start:g}u to={stop:g}u",
            f".measure tran tone_q_{name} avg v(tone_q) from={start:g}u to={stop:g}u",
            f".measure tran cm_{name} avg v(output_cm) from={start:g}u to={stop:g}u",
        ))
    measures.extend((
        f".measure tran cm_min_transition min v(output_cm) from={BLANK_START_US:g}u to=22.25u",
        f".measure tran cm_max_transition max v(output_cm) from={BLANK_START_US:g}u to=22.25u",
        f".measure tran outp_min_transition min v(outp_pad) from={BLANK_START_US:g}u to=22.25u",
        f".measure tran outp_max_transition max v(outp_pad) from={BLANK_START_US:g}u to=22.25u",
        f".measure tran outn_min_transition min v(outn_pad) from={BLANK_START_US:g}u to=22.25u",
        f".measure tran outn_max_transition max v(outn_pad) from={BLANK_START_US:g}u to=22.25u",
        f".measure tran bias_min_transition min v(vbias_ch) from={BLANK_START_US:g}u to=22.25u",
        f".measure tran bias_max_transition max v(vbias_ch) from={BLANK_START_US:g}u to=22.25u",
    ))
    return f"""* V3 blanked code transition 0x{old_word:02x} -> 0x{new_word:02x}.
.option scale=1e-6
.option method=gear reltol=1e-4 vabstol=1e-7 iabstol=1e-12
.temp 27
.include "spice/sky130/sky130_1v8_tt.inc"
.include "v3/spice/vector_channel_15.inc"

.param VDD=1.8 VCM=1.2 FIN=5meg FOUT=1meg VINPK=5m
VDD_SOURCE vdd 0 {{VDD}}
VSIG sig 0 sin({{VCM}} {{VINPK}} {{FIN}})
VREF ref 0 {{VCM}}
RBIAS vdd vbias 10.5k
XBIAS_REF vbias vbias 0 0 sky130_fd_pr__nfet_01v8 w=64 l=1.00
CBIAS vbias 0 2p

VLO0 lo0 0 pulse(0 {{VDD}} 10n 1n 1n 123n 250n)
BLO180 lo180 0 v={{VDD}}-v(lo0)
VLO90 lo90 0 pulse(0 {{VDD}} 72.5n 1n 1n 123n 250n)
BLO270 lo270 0 v={{VDD}}-v(lo90)

* Mandatory safe update: all LO gates are low and a real NMOS bias switch
* discharges the channel tail-gate bus for one complete 4 MHz LO period.  The
* shared reference remains undisturbed.
{controls}
BBIAS_ENABLE bias_enable 0 v=(time<{BLANK_START_US:g}u?VDD:(time<{UPDATE_US:g}u?0:(time<{EDGE_END_US:g}u?VDD*(time-{UPDATE_US:g}u)/{SELECTOR_EDGE_NS:g}n:VDD)))
BBIAS_BLANK bias_blank 0 v=(time<{BLANK_START_US:g}u?0:(time<{UPDATE_US:g}u?VDD:0))
XBIAS_GATE vbias bias_enable bias_blank vbias_ch 0 v3_bias_blank_switch

XCHANNEL sig ref g0p g0n g1p g1n g2p g2n g3p g3n outp outn vbias_ch 0 v3_vector_channel_15_mos
RLOADP vdd outp 5k
RLOADN vdd outn 5k
ROUTP outp outp_pad 500
ROUTN outn outn_pad 500
COUTP outp_pad 0 10p
COUTN outn_pad 0 10p
RINSTRP outp_pad 0 1meg
RINSTRN outn_pad 0 1meg
EDIFF differential 0 outp_pad outn_pad 1
BCM output_cm 0 v=(v(outp_pad)+v(outn_pad))/2
BTONEI tone_i 0 v=v(differential)*cos(2*pi*FOUT*time)
BTONEQ tone_q 0 v=v(differential)*sin(2*pi*FOUT*time)

.tran 2n {STOP_US:g}u 15u
{chr(10).join(measures)}
.end
"""


def phasor(values: dict[str, float], suffix: str) -> complex:
    # Same sine reference convention as the static V3 sweep.
    return complex(values[f"tone_q_{suffix}"], values[f"tone_i_{suffix}"])


def run_case(name: str, old_word: int, new_word: int) -> dict[str, Any]:
    work = BUILD / name
    work.mkdir(parents=True, exist_ok=True)
    deck_path = work / "transition.spice"
    log_path = work / "ngspice.log"
    deck_path.write_text(deck(old_word, new_word))
    completed = subprocess.run(
        ["ngspice", "-b", "-o", str(log_path), str(deck_path)],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=240, check=False,
    )
    log = log_path.read_text(errors="replace") if log_path.exists() else completed.stdout
    values = {key: float(value) for key, value in MEASURE_RE.findall(log)}
    required = {
        f"{quantity}_{suffix}"
        for suffix, _, _ in WINDOWS_US
        for quantity in ("tone_i", "tone_q", "cm")
    } | {
        "cm_min_transition", "cm_max_transition",
        "outp_min_transition", "outp_max_transition",
        "outn_min_transition", "outn_max_transition",
        "bias_min_transition", "bias_max_transition",
    }
    if completed.returncode or not required.issubset(values):
        missing = sorted(required - values.keys())
        raise RuntimeError(
            f"transition {name} failed return={completed.returncode} missing={missing}\n"
            + "\n".join(log.splitlines()[-50:])
        )
    final = phasor(values, "final")
    windows: dict[str, Any] = {}
    first_settled_us: float | None = None
    for suffix, start, stop in WINDOWS_US:
        value = phasor(values, suffix)
        amplitude_error_percent = 100.0 * (abs(value) / abs(final) - 1.0)
        phase_error_deg = wrapped_phase_error_deg(
            math.degrees(math.atan2(value.imag, value.real)),
            math.degrees(math.atan2(final.imag, final.real)),
        )
        windows[suffix] = {
            "start_us": start,
            "stop_us": stop,
            "tone_peak_v": 2.0 * abs(value),
            "raw_phase_deg": math.degrees(math.atan2(value.imag, value.real)),
            "amplitude_error_from_final_percent": amplitude_error_percent,
            "phase_error_from_final_deg": phase_error_deg,
            "output_common_mode_v": values[f"cm_{suffix}"],
        }
        if (
            suffix.startswith("post_")
            and first_settled_us is None
            and abs(amplitude_error_percent) <= 5.0
            and abs(phase_error_deg) <= 5.0
            and abs(values[f"cm_{suffix}"] - values["cm_final"]) <= 0.010
        ):
            first_settled_us = stop - UPDATE_US
    return {
        "name": name,
        "old_word": old_word,
        "new_word": new_word,
        "old_group_codes": list(unpack_group_codes(old_word)),
        "new_group_codes": list(unpack_group_codes(new_word)),
        "first_bounded_settled_time_us": first_settled_us,
        "windows": windows,
        "transition_extrema_v": {
            key: values[key]
            for key in sorted(required)
            if key.endswith("_transition")
        },
        "deck": str(deck_path.relative_to(ROOT)),
        "deck_sha256": sha256(deck_path),
        "log": str(log_path.relative_to(ROOT)),
    }


def analyze(cases: list[dict[str, Any]]) -> dict[str, Any]:
    gate = {
        "all_56_ordered_phase_transitions_are_covered": len(cases) == 8 * 7,
        "all_transitions_settle_within_2us": all(
            case["first_bounded_settled_time_us"] is not None
            and case["first_bounded_settled_time_us"] <= 2.0
            for case in cases
        ),
        "all_output_pads_remain_within_supply_rails": all(
            0.0 <= case["transition_extrema_v"][key] <= 1.8
            for case in cases
            for key in (
                "outp_min_transition", "outp_max_transition",
                "outn_min_transition", "outn_max_transition",
            )
        ),
        "transition_common_mode_remains_within_supply_rails": all(
            case["transition_extrema_v"]["cm_min_transition"] >= 0.8
            and case["transition_extrema_v"]["cm_max_transition"] <= 1.8
            for case in cases
        ),
        "tail_gate_blank_is_observed": all(
            case["transition_extrema_v"]["bias_min_transition"] <= 1e-6
            for case in cases
        ),
    }
    return {
        "schema_version": 1,
        "status": "pass" if all(gate.values()) else "fail",
        "scope": "TT transistor-level analog cell with ideal safe-update controls; not extracted selector timing",
        "blank_duration_ns": (UPDATE_US - BLANK_START_US) * 1000.0,
        "bounded_selector_edge_ns": SELECTOR_EDGE_NS,
        "ordered_transition_count": len(cases),
        "settling_definition": "one complete 1 MHz IF window within 5% amplitude, 5 degrees phase, and 10 mV common mode of the final two-cycle window",
        "gate": gate,
        "cases": cases,
        "limitations": [
            "behavioral group-selector controls use a bounded 5 ns edge; the bias gate itself is a real MOS pass/pulldown pair",
            "no standard-cell delay, clock-route skew, package, or layout RC",
            "one nominal TT operating condition",
        ],
    }


def main() -> None:
    table = phase_table(8)
    transitions = tuple(
        (
            f"phase_{old_state * 45:03d}_to_{new_state * 45:03d}",
            table[old_state].word,
            table[new_state].word,
        )
        for old_state in range(8)
        for new_state in range(8)
        if old_state != new_state
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        cases = list(pool.map(lambda args: run_case(*args), transitions))
    report = analyze(cases)
    BUILD.mkdir(parents=True, exist_ok=True)
    output = BUILD / "summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": report["status"],
        "gate": report["gate"],
        "settled_time_us": {
            case["name"]: case["first_bounded_settled_time_us"] for case in cases
        },
    }, indent=2, sort_keys=True))
    print(f"report={output.relative_to(ROOT)}")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
