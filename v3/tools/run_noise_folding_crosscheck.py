#!/usr/bin/env python3
"""Independent frequency-domain bound for V3 mixer-noise folding.

ngspice linearizes all eight required vector words in each of the four held-LO
states.  The total output-noise spectrum is split into output-passive noise,
which remains at its original frequency, and the remaining circuit noise,
which is folded with Fourier coefficients of the actual 5 ns-edge bipolar
4 MHz commutation waveform.  This is deliberately independent of VACASK's
time-domain random-number path.

The calculation is a bounded equivalent rather than native PNoise: internal
device transfer functions are represented by held-state spectra.  Agreement
with multi-seed switched transient noise is therefore required and the
approximation is kept explicit in the evidence.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import math
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILD = ROOT / "build/v3/noise_folding_crosscheck"
DEFAULT_SWITCHED = ROOT / "build/v3/vacask_switched_noise/summary.json"
PASSIVE_VECTORS = (
    "onoise_rloadp",
    "onoise_rloadn",
    "onoise_routp",
    "onoise_routn",
    "onoise_rinstrp",
    "onoise_rinstrn",
)
LO_STATES = ((False, False), (True, False), (True, True), (False, True))


def load_module(name: str, filename: str) -> Any:
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SPUR = load_module("v3_spur_noise", "run_spur_noise_characterization.py")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def spectrum_deck(
    word: int,
    lo0_high: bool,
    lo90_high: bool,
    output_path: Path,
    maximum_hz: float,
) -> str:
    deck = SPUR.static_noise_deck(word, lo0_high, lo90_high)
    deck = deck.replace(
        ".noise v(outp_pad,outn_pad) VSIG dec 20 10 2meg 1",
        f".noise v(outp_pad,outn_pad) VSIG dec 40 10 {maximum_hz:.12g} 1",
        1,
    )
    old_control = """run
setplot noise2
print onoise_total inoise_total
quit"""
    vectors = " ".join(("onoise_spectrum", "inoise_spectrum", *PASSIVE_VECTORS))
    new_control = f"""run
set wr_vecnames
set wr_singlescale
set numdgt=16
setplot noise1
wrdata {output_path} {vectors}
setplot noise2
print onoise_total inoise_total
quit"""
    if old_control not in deck:
        raise RuntimeError("held-LO control block changed unexpectedly")
    return deck.replace(old_control, new_control, 1)


def run_snapshot(
    args: argparse.Namespace,
    build: Path,
    word: int,
    index: int,
    levels: tuple[bool, bool],
) -> dict[str, Any]:
    work = build / f"word_{word:03d}" / f"snapshot_{index}"
    work.mkdir(parents=True, exist_ok=True)
    data_path = work / "noise_spectrum.dat"
    deck_path = work / "noise.spice"
    log_path = work / "ngspice.log"
    write_if_changed(
        deck_path,
        spectrum_deck(word, *levels, data_path, args.maximum_source_hz),
    )
    completed = subprocess.run(
        [str(args.ngspice), "-b", "-o", str(log_path), str(deck_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=args.timeout,
        check=False,
    )
    log = log_path.read_text(errors="replace") if log_path.exists() else completed.stdout
    if completed.returncode or not data_path.exists():
        raise RuntimeError(
            f"noise snapshot word={word} state={index} failed\n"
            + "\n".join(log.splitlines()[-80:])
        )
    data = np.loadtxt(data_path, skiprows=1)
    expected_columns = 1 + 2 + len(PASSIVE_VECTORS)
    if data.ndim != 2 or data.shape[1] != expected_columns:
        raise RuntimeError(f"unexpected noise spectrum shape: {data.shape}")
    frequency = data[:, 0]
    total_density = data[:, 1]
    passive_power_density = np.sum(data[:, 3:] ** 2, axis=1)
    total_power_density = total_density**2
    modulated_power_density = np.maximum(
        total_power_density - passive_power_density, 0.0
    )
    return {
        "word": word,
        "snapshot": index,
        "lo0_high": levels[0],
        "lo90_high": levels[1],
        "frequency_hz": frequency,
        "total_power_density_v2_per_hz": total_power_density,
        "passive_power_density_v2_per_hz": passive_power_density,
        "modulated_power_density_v2_per_hz": modulated_power_density,
        "deck_sha256": sha256(deck_path),
        "log_sha256": sha256(log_path),
        "point_count": int(frequency.size),
    }


def log_interpolate(
    frequency_hz: np.ndarray,
    power_density: np.ndarray,
    target_hz: np.ndarray,
) -> np.ndarray:
    safe_power = np.maximum(power_density, np.finfo(float).tiny)
    return np.exp(
        np.interp(
            np.log(np.maximum(target_hz, frequency_hz[0])),
            np.log(frequency_hz),
            np.log(safe_power),
        )
    )


def commutator_coefficients(
    lo_hz: float, rise_s: float, maximum_harmonic: int
) -> tuple[dict[int, complex], float, float]:
    """Numerically integrate the bipolar, half-duty, finite-edge LO waveform."""

    period = 1.0 / lo_hz
    samples = 1 << 20
    time_s = np.arange(samples) * period / samples
    # The source declaration uses rise=5 ns, width=120 ns, fall=5 ns at a
    # 250 ns period.  ``width`` is the flat high interval, so the falling edge
    # starts at rise+width rather than at half a period.
    flat_width = period / 2.0 - rise_s
    fall_start = rise_s + flat_width
    fall_end = fall_start + rise_s
    phase = np.mod(time_s, period)
    high = np.ones_like(phase)
    rising = phase < rise_s
    high[rising] = phase[rising] / rise_s
    falling = (phase >= fall_start) & (phase < fall_end)
    high[falling] = (fall_end - phase[falling]) / rise_s
    high[phase >= fall_end] = 0.0
    # The complementary source has the opposite voltage at every instant.
    bipolar = 2.0 * high - 1.0
    coefficients = {
        harmonic: complex(
            np.mean(bipolar * np.exp(-2j * math.pi * harmonic * time_s / period))
        )
        for harmonic in range(-maximum_harmonic, maximum_harmonic + 1)
    }
    coefficient_energy = float(sum(abs(value) ** 2 for value in coefficients.values()))
    waveform_energy = float(np.mean(bipolar**2))
    return coefficients, coefficient_energy, waveform_energy


def receiver_power_gain(frequency_hz: np.ndarray, cutoff_hz: float) -> np.ndarray:
    return 1.0 / (1.0 + (frequency_hz / cutoff_hz) ** 2) ** 2


def integrate_band(
    frequency_hz: np.ndarray,
    power_density: np.ndarray,
    low_hz: float,
    high_hz: float,
) -> float:
    mask = (frequency_hz >= low_hz) & (frequency_hz <= high_hz)
    return float(math.sqrt(float(np.trapezoid(power_density[mask], frequency_hz[mask]))))


def fold_snapshot(
    snapshot: dict[str, Any],
    coefficients: dict[int, complex],
    output_low_hz: float,
    output_high_hz: float,
    lo_hz: float,
    receiver_cutoff_hz: float,
) -> dict[str, float]:
    source_frequency = snapshot["frequency_hz"]
    total = snapshot["total_power_density_v2_per_hz"]
    passive = snapshot["passive_power_density_v2_per_hz"]
    modulated = snapshot["modulated_power_density_v2_per_hz"]
    output_frequency = np.geomspace(output_low_hz, output_high_hz, 4000)
    folded = np.zeros_like(output_frequency)
    for harmonic, coefficient in coefficients.items():
        translated = np.abs(output_frequency - harmonic * lo_hz)
        folded += abs(coefficient) ** 2 * log_interpolate(
            source_frequency, modulated, translated
        )
    unmodulated_passive = log_interpolate(
        source_frequency, passive, output_frequency
    )
    held_total = log_interpolate(source_frequency, total, output_frequency)
    receiver = receiver_power_gain(output_frequency, receiver_cutoff_hz)
    periodic_total = (folded + unmodulated_passive) * receiver
    held_filtered = held_total * receiver
    result = {
        "folded_receiver_noise_v_rms_10hz_to_2mhz": integrate_band(
            output_frequency, periodic_total, output_low_hz, output_high_hz
        ),
        "folded_receiver_noise_v_rms_10khz_to_2mhz": integrate_band(
            output_frequency, periodic_total, 10e3, output_high_hz
        ),
        "held_receiver_noise_v_rms_10hz_to_2mhz": integrate_band(
            output_frequency, held_filtered, output_low_hz, output_high_hz
        ),
        "held_receiver_noise_v_rms_10khz_to_2mhz": integrate_band(
            output_frequency, held_filtered, 10e3, output_high_hz
        ),
        "unmodulated_output_passive_noise_v_rms_10hz_to_2mhz": integrate_band(
            output_frequency,
            unmodulated_passive * receiver,
            output_low_hz,
            output_high_hz,
        ),
    }
    return result


def switched_comparison(
    switched_path: Path, folded_cases: list[dict[str, Any]], tolerance_db: float
) -> dict[str, Any]:
    if not switched_path.exists():
        return {
            "status": "blocked",
            "reason": f"switched-noise summary not found: {switched_path}",
        }
    switched = json.loads(switched_path.read_text())
    if switched.get("status") not in {"pass_pending_frequency_domain_crosscheck", "pass"}:
        return {
            "status": "blocked",
            "reason": f"switched-noise campaign status is {switched.get('status')}",
            "summary_sha256": sha256(switched_path),
        }
    transient_by_algorithm = {
        mode: [
            case["metrics"]["periodogram_band_rms_v"]
            for case in switched["cases"]
            if case["mode"] == mode
        ]
        for mode in sorted({case["mode"] for case in switched["cases"]})
    }
    folded = [
        case["folding"]["folded_receiver_noise_v_rms_10khz_to_2mhz"]
        for case in folded_cases
    ]
    reference = float(np.mean(folded))

    def comparison(values: list[float]) -> dict[str, Any]:
        observed = float(np.mean(values))
        delta_db = float(20.0 * math.log10(observed / reference))
        return {
            "mean_transient_noise_v_rms": observed,
            "mean_folded_reference_v_rms": reference,
            "delta_db": delta_db,
            "within_tolerance": abs(delta_db) <= tolerance_db,
        }

    comparisons = {
        mode: comparison(values)
        for mode, values in transient_by_algorithm.items()
        if values
    }
    passed = all(entry["within_tolerance"] for entry in comparisons.values())
    return {
        "status": "pass" if passed else "fail",
        "tolerance_db": tolerance_db,
        "switched_summary_sha256": sha256(switched_path),
        "algorithms": comparisons,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ngspice", type=Path, default=Path("/usr/bin/ngspice"))
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--switched-summary", type=Path, default=DEFAULT_SWITCHED)
    parser.add_argument("--maximum-source-hz", type=float, default=64e6)
    parser.add_argument("--output-low-hz", type=float, default=10.0)
    parser.add_argument("--output-high-hz", type=float, default=2e6)
    parser.add_argument("--receiver-cutoff-hz", type=float, default=2e6)
    parser.add_argument("--lo-hz", type=float, default=4e6)
    parser.add_argument("--lo-rise-ns", type=float, default=5.0)
    parser.add_argument("--comparison-tolerance-db", type=float, default=3.0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--jobs", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build = args.build.resolve()
    build.mkdir(parents=True, exist_ok=True)
    if not args.ngspice.exists():
        raise FileNotFoundError(args.ngspice)
    required_words = [entry.word for entry in SPUR.phase_table(8)]
    requested = [
        (word, index, levels)
        for word in required_words
        for index, levels in enumerate(LO_STATES)
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            (word, index): pool.submit(
                run_snapshot, args, build, word, index, levels
            )
            for word, index, levels in requested
        }
        snapshots = [
            futures[(word, index)].result()
            for word, index, _levels in requested
        ]
    maximum_harmonic = int(args.maximum_source_hz // args.lo_hz)
    coefficients, coefficient_energy, waveform_energy = commutator_coefficients(
        args.lo_hz, args.lo_rise_ns * 1e-9, maximum_harmonic
    )
    folded_cases = []
    for snapshot in snapshots:
        folded_cases.append(
            {
                "word": snapshot["word"],
                "snapshot": snapshot["snapshot"],
                "lo0_high": snapshot["lo0_high"],
                "lo90_high": snapshot["lo90_high"],
                "point_count": snapshot["point_count"],
                "deck_sha256": snapshot["deck_sha256"],
                "log_sha256": snapshot["log_sha256"],
                "folding": fold_snapshot(
                    snapshot,
                    coefficients,
                    args.output_low_hz,
                    args.output_high_hz,
                    args.lo_hz,
                    args.receiver_cutoff_hz,
                ),
            }
        )
    comparison = switched_comparison(
        args.switched_summary.resolve(), folded_cases, args.comparison_tolerance_db
    )
    folded_full = np.asarray(
        [
            case["folding"]["folded_receiver_noise_v_rms_10hz_to_2mhz"]
            for case in folded_cases
        ]
    )
    folded_high = np.asarray(
        [
            case["folding"]["folded_receiver_noise_v_rms_10khz_to_2mhz"]
            for case in folded_cases
        ]
    )
    coefficient_closure = abs(coefficient_energy - waveform_energy) / waveform_energy
    gates = {
        "all_eight_words_and_four_held_states": len(folded_cases) == 32,
        "commutator_parseval_truncation_below_1_percent": coefficient_closure
        <= 1e-2,
        "all_folded_results_finite_and_nonzero": bool(
            np.all(np.isfinite(folded_full)) and np.all(folded_full > 0)
        ),
        "switched_transient_agrees_within_3db": comparison.get("status") == "pass",
    }
    if comparison.get("status") == "blocked":
        status = "diagnostic_only_pending_switched_noise"
    else:
        status = "pass" if all(gates.values()) else "fail"
    report = {
        "schema_version": 1,
        "status": status,
        "scope": (
            "independent held-state ngspice spectra plus finite-edge Fourier "
            "folding through the specified two-pole 2 MHz receiver"
        ),
        "platform": platform.platform(),
        "python": sys.version,
        "numpy": np.__version__,
        "configuration": {
            "words": required_words,
            "held_lo_states": [list(levels) for levels in LO_STATES],
            "source_frequency_hz": [10.0, args.maximum_source_hz],
            "output_frequency_hz": [args.output_low_hz, args.output_high_hz],
            "receiver_cutoff_hz": args.receiver_cutoff_hz,
            "lo_hz": args.lo_hz,
            "lo_rise_ns": args.lo_rise_ns,
            "maximum_harmonic": maximum_harmonic,
        },
        "commutator": {
            "coefficient_energy_through_maximum_harmonic": coefficient_energy,
            "sampled_waveform_energy": waveform_energy,
            "relative_parseval_truncation": coefficient_closure,
            "coefficients": {
                str(index): [value.real, value.imag]
                for index, value in coefficients.items()
            },
        },
        "aggregate": {
            "mean_folded_noise_v_rms_10hz_to_2mhz": float(np.mean(folded_full)),
            "state_snapshot_span_db_10hz_to_2mhz": float(
                20.0 * math.log10(np.max(folded_full) / np.min(folded_full))
            ),
            "mean_folded_noise_v_rms_10khz_to_2mhz": float(np.mean(folded_high)),
            "state_snapshot_span_db_10khz_to_2mhz": float(
                20.0 * math.log10(np.max(folded_high) / np.min(folded_high))
            ),
        },
        "comparison_to_switched_transient": comparison,
        "gates": gates,
        "cases": folded_cases,
        "limitations": [
            "This is not native PNoise: periodically changing internal transfer functions are approximated by held-LO spectra.",
            "Noise from the output load, series, and receiver resistors is kept unmodulated; remaining device and bias noise is folded by the commutator coefficients.",
            "Agreement with the qualified full-channel intrinsic transient-noise campaign is required within 3 dB.",
            "Clock-source phase noise, package noise, and layout parasitics are outside this pre-layout schematic calculation.",
        ],
    }
    summary = build / "summary.json"
    summary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
