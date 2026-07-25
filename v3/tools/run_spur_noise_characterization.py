#!/usr/bin/env python3
"""Characterize V3 schematic spurs and a bounded static noise proxy.

Transient Fourier measurements cover the periodically switched circuit.  The
ngspice noise analysis is intentionally labelled a held-LO snapshot proxy:
ordinary ``.noise`` linearizes one DC state and cannot calculate mixer noise
folding.  PSS/PNoise or an equivalent periodic-noise simulator remains a
separate pre-release requirement.
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


BUILD = ROOT / "build/v3/spur_noise"
AXIS_LO_PAIR = {
    0: ("lo0", "lo180"),
    1: ("lo90", "lo270"),
    2: ("lo180", "lo0"),
    3: ("lo270", "lo90"),
}
SPECTRAL_BINS_MHZ = tuple(range(1, 16))
MEASURE_RE = re.compile(r"^([a-z0-9_]+)\s*=\s*([-+0-9.eE]+)", re.MULTILINE)
OUTPUT_NOISE_RE = re.compile(
    r"(?:Integrated output noise|onoise_total)\s*=\s*([-+0-9.eE]+)", re.IGNORECASE
)
INPUT_NOISE_RE = re.compile(
    r"(?:Integrated input noise|inoise_total)\s*=\s*([-+0-9.eE]+)", re.IGNORECASE
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def group_nodes(word: int) -> list[str]:
    return [
        node
        for code in unpack_group_codes(word)
        for node in AXIS_LO_PAIR[code]
    ]


def transient_deck(word: int, input_peak_v: float) -> str:
    demodulators: list[str] = []
    measures: list[str] = []
    for frequency in SPECTRAL_BINS_MHZ:
        for output, node in (("diff", "differential"), ("cm", "output_cm_ac")):
            demodulators.extend((
                f"B{output.upper()}{frequency}I {output}_{frequency}_i 0 "
                f"v=v({node})*cos(2*pi*{frequency}meg*time)",
                f"B{output.upper()}{frequency}Q {output}_{frequency}_q 0 "
                f"v=v({node})*sin(2*pi*{frequency}meg*time)",
            ))
            measures.extend((
                f".measure tran {output}_{frequency}_i_avg avg v({output}_{frequency}_i) from=20u to=30u",
                f".measure tran {output}_{frequency}_q_avg avg v({output}_{frequency}_q) from=20u to=30u",
            ))
    nodes = " ".join(group_nodes(word))
    return f"""* V3 periodic spur sweep, word=0x{word:02x}, input={input_peak_v:g} Vpk.
.option scale=1e-6
.option method=gear reltol=1e-4 vabstol=1e-7 iabstol=1e-12
.temp 27
.include "spice/sky130/sky130_1v8_tt.inc"
.include "v3/spice/vector_channel_15.inc"
.param VDD=1.8 VCM=1.2 FIN=5meg VINPK={input_peak_v:.12g}
VDD_SOURCE vdd 0 {{VDD}}
VSIG sig 0 sin({{VCM}} {{VINPK}} {{FIN}})
VREF ref 0 {{VCM}}
RBIAS vdd vbias 10.5k
XBIAS_REF vbias vbias 0 0 sky130_fd_pr__nfet_01v8 w=64 l=1.00
CBIAS vbias 0 2p
VBIAS_ENABLE bias_enable 0 {{VDD}}
VBIAS_BLANK bias_blank 0 0
XBIAS_GATE vbias bias_enable bias_blank vbias_ch 0 v3_bias_blank_switch
VLO0 lo0 0 pulse(0 {{VDD}} 10n 1n 1n 123n 250n)
BLO180 lo180 0 v={{VDD}}-v(lo0)
VLO90 lo90 0 pulse(0 {{VDD}} 72.5n 1n 1n 123n 250n)
BLO270 lo270 0 v={{VDD}}-v(lo90)
XCHANNEL sig ref {nodes} outp outn vbias_ch 0 v3_vector_channel_15_mos
RLOADP vdd outp 5k
RLOADN vdd outn 5k
ROUTP outp outp_pad 500
ROUTN outn outn_pad 500
COUTP outp_pad 0 10p
COUTN outn_pad 0 10p
RINSTRP outp_pad 0 1meg
RINSTRN outn_pad 0 1meg
EDIFF differential 0 outp_pad outn_pad 1
BCM output_cm_ac 0 v=(v(outp_pad)+v(outn_pad))/2-0.9
{chr(10).join(demodulators)}
.tran 2n 30u 15u
{chr(10).join(measures)}
.end
"""


def run_transient(word: int, input_peak_v: float) -> dict[str, Any]:
    label = "background" if input_peak_v == 0 else "signal"
    work = BUILD / f"word_{word:03d}" / label
    work.mkdir(parents=True, exist_ok=True)
    deck_path = work / "spur.spice"
    log_path = work / "ngspice.log"
    deck_path.write_text(transient_deck(word, input_peak_v))
    completed = subprocess.run(
        ["ngspice", "-b", "-o", str(log_path), str(deck_path)], cwd=ROOT,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=300, check=False,
    )
    log = log_path.read_text(errors="replace") if log_path.exists() else completed.stdout
    values = {key: float(value) for key, value in MEASURE_RE.findall(log)}
    required = {
        f"{output}_{frequency}_{component}_avg"
        for output in ("diff", "cm")
        for frequency in SPECTRAL_BINS_MHZ
        for component in ("i", "q")
    }
    if completed.returncode or not required.issubset(values):
        raise RuntimeError(
            f"spur run word={word} {label} failed; missing={sorted(required-values.keys())}\n"
            + "\n".join(log.splitlines()[-60:])
        )
    spectrum = {}
    phasors = {}
    for output in ("diff", "cm"):
        spectrum[output] = {}
        phasors[output] = {}
        for frequency in SPECTRAL_BINS_MHZ:
            value = complex(
                values[f"{output}_{frequency}_i_avg"],
                values[f"{output}_{frequency}_q_avg"],
            )
            spectrum[output][str(frequency)] = 2.0 * abs(value)
            phasors[output][str(frequency)] = [value.real, value.imag]
    return {
        "word": word,
        "input_peak_v": input_peak_v,
        "spectrum_peak_v": spectrum,
        "demodulator_phasors_v": phasors,
        "deck": str(deck_path.relative_to(ROOT)),
        "deck_sha256": sha256(deck_path),
        "log": str(log_path.relative_to(ROOT)),
    }


def static_noise_deck(word: int, lo0_high: bool, lo90_high: bool) -> str:
    levels = {
        "lo0": lo0_high,
        "lo180": not lo0_high,
        "lo90": lo90_high,
        "lo270": not lo90_high,
    }
    sources = "\n".join(
        f"V{name.upper()} {name} 0 {1.8 if high else 0.0:g}"
        for name, high in levels.items()
    )
    nodes = " ".join(group_nodes(word))
    return f"""* V3 held-LO small-signal noise proxy, word=0x{word:02x}.
.option scale=1e-6
.temp 27
.include "spice/sky130/sky130_1v8_tt.inc"
.include "v3/spice/vector_channel_15.inc"
VDD_SOURCE vdd 0 1.8
VSIG sig 0 dc 1.2 ac 1
VREF ref 0 1.2
RBIAS vdd vbias 10.5k
XBIAS_REF vbias vbias 0 0 sky130_fd_pr__nfet_01v8 w=64 l=1.00
CBIAS vbias 0 2p
VBIAS_ENABLE bias_enable 0 1.8
VBIAS_BLANK bias_blank 0 0
XBIAS_GATE vbias bias_enable bias_blank vbias_ch 0 v3_bias_blank_switch
{sources}
XCHANNEL sig ref {nodes} outp outn vbias_ch 0 v3_vector_channel_15_mos
RLOADP vdd outp 5k
RLOADN vdd outn 5k
ROUTP outp outp_pad 500
ROUTN outn outn_pad 500
COUTP outp_pad 0 10p
COUTN outn_pad 0 10p
RINSTRP outp_pad 0 1meg
RINSTRN outn_pad 0 1meg
.noise v(outp_pad,outn_pad) VSIG dec 20 10 2meg 1
.control
run
setplot noise2
print onoise_total inoise_total
quit
.endc
.end
"""


def run_noise_snapshot(word: int, index: int, levels: tuple[bool, bool]) -> dict[str, Any]:
    work = BUILD / f"word_{word:03d}" / "noise" / f"snapshot_{index}"
    work.mkdir(parents=True, exist_ok=True)
    deck_path = work / "noise.spice"
    log_path = work / "ngspice.log"
    deck_path.write_text(static_noise_deck(word, *levels))
    completed = subprocess.run(
        ["ngspice", "-b", "-o", str(log_path), str(deck_path)], cwd=ROOT,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=180, check=False,
    )
    log = log_path.read_text(errors="replace") if log_path.exists() else completed.stdout
    output_match = OUTPUT_NOISE_RE.search(log)
    input_match = INPUT_NOISE_RE.search(log)
    if completed.returncode or output_match is None or input_match is None:
        raise RuntimeError(
            f"noise snapshot word={word} index={index} failed\n"
            + "\n".join(log.splitlines()[-80:])
        )
    return {
        "snapshot": index,
        "lo0_high": levels[0],
        "lo90_high": levels[1],
        "integrated_output_noise_v_rms_10hz_to_2mhz": float(output_match.group(1)),
        "integrated_input_referred_noise_v_rms_10hz_to_2mhz": float(input_match.group(1)),
        "deck": str(deck_path.relative_to(ROOT)),
        "deck_sha256": sha256(deck_path),
        "log": str(log_path.relative_to(ROOT)),
    }


def db_ratio(numerator: float, denominator: float) -> float:
    return -math.inf if numerator <= 0 else 20.0 * math.log10(numerator / denominator)


def two_pole_2mhz_magnitude(frequency_mhz: float) -> float:
    """Magnitude of the two cascaded 1 kOhm/79.577 pF bench poles."""

    return 1.0 / (1.0 + (frequency_mhz / 2.0) ** 2)


def analyze_word(
    word: int,
    signal: dict[str, Any],
    background: dict[str, Any],
    noise: list[dict[str, Any]],
) -> dict[str, Any]:
    corrected = {
        output: {
            str(frequency): 2.0 * abs(
                complex(*signal["demodulator_phasors_v"][output][str(frequency)])
                - complex(*background["demodulator_phasors_v"][output][str(frequency)])
            )
            for frequency in SPECTRAL_BINS_MHZ
        }
        for output in ("diff", "cm")
    }
    desired = corrected["diff"]["1"]
    signal_spurs = {
        frequency: db_ratio(amplitude, desired)
        for frequency, amplitude in corrected["diff"].items()
        if frequency != "1"
    }
    receiver_spurs = {
        frequency: raw_dbc + 20.0 * math.log10(
            two_pole_2mhz_magnitude(float(frequency))
            / two_pole_2mhz_magnitude(1.0)
        )
        for frequency, raw_dbc in signal_spurs.items()
    }
    background_diff = background["spectrum_peak_v"]["diff"]
    background_cm = background["spectrum_peak_v"]["cm"]
    return {
        "word": word,
        "desired_1mhz_peak_v": desired,
        "corrected_differential_signal_spectrum_peak_v": corrected["diff"],
        "corrected_differential_spurs_dbc": signal_spurs,
        "worst_corrected_signal_spur_dbc": max(signal_spurs.values()),
        "two_pole_2mhz_receiver_spurs_dbc": receiver_spurs,
        "worst_two_pole_2mhz_receiver_spur_dbc": max(receiver_spurs.values()),
        "differential_lo_feedthrough_dbc": {
            frequency: db_ratio(background_diff[frequency], desired)
            for frequency in ("4", "8", "12")
        },
        "common_mode_clock_components_peak_v": {
            frequency: background_cm[frequency]
            for frequency in ("4", "8", "12")
        },
        "held_lo_noise_snapshots": noise,
        "held_lo_integrated_output_noise_range_v_rms": [
            min(item["integrated_output_noise_v_rms_10hz_to_2mhz"] for item in noise),
            max(item["integrated_output_noise_v_rms_10hz_to_2mhz"] for item in noise),
        ],
        "transient_cases": {"signal": signal, "background": background},
    }


def main() -> None:
    words = tuple(entry.word for entry in phase_table(8))
    snapshots = ((False, False), (True, False), (True, True), (False, True))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        transient_futures = {
            (word, amplitude): pool.submit(run_transient, word, amplitude)
            for word in words for amplitude in (0.0, 0.005)
        }
        transient = {key: future.result() for key, future in transient_futures.items()}
        noise_futures = {
            (word, index): pool.submit(run_noise_snapshot, word, index, levels)
            for word in words for index, levels in enumerate(snapshots)
        }
        noise = {
            word: [noise_futures[(word, index)].result() for index in range(4)]
            for word in words
        }
    word_reports = [
        analyze_word(word, transient[(word, 0.005)], transient[(word, 0.0)], noise[word])
        for word in words
    ]
    gate = {
        "all_eight_phase_states_are_covered": len(word_reports) == 8,
        "desired_output_is_nonzero": all(item["desired_1mhz_peak_v"] >= 1e-3 for item in word_reports),
        "receiver_filtered_signal_spurs_below_minus_20dbc": all(
            item["worst_two_pole_2mhz_receiver_spur_dbc"] <= -20.0
            for item in word_reports
        ),
        "differential_lo_feedthrough_below_minus_20dbc": all(
            max(item["differential_lo_feedthrough_dbc"].values()) <= -20.0
            for item in word_reports
        ),
        "held_lo_noise_proxies_completed": all(
            len(item["held_lo_noise_snapshots"]) == 4 for item in word_reports
        ),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(gate.values()) else "fail",
        "scope": "TT one-channel schematic periodic spur characterization plus held-LO small-signal noise proxy",
        "gate": gate,
        "words": word_reports,
        "noise_signoff": {
            "status": "blocked_pending_periodic_noise_tool",
            "reason": "ngspice .noise linearizes a DC state and does not include mixer noise folding, cyclostationary noise, LO phase noise, or clock-edge noise",
            "required_resolution": "run PSS/PNoise (or an independently reviewed equivalent) after the selector schematic is frozen",
        },
        "limitations": [
            "schematic devices without selector, route, package, or extracted RC",
            "integer-MHz coherent spectral bins from 1 through 15 MHz",
            "spur amplitudes use deterministic background subtraction; raw LO feedthrough is reported separately",
        ],
    }
    BUILD.mkdir(parents=True, exist_ok=True)
    output = BUILD / "summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": report["status"],
        "gate": report["gate"],
        "noise_signoff": report["noise_signoff"]["status"],
        "words": [{
            "word": item["word"],
            "desired_1mhz_peak_v": item["desired_1mhz_peak_v"],
            "worst_corrected_signal_spur_dbc": item["worst_corrected_signal_spur_dbc"],
            "worst_two_pole_2mhz_receiver_spur_dbc": item["worst_two_pole_2mhz_receiver_spur_dbc"],
            "differential_lo_feedthrough_dbc": item["differential_lo_feedthrough_dbc"],
            "held_lo_integrated_output_noise_range_v_rms": item["held_lo_integrated_output_noise_range_v_rms"],
        } for item in word_reports],
    }, indent=2, sort_keys=True))
    print(f"report={output.relative_to(ROOT)}")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
