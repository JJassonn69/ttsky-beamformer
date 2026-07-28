#!/usr/bin/env python3
"""Screen geometry root fixes for the V3 mismatch failure."""

from __future__ import annotations

import argparse
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


BUILD = ROOT / "build/v3/mismatch_geometry_sweep"
GEOMETRIES = {
    "baseline": {
        "gm_width_um": 0.42,
        "gm_length_um": 0.30,
        "switch_width_um": 0.65,
        "switch_length_um": 0.15,
        "tail_width_um": 2.533333333,
        "tail_length_um": 0.50,
        "bias_reference_width_um": 32.0,
        "bias_reference_length_um": 0.50,
    },
    "double_gm_area": {
        "gm_width_um": 0.84,
        "gm_length_um": 0.30,
        "switch_width_um": 0.65,
        "switch_length_um": 0.15,
        "tail_width_um": 2.533333333,
        "tail_length_um": 0.50,
        "bias_reference_width_um": 32.0,
        "bias_reference_length_um": 0.50,
    },
    "double_tail_mirror_area": {
        "gm_width_um": 0.42,
        "gm_length_um": 0.30,
        "switch_width_um": 0.65,
        "switch_length_um": 0.15,
        "tail_width_um": 5.066666666,
        "tail_length_um": 0.50,
        "bias_reference_width_um": 64.0,
        "bias_reference_length_um": 0.50,
    },
    "double_gm_and_tail_area": {
        "gm_width_um": 0.84,
        "gm_length_um": 0.30,
        "switch_width_um": 0.65,
        "switch_length_um": 0.15,
        "tail_width_um": 5.066666666,
        "tail_length_um": 0.50,
        "bias_reference_width_um": 64.0,
        "bias_reference_length_um": 0.50,
    },
    "quadruple_area_constant_aspect": {
        "gm_width_um": 0.84,
        "gm_length_um": 0.60,
        "switch_width_um": 0.65,
        "switch_length_um": 0.15,
        "tail_width_um": 5.066666666,
        "tail_length_um": 1.00,
        "bias_reference_width_um": 64.0,
        "bias_reference_length_um": 1.00,
    },
    "quadruple_area_by_width": {
        "gm_width_um": 1.68,
        "switch_width_um": 0.65,
        "tail_width_um": 10.133333332,
        "bias_reference_width_um": 128.0,
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", choices=tuple(GEOMETRIES))
    args = parser.parse_args()
    selected_geometries = {
        name: geometry for name, geometry in GEOMETRIES.items()
        if args.only is None or name in args.only
    }
    BUILD.mkdir(parents=True, exist_ok=True)
    model_include, model_manifest = mismatch.build_model_bundle(BUILD)
    seeds = tuple(range(3001, 3013))
    codebook = {entry.index: entry.word for entry in phase_table(8)}
    words = tuple(codebook.values())
    reports: dict[str, Any] = {}
    for name, geometry in selected_geometries.items():
        factors = {seed: mismatch.mismatch_factors(seed) for seed in seeds}
        responses = {seed: {} for seed in seeds}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(
                    mismatch.run_case, f"geometry_{name}", seed, word,
                    factors[seed], model_include, "ngspice", geometry,
                ): (seed, word)
                for seed in seeds for word in words
            }
            for future in concurrent.futures.as_completed(futures):
                seed, word = futures[future]
                responses[seed][word] = future.result()
        metrics = mismatch.population_metrics(responses, codebook)
        gates = {
            "worst_phase_error_at_most_5deg": metrics["worst_phase_error_deg"] <= 5.0,
            "worst_gain_span_at_most_0p5db": metrics["worst_gain_span_db"] <= 0.5,
            "minimum_output_common_mode_at_least_0p8v": metrics["minimum_output_common_mode_v"] >= 0.8,
        }
        reports[name] = {
            "geometry": geometry,
            "status": "pass" if all(gates.values()) else "fail",
            "gate": gates,
            "worst_phase_error_deg": metrics["worst_phase_error_deg"],
            "worst_gain_span_db": metrics["worst_gain_span_db"],
            "minimum_output_common_mode_v": metrics["minimum_output_common_mode_v"],
            "seed_count": metrics["seed_count"],
        }
        print(
            f"{name}: {reports[name]['status']} phase={metrics['worst_phase_error_deg']:.3f} "
            f"gain={metrics['worst_gain_span_db']:.3f}dB cm={metrics['minimum_output_common_mode_v']:.3f}V",
            flush=True,
        )
    passing = [name for name, report in reports.items() if report["status"] == "pass"]
    report = {
        "schema_version": 1,
        "status": "pass" if passing else "fail",
        "scope": "twelve-seed TT open-PDK mismatch geometry screen on the fixed nominal eight-state codebook",
        "model_bundle_sha256": model_manifest["bundle_sha256"],
        "seeds": list(seeds),
        "geometries": reports,
        "passing_geometries": passing,
        "selection_rule": "choose the smallest passing root-fix geometry, then rerun PVT, transition, spur, loading, and PCell gates",
        "limitations": model_manifest["limitations"] + [
            "schematic only",
            "geometry screen is not a final calibrated mismatch campaign",
        ],
    }
    output = BUILD / ("followup_summary.json" if args.only else "summary.json")
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"report={output.relative_to(ROOT)}")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
