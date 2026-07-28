#!/usr/bin/env python3
"""Qualify reduced-amplitude VACASK transient-noise extrapolation.

The full SKY130-derived switched compact-model circuit cannot converge when
VACASK injects unity-amplitude transient noise directly.  This runner applies
the same normalized random sequence at three stable amplitudes and requires
the measured output noise to remain linear before the production campaign is
allowed to extrapolate the 0.01-amplitude result to physical unity.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import math
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILD = ROOT / "build/v3/vacask_noise_scale_linearity"
DEFAULT_MODEL_BUILD = ROOT / "build/v3/vacask_sky130_qualification"
DEFAULT_CHANNEL_BUILD = ROOT / "build/v3/vacask_channel_qualification"
DEFAULT_SCALES = (1e-5, 3e-5, 1e-4)


def load_runner() -> Any:
    path = Path(__file__).with_name("run_vacask_switched_noise.py")
    spec = importlib.util.spec_from_file_location("v3_switched_noise", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load_runner()
CHANNEL = RUNNER.CHANNEL


def scale_args(args: argparse.Namespace, scale: float) -> argparse.Namespace:
    values = vars(args).copy()
    values["noise_scale"] = scale
    return argparse.Namespace(**values)


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
    parser.add_argument("--word", type=lambda value: int(value, 0), default=8)
    parser.add_argument("--seed", type=int, default=104729)
    parser.add_argument("--scales", type=float, nargs="+", default=DEFAULT_SCALES)
    parser.add_argument("--production-scale", type=float, default=1e-5)
    parser.add_argument("--primary-mode", choices=("zoh", "sde"), default="zoh")
    parser.add_argument("--stop-us", type=float, default=110.0)
    parser.add_argument("--settle-us", type=float, default=10.0)
    parser.add_argument("--precondition-us", type=float, default=20.0)
    parser.add_argument("--step-ns", type=float, default=0.25)
    parser.add_argument("--noise-fmin-hz", type=float, default=10e3)
    parser.add_argument("--noise-fmax-hz", type=float, default=64e6)
    parser.add_argument("--receiver-cutoff-hz", type=float, default=2e6)
    parser.add_argument("--oversample", type=int, default=2)
    parser.add_argument("--noise-debug", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--jobs", type=int, default=3)
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
    if len(set(args.scales)) < 3 or any(not 0.0 < scale < 1.0 for scale in args.scales):
        raise ValueError("at least three unique scales in (0, 1) are required")
    channel_summary = json.loads((args.channel_build / "summary.json").read_text())
    if channel_summary.get("status") != "pass":
        raise RuntimeError("complete noiseless channel qualification is not passing")
    model_text, model_hashes = CHANNEL.qualified_models(args.model_build.resolve())
    baseline_args = scale_args(args, max(args.scales))
    baseline = RUNNER.run_baseline(
        baseline_args, build / "common", args.word, model_text
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            scale: pool.submit(
                RUNNER.run_noise_case,
                scale_args(args, scale),
                build / f"scale_{scale:.6g}",
                args.word,
                args.primary_mode,
                args.seed,
                model_text,
                baseline,
            )
            for scale in args.scales
        }
        cases = [futures[scale].result() for scale in args.scales]
    measured = np.asarray(
        [case["measured_scaled_metrics"]["periodogram_band_rms_v"] for case in cases]
    )
    scales = np.asarray(args.scales, dtype=float)
    physical = measured / scales
    slope = float(np.dot(scales, measured) / np.dot(scales, scales))
    fitted = scales * slope
    residual_sum = float(np.sum((measured - fitted) ** 2))
    total_sum = float(np.sum((measured - np.mean(measured)) ** 2))
    r_squared = 1.0 - residual_sum / total_sum if total_sum > 0 else 1.0
    span_db = float(20.0 * math.log10(np.max(physical) / np.min(physical)))
    endpoint_delta_percent = float(
        100.0 * (physical[-1] / physical[0] - 1.0)
    )
    gates = {
        "all_scale_runs_numerically_valid": all(case["status"] == "pass" for case in cases),
        "through_origin_r_squared_at_least_0p999": r_squared >= 0.999,
        "extrapolated_noise_span_no_more_than_0p25db": span_db <= 0.25,
        "production_scale_is_in_qualified_sweep": any(
            math.isclose(scale, args.production_scale, rel_tol=0.0, abs_tol=1e-15)
            for scale in args.scales
        ),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(gates.values()) else "fail",
        "scope": (
            "same-seed reduced-amplitude linearity qualification for complete "
            "driven switched-channel intrinsic transient noise"
        ),
        "platform": platform.platform(),
        "python": sys.version,
        "numpy": np.__version__,
        "vacask_binary_sha256": CHANNEL.sha256(args.vacask_bin),
        "vacask_bsim4_osdi_sha256": CHANNEL.sha256(
            args.module_dir / "spice/bsim4v8.osdi"
        ),
        "qualified_model_sha256": model_hashes,
        "configuration": {
            "word": args.word,
            "seed": args.seed,
            "mode": args.primary_mode,
            "scales": list(args.scales),
            "production_scale": args.production_scale,
            "stop_us": args.stop_us,
            "settle_us": args.settle_us,
            "precondition_us": args.precondition_us,
            "step_ns": args.step_ns,
            "source_noise_band_hz": [args.noise_fmin_hz, args.noise_fmax_hz],
            "receiver_cutoff_hz": args.receiver_cutoff_hz,
            "oversample": args.oversample,
        },
        "baseline": {
            "elapsed_s": baseline["elapsed_s"],
            "deck_sha256": baseline["deck_sha256"],
        },
        "cases": cases,
        "fit": {
            "measured_rms_per_unit_scale_v": slope,
            "through_origin_r_squared": r_squared,
            "extrapolated_noise_span_db": span_db,
            "endpoint_extrapolated_delta_percent": endpoint_delta_percent,
            "extrapolated_periodogram_band_rms_v": physical.tolist(),
        },
        "gates": gates,
        "limitations": [
            "This validates linear extrapolation of the simulator result; it does not replace the independent frequency-domain folding crosscheck.",
            "One representative cardinal word and one fixed normalized random sequence are used so amplitude scaling is isolated from Monte Carlo scatter.",
            f"The {args.production_scale:g} production scale is extrapolated by {1.0 / args.production_scale:g} to physical unity only after this gate passes.",
        ],
    }
    summary = build / "summary.json"
    summary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
