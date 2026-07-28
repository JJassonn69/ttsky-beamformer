#!/usr/bin/env python3
"""Characterize and calibrate the four production post-layout gain trims."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import itertools
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "v2/tools/run_control_postlayout_smoke.py"
BUILD = ROOT / "build/v2/postlayout_trim"
SMOKE_BUILD = ROOT / "build/v2/postlayout_smoke"
GDS = ROOT / "build/v2/control_routing/direct/v2_control_quadrature_routed.gds"
NETLIST_BY_VIEW = {
    "base": ROOT / "build/v2/control_routing/final_rc/control_final_base.spice",
    "rc": ROOT / "build/v2/control_routing/final_rc/control_final_rc.spice",
}
MONOTONIC_TOLERANCE_DB = 0.01
MINIMUM_ADJACENT_STEP_DB = 0.03
MINIMUM_TRIM_SPAN_DB = 1.5
INJECTED_MISMATCH_STRESS_DB = (-0.6, -0.2, 0.2, 0.6)
MAXIMUM_STRESS_CALIBRATED_SPREAD_DB = 0.1
CALIBRATION_SIGNIFICANCE_FLOOR_DB = 0.01


def codes_for_case(channel: int, code: int) -> tuple[int, int, int, int]:
    codes = [8, 8, 8, 8]
    codes[channel] = code
    return tuple(codes)  # type: ignore[return-value]


def case_report_path(
    channel: int,
    code: int,
    view: str,
    transient_step_ns: float,
    analysis_start_us: float,
    analysis_stop_us: float,
) -> Path:
    codes = codes_for_case(channel, code)
    label = f"selected_0_incident_0_mask_{1 << channel:x}_startup_op"
    if analysis_start_us != 2.0 or analysis_stop_us != 4.0:
        label += (
            f"_window_{analysis_start_us:g}us_{analysis_stop_us:g}us"
        ).replace(".", "p")
    if transient_step_ns != 2.0:
        label += f"_step_{transient_step_ns:g}ns".replace(".", "p")
    if codes != (8, 8, 8, 8):
        label += "_trim_" + "_".join(str(item) for item in codes)
    return SMOKE_BUILD / view / "codebook" / label / "report.json"


def run_case(
    channel: int,
    code: int,
    view: str,
    ngspice: str,
    timeout: int,
    transient_step_ns: float,
    analysis_start_us: float,
    analysis_stop_us: float,
) -> tuple[int, int, int, str]:
    codes = codes_for_case(channel, code)
    command = [
        sys.executable,
        str(RUNNER),
        "--view", view,
        "--startup", "op",
        "--beam", "0",
        "--incident-beam", "0",
        "--channel-mask", hex(1 << channel),
        "--trim-codes", ",".join(str(item) for item in codes),
        "--ngspice", ngspice,
        "--timeout", str(timeout),
        "--transient-step-ns", str(transient_step_ns),
        "--analysis-start-us", str(analysis_start_us),
        "--analysis-stop-us", str(analysis_stop_us),
    ]
    completed = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, check=False
    )
    output = completed.stdout + completed.stderr
    return channel, code, completed.returncode, output


def report_path_from_output(output: str) -> Path | None:
    for line in reversed(output.splitlines()):
        if line.startswith("report="):
            path = Path(line.removeprefix("report="))
            return path if path.is_absolute() else ROOT / path
    return None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reusable_report(
    path: Path,
    channel: int,
    code: int,
    view: str,
    transient_step_ns: float,
    analysis_start_us: float,
    analysis_stop_us: float,
    gds_sha256: str,
    netlist_sha256: str,
) -> bool:
    """Return true only for an exact passing report from the current artifacts."""
    if not path.is_file():
        return False
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expected = {
        "status": "pass",
        "view": view,
        "startup": "op",
        "selected_beam": 0,
        "incident_beam": 0,
        "channel_mask": 1 << channel,
        "trim_codes": list(codes_for_case(channel, code)),
        "transient_step_ns": transient_step_ns,
        "analysis_window_us": [analysis_start_us, analysis_stop_us],
        "gds_sha256": gds_sha256,
        "netlist_sha256": netlist_sha256,
    }
    return all(report.get(field) == value for field, value in expected.items())


def spread_db(values: tuple[float, ...] | list[float]) -> float:
    if min(values) <= 0.0:
        return math.inf
    return 20.0 * math.log10(max(values) / min(values))


def monotonicity(values: list[float]) -> dict[str, Any]:
    deltas_db = [
        20.0 * math.log10(values[code + 1] / values[code])
        if values[code] > 0.0 and values[code + 1] > 0.0 else -math.inf
        for code in range(15)
    ]
    bad_steps = [
        code for code, delta_db in enumerate(deltas_db)
        if delta_db < -MONOTONIC_TOLERANCE_DB
    ]
    return {
        "status": "pass" if not bad_steps else "fail",
        "adjacent_step_db": deltas_db,
        "minimum_adjacent_step_db": min(deltas_db),
        "inverted_steps_after_codes": bad_steps,
        "numerical_tolerance_db": MONOTONIC_TOLERANCE_DB,
    }


def useful_resolution(
    values: list[float], minimum_adjacent_step_db: float = MINIMUM_ADJACENT_STEP_DB
) -> dict[str, Any]:
    adjacent_steps_db = [
        20.0 * math.log10(values[code + 1] / values[code])
        if values[code] > 0.0 and values[code + 1] > 0.0 else -math.inf
        for code in range(15)
    ]
    under_resolved_steps = [
        code for code, step_db in enumerate(adjacent_steps_db)
        if step_db < minimum_adjacent_step_db
    ]
    return {
        "status": "pass" if not under_resolved_steps else "fail",
        "adjacent_step_db": adjacent_steps_db,
        "minimum_adjacent_step_db": min(adjacent_steps_db),
        "required_minimum_adjacent_step_db": minimum_adjacent_step_db,
        "under_resolved_steps_after_codes": under_resolved_steps,
    }


def choose_calibration(
    responses: list[list[float]],
    maximum_gain_shift_db: float = 2.0,
    significance_floor_db: float = CALIBRATION_SIGNIFICANCE_FLOOR_DB,
) -> dict[str, Any]:
    default_values = [responses[channel][8] for channel in range(4)]
    target = sum(default_values) / 4.0
    best: tuple[
        tuple[float, float, int, float],
        tuple[int, ...],
        tuple[float, ...],
        tuple[float, ...],
    ] | None = None
    for codes in itertools.product(range(16), repeat=4):
        values = tuple(responses[channel][codes[channel]] for channel in range(4))
        individual_gain_shifts_db = tuple(
            20.0 * math.log10(values[channel] / default_values[channel])
            if values[channel] > 0.0 and default_values[channel] > 0.0 else math.inf
            for channel in range(4)
        )
        # The trim budget is a per-channel analog constraint.  Applying it only
        # to the four-channel mean could hide an excessive positive excursion on
        # one channel behind a negative excursion on another.
        if any(
            abs(shift_db) > maximum_gain_shift_db
            for shift_db in individual_gain_shifts_db
        ):
            continue
        mean = sum(values) / 4.0
        gain_shift_db = 20.0 * math.log10(mean / target) if mean > 0.0 else math.inf
        raw_spread_db = spread_db(values)
        objective = (
            max(raw_spread_db - significance_floor_db, 0.0),
            abs(gain_shift_db),
            sum(abs(code - 8) for code in codes),
            raw_spread_db,
        )
        if best is None or objective < best[0]:
            best = (objective, codes, values, individual_gain_shifts_db)
    if best is None:
        raise ValueError(
            "no calibration combination keeps every channel inside the gain-shift limit"
        )
    objective, codes, values, individual_gain_shifts_db = best
    return {
        "codes_ch0_to_ch3": list(codes),
        "responses_v_rms": list(values),
        "spread_db": objective[3],
        "spread_significance_floor_db": significance_floor_db,
        "mean_gain_shift_from_default_db": (
            20.0 * math.log10((sum(values) / 4.0) / target)
        ),
        "gain_shift_from_default_db_by_channel": list(individual_gain_shifts_db),
        "maximum_absolute_gain_shift_from_default_db": max(
            abs(value) for value in individual_gain_shifts_db
        ),
        "total_code_distance_from_default": objective[2],
    }


def injected_mismatch_stress(
    responses: list[list[float]],
    offsets_db: tuple[float, float, float, float] = INJECTED_MISMATCH_STRESS_DB,
    maximum_gain_shift_db: float = 2.0,
) -> dict[str, Any]:
    if len(responses) != 4 or any(len(row) != 16 for row in responses):
        raise ValueError("mismatch stress requires four complete 16-code curves")
    stressed = [
        [value * (10.0 ** (offsets_db[channel] / 20.0)) for value in row]
        for channel, row in enumerate(responses)
    ]
    default_values = [stressed[channel][8] for channel in range(4)]
    calibration = choose_calibration(stressed, maximum_gain_shift_db)
    return {
        "method": (
            "deterministic gain offsets applied to measured extracted curves; "
            "not foundry mismatch Monte Carlo"
        ),
        "injected_gain_offset_db_by_channel": list(offsets_db),
        "untrimmed_code8_spread_db": spread_db(default_values),
        "calibration": calibration,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("base", "rc"), default="base")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--transient-step-ns", type=float, default=5.0)
    parser.add_argument(
        "--analysis-start-us",
        type=float,
        default=2.0,
        help="start after the finite serial packet has committed (default: 2 us)",
    )
    parser.add_argument(
        "--analysis-stop-us",
        type=float,
        default=3.0,
        help="stop after an integer number of 1 MHz cycles (default: 3 us)",
    )
    parser.add_argument("--maximum-gain-shift-db", type=float, default=2.0)
    parser.add_argument(
        "--reuse-reports",
        action="store_true",
        help="summarize exact existing case reports without rerunning ngspice",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse only exact passing reports bound to the current GDS/netlist",
    )
    args = parser.parse_args()
    if not 1 <= args.jobs <= 4:
        raise SystemExit("--jobs must be between one and four")
    if not 0.5 <= args.transient_step_ns <= 10.0:
        raise SystemExit("--transient-step-ns must be between 0.5 and 10")
    if args.analysis_start_us <= 0.0 or args.analysis_stop_us <= args.analysis_start_us:
        raise SystemExit("analysis window must have positive, increasing times")
    window_us = args.analysis_stop_us - args.analysis_start_us
    if abs(window_us - round(window_us)) > 1e-9:
        raise SystemExit("analysis window must span an integer number of 1 MHz cycles")

    if args.reuse_reports and args.resume:
        raise SystemExit("--reuse-reports and --resume are mutually exclusive")
    current_gds_sha256 = sha256(GDS)
    current_netlist_sha256 = sha256(NETLIST_BY_VIEW[args.view])
    executions: list[tuple[int, int, int, str]] = []
    reused_report_count = 0
    cases_to_run: list[tuple[int, int]] = []
    if args.reuse_reports:
        for channel in range(4):
            for code in range(16):
                path = case_report_path(
                    channel, code, args.view, args.transient_step_ns,
                    args.analysis_start_us, args.analysis_stop_us,
                )
                executions.append((channel, code, 0, f"report={path}\n"))
    else:
        for channel in range(4):
            for code in range(16):
                path = case_report_path(
                    channel, code, args.view, args.transient_step_ns,
                    args.analysis_start_us, args.analysis_stop_us,
                )
                if args.resume and reusable_report(
                    path, channel, code, args.view, args.transient_step_ns,
                    args.analysis_start_us, args.analysis_stop_us,
                    current_gds_sha256, current_netlist_sha256,
                ):
                    executions.append((channel, code, 0, f"report={path}\n"))
                    reused_report_count += 1
                else:
                    cases_to_run.append((channel, code))
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = [
                executor.submit(
                    run_case, channel, code, args.view, args.ngspice, args.timeout,
                    args.transient_step_ns, args.analysis_start_us,
                    args.analysis_stop_us,
                )
                for channel, code in cases_to_run
            ]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                executions.append(result)
                print(
                    f"channel={result[0]} code={result[1]} returncode={result[2]}",
                    flush=True,
                )

    errors: list[str] = []
    responses = [[0.0 for _ in range(16)] for _ in range(4)]
    supply_currents_a = [[0.0 for _ in range(16)] for _ in range(4)]
    vcm_voltages_v = [[0.0 for _ in range(16)] for _ in range(4)]
    output_common_modes_v = [[0.0 for _ in range(16)] for _ in range(4)]
    reports: list[dict[str, Any]] = []
    for channel, code, returncode, output in executions:
        path = report_path_from_output(output)
        if returncode:
            errors.append(
                f"channel {channel} code {code} returned {returncode}: {output[-800:]!r}"
            )
        if path is None or not path.is_file():
            errors.append(f"channel {channel} code {code} has no report")
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        reports.append(report)
        expected_codes = list(codes_for_case(channel, code))
        expected_identity = {
            "status": "pass",
            "view": args.view,
            "startup": "op",
            "selected_beam": 0,
            "incident_beam": 0,
            "channel_mask": 1 << channel,
            "trim_codes": expected_codes,
            "transient_step_ns": args.transient_step_ns,
            "analysis_window_us": [
                args.analysis_start_us,
                args.analysis_stop_us,
            ],
        }
        for field, expected in expected_identity.items():
            if report.get(field) != expected:
                errors.append(
                    f"channel {channel} code {code}: {field}={report.get(field)!r}, "
                    f"expected {expected!r}"
                )
        try:
            responses[channel][code] = float(report["analysis"]["output_tone_rms_v"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"channel {channel} code {code} lacks output tone response")
        for field, destination in (
            ("supply_avg", supply_currents_a),
            ("vcm_avg", vcm_voltages_v),
            ("common_mode_avg", output_common_modes_v),
        ):
            try:
                destination[channel][code] = float(report["measurements"][field])
            except (KeyError, TypeError, ValueError):
                errors.append(
                    f"channel {channel} code {code} lacks measurement {field}"
                )
        verified_codes = report.get("analysis", {}).get("verified_trim_codes")
        if expected_codes == [8, 8, 8, 8]:
            if verified_codes != []:
                errors.append(
                    f"channel {channel} code {code}: reset-default case unexpectedly "
                    f"reported serial verification {verified_codes!r}"
                )
        elif verified_codes != expected_codes:
            errors.append(
                f"channel {channel} code {code}: extracted active trim bits do not "
                "match the serial packet"
            )

    monotonicity_by_channel = []
    useful_resolution_by_channel = []
    for channel, values in enumerate(responses):
        channel_monotonicity = monotonicity(values)
        monotonicity_by_channel.append(channel_monotonicity)
        if channel_monotonicity["status"] != "pass":
            errors.append(
                f"channel {channel} has gain inversions beyond "
                f"{MONOTONIC_TOLERANCE_DB:g} dB after codes "
                f"{channel_monotonicity['inverted_steps_after_codes']}"
            )
        channel_resolution = useful_resolution(values)
        useful_resolution_by_channel.append(channel_resolution)
        if channel_resolution["status"] != "pass":
            errors.append(
                f"channel {channel} has under-resolved trim transitions after codes "
                f"{channel_resolution['under_resolved_steps_after_codes']}"
            )

    default_values = [responses[channel][8] for channel in range(4)]
    default_spread = spread_db(default_values)
    response_gain_db_relative_to_default = [
        [
            20.0 * math.log10(value / default_values[channel])
            if value > 0.0 and default_values[channel] > 0.0 else math.inf
            for value in responses[channel]
        ]
        for channel in range(4)
    ]
    trim_span_db_by_channel = [
        spread_db(values) for values in responses
    ]
    for channel, trim_span_db in enumerate(trim_span_db_by_channel):
        if trim_span_db < MINIMUM_TRIM_SPAN_DB:
            errors.append(
                f"channel {channel} trim span {trim_span_db:.6f} dB is below "
                f"the required {MINIMUM_TRIM_SPAN_DB:g} dB"
            )
    calibration: dict[str, Any] = {}
    mismatch_stress: dict[str, Any] = {}
    if all(value > 0.0 for row in responses for value in row):
        calibration = choose_calibration(responses, args.maximum_gain_shift_db)
        if calibration["spread_db"] > default_spread + 1e-12:
            errors.append("calibrated channel spread is worse than default code 8")
        mismatch_stress = injected_mismatch_stress(
            responses,
            maximum_gain_shift_db=args.maximum_gain_shift_db,
        )
        if (
            mismatch_stress["calibration"]["spread_db"]
            > MAXIMUM_STRESS_CALIBRATED_SPREAD_DB
        ):
            errors.append(
                "injected mismatch stress remains above "
                f"{MAXIMUM_STRESS_CALIBRATED_SPREAD_DB:g} dB after calibration"
            )

    result = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "view": args.view,
        "method": "single enabled channel, faithful 24-bit serial trim commit",
        "acceptance_basis": "raw_unsubtracted_1mhz_output_tone",
        "case_count": len(reports),
        "codes_per_channel": 16,
        "transient_step_ns": args.transient_step_ns,
        "analysis_window_us": [args.analysis_start_us, args.analysis_stop_us],
        "responses_v_rms_by_channel_and_code": responses,
        "supply_current_a_by_channel_and_code": supply_currents_a,
        "vcm_v_by_channel_and_code": vcm_voltages_v,
        "output_common_mode_v_by_channel_and_code": output_common_modes_v,
        "gain_db_relative_to_code8_by_channel_and_code": (
            response_gain_db_relative_to_default
        ),
        "trim_span_db_by_channel": trim_span_db_by_channel,
        "monotonicity_by_channel": monotonicity_by_channel,
        "useful_resolution_by_channel": useful_resolution_by_channel,
        "minimum_required_trim_span_db": MINIMUM_TRIM_SPAN_DB,
        "default_code": 8,
        "default_responses_v_rms": default_values,
        "default_spread_db": default_spread,
        "maximum_calibration_gain_shift_db": args.maximum_gain_shift_db,
        "reused_reports": args.reuse_reports,
        "resumed": args.resume,
        "resumed_report_count": reused_report_count,
        "rerun_report_count": len(cases_to_run),
        "calibration": calibration,
        "injected_mismatch_stress": mismatch_stress,
        "artifact_hashes": {
            "gds_sha256": sorted({report.get("gds_sha256") for report in reports}),
            "netlist_sha256": sorted(
                {report.get("netlist_sha256") for report in reports}
            ),
            "spiceinit_sha256": sorted(
                {report.get("spiceinit_sha256") for report in reports}
            ),
        },
    }
    result_path = BUILD / args.view / "summary.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"report={result_path}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
