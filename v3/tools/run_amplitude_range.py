#!/usr/bin/env python3
"""Verify bounded outer-to-inner raw-vector amplitude range over PVT."""

from __future__ import annotations

import concurrent.futures
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))
sys.path.insert(0, str(ROOT / "v3/model"))

import run_one_channel_vector_sweep as sweep  # noqa: E402
from beamformer_v3 import constellation, phase_table, unpack_group_codes, vector_from_word  # noqa: E402


BUILD = ROOT / "build/v3/amplitude_range"
CORNERS = {
    "tt_1p80v_27c": ("tt", 1.80, 27.0),
    "sf_1p80v_27c": ("sf", 1.80, 27.0),
    "fs_1p80v_27c": ("fs", 1.80, 27.0),
    "ff_1p98v_minus40c": ("ff", 1.98, -40.0),
    "ss_1p62v_85c": ("ss", 1.62, 85.0),
}
INNER_POINTS = ((1, 0), (0, 1), (-1, 0), (0, -1))


def entry(word: int, phase: float) -> Any:
    value = vector_from_word(word)
    return SimpleNamespace(
        word=word,
        group_codes=unpack_group_codes(word),
        target_phase_deg=phase,
        i_code=int(value.real),
        q_code=int(value.imag),
    )


def phase_delta(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def run_one(args: tuple[str, str, float, float, str, Any]) -> tuple[str, str, dict[str, Any]]:
    corner_name, process, supply, temperature, level, item = args
    result = sweep.run_case(
        item, "ngspice", "mos", process, supply, temperature,
        1.2, 0.65, 0.005, 10.0,
    )
    return corner_name, level, result


def main() -> None:
    outer = [phase_table(8)[index] for index in (0, 2, 4, 6)]
    points = constellation()
    inner = [entry(points[point], 90.0 * index) for index, point in enumerate(INNER_POINTS)]
    jobs = []
    for corner_name, (process, supply, temperature) in CORNERS.items():
        for index in range(4):
            jobs.append((corner_name, process, supply, temperature, f"outer_{index}", outer[index]))
            jobs.append((corner_name, process, supply, temperature, f"inner_{index}", inner[index]))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        raw = list(pool.map(run_one, jobs))
    by_corner: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in CORNERS}
    for corner, level, result in raw:
        by_corner[corner][level] = result
    corner_reports = {}
    for corner, cases in by_corner.items():
        states = []
        for index in range(4):
            outer_case = cases[f"outer_{index}"]
            inner_case = cases[f"inner_{index}"]
            states.append({
                "phase_deg": 90.0 * index,
                "outer_word": outer_case["word"],
                "inner_word": inner_case["word"],
                "outer_tone_peak_v": outer_case["tone_peak_v"],
                "inner_tone_peak_v": inner_case["tone_peak_v"],
                "amplitude_range_db": 20.0 * math.log10(
                    outer_case["tone_peak_v"] / inner_case["tone_peak_v"]
                ),
                "inner_to_outer_phase_delta_deg": phase_delta(
                    inner_case["raw_phase_deg"], outer_case["raw_phase_deg"]
                ),
                "minimum_output_common_mode_v": min(
                    outer_case["output_common_mode_v"], inner_case["output_common_mode_v"]
                ),
            })
        corner_reports[corner] = {
            "minimum_amplitude_range_db": min(item["amplitude_range_db"] for item in states),
            "worst_inner_to_outer_phase_delta_deg": max(
                abs(item["inner_to_outer_phase_delta_deg"]) for item in states
            ),
            "minimum_output_common_mode_v": min(item["minimum_output_common_mode_v"] for item in states),
            "states": states,
        }
    gate = {
        "minimum_cardinal_amplitude_range_at_least_12db": min(
            item["minimum_amplitude_range_db"] for item in corner_reports.values()
        ) >= 12.0,
        "inner_to_outer_phase_delta_at_most_5deg": max(
            item["worst_inner_to_outer_phase_delta_deg"] for item in corner_reports.values()
        ) <= 5.0,
        "output_common_mode_at_least_0p8v": min(
            item["minimum_output_common_mode_v"] for item in corner_reports.values()
        ) >= 0.8,
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(gate.values()) else "fail",
        "scope": "five-corner cardinal outer-to-inner raw-vector amplitude range; schematic and deterministic",
        "outer_ideal_radius": 11.0,
        "inner_ideal_radius": 1.0,
        "gate": gate,
        "corners": corner_reports,
        "limitations": [
            "cardinal phases only",
            "inner-state mismatch and noise floor are covered separately",
            "no selector or layout parasitics",
        ],
    }
    BUILD.mkdir(parents=True, exist_ok=True)
    output = BUILD / "summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": report["status"],
        "gate": gate,
        "minimum_amplitude_range_db": min(
            item["minimum_amplitude_range_db"] for item in corner_reports.values()
        ),
        "worst_phase_delta_deg": max(
            item["worst_inner_to_outer_phase_delta_deg"] for item in corner_reports.values()
        ),
    }, indent=2, sort_keys=True))
    print(f"report={output.relative_to(ROOT)}")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
