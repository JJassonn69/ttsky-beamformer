#!/usr/bin/env python3
"""Run a calibration/validation split with independent SKY130 MOS mismatch.

This reuses the V2 method that exposes the open PDK's geometry-scaled Spectre
mismatch coefficients to ngspice, then assigns independent Gaussian factors to
every physical MOS instance in a flattened V3 channel.  Calibration seeds
select one global eight-state codebook from bounded nearby raw words.  A
disjoint validation-seed population is then simulated without refitting.

The result is an open-PDK mismatch sensitivity study, not a foundry-qualified
yield claim.  Passive mismatch, spatial correlation, systematic gradients,
package variation, and layout parasitics are not represented.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import random
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/model"))
sys.path.insert(0, str(ROOT / "v2/tools"))

from beamformer_v3 import constellation, phase_table, unpack_group_codes  # noqa: E402
from run_gate5_mismatch_pilot import (  # noqa: E402
    MODEL_SPECS,
    build_model_bundle,
)


BUILD = ROOT / "build/v3/mismatch_calibration_split"
MODEL = "sky130_fd_pr__nfet_01v8"
MODEL_PARAMETERS = tuple(MODEL_SPECS[MODEL]["parameters"])
AXIS_LO_PAIR = {
    0: ("lo0", "lo180"),
    1: ("lo90", "lo270"),
    2: ("lo180", "lo0"),
    3: ("lo270", "lo90"),
}
MEASURE_RE = re.compile(r"^([a-z0-9_]+)\s*=\s*([-+0-9.eE]+)", re.MULTILINE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def device_names() -> tuple[str, ...]:
    names = ["XBIAS_REF", "XBIAS_PASS", "XBIAS_PULLDOWN"]
    for unit in range(15):
        names.extend(
            f"XU{unit:02d}_{suffix}"
            for suffix in ("GM_P", "GM_N", "SW_PP", "SW_PN", "SW_NP", "SW_NN", "TAIL")
        )
    return tuple(names)


def mismatch_factors(seed: int) -> dict[str, dict[str, float]]:
    rng = random.Random(seed)
    return {
        device: {parameter: rng.gauss(0.0, 1.0) for parameter in MODEL_PARAMETERS}
        for device in device_names()
    }


def factor_manifest(seed: int, factors: dict[str, dict[str, float]]) -> dict[str, Any]:
    values = {
        parameter: [item[parameter] for item in factors.values()]
        for parameter in MODEL_PARAMETERS
    }
    return {
        "seed": seed,
        "rng": "Python random.Random (MT19937), independent Gaussian draws",
        "physical_mos_instances": len(factors),
        "factor_sha256": canonical_hash(factors),
        "statistics": {
            parameter: {
                "mean": statistics.fmean(samples),
                "sample_stddev": statistics.stdev(samples),
                "minimum": min(samples),
                "maximum": max(samples),
            }
            for parameter, samples in values.items()
        },
    }


def mos_line(
    name: str,
    nodes: str,
    width_um: float,
    length_um: float,
    factors: dict[str, dict[str, float]],
) -> str:
    suffix = MODEL.split("__")[-1]
    parameters = " ".join(
        f"mc_{suffix}_{parameter}={factors[name][parameter]:.17g}"
        for parameter in MODEL_PARAMETERS
    )
    return (
        f"{name} {nodes} {MODEL} w={width_um:.12g} l={length_um:.12g} "
        f"{parameters}"
    )


def flattened_channel(word: int, factors: dict[str, dict[str, float]]) -> str:
    return flattened_channel_with_geometry(word, factors, {})


def flattened_channel_with_geometry(
    word: int,
    factors: dict[str, dict[str, float]],
    geometry: dict[str, float],
) -> str:
    codes = unpack_group_codes(word)
    gm_width = geometry.get("gm_width_um", 0.84)
    gm_length = geometry.get("gm_length_um", 0.60)
    switch_width = geometry.get("switch_width_um", 0.65)
    switch_length = geometry.get("switch_length_um", 0.15)
    tail_width = geometry.get("tail_width_um", 5.066666666)
    tail_length = geometry.get("tail_length_um", 1.00)
    unit_groups = tuple(
        group for group, count in enumerate((1, 2, 4, 8)) for _ in range(count)
    )
    lines: list[str] = []
    for unit, group in enumerate(unit_groups):
        lop, lon = AXIS_LO_PAIR[codes[group]]
        tail = f"tail_{unit}"
        gm_p = f"gm_p_{unit}"
        gm_n = f"gm_n_{unit}"
        prefix = f"XU{unit:02d}_"
        lines.extend((
            mos_line(prefix + "GM_P", f"{gm_p} sig {tail} 0", gm_width, gm_length, factors),
            mos_line(prefix + "GM_N", f"{gm_n} ref {tail} 0", gm_width, gm_length, factors),
            mos_line(prefix + "SW_PP", f"outp {lop} {gm_p} 0", switch_width, switch_length, factors),
            mos_line(prefix + "SW_PN", f"outn {lon} {gm_p} 0", switch_width, switch_length, factors),
            mos_line(prefix + "SW_NP", f"outn {lop} {gm_n} 0", switch_width, switch_length, factors),
            mos_line(prefix + "SW_NN", f"outp {lon} {gm_n} 0", switch_width, switch_length, factors),
            mos_line(prefix + "TAIL", f"{tail} vbias 0 0", tail_width, tail_length, factors),
        ))
    return "\n".join(lines)


def deck(
    word: int,
    factors: dict[str, dict[str, float]],
    model_include: Path,
    geometry: dict[str, float] | None = None,
    input_peak_v: float = 0.005,
) -> str:
    geometry = geometry or {}
    bias = mos_line(
        "XBIAS_REF", "vbias vbias 0 0",
        geometry.get("bias_reference_width_um", 64.0),
        geometry.get("bias_reference_length_um", 1.00), factors,
    )
    channel = flattened_channel_with_geometry(word, factors, geometry)
    bias_pass = mos_line("XBIAS_PASS", "vbias_ch bias_enable vbias 0", 2.0, 0.15, factors)
    bias_pulldown = mos_line("XBIAS_PULLDOWN", "vbias_ch bias_blank 0 0", 1.0, 0.15, factors)
    return f"""* V3 flattened mismatch sample word=0x{word:02x}.
.option scale=1e-6
.option klu
.option method=gear reltol=1e-4 vabstol=1e-7 iabstol=1e-12
.temp 27
.include "{model_include.relative_to(ROOT)}"
.param VDD=1.8 VCM=1.2 FIN=5meg FOUT=1meg VINPK={input_peak_v:.12g}
VDD_SOURCE vdd 0 {{VDD}}
VSIG sig 0 sin({{VCM}} {{VINPK}} {{FIN}})
VREF ref 0 {{VCM}}
RBIAS vdd vbias 10.5k
{bias}
CBIAS vbias 0 2p
VBIAS_ENABLE bias_enable 0 {{VDD}}
VBIAS_BLANK bias_blank 0 0
{bias_pass}
{bias_pulldown}
VLO0 lo0 0 pulse(0 {{VDD}} 10n 1n 1n 123n 250n)
BLO180 lo180 0 v={{VDD}}-v(lo0)
VLO90 lo90 0 pulse(0 {{VDD}} 72.5n 1n 1n 123n 250n)
BLO270 lo270 0 v={{VDD}}-v(lo90)
{channel.replace(' vbias 0 0 ', ' vbias_ch 0 0 ')}
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
.tran 2n 14u 8u
.measure tran tone_i_avg avg v(tone_i) from=10u to=14u
.measure tran tone_q_avg avg v(tone_q) from=10u to=14u
.measure tran output_cm_avg avg v(output_cm) from=10u to=14u
.measure tran supply_avg avg i(VDD_SOURCE) from=10u to=14u
.end
"""


def run_case(
    population: str,
    seed: int,
    word: int,
    factors: dict[str, dict[str, float]],
    model_include: Path,
    ngspice: str,
    geometry: dict[str, float] | None = None,
    input_peak_v: float = 0.005,
) -> dict[str, Any]:
    work = BUILD / population / f"seed_{seed:04d}" / f"word_{word:03d}"
    work.mkdir(parents=True, exist_ok=True)
    deck_path = work / "mismatch.spice"
    log_path = work / "ngspice.log"
    deck_path.write_text(deck(word, factors, model_include, geometry, input_peak_v))
    completed = subprocess.run(
        [ngspice, "-b", "-o", str(log_path), str(deck_path)], cwd=ROOT,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=240, check=False,
    )
    log = log_path.read_text(errors="replace") if log_path.exists() else completed.stdout
    values = {key: float(value) for key, value in MEASURE_RE.findall(log)}
    required = {"tone_i_avg", "tone_q_avg", "output_cm_avg", "supply_avg"}
    if completed.returncode or not required.issubset(values):
        raise RuntimeError(
            f"mismatch {population} seed={seed} word={word} failed\n"
            + "\n".join(log.splitlines()[-60:])
        )
    value = complex(values["tone_q_avg"], values["tone_i_avg"])
    return {
        "seed": seed,
        "word": word,
        "phasor_v": [value.real, value.imag],
        "tone_peak_v": 2.0 * abs(value),
        "raw_phase_deg": math.degrees(math.atan2(value.imag, value.real)),
        "output_common_mode_v": values["output_cm_avg"],
        "supply_current_a": abs(values["supply_avg"]),
        "deck": str(deck_path.relative_to(ROOT)),
        "deck_sha256": sha256(deck_path),
        "log": str(log_path.relative_to(ROOT)),
    }


def reusable_case(
    population: str,
    seed: int,
    word: int,
    factors: dict[str, dict[str, float]],
    model_include: Path,
    geometry: dict[str, float] | None = None,
    input_peak_v: float = 0.005,
) -> dict[str, Any] | None:
    work = BUILD / population / f"seed_{seed:04d}" / f"word_{word:03d}"
    deck_path = work / "mismatch.spice"
    log_path = work / "ngspice.log"
    expected = deck(word, factors, model_include, geometry, input_peak_v)
    if not deck_path.is_file() or deck_path.read_text() != expected or not log_path.is_file():
        return None
    values = {key: float(value) for key, value in MEASURE_RE.findall(log_path.read_text(errors="replace"))}
    required = {"tone_i_avg", "tone_q_avg", "output_cm_avg", "supply_avg"}
    if not required.issubset(values):
        return None
    value = complex(values["tone_q_avg"], values["tone_i_avg"])
    return {
        "seed": seed,
        "word": word,
        "phasor_v": [value.real, value.imag],
        "tone_peak_v": 2.0 * abs(value),
        "raw_phase_deg": math.degrees(math.atan2(value.imag, value.real)),
        "output_common_mode_v": values["output_cm_avg"],
        "supply_current_a": abs(values["supply_avg"]),
        "deck": str(deck_path.relative_to(ROOT)),
        "deck_sha256": sha256(deck_path),
        "log": str(log_path.relative_to(ROOT)),
    }


def candidate_words(count_per_state: int) -> dict[int, tuple[int, ...]]:
    points = constellation()
    result: dict[int, tuple[int, ...]] = {}
    for entry in phase_table(8):
        target = 11.0 * complex(
            math.cos(math.radians(entry.target_phase_deg)),
            math.sin(math.radians(entry.target_phase_deg)),
        )
        result[entry.index] = tuple(
            word
            for _, word in sorted(
                points.items(), key=lambda item: (abs(complex(*item[0]) - target), item[1])
            )[:count_per_state]
        )
    return result


def phase_error(actual: float, target: float) -> float:
    return (actual - target + 180.0) % 360.0 - 180.0


def select_codebook(
    responses: dict[int, dict[int, dict[str, Any]]],
    candidates: dict[int, tuple[int, ...]],
) -> tuple[dict[int, int], dict[str, Any]]:
    nominal_reference = phase_table(8)[0].word
    selections: dict[int, int] = {}
    scoring: dict[str, Any] = {}
    for state, words in candidates.items():
        target_phase = 45.0 * state
        scored = []
        for word in words:
            phase_errors = []
            gain_errors = []
            for seed, by_word in responses.items():
                candidate = complex(*by_word[word]["phasor_v"])
                reference = complex(*by_word[nominal_reference]["phasor_v"])
                relative_phase = math.degrees(math.atan2(candidate.imag, candidate.real)) - math.degrees(
                    math.atan2(reference.imag, reference.real)
                )
                phase_errors.append(phase_error(relative_phase, target_phase))
                gain_errors.append(20.0 * math.log10(abs(candidate) / abs(reference)))
            maximum_phase = max(abs(value) for value in phase_errors)
            maximum_gain = max(abs(value) for value in gain_errors)
            score = (
                max(maximum_phase / 5.0, maximum_gain / 0.5),
                maximum_gain / 0.5 + maximum_phase / 5.0,
                math.sqrt(statistics.fmean(value * value for value in phase_errors)),
                math.sqrt(statistics.fmean(value * value for value in gain_errors)),
                word,
            )
            scored.append((score, word, phase_errors, gain_errors))
        score, word, phase_errors, gain_errors = min(scored)
        selections[state] = word
        scoring[str(state)] = {
            "selected_word": word,
            "candidate_words": list(words),
            "score": list(score[:-1]),
            "calibration_phase_error_range_deg": [min(phase_errors), max(phase_errors)],
            "calibration_gain_error_range_db": [min(gain_errors), max(gain_errors)],
        }
    return selections, scoring


def population_metrics(
    responses: dict[int, dict[int, dict[str, Any]]],
    codebook: dict[int, int],
) -> dict[str, Any]:
    seed_reports: dict[str, Any] = {}
    for seed, by_word in sorted(responses.items()):
        reference = complex(*by_word[codebook[0]]["phasor_v"])
        states = []
        for state in range(8):
            case = by_word[codebook[state]]
            value = complex(*case["phasor_v"])
            relative = math.degrees(math.atan2(value.imag, value.real)) - math.degrees(
                math.atan2(reference.imag, reference.real)
            )
            states.append({
                "state": state,
                "word": codebook[state],
                "phase_error_deg": phase_error(relative, 45.0 * state),
                "tone_peak_v": case["tone_peak_v"],
                "output_common_mode_v": case["output_common_mode_v"],
                "supply_current_a": case["supply_current_a"],
            })
        peaks = [item["tone_peak_v"] for item in states]
        seed_reports[str(seed)] = {
            "worst_phase_error_deg": max(abs(item["phase_error_deg"]) for item in states),
            "gain_span_db": 20.0 * math.log10(max(peaks) / min(peaks)),
            "minimum_output_common_mode_v": min(item["output_common_mode_v"] for item in states),
            "states": states,
        }
    return {
        "seed_count": len(seed_reports),
        "worst_phase_error_deg": max(item["worst_phase_error_deg"] for item in seed_reports.values()),
        "worst_gain_span_db": max(item["gain_span_db"] for item in seed_reports.values()),
        "minimum_output_common_mode_v": min(
            item["minimum_output_common_mode_v"] for item in seed_reports.values()
        ),
        "seeds": seed_reports,
    }


def run_population(
    name: str,
    seeds: tuple[int, ...],
    words: tuple[int, ...],
    factors: dict[int, dict[str, dict[str, float]]],
    model_include: Path,
    ngspice: str,
    jobs: int,
    resume: bool = False,
    input_peak_v: float = 0.005,
) -> dict[int, dict[int, dict[str, Any]]]:
    output = {seed: {} for seed in seeds}
    pending: list[tuple[int, int]] = []
    reused = 0
    for seed in seeds:
        for word in words:
            prior = reusable_case(
                name, seed, word, factors[seed], model_include,
                input_peak_v=input_peak_v,
            ) if resume else None
            if prior is None:
                pending.append((seed, word))
            else:
                output[seed][word] = prior
                reused += 1
    if reused:
        print(f"{name}: reused {reused}/{len(seeds) * len(words)} hash-identical cases", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(
                run_case, name, seed, word, factors[seed], model_include, ngspice,
                input_peak_v=input_peak_v,
            ): (seed, word)
            for seed, word in pending
        }
        completed_count = 0
        for future in concurrent.futures.as_completed(futures):
            seed, word = futures[future]
            output[seed][word] = future.result()
            completed_count += 1
            if completed_count % 64 == 0 or completed_count == len(futures):
                print(f"{name}: ran {completed_count}/{len(futures)} pending cases", flush=True)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-seeds", type=int, default=8)
    parser.add_argument("--validation-seeds", type=int, default=16)
    parser.add_argument("--candidates-per-state", type=int, default=8)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if min(args.calibration_seeds, args.validation_seeds, args.candidates_per_state, args.jobs) < 1:
        raise SystemExit("all counts must be positive")
    calibration_seeds = tuple(range(1, args.calibration_seeds + 1))
    validation_seeds = tuple(range(1001, 1001 + args.validation_seeds))
    if set(calibration_seeds) & set(validation_seeds):
        raise RuntimeError("calibration and validation populations overlap")
    BUILD.mkdir(parents=True, exist_ok=True)
    model_include, model_manifest = build_model_bundle(BUILD)
    all_seeds = calibration_seeds + validation_seeds
    factors = {seed: mismatch_factors(seed) for seed in all_seeds}
    factor_manifests = {str(seed): factor_manifest(seed, factors[seed]) for seed in all_seeds}
    (BUILD / "factor_manifests.json").write_text(
        json.dumps(factor_manifests, indent=2, sort_keys=True) + "\n"
    )
    candidates = candidate_words(args.candidates_per_state)
    calibration_words = tuple(sorted({word for words in candidates.values() for word in words}))
    nominal_reference = phase_table(8)[0].word
    if nominal_reference not in calibration_words:
        calibration_words += (nominal_reference,)
    calibration = run_population(
        "calibration", calibration_seeds, calibration_words, factors,
        model_include, args.ngspice, min(args.jobs, 4), args.resume,
    )
    codebook, scoring = select_codebook(calibration, candidates)
    validation_words = tuple(sorted(set(codebook.values())))
    validation = run_population(
        "validation", validation_seeds, validation_words, factors,
        model_include, args.ngspice, min(args.jobs, 4), args.resume,
    )
    calibration_metrics = population_metrics(calibration, codebook)
    validation_metrics = population_metrics(validation, codebook)
    gate = {
        "calibration_and_validation_seed_sets_are_disjoint": not (
            set(calibration_seeds) & set(validation_seeds)
        ),
        "validation_worst_phase_error_at_most_5deg": validation_metrics["worst_phase_error_deg"] <= 5.0,
        "validation_worst_gain_span_at_most_0p5db": validation_metrics["worst_gain_span_db"] <= 0.5,
        "validation_output_common_mode_at_least_0p8v": validation_metrics["minimum_output_common_mode_v"] >= 0.8,
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(gate.values()) else "fail",
        "scope": "TT one-channel open-PDK MOS mismatch sensitivity with population holdout; not foundry-qualified yield",
        "method": model_manifest["method"],
        "limitations": model_manifest["limitations"] + [
            "schematic flattened channel without passive mismatch or layout parasitics",
            "bounded global codebook candidates near the nominal radius",
            "calibration is population-level codebook selection, not per-die measurement",
        ],
        "model_bundle_sha256": model_manifest["bundle_sha256"],
        "factor_manifests": "build/v3/mismatch_calibration_split/factor_manifests.json",
        "factor_manifests_sha256": sha256(BUILD / "factor_manifests.json"),
        "calibration_seeds": list(calibration_seeds),
        "validation_seeds": list(validation_seeds),
        "candidate_words_per_state": {str(key): list(value) for key, value in candidates.items()},
        "calibration_word_count": len(calibration_words),
        "selected_codebook": {str(state): word for state, word in codebook.items()},
        "selection_scoring": scoring,
        "calibration_metrics": calibration_metrics,
        "validation_metrics": validation_metrics,
        "gate": gate,
    }
    output = BUILD / "summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": report["status"],
        "gate": gate,
        "selected_codebook": report["selected_codebook"],
        "calibration_metrics": {
            key: calibration_metrics[key] for key in (
                "seed_count", "worst_phase_error_deg", "worst_gain_span_db", "minimum_output_common_mode_v"
            )
        },
        "validation_metrics": {
            key: validation_metrics[key] for key in (
                "seed_count", "worst_phase_error_deg", "worst_gain_span_db", "minimum_output_common_mode_v"
            )
        },
    }, indent=2, sort_keys=True))
    print(f"report={output.relative_to(ROOT)}")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
