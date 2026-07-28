#!/usr/bin/env python3
"""Fast pre-layout proxy screen for proposed fixed tail-bank counts.

This is a Gate-1 decision aid, not release signoff.  The current layout has 36
always-on tail units.  A proposed bank with F fixed units and reset code 8 has
the same active-unit count as the current layout at trim code F - 28.  The
proxy preserves DC active-unit count while avoiding layout regeneration for
architectures that should be rejected cheaply.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "v2/tools/run_control_postlayout_smoke.py"
BUILD = ROOT / "build/v2/tail_headroom_screen"
CURRENT_FIXED_UNITS = 36
RESET_CODE = 8
TRIM_PROGRAM_COMPLETE_US = 0.842
MINIMUM_SETTLING_US = 1.0
ANALYSIS_START_US = 2.0
ANALYSIS_STOP_US = 3.0


@dataclass(frozen=True)
class Corner:
    name: str
    process: str
    passive: str
    supply_v: float
    temperature_c: float


# Small architecture-screening set.  The complete PVT matrix belongs to a
# frozen candidate at a later gate.
CORNERS = (
    Corner("nominal", "tt", "tt", 1.80, 27.0),
    Corner("observed_low_cm", "sf", "tt", 1.80, 27.0),
    Corner("fast_high_supply_cold", "ff", "hh", 1.98, -40.0),
    Corner("slow_low_supply_hot", "ss", "ll", 1.62, 85.0),
)


def proxy_trim_code(proposed_fixed_units: int) -> int:
    """Map a proposed reset bank to the equivalent current-layout trim code."""
    code = proposed_fixed_units + RESET_CODE - CURRENT_FIXED_UNITS
    if not 0 <= code <= 15:
        raise ValueError(
            f"{proposed_fixed_units} fixed units require unsupported proxy code {code}"
        )
    return code


def validate_screen_timing(
    analysis_start_us: float = ANALYSIS_START_US,
    analysis_stop_us: float = ANALYSIS_STOP_US,
) -> None:
    if analysis_start_us - TRIM_PROGRAM_COMPLETE_US < MINIMUM_SETTLING_US:
        raise ValueError(
            "tail screen must allow at least 1 us after trim programming before measurement"
        )
    if analysis_stop_us - analysis_start_us < 1.0:
        raise ValueError("tail screen measurement window must span at least 1 us")


def parse_counts(text: str) -> list[int]:
    try:
        counts = sorted({int(item.strip()) for item in text.split(",")})
    except ValueError as error:
        raise argparse.ArgumentTypeError("fixed counts must be integers") from error
    if not counts:
        raise argparse.ArgumentTypeError("at least one fixed count is required")
    try:
        for count in counts:
            proxy_trim_code(count)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return counts


def report_path_from_output(output: str) -> Path | None:
    for line in reversed(output.splitlines()):
        if line.startswith("report="):
            path = Path(line.removeprefix("report="))
            return path if path.is_absolute() else ROOT / path
    return None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def conservative_node_proxies(
    measurements: dict[str, Any], supply_v: float
) -> dict[str, float | None]:
    """Return cheap, deliberately conservative node-level headroom proxies.

    Minima and maxima are not time aligned, so these values can only reject a
    candidate or trigger deeper device analysis.  They cannot prove MOS
    saturation and do not replace model-derived VDS-VDSAT/VGS-VTH checks.
    """
    required = [
        f"ch{channel}_{node}_{edge}"
        for channel in range(4)
        for node in ("gm_p", "gm_n", "tail")
        for edge in ("min", "max")
    ]
    required += [
        "core_output_p_min", "core_output_p_max",
        "core_output_n_min", "core_output_n_max",
    ]
    if any(name not in measurements for name in required):
        return {
            "minimum_gm_drain_to_tail_v": None,
            "minimum_tail_drain_to_ground_v": None,
            "minimum_core_output_rail_clearance_v": None,
            "minimum_time_aligned_gm_drain_to_tail_v": None,
        }
    gm_separations = []
    tail_minima = []
    for channel in range(4):
        tail_max = measurements[f"ch{channel}_tail_max"]
        tail_minima.append(measurements[f"ch{channel}_tail_min"])
        gm_separations.extend((
            measurements[f"ch{channel}_gm_p_min"] - tail_max,
            measurements[f"ch{channel}_gm_n_min"] - tail_max,
        ))
    output_clearances = (
        measurements["core_output_p_min"],
        measurements["core_output_n_min"],
        supply_v - measurements["core_output_p_max"],
        supply_v - measurements["core_output_n_max"],
    )
    aligned_names = [
        f"ch{channel}_{branch}_vds_min"
        for channel in range(4)
        for branch in ("gm_p", "gm_n")
    ]
    return {
        "minimum_gm_drain_to_tail_v": min(gm_separations),
        "minimum_tail_drain_to_ground_v": min(tail_minima),
        "minimum_core_output_rail_clearance_v": min(output_clearances),
        "minimum_time_aligned_gm_drain_to_tail_v": (
            min(measurements[name] for name in aligned_names)
            if all(name in measurements for name in aligned_names)
            else None
        ),
    }


def run_case(
    fixed_units: int,
    corner: Corner,
    view: str,
    ngspice: str,
    timeout_s: int,
) -> dict[str, Any]:
    code = proxy_trim_code(fixed_units)
    command = [
        sys.executable,
        str(RUNNER),
        "--view", view,
        "--startup", "op",
        "--beam", "0",
        "--incident-beam", "0",
        "--channel-mask", "0xf",
        "--input-peak-v", "0",
        "--trim-codes", ",".join([str(code)] * 4),
        "--ngspice", ngspice,
        "--timeout", str(timeout_s),
        "--transient-step-ns", "10",
        # Non-default trim programming completes near 0.842 us.  Retain more
        # than 1 us of settling before measuring; the earlier 1..2 us screen
        # observed control transitions and rail overshoot rather than steady
        # operation.
        "--analysis-start-us", str(ANALYSIS_START_US),
        "--analysis-stop-us", str(ANALYSIS_STOP_US),
        "--process-corner", corner.process,
        "--passive-corner", corner.passive,
        "--supply-voltage-v", str(corner.supply_v),
        "--temperature-c", str(corner.temperature_c),
    ]
    completed = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, check=False
    )
    output = completed.stdout + completed.stderr
    path = report_path_from_output(output)
    record: dict[str, Any] = {
        "proposed_fixed_units": fixed_units,
        "reset_code": RESET_CODE,
        "trim_program_complete_us": TRIM_PROGRAM_COMPLETE_US,
        "minimum_settling_us": MINIMUM_SETTLING_US,
        "analysis_window_us": [ANALYSIS_START_US, ANALYSIS_STOP_US],
        "active_units_at_reset": fixed_units + RESET_CODE,
        "proxy_trim_code_on_current_layout": code,
        "corner": corner.name,
        "process_corner": corner.process,
        "passive_corner": corner.passive,
        "supply_voltage_v": corner.supply_v,
        "temperature_c": corner.temperature_c,
        "runner_returncode": completed.returncode,
        "view": view,
    }
    if path is None or not path.is_file():
        record.update(status="error", error="runner did not produce a report")
        return record
    report = json.loads(path.read_text(encoding="utf-8"))
    analysis = report.get("analysis", {})
    measurements = report.get("measurements", {})
    common_mode = analysis.get("output_common_mode_v")
    record.update(
        status=report.get("status", "error"),
        report=str(path.relative_to(ROOT)),
        report_sha256=sha256(path),
        output_common_mode_v=common_mode,
        output_common_mode_fraction_vdd=(
            common_mode / corner.supply_v if common_mode is not None else None
        ),
        vcm_v=analysis.get("vcm_v"),
        supply_current_a=analysis.get("supply_current_a"),
        estimated_power_w=analysis.get("estimated_power_w"),
        core_output_p_range_v=analysis.get("core_output_p_range_v"),
        core_output_n_range_v=analysis.get("core_output_n_range_v"),
        conservative_node_proxies=conservative_node_proxies(
            measurements, corner.supply_v
        ),
        errors=report.get("errors", []),
    )
    return record


def summarize(records: list[dict[str, Any]], view: str = "base") -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for fixed_units in sorted({item["proposed_fixed_units"] for item in records}):
        cases = [item for item in records if item["proposed_fixed_units"] == fixed_units]
        common_modes = [
            item["output_common_mode_v"]
            for item in cases
            if isinstance(item.get("output_common_mode_v"), (int, float))
        ]
        candidates.append({
            "proposed_fixed_units": fixed_units,
            "active_units_at_reset": fixed_units + RESET_CODE,
            "proxy_trim_code_on_current_layout": proxy_trim_code(fixed_units),
            "completed_cases": len(common_modes),
            "passing_runner_cases": sum(item["status"] == "pass" for item in cases),
            "output_common_mode_v_range": (
                [min(common_modes), max(common_modes)] if common_modes else None
            ),
            "ready_for_device_region_check": (
                len(common_modes) == len(CORNERS)
                and all(0.8 < value < 1.2 for value in common_modes)
            ),
        })
    return {
        "schema_version": 1,
        "purpose": "Gate-1 architecture proxy screen; not release signoff",
        "view": view,
        "current_fixed_units": CURRENT_FIXED_UNITS,
        "reset_code": RESET_CODE,
        "equivalence": "proposed_fixed+8 == current_fixed+proxy_code",
        "limitations": [
            "Uses the current physical layout as an active-unit-count proxy.",
            "Base extraction is the default for broad screening; correlate the limiting corner once with distributed RC.",
            "Does not replace exact regenerated-layout extraction.",
            "Common mode is a screen; device VGS-VTH and VDS-VDSAT decide headroom.",
            "Node proxies use non-time-aligned extrema and cannot prove saturation.",
            "Does not authorize exhaustive beam, trim, or PVT matrices.",
        ],
        "candidates": candidates,
        "cases": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed-counts", type=parse_counts, default=parse_counts("32,33,34"))
    parser.add_argument(
        "--view", choices=("base", "rc"), default="base",
        help="base is the Gate-1 default; use rc only for a focused correlation",
    )
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    validate_screen_timing()
    if not 1 <= args.jobs <= 4:
        raise SystemExit("--jobs must be between one and four")

    cases = [
        (fixed_units, corner)
        for fixed_units in args.fixed_counts
        for corner in CORNERS
    ]
    records: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                run_case, fixed, corner, args.view, args.ngspice, args.timeout
            ):
            (fixed, corner.name)
            for fixed, corner in cases
        }
        for future in concurrent.futures.as_completed(futures):
            record = future.result()
            records.append(record)
            print(
                f"fixed={record['proposed_fixed_units']} "
                f"corner={record['corner']} status={record['status']}",
                flush=True,
            )

    records.sort(key=lambda item: (item["proposed_fixed_units"], item["corner"]))
    summary = summarize(records, args.view)
    BUILD.mkdir(parents=True, exist_ok=True)
    path = BUILD / "summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"summary={path}")
    return 0 if all(
        item["completed_cases"] == len(CORNERS)
        for item in summary["candidates"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
