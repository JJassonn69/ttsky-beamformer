#!/usr/bin/env python3
"""Run the V3 Gate-2A one-channel SKY130 vector-modulator sweep."""

from __future__ import annotations

import argparse
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
MODEL_DIR = ROOT / "v3/model"
sys.path.insert(0, str(MODEL_DIR))

from beamformer_v3 import phase_table, unpack_group_codes, vector_from_word  # noqa: E402


BUILD = ROOT / "build/v3/one_channel_vector"
MEASURE_RE = re.compile(
    r"^(tone_i_avg|tone_q_avg|output_cm_avg|supply_avg|vbias_avg|tail_min|"
    r"tail_max|gm_p_vds_min|gm_n_vds_min)\s*=\s*([-+0-9.eE]+)",
    re.MULTILINE,
)
COMPLIANCE_RE = re.compile(
    r"^(ilow|ihigh|compliance_vbias)\s*=\s*([-+0-9.eE]+)", re.MULTILINE
)
AXIS_LO_PAIR = {
    0: ("lo0", "lo180"),
    1: ("lo90", "lo270"),
    2: ("lo180", "lo0"),
    3: ("lo270", "lo90"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wrap_phase_deg(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def deck(
    word: int, bias: str, process: str, supply_v: float,
    temperature_c: float, common_mode_v: float, switch_width_um: float,
    input_peak_v: float, output_capacitance_pf: float,
) -> str:
    group_nodes = [
        node
        for code in unpack_group_codes(word)
        for node in AXIS_LO_PAIR[code]
    ]
    if bias == "mos":
        bias_circuit = """RBIAS vdd vbias 10.5k
XBIAS_REF vbias vbias 0 0 sky130_fd_pr__nfet_01v8 w=32 l=0.50
CBIAS vbias 0 2p"""
        channel = (
            f"XCHANNEL sig ref {' '.join(group_nodes)} outp outn vbias 0 "
            f"v3_vector_channel_15_mos params: wsw={switch_width_um:.12g}"
        )
        bias_measures = """.measure tran vbias_avg avg v(vbias) from=12u to=20u
.measure tran tail_min min v(xchannel.xg0_0.tail) from=12u to=20u
.measure tran tail_max max v(xchannel.xg0_0.tail) from=12u to=20u
BGM_P_VDS gm_p_vds 0 v=v(xchannel.xg0_0.gm_p)-v(xchannel.xg0_0.tail)
BGM_N_VDS gm_n_vds 0 v=v(xchannel.xg0_0.gm_n)-v(xchannel.xg0_0.tail)
.measure tran gm_p_vds_min min v(gm_p_vds) from=12u to=20u
.measure tran gm_n_vds_min min v(gm_n_vds) from=12u to=20u"""
    else:
        bias_circuit = ""
        channel = (
            f"XCHANNEL sig ref {' '.join(group_nodes)} outp outn 0 "
            f"v3_vector_channel_15 params: wsw={switch_width_um:.12g}"
        )
        bias_measures = ""
    return f"""* Generated V3 one-channel vector case, word={word}, bias={bias}.
.option scale=1e-6
.option method=gear reltol=1e-4 vabstol=1e-7 iabstol=1e-12
.temp {temperature_c:g}
.include "spice/sky130/sky130_1v8_{process}.inc"
.include "v3/spice/vector_channel_15.inc"

.param VDD={supply_v:.12g} VCM={common_mode_v:.12g} FIN=5meg FLO=4meg FOUT=1meg VINPK={input_peak_v:.12g}
VDD_SOURCE vdd 0 {{VDD}}
VSIG sig 0 sin({{VCM}} {{VINPK}} {{FIN}})
VREF ref 0 {{VCM}}
{bias_circuit}

* Quadrature square-wave roots. lo180 and lo270 are exact complements.
VLO0 lo0 0 pulse(0 {{VDD}} 10n 1n 1n 123n 250n)
BLO180 lo180 0 v={{VDD}}-v(lo0)
VLO90 lo90 0 pulse(0 {{VDD}} 72.5n 1n 1n 123n 250n)
BLO270 lo270 0 v={{VDD}}-v(lo90)

{channel}
RLOADP vdd outp 5k
RLOADN vdd outn 5k

* Tiny Tapeout worst-case path envelope and high-impedance receiver.
ROUTP outp outp_pad 500
ROUTN outn outn_pad 500
COUTP outp_pad 0 {output_capacitance_pf:.12g}p
COUTN outn_pad 0 {output_capacitance_pf:.12g}p
RINSTRP outp_pad 0 1meg
RINSTRN outn_pad 0 1meg
EDIFF differential 0 outp_pad outn_pad 1
BCM output_cm 0 v=(v(outp_pad)+v(outn_pad))/2

* Two-pole 2 MHz measurement filter, matching the V2 bench convention.
RF1 differential filt1 1k
CF1 filt1 0 79.577p
RF2 filt1 filtered 1k
CF2 filtered 0 79.577p
BTONEI tone_i 0 v=v(filtered)*cos(2*pi*FOUT*time)
BTONEQ tone_q 0 v=v(filtered)*sin(2*pi*FOUT*time)

.tran 2n 20u 10u
.measure tran tone_i_avg avg v(tone_i) from=12u to=20u
.measure tran tone_q_avg avg v(tone_q) from=12u to=20u
.measure tran output_cm_avg avg v(output_cm) from=12u to=20u
.measure tran supply_avg avg i(VDD_SOURCE) from=12u to=20u
{bias_measures}
.end
"""


def run_case(
    entry: Any,
    ngspice: str,
    bias: str,
    process: str,
    supply_v: float,
    temperature_c: float,
    common_mode_v: float,
    switch_width_um: float,
    input_peak_v: float,
    output_capacitance_pf: float,
) -> dict[str, Any]:
    vcm_tag = f"vcm_{common_mode_v:.3f}".replace(".", "p")
    wsw_tag = f"wsw_{switch_width_um:.3f}".replace(".", "p")
    vin_tag = f"vin_{input_peak_v:.4f}".replace(".", "p")
    cout_tag = f"cout_{output_capacitance_pf:.1f}p".replace(".", "p")
    case_dir = BUILD / bias / process / vcm_tag / wsw_tag / vin_tag / cout_tag / f"word_{entry.word:03d}"
    case_dir.mkdir(parents=True, exist_ok=True)
    deck_path = case_dir / "vector.spice"
    log_path = case_dir / "ngspice.log"
    deck_path.write_text(deck(
        entry.word, bias, process, supply_v, temperature_c, common_mode_v,
        switch_width_um, input_peak_v, output_capacitance_pf,
    ))
    completed = subprocess.run(
        [ngspice, "-b", "-o", str(log_path), str(deck_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    log = log_path.read_text(errors="replace") if log_path.exists() else completed.stdout
    values = {name: float(value) for name, value in MEASURE_RE.findall(log)}
    required = {"tone_i_avg", "tone_q_avg", "output_cm_avg", "supply_avg"}
    if bias == "mos":
        required.update({
            "vbias_avg", "tail_min", "tail_max", "gm_p_vds_min", "gm_n_vds_min",
        })
    if completed.returncode != 0 or set(values) != required:
        raise RuntimeError(
            f"ngspice failed for word {entry.word}: return={completed.returncode}\n"
            + "\n".join(log.splitlines()[-30:])
        )
    # For a sine-referenced waveform, <v*sin> is the real component and
    # <v*cos> is the quadrature component.
    phasor = complex(values["tone_q_avg"], values["tone_i_avg"])
    result = {
        "word": entry.word,
        "group_codes": list(entry.group_codes),
        "target_phase_deg": entry.target_phase_deg,
        "ideal_i_code": entry.i_code,
        "ideal_q_code": entry.q_code,
        "ideal_magnitude": abs(vector_from_word(entry.word)),
        "raw_phase_deg": math.degrees(math.atan2(phasor.imag, phasor.real)),
        "tone_peak_v": 2.0 * abs(phasor),
        "output_common_mode_v": values["output_cm_avg"],
        "supply_current_a": abs(values["supply_avg"]),
        "deck_sha256": sha256(deck_path),
        "log": str(log_path.relative_to(ROOT)),
    }
    if bias == "mos":
        result.update({
            "vbias_v": values["vbias_avg"],
            "tail_min_v": values["tail_min"],
            "tail_max_v": values["tail_max"],
            "minimum_gm_drain_to_tail_v": min(
                values["gm_p_vds_min"], values["gm_n_vds_min"]
            ),
        })
    return result


def run_tail_compliance(
    observed_tail_min_v: float,
    ngspice: str,
    process: str,
    supply_v: float,
    temperature_c: float,
) -> dict[str, Any]:
    """Compare sink current at the observed drain voltage with a 0.30 V reference.

    This is a more portable compliance test than trusting a simulator-specific
    internal VDSAT vector. The same gate voltage and device geometry are used
    for both sinks, so the ratio directly exposes current loss at the measured
    worst tail voltage.
    """

    case_dir = BUILD / "mos" / process / "tail_compliance"
    case_dir.mkdir(parents=True, exist_ok=True)
    deck_path = case_dir / "compliance.spice"
    log_path = case_dir / "ngspice.log"
    text = f"""* V3 MOS tail compliance at the observed one-channel minimum.
.option scale=1e-6
.temp {temperature_c:g}
.include "spice/sky130/sky130_1v8_{process}.inc"
.param VDD={supply_v:.12g}
VDD_SOURCE vdd 0 {{VDD}}
RBIAS vdd vbias 10.5k
XBIAS_REF vbias vbias 0 0 sky130_fd_pr__nfet_01v8 w=32 l=0.50
VLOW tail_low 0 {observed_tail_min_v:.12g}
VHIGH tail_high 0 0.30
XLOW tail_low vbias 0 0 sky130_fd_pr__nfet_01v8 w=2.533333333 l=0.50
XHIGH tail_high vbias 0 0 sky130_fd_pr__nfet_01v8 w=2.533333333 l=0.50
.tran 100p 2n 1n
.measure tran ilow avg i(VLOW) from=1n to=2n
.measure tran ihigh avg i(VHIGH) from=1n to=2n
.measure tran compliance_vbias avg v(vbias) from=1n to=2n
.end
"""
    deck_path.write_text(text)
    completed = subprocess.run(
        [ngspice, "-b", "-o", str(log_path), str(deck_path)], cwd=ROOT,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=60, check=False,
    )
    log = log_path.read_text(errors="replace") if log_path.exists() else completed.stdout
    values = {name: abs(float(value)) for name, value in COMPLIANCE_RE.findall(log)}
    if completed.returncode != 0 or set(values) != {"ilow", "ihigh", "compliance_vbias"}:
        raise RuntimeError(
            f"tail compliance failed: return={completed.returncode}\n"
            + "\n".join(log.splitlines()[-30:])
        )
    return {
        "observed_tail_min_v": observed_tail_min_v,
        "reference_drain_v": 0.30,
        "current_at_observed_tail_a": values["ilow"],
        "current_at_reference_a": values["ihigh"],
        "current_fraction": values["ilow"] / values["ihigh"],
        "vbias_v": values["compliance_vbias"],
        "deck_sha256": sha256(deck_path),
        "log": str(log_path.relative_to(ROOT)),
    }


def analyze(
    cases: list[dict[str, Any]], state_count: int, ngspice: str, bias: str,
    process: str, supply_v: float, temperature_c: float,
    common_mode_v: float,
    switch_width_um: float,
    input_peak_v: float,
    output_capacitance_pf: float,
) -> dict[str, Any]:
    cases.sort(key=lambda item: item["target_phase_deg"])
    reference_phase = cases[0]["raw_phase_deg"]
    for case in cases:
        case["relative_phase_deg"] = (
            wrap_phase_deg(case["raw_phase_deg"] - reference_phase) % 360.0
        )
        case["phase_error_deg"] = wrap_phase_deg(
            case["relative_phase_deg"] - case["target_phase_deg"]
        )
    peaks = [case["tone_peak_v"] for case in cases]
    phase_errors = [abs(case["phase_error_deg"]) for case in cases]
    currents = [case["supply_current_a"] for case in cases]
    span_db = 20.0 * math.log10(max(peaks) / min(peaks))
    current_spread_percent = 100.0 * (max(currents) - min(currents)) / (
        sum(currents) / len(currents)
    )
    compliance = None
    if bias == "mos":
        compliance = run_tail_compliance(
            min(case["tail_min_v"] for case in cases), ngspice, process,
            supply_v, temperature_c,
        )
    gate = {
        "all_cases_completed": len(cases) == state_count,
        "worst_phase_error_deg_at_most_6": max(phase_errors) <= 6.0,
        "tone_span_db_at_most_1": span_db <= 1.0,
        "output_common_mode_has_0p8_v_floor_and_0p05_v_rail_clearance": all(
            0.8 <= case["output_common_mode_v"] <= supply_v - 0.05 for case in cases
        ),
        "supply_current_spread_percent_at_most_1": current_spread_percent <= 1.0,
    }
    if bias == "mos":
        gate.update({
            "tail_current_compliance_at_least_95_percent": (
                compliance is not None and compliance["current_fraction"] >= 0.95
            ),
            "minimum_commutating_gm_drain_to_tail_at_least_0p02_v": min(
                case["minimum_gm_drain_to_tail_v"] for case in cases
            ) >= 0.02,
        })
    return {
        "status": "pass" if all(gate.values()) else "fail",
        "gate": gate,
        "state_count": state_count,
        "worst_phase_error_deg": max(phase_errors),
        "tone_peak_span_db": span_db,
        "tone_peak_range_v": [min(peaks), max(peaks)],
        "output_common_mode_range_v": [
            min(case["output_common_mode_v"] for case in cases),
            max(case["output_common_mode_v"] for case in cases),
        ],
        "supply_current_range_a": [min(currents), max(currents)],
        "supply_current_spread_percent": current_spread_percent,
        "tail_compliance": compliance,
        "bias": bias,
        "corner": {
            "process": process,
            "supply_v": supply_v,
            "temperature_c": temperature_c,
            "input_common_mode_v": common_mode_v,
            "switch_width_um": switch_width_um,
            "input_peak_v": input_peak_v,
            "output_capacitance_pf_per_pad": output_capacitance_pf,
        },
        "limitations": [
            "one deterministic PVT corner per report",
            (
                "resistor-referenced matched MOS tail sinks"
                if bias == "mos"
                else "ideal equal tail-current sources isolate vector weighting from bias design"
            ),
            "hard-wired static group phases; selector timing is a later gate",
            "schematic devices without layout parasitics or mismatch",
        ],
        "inputs": {
            "vector_cell": "v3/spice/vector_channel_15.inc",
            "vector_cell_sha256": sha256(ROOT / "v3/spice/vector_channel_15.inc"),
            "model": "v3/model/beamformer_v3.py",
            "model_sha256": sha256(ROOT / "v3/model/beamformer_v3.py"),
            "ngspice": ngspice_version(ngspice),
        },
        "cases": cases,
    }


def ngspice_version(ngspice: str) -> str:
    completed = subprocess.run(
        [ngspice, "--version"], text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return lines[0] if lines else "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", type=int, choices=(8, 16), default=8)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--bias", choices=("ideal", "mos"), default="ideal")
    parser.add_argument("--process", choices=("tt", "ff", "ss", "sf", "fs"), default="tt")
    parser.add_argument("--supply", type=float, default=1.8)
    parser.add_argument("--temperature", type=float, default=27.0)
    parser.add_argument("--common-mode", type=float, default=1.2)
    parser.add_argument("--switch-width", type=float, default=0.65)
    parser.add_argument("--input-peak", type=float, default=0.005)
    parser.add_argument("--output-capacitance-pf", type=float, default=10.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--jobs", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    entries = phase_table(args.states)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        cases = list(pool.map(
            lambda entry: run_case(
                entry, args.ngspice, args.bias, args.process,
                args.supply, args.temperature, args.common_mode, args.switch_width,
                args.input_peak, args.output_capacitance_pf,
            ),
            entries,
        ))
    report = analyze(
        cases, args.states, args.ngspice, args.bias, args.process,
        args.supply, args.temperature, args.common_mode, args.switch_width,
        args.input_peak, args.output_capacitance_pf,
    )
    vcm_tag = f"vcm_{args.common_mode:.3f}".replace(".", "p")
    wsw_tag = f"wsw_{args.switch_width:.3f}".replace(".", "p")
    vin_tag = f"vin_{args.input_peak:.4f}".replace(".", "p")
    cout_tag = f"cout_{args.output_capacitance_pf:.1f}p".replace(".", "p")
    default_output = BUILD / args.bias / args.process / vcm_tag / wsw_tag / vin_tag / cout_tag / "summary.json"
    requested_output = args.output or default_output
    output = requested_output if requested_output.is_absolute() else ROOT / requested_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    keys = (
        "status", "worst_phase_error_deg", "tone_peak_span_db",
        "tone_peak_range_v", "output_common_mode_range_v",
        "supply_current_range_a", "supply_current_spread_percent", "gate",
    )
    print(json.dumps({key: report[key] for key in keys}, indent=2, sort_keys=True))
    print(f"report={output.relative_to(ROOT)}")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
