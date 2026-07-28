#!/usr/bin/env python3
"""Separate V3 gm, switch, tail, and bias-reference mismatch sensitivity."""

from __future__ import annotations

import concurrent.futures
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))
sys.path.insert(0, str(ROOT / "v3/model"))

import run_mismatch_calibration_split as mismatch  # noqa: E402
from beamformer_v3 import phase_table  # noqa: E402


BUILD = ROOT / "build/v3/mismatch_contributions"
CATEGORIES = {
    "gm_only": ("GM_P", "GM_N"),
    "switch_only": ("SW_PP", "SW_PN", "SW_NP", "SW_NN"),
    "tail_only": ("TAIL",),
    "bias_reference_only": ("BIAS_REF",),
    "all_devices": ("BIAS_REF", "GM_P", "GM_N", "SW_PP", "SW_PN", "SW_NP", "SW_NN", "TAIL"),
}


def category_factors(seed: int, enabled: tuple[str, ...]) -> dict[str, dict[str, float]]:
    factors = mismatch.mismatch_factors(seed)
    for device, parameters in factors.items():
        if not any(device.endswith(suffix) for suffix in enabled):
            for parameter in parameters:
                parameters[parameter] = 0.0
    return factors


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    model_include, model_manifest = mismatch.build_model_bundle(BUILD)
    seeds = tuple(range(2001, 2009))
    codebook = {entry.index: entry.word for entry in phase_table(8)}
    words = tuple(codebook.values())
    category_reports: dict[str, Any] = {}
    for category, enabled in CATEGORIES.items():
        factors = {seed: category_factors(seed, enabled) for seed in seeds}
        responses = {seed: {} for seed in seeds}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(
                    mismatch.run_case, category, seed, word, factors[seed],
                    model_include, "ngspice",
                ): (seed, word)
                for seed in seeds for word in words
            }
            for future in concurrent.futures.as_completed(futures):
                seed, word = futures[future]
                responses[seed][word] = future.result()
        metrics = mismatch.population_metrics(responses, codebook)
        category_reports[category] = {
            "enabled_instance_suffixes": list(enabled),
            "worst_phase_error_deg": metrics["worst_phase_error_deg"],
            "worst_gain_span_db": metrics["worst_gain_span_db"],
            "minimum_output_common_mode_v": metrics["minimum_output_common_mode_v"],
            "seed_count": metrics["seed_count"],
        }
        print(f"{category}: phase={metrics['worst_phase_error_deg']:.3f} deg gain={metrics['worst_gain_span_db']:.3f} dB", flush=True)
    report = {
        "schema_version": 1,
        "status": "characterization_complete",
        "scope": "eight-seed TT open-PDK coefficient mismatch attribution on the nominal eight-state codebook",
        "model_bundle_sha256": model_manifest["bundle_sha256"],
        "seeds": list(seeds),
        "categories": category_reports,
        "interpretation_rule": "compare each isolated category with all_devices; categories are not statistically additive",
        "limitations": model_manifest["limitations"] + [
            "schematic only",
            "eight sensitivity seeds are diagnostic rather than a yield population",
        ],
    }
    output = BUILD / "summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"report={output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
