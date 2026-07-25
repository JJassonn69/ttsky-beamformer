#!/usr/bin/env python3
"""Measure intrinsic noise in the complete periodically switched V3 channel.

VACASK does not presently provide a native PNoise analysis.  This runner uses
its compact-model transient-noise implementation on the complete driven
channel, subtracts an identically stepped noiseless waveform, and applies the
specified two-pole 2 MHz receiver filter.  Multiple deterministic seeds make
the stochastic uncertainty visible instead of hiding it behind one waveform.

The finite record covers the switched 10 kHz-to-64 MHz source-noise band.  A
separate frequency-domain calculation must bound the unresolved 10 Hz-to-
10 kHz contribution and independently check mixer folding before this result
can close the periodic-noise gate.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import math
import platform
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILD = ROOT / "build/v3/vacask_switched_noise"
DEFAULT_MODEL_BUILD = ROOT / "build/v3/vacask_sky130_qualification"
DEFAULT_CHANNEL_BUILD = ROOT / "build/v3/vacask_channel_qualification"
DEFAULT_SCALE_BUILD = ROOT / "build/v3/vacask_noise_scale_linearity"
DEFAULT_SEEDS = (104729, 130363, 155921, 181081)


def load_channel_module() -> Any:
    path = Path(__file__).with_name("run_vacask_channel_qualification.py")
    spec = importlib.util.spec_from_file_location("v3_vacask_channel", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHANNEL = load_channel_module()


def switched_deck(
    word: int,
    model_text: str,
    *,
    stop_us: float,
    step_ns: float,
    mode: str | None,
    seed: int | None,
    noise_fmin_hz: float,
    noise_fmax_hz: float,
    oversample: int,
    noise_scale: float,
    noise_debug: int,
    precondition_us: float,
) -> str:
    """Derive a zero-signal deck from the already qualified channel deck."""

    deck = CHANNEL.vacask_deck(word, model_text)
    deck = deck.replace("ampl=0.005", "ampl=0", 1)
    old_save = "save outp_pad outn_pad vbias_ch p(vdd_source,i) default"
    if old_save not in deck:
        raise RuntimeError("qualified channel save line changed unexpectedly")
    # The qualified cross-check retained every default unknown for debugging.
    # Periodic-noise records are much longer, so retain only the two physical
    # output pins needed by this measurement.
    deck = deck.replace(old_save, "save v(outp_pad) v(outn_pad)", 1)
    old_options = (
        'options tran_method="euler" tran_itl=50 tran_predictor=0 '
        "tran_redofactor=0"
    )
    new_options = old_options + " tran_laggednoise=1"
    if mode is not None:
        new_options += f" tran_extraoct=8 tran_noisedebug={noise_debug}"
    deck = deck.replace(old_options, new_options, 1)
    old_analysis = "analysis channel tran stop=20u step=0.25n maxstep=0.25n"
    analysis = (
        f"analysis channel tran stop={stop_us:.12g}u "
        f"step={step_ns:.12g}n maxstep={step_ns:.12g}n"
    )
    if mode is not None:
        if seed is None:
            raise ValueError("a transient-noise deck requires a seed")
        analysis += (
            f" noisefmax={noise_fmax_hz:.12g} noisefmin={noise_fmin_hz:.12g}"
            f' oversample={oversample} noisemode="{mode}" noiseseed={seed}'
            f" noisescale={noise_scale:.12g}"
        )
        precondition = (
            f"analysis settle tran stop={precondition_us:.12g}u "
            f"step={step_ns:.12g}n maxstep={step_ns:.12g}n "
            'store="noise_ic" write=0\n  '
        )
        analysis = precondition + analysis + ' ic="noise_ic" icmode="uic"'
    if old_analysis not in deck:
        raise RuntimeError("qualified channel analysis line changed unexpectedly")
    return deck.replace(old_analysis, analysis, 1)


def load_outputs(args: argparse.Namespace, raw_path: Path) -> dict[str, np.ndarray]:
    python_dir = str(args.python_dir)
    if python_dir not in sys.path:
        sys.path.insert(0, python_dir)
    from rawfile import rawread  # type: ignore[import-not-found]

    raw = rawread(str(raw_path)).get()
    return {
        "time": np.real(np.asarray(raw["time"], dtype=float)),
        "differential": np.real(
            np.asarray(raw["outp_pad"], dtype=float)
            - np.asarray(raw["outn_pad"], dtype=float)
        ),
    }


def interpolate(time: np.ndarray, values: np.ndarray, target: np.ndarray) -> np.ndarray:
    if time.shape == target.shape and np.array_equal(time, target):
        return values
    return np.interp(target, time, values)


def two_pole_receiver(
    time_s: np.ndarray, values: np.ndarray, cutoff_hz: float = 2e6
) -> np.ndarray:
    """Exact per-step update for two cascaded first-order RC sections."""

    if time_s.size != values.size or time_s.size < 2:
        raise ValueError("receiver input must contain at least two time samples")
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    first = np.empty_like(values)
    second = np.empty_like(values)
    first[0] = values[0]
    second[0] = values[0]
    for index in range(1, values.size):
        alpha = -math.expm1(-(time_s[index] - time_s[index - 1]) / tau)
        first[index] = first[index - 1] + alpha * (values[index] - first[index - 1])
        second[index] = second[index - 1] + alpha * (first[index] - second[index - 1])
    return second


def periodogram_band_rms(
    time_s: np.ndarray,
    values: np.ndarray,
    low_hz: float,
    high_hz: float,
) -> tuple[float, int, float]:
    """Return rectangular-record band RMS and the available bin resolution."""

    count = values.size
    if count < 4:
        raise ValueError("not enough samples for a spectrum")
    dt = float(np.median(np.diff(time_s)))
    uniform_time = time_s[0] + np.arange(count) * dt
    uniform_values = np.interp(uniform_time, time_s, values)
    # Remove only the ensemble-unobservable exact DC bin.  Very-low-frequency
    # noise is handled by the separate analytic bound, not claimed here.
    uniform_values = uniform_values - float(np.mean(uniform_values))
    spectrum = np.fft.rfft(uniform_values)
    frequencies = np.fft.rfftfreq(count, dt)
    power_per_bin = np.abs(spectrum) ** 2 / count**2
    if count > 2:
        power_per_bin[1:-1] *= 2.0
    mask = (frequencies >= low_hz) & (frequencies <= high_hz)
    return (
        float(math.sqrt(float(np.sum(power_per_bin[mask])))),
        int(np.count_nonzero(mask)),
        float(1.0 / (count * dt)),
    )


def waveform_reaches_stop(
    waveform: dict[str, np.ndarray], stop_us: float
) -> bool:
    time_s = waveform.get("time")
    return bool(
        time_s is not None
        and time_s.size >= 2
        and np.all(np.isfinite(time_s))
        and time_s[-1] >= stop_us * 1e-6 * (1.0 - 1e-9)
    )


def waveform_metrics(
    baseline: dict[str, np.ndarray],
    noisy: dict[str, np.ndarray],
    *,
    settle_us: float,
    band_low_hz: float,
    receiver_cutoff_hz: float,
) -> dict[str, float | int]:
    time_s = noisy["time"]
    baseline_differential = interpolate(
        baseline["time"], baseline["differential"], time_s
    )
    residual = noisy["differential"] - baseline_differential
    filtered = two_pole_receiver(time_s, residual, receiver_cutoff_hz)
    mask = time_s >= settle_us * 1e-6
    selected_time = time_s[mask]
    selected_raw = residual[mask]
    selected_filtered = filtered[mask]
    spectral_rms, spectral_bins, resolution_hz = periodogram_band_rms(
        selected_time,
        selected_filtered,
        band_low_hz,
        receiver_cutoff_hz,
    )
    return {
        "raw_differential_rms_v": float(math.sqrt(np.mean(selected_raw**2))),
        "receiver_filtered_rms_v": float(
            math.sqrt(np.mean(selected_filtered**2))
        ),
        "receiver_filtered_mean_v": float(np.mean(selected_filtered)),
        "receiver_filtered_ac_rms_v": float(np.std(selected_filtered)),
        "periodogram_band_rms_v": spectral_rms,
        "periodogram_bin_count": spectral_bins,
        "record_frequency_resolution_hz": resolution_hz,
        "post_settle_sample_count": int(selected_time.size),
        "maximum_absolute_residual_v": float(np.max(np.abs(selected_raw))),
    }


def run_deck(
    args: argparse.Namespace,
    work: Path,
    deck: str,
    timeout: int,
) -> tuple[dict[str, np.ndarray], float, Path]:
    work.mkdir(parents=True, exist_ok=True)
    deck_path = work / "channel.sim"
    raw_path = work / "channel.raw"
    deck_is_unchanged = deck_path.is_file() and deck_path.read_text() == deck
    if getattr(args, "reuse_completed", False) and deck_is_unchanged and raw_path.is_file():
        try:
            waveform = load_outputs(args, raw_path)
        except Exception:  # A truncated/interrupted raw file must be regenerated.
            waveform = None
        if waveform is not None and waveform_reaches_stop(waveform, args.stop_us):
            return waveform, 0.0, deck_path
    CHANNEL.write_if_changed(deck_path, deck)
    started = time.monotonic()
    CHANNEL.run_command(
        [str(args.vacask_bin), "-dp", str(deck_path)],
        work,
        work / "vacask.log",
        timeout,
        CHANNEL.runtime_environment(args),
    )
    elapsed = time.monotonic() - started
    return load_outputs(args, raw_path), elapsed, deck_path


def run_baseline(
    args: argparse.Namespace,
    build: Path,
    word: int,
    model_text: str,
) -> dict[str, Any]:
    work = build / f"word_{word:03d}" / "baseline"
    waveform, elapsed, deck_path = run_deck(
        args,
        work,
        switched_deck(
            word,
            model_text,
            stop_us=args.stop_us,
            step_ns=args.step_ns,
            mode=None,
            seed=None,
            noise_fmin_hz=args.noise_fmin_hz,
            noise_fmax_hz=args.noise_fmax_hz,
            oversample=args.oversample,
            noise_scale=args.noise_scale,
            noise_debug=args.noise_debug,
            precondition_us=args.precondition_us,
        ),
        args.timeout,
    )
    return {
        "waveform": waveform,
        "elapsed_s": elapsed,
        "deck_sha256": CHANNEL.sha256(deck_path),
    }


def run_noise_case(
    args: argparse.Namespace,
    build: Path,
    word: int,
    mode: str,
    seed: int,
    model_text: str,
    baseline: dict[str, Any],
) -> dict[str, Any]:
    work = build / f"word_{word:03d}" / mode / f"seed_{seed}"
    waveform, elapsed, deck_path = run_deck(
        args,
        work,
        switched_deck(
            word,
            model_text,
            stop_us=args.stop_us,
            step_ns=args.step_ns,
            mode=mode,
            seed=seed,
            noise_fmin_hz=args.noise_fmin_hz,
            noise_fmax_hz=args.noise_fmax_hz,
            oversample=args.oversample,
            noise_scale=args.noise_scale,
            noise_debug=args.noise_debug,
            precondition_us=args.precondition_us,
        ),
        args.timeout,
    )
    measured_metrics = waveform_metrics(
        baseline["waveform"],
        waveform,
        settle_us=args.settle_us,
        band_low_hz=args.noise_fmin_hz,
        receiver_cutoff_hz=args.receiver_cutoff_hz,
    )
    physical_metrics = {
        key: (
            float(value) / args.noise_scale
            if key.endswith("_v")
            else value
        )
        for key, value in measured_metrics.items()
    }
    finite = all(
        math.isfinite(float(value))
        for value in physical_metrics.values()
        if isinstance(value, float)
    )
    return {
        "status": "pass" if finite else "fail",
        "word": word,
        "mode": mode,
        "seed": seed,
        "metrics": physical_metrics,
        "measured_scaled_metrics": measured_metrics,
        "noise_amplitude_extrapolation_factor": 1.0 / args.noise_scale,
        "elapsed_s": elapsed,
        "deck_sha256": CHANNEL.sha256(deck_path),
    }


def summarize_mode(cases: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    selected = [case for case in cases if case["mode"] == mode]
    by_word: dict[str, Any] = {}
    for word in sorted({int(case["word"]) for case in selected}):
        word_cases = [case for case in selected if int(case["word"]) == word]
        values = np.asarray(
            [case["metrics"]["periodogram_band_rms_v"] for case in word_cases]
        )
        by_word[str(word)] = {
            "seed_count": len(word_cases),
            "mean_periodogram_band_rms_v": float(np.mean(values)),
            "sample_standard_deviation_v": (
                float(np.std(values, ddof=1)) if values.size > 1 else None
            ),
            "minimum_v": float(np.min(values)),
            "maximum_v": float(np.max(values)),
        }
    word_means = np.asarray(
        [entry["mean_periodogram_band_rms_v"] for entry in by_word.values()]
    )
    return {
        "case_count": len(selected),
        "by_word": by_word,
        "mean_over_cases_v": float(
            np.mean(
                [case["metrics"]["periodogram_band_rms_v"] for case in selected]
            )
        ),
        "state_span_db": (
            float(20.0 * math.log10(np.max(word_means) / np.min(word_means)))
            if word_means.size > 1 and np.min(word_means) > 0
            else 0.0
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vacask-bin", type=Path, required=True)
    parser.add_argument("--module-dir", type=Path, required=True)
    parser.add_argument("--include-dir", type=Path, required=True)
    parser.add_argument("--python-dir", type=Path, required=True)
    parser.add_argument("--runtime-lib-dir", type=Path)
    parser.add_argument("--ngspice", type=Path, default=Path("/usr/bin/ngspice"))
    parser.add_argument("--model-build", type=Path, default=DEFAULT_MODEL_BUILD)
    parser.add_argument("--channel-build", type=Path, default=DEFAULT_CHANNEL_BUILD)
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--words", type=lambda value: int(value, 0), nargs="+")
    parser.add_argument("--seeds", type=int, nargs="+", default=DEFAULT_SEEDS)
    parser.add_argument(
        "--primary-mode", choices=("sde", "zoh"), default="zoh"
    )
    parser.add_argument("--stop-us", type=float, default=110.0)
    parser.add_argument("--settle-us", type=float, default=10.0)
    parser.add_argument("--step-ns", type=float, default=0.25)
    parser.add_argument("--noise-fmin-hz", type=float, default=10e3)
    parser.add_argument("--noise-fmax-hz", type=float, default=64e6)
    parser.add_argument("--receiver-cutoff-hz", type=float, default=2e6)
    parser.add_argument("--oversample", type=int, default=2)
    parser.add_argument("--noise-scale", type=float, default=1e-5)
    parser.add_argument("--noise-debug", type=int, default=0)
    parser.add_argument("--precondition-us", type=float, default=20.0)
    parser.add_argument(
        "--scale-linearity-summary", type=Path, default=DEFAULT_SCALE_BUILD / "summary.json"
    )
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument(
        "--reuse-completed",
        action="store_true",
        help=(
            "reuse a raw waveform only when its deck is byte-identical and "
            "the waveform reaches the requested stop time"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build = args.build.resolve()
    build.mkdir(parents=True, exist_ok=True)
    for path in (
        args.vacask_bin,
        args.module_dir,
        args.include_dir,
        args.python_dir,
        args.model_build,
        args.channel_build,
    ):
        if not path.exists():
            raise FileNotFoundError(path)
    channel_summary_path = args.channel_build / "summary.json"
    channel_summary = json.loads(channel_summary_path.read_text())
    if channel_summary.get("status") != "pass":
        raise RuntimeError("complete noiseless channel qualification is not passing")
    model_text, model_hashes = CHANNEL.qualified_models(args.model_build.resolve())
    required_words = [entry.word for entry in CHANNEL.phase_table(8)]
    selected_words = args.words if args.words is not None else required_words
    unknown = sorted(set(selected_words) - set(required_words))
    if unknown:
        raise ValueError(f"unknown phase-table words: {unknown}")
    if args.jobs < 1 or args.oversample < 1:
        raise ValueError("jobs and oversample must be positive")
    if not 0.0 < args.noise_scale <= 1.0:
        raise ValueError("noise-scale must be in (0, 1]")
    if not 0 <= args.settle_us < args.stop_us:
        raise ValueError("settle-us must be nonnegative and less than stop-us")
    baselines: dict[int, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            word: pool.submit(run_baseline, args, build, word, model_text)
            for word in selected_words
        }
        for word in selected_words:
            baselines[word] = futures[word].result()
    requested_cases = [
        (word, args.primary_mode, seed)
        for word in selected_words
        for seed in args.seeds
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            key: pool.submit(
                run_noise_case,
                args,
                build,
                key[0],
                key[1],
                key[2],
                model_text,
                baselines[key[0]],
            )
            for key in requested_cases
        }
        cases = [futures[key].result() for key in requested_cases]
    mode_summary = {
        mode: summarize_mode(cases, mode)
        for mode in ("zoh", "sde")
        if any(case["mode"] == mode for case in cases)
    }
    full_primary_coverage = (
        set(selected_words) == set(required_words)
        and len(set(args.seeds)) >= len(DEFAULT_SEEDS)
        and all(
            len(
                {
                    case["seed"]
                    for case in cases
                    if case["word"] == word and case["mode"] == args.primary_mode
                }
            )
            >= len(DEFAULT_SEEDS)
            for word in required_words
        )
    )
    all_numerically_valid = all(case["status"] == "pass" for case in cases)
    scale_linearity = None
    scale_linearity_passed = args.noise_scale == 1.0
    if args.noise_scale < 1.0 and args.scale_linearity_summary.exists():
        scale_linearity = json.loads(args.scale_linearity_summary.read_text())
        qualified = scale_linearity.get("configuration", {})
        scale_linearity_passed = (
            scale_linearity.get("status") == "pass"
            and math.isclose(
                float(qualified.get("production_scale", math.nan)),
                args.noise_scale,
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            and math.isclose(
                float(qualified.get("stop_us", math.nan)),
                args.stop_us,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            and qualified.get("source_noise_band_hz")
            == [args.noise_fmin_hz, args.noise_fmax_hz]
        )
    status = (
        "pass_pending_frequency_domain_crosscheck"
        if all_numerically_valid and full_primary_coverage and scale_linearity_passed
        else "diagnostic_only" if all_numerically_valid else "fail"
    )
    report = {
        "schema_version": 1,
        "status": status,
        "scope": (
            "TT schematic complete-channel intrinsic transient noise with driven "
            "4 MHz quadrature switching and a numerical two-pole 2 MHz receiver"
        ),
        "platform": platform.platform(),
        "python": sys.version,
        "numpy": np.__version__,
        "vacask_binary_sha256": CHANNEL.sha256(args.vacask_bin),
        "vacask_bsim4_osdi_sha256": CHANNEL.sha256(
            args.module_dir / "spice/bsim4v8.osdi"
        ),
        "qualified_model_sha256": model_hashes,
        "model_qualification_summary_sha256": CHANNEL.sha256(
            args.model_build / "summary.json"
        ),
        "channel_qualification_summary_sha256": CHANNEL.sha256(channel_summary_path),
        "scale_linearity_summary_sha256": (
            CHANNEL.sha256(args.scale_linearity_summary)
            if scale_linearity is not None
            else None
        ),
        "configuration": {
            "required_words": required_words,
            "selected_words": selected_words,
            "primary_mode": args.primary_mode,
            "primary_seeds": args.seeds,
            "stop_us": args.stop_us,
            "settle_us": args.settle_us,
            "step_ns": args.step_ns,
            "source_noise_band_hz": [args.noise_fmin_hz, args.noise_fmax_hz],
            "receiver_cutoff_hz": args.receiver_cutoff_hz,
            "oversample": args.oversample,
            "noise_scale": args.noise_scale,
            "precondition_us": args.precondition_us,
            "reuse_completed": args.reuse_completed,
        },
        "coverage": {
            "all_eight_words_with_at_least_four_primary_mode_seeds": full_primary_coverage,
            "all_cases_numerically_valid": all_numerically_valid,
            "noise_amplitude_scaling_is_independently_qualified": scale_linearity_passed,
            "reused_baseline_count": sum(
                baseline["elapsed_s"] == 0.0 for baseline in baselines.values()
            ),
            "reused_noise_case_count": sum(
                case["elapsed_s"] == 0.0 for case in cases
            ),
        },
        "baselines": {
            str(word): {
                "elapsed_s": baseline["elapsed_s"],
                "deck_sha256": baseline["deck_sha256"],
            }
            for word, baseline in baselines.items()
        },
        "cases": cases,
        "mode_summary": mode_summary,
        "limitations": [
            "VACASK has no native PNoise/HBNoise analysis; this is a driven intrinsic transient-noise equivalent.",
            "Physical-amplitude compact-model transient noise causes timestep collapse; the passing scale-linearity qualification is required before reduced-amplitude ZOH results are extrapolated to unity.",
            "The finite record directly estimates only the source-noise band beginning at 10 kHz; 10 Hz-to-10 kHz flicker noise requires a separate frequency-domain bound.",
            "The receiver filter is applied numerically after the simulated 500 ohm/10 pF output path.",
            "This is schematic-only and excludes clock-source phase noise, package noise, and layout parasitics.",
            "The gate remains open until the independent frequency-domain folding calculation agrees within its declared tolerance.",
        ],
    }
    summary_path = build / "summary.json"
    summary_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
