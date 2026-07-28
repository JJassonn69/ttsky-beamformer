#!/usr/bin/env python3
"""Calibrate and independently validate one frozen codebook per mismatched die.

Each deterministic mismatch seed represents one fabricated die.  A 20 mV-peak
known calibration tone is used to choose that die's eight raw words.  The
codebook is then frozen and checked on a separate 5 mV-peak validation run of
the same physical die.  This tests codebook generalization across signal level;
it does not model measurement noise, aging, temperature drift, passive
mismatch, spatial correlation, package effects, or extracted layout.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

import run_mismatch_calibration_split as mismatch  # noqa: E402
from run_gate5_mismatch_pilot import build_model_bundle  # noqa: E402


BUILD = ROOT / "build/v3/per_die_calibration_validation"


def run_frozen_codebooks(
    seeds: tuple[int, ...],
    codebooks: dict[int, dict[int, int]],
    factors: dict[int, dict[str, dict[str, float]]],
    model_include: Path,
    ngspice: str,
    jobs: int,
    resume: bool,
) -> dict[int, dict[int, dict[str, Any]]]:
    """Validate only the eight words that the corresponding die will use."""

    name = "validation_5mv"
    output: dict[int, dict[int, dict[str, Any]]] = {seed: {} for seed in seeds}
    pending: list[tuple[int, int]] = []
    reused = 0
    for seed in seeds:
        for word in sorted(set(codebooks[seed].values())):
            prior = mismatch.reusable_case(
                name, seed, word, factors[seed], model_include,
                input_peak_v=0.005,
            ) if resume else None
            if prior is None:
                pending.append((seed, word))
            else:
                output[seed][word] = prior
                reused += 1
    total = reused + len(pending)
    if reused:
        print(f"{name}: reused {reused}/{total} hash-identical cases", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(
                mismatch.run_case, name, seed, word, factors[seed],
                model_include, ngspice, input_peak_v=0.005,
            ): (seed, word)
            for seed, word in pending
        }
        for count, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            seed, word = futures[future]
            output[seed][word] = future.result()
            if count % 64 == 0 or count == len(futures):
                print(f"{name}: ran {count}/{len(futures)} pending cases", flush=True)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dies", type=int, default=16)
    parser.add_argument("--candidates-per-state", type=int, default=2)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--prepare-only", action="store_true",
        help="freeze factor values and model files without launching ngspice",
    )
    return parser.parse_args()


def load_or_create_factor_values(
    seeds: tuple[int, ...],
) -> tuple[dict[int, dict[str, dict[str, float]]], Path]:
    """Persist actual Gaussian values so ARM and x86 use identical decks."""

    path = BUILD / "factor_values.json"
    if path.is_file():
        serialized = json.loads(path.read_text())
        if {int(seed) for seed in serialized} != set(seeds):
            raise RuntimeError("frozen factor-value seed set does not match requested dies")
        factors = {
            int(seed): {
                device: {parameter: float(value) for parameter, value in values.items()}
                for device, values in devices.items()
            }
            for seed, devices in serialized.items()
        }
    else:
        factors = {seed: mismatch.mismatch_factors(seed) for seed in seeds}
        path.write_text(json.dumps(factors, indent=2, sort_keys=True) + "\n")
    for seed, values in factors.items():
        if set(values) != set(mismatch.device_names()):
            raise RuntimeError(f"frozen factor-value device set changed for seed {seed}")
    return factors, path


def main() -> None:
    args = parse_args()
    if min(args.dies, args.candidates_per_state, args.jobs) < 1:
        raise SystemExit("all counts must be positive")

    BUILD.mkdir(parents=True, exist_ok=True)
    mismatch.BUILD = BUILD
    model_include, model_manifest = build_model_bundle(BUILD)
    seeds = tuple(range(4001, 4001 + args.dies))
    factors, factor_values_path = load_or_create_factor_values(seeds)
    manifests = {
        str(seed): mismatch.factor_manifest(seed, factors[seed]) for seed in seeds
    }
    manifest_path = BUILD / "factor_manifests.json"
    manifest_path.write_text(json.dumps(manifests, indent=2, sort_keys=True) + "\n")
    if args.prepare_only:
        print(json.dumps({
            "factor_values": str(factor_values_path.relative_to(ROOT)),
            "factor_values_sha256": mismatch.sha256(factor_values_path),
            "model_bundle_sha256": model_manifest["bundle_sha256"],
        }, indent=2, sort_keys=True))
        return

    candidates = mismatch.candidate_words(args.candidates_per_state)
    calibration_words = tuple(sorted({word for words in candidates.values() for word in words}))
    calibration = mismatch.run_population(
        "calibration_20mv", seeds, calibration_words, factors, model_include,
        args.ngspice, min(args.jobs, 12), args.resume, input_peak_v=0.020,
    )

    codebooks: dict[int, dict[int, int]] = {}
    scoring: dict[str, Any] = {}
    calibration_metrics: dict[str, Any] = {}
    for seed in seeds:
        codebook, seed_scoring = mismatch.select_codebook(
            {seed: calibration[seed]}, candidates
        )
        codebooks[seed] = codebook
        scoring[str(seed)] = seed_scoring
        calibration_metrics[str(seed)] = mismatch.population_metrics(
            {seed: calibration[seed]}, codebook
        )["seeds"][str(seed)]

    validation = run_frozen_codebooks(
        seeds, codebooks, factors, model_include, args.ngspice,
        min(args.jobs, 12), args.resume,
    )

    validation_metrics: dict[str, Any] = {}
    for seed in seeds:
        validation_metrics[str(seed)] = mismatch.population_metrics(
            {seed: validation[seed]}, codebooks[seed]
        )["seeds"][str(seed)]

    aggregate = {
        "die_count": len(seeds),
        "worst_phase_error_deg": max(
            item["worst_phase_error_deg"] for item in validation_metrics.values()
        ),
        "worst_gain_span_db": max(
            item["gain_span_db"] for item in validation_metrics.values()
        ),
        "minimum_output_common_mode_v": min(
            item["minimum_output_common_mode_v"] for item in validation_metrics.values()
        ),
    }
    gate = {
        "codebook_is_independently_selected_per_die": len(codebooks) == len(seeds),
        "every_die_has_eight_unique_state_words": all(
            len(set(codebook.values())) == 8 for codebook in codebooks.values()
        ),
        "calibration_and_validation_input_levels_are_distinct": 0.020 != 0.005,
        "validation_worst_phase_error_at_most_5deg": aggregate["worst_phase_error_deg"] <= 5.0,
        "validation_worst_gain_span_at_most_0p5db": aggregate["worst_gain_span_db"] <= 0.5,
        "validation_output_common_mode_at_least_0p8v": aggregate["minimum_output_common_mode_v"] >= 0.8,
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(gate.values()) else "fail",
        "scope": "TT one-channel open-PDK MOS mismatch sensitivity with per-die calibration; not foundry-qualified yield",
        "method": model_manifest["method"],
        "execution_environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "ngspice_version": subprocess.run(
                [args.ngspice, "--version"], text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, check=True,
            ).stdout.splitlines()[0:3],
            "resume_requested": args.resume,
        },
        "calibration": {
            "input_peak_v": 0.020,
            "candidate_words_per_state": args.candidates_per_state,
            "word_count": len(calibration_words),
            "sample": "deterministic 20 mV calibration transient",
        },
        "validation": {
            "input_peak_v": 0.005,
            "word_count_per_die": 8,
            "total_case_count": sum(
                len(set(codebook.values())) for codebook in codebooks.values()
            ),
            "sample": "separate deterministic 5 mV validation transient with frozen codebook",
        },
        "independence_contract": (
            "Calibration and validation use separate SPICE decks and signal amplitudes "
            "on the same mismatch realization. No validation result participates in "
            "code selection. Deterministic simulation does not include measurement noise."
        ),
        "seeds": list(seeds),
        "factor_manifests": str(manifest_path.relative_to(ROOT)),
        "factor_manifests_sha256": mismatch.sha256(manifest_path),
        "factor_values": str(factor_values_path.relative_to(ROOT)),
        "factor_values_sha256": mismatch.sha256(factor_values_path),
        "model_bundle_sha256": model_manifest["bundle_sha256"],
        "selected_codebooks": {
            str(seed): {str(state): word for state, word in codebooks[seed].items()}
            for seed in seeds
        },
        "selection_scoring": scoring,
        "calibration_metrics_by_die": calibration_metrics,
        "validation_metrics_by_die": validation_metrics,
        "validation_metrics": aggregate,
        "gate": gate,
        "limitations": model_manifest["limitations"] + [
            "schematic flattened channel without passive mismatch or layout parasitics",
            "independent Gaussian device factors omit spatial correlation and systematic gradients",
            "calibration and validation are deterministic and omit measurement noise and drift",
            "sixteen mismatch realizations are a bounded design screen, not a yield estimate",
        ],
    }
    output = BUILD / "summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "gate": gate, **aggregate}, indent=2, sort_keys=True))
    print(f"report={output.relative_to(ROOT)}")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
