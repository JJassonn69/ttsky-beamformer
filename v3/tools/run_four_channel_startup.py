#!/usr/bin/env python3
"""Bounded power-on startup gate for the selected four-channel support circuit."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

import run_four_channel_support_pvt as pvt  # noqa: E402
import run_four_channel_support_sweep as base  # noqa: E402


BUILD = ROOT / "build/v3/four_channel_startup"
OUTPUT = ROOT / "v3/evidence/four_channel_startup.json"
LOAD_OHM = 2925.0
MIM_COUNT = 3
VARACTOR_COUNT = 0
DIVIDER_SCALE = 0.25
SUPPLY_RAMP_END_S = 40e-9
LO_START_S = 2e-6
STOP_S = 100e-6


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def startup_deck(mode: base.Mode, corner: pvt.Corner, trace: Path) -> str:
    text = pvt.corner_deck(
        mode, LOAD_OHM, MIM_COUNT, VARACTOR_COUNT, DIVIDER_SCALE, corner
    )
    text = text.replace(
        "VDD_SOURCE VDD_NODE 0 {VDD}",
        "VDD_SOURCE VDD_NODE 0 PWL(0 0 20n 0 40n {VDD})",
        1,
    )
    text = text.replace(
        "VLO0 lo0 0 pulse(0 {VDD} 10n 1n 1n 123n 250n)",
        "VLO0 lo0 0 pulse(0 {VDD} 2.01u 1n 1n 123n 250n)",
        1,
    )
    text = text.replace("BLO180 lo180 0 v={VDD}-v(lo0)", "BLO180 lo180 0 v=v(VDD_NODE)-v(lo0)", 1)
    text = text.replace(
        "VLO90 lo90 0 pulse(0 {VDD} 72.5n 1n 1n 123n 250n)",
        "VLO90 lo90 0 pulse(0 {VDD} 2.0725u 1n 1n 123n 250n)",
        1,
    )
    text = text.replace("BLO270 lo270 0 v={VDD}-v(lo90)", "BLO270 lo270 0 v=v(VDD_NODE)-v(lo90)", 1)
    text = text.replace(".tran 2n 8u 2u", ".tran 10n 100u 0 uic", 1)
    control = f"""
.control
set wr_singlescale
set wr_vecnames
run
wrdata {trace.as_posix()} v(vcm) v(output_cm) v(vbias) v(VDD_NODE)
quit
.endc
"""
    return text.replace(".end\n", control + ".end\n", 1)


def read_trace(path: Path) -> dict[str, list[float]]:
    lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    header = lines[0]
    values = [[float(value) for value in row] for row in lines[1:]]
    if not values or any(len(row) != len(header) for row in values):
        raise RuntimeError(f"malformed startup trace {path}")
    columns = {name.lower(): [row[index] for row in values] for index, name in enumerate(header)}
    required = {"time", "v(vcm)", "v(output_cm)", "v(vbias)", "v(vdd_node)"}
    if not required <= columns.keys():
        raise RuntimeError(f"missing startup trace columns {sorted(required-columns.keys())}: {header}")
    return columns


def first_crossing(time: list[float], values: list[float], threshold: float) -> float:
    for t, value in zip(time, values):
        if t >= 0 and value >= threshold:
            return t
    raise RuntimeError(f"trace never crosses {threshold:g} V")


def stable_time(
    time: list[float], values: list[float], final: float, tolerance_fraction: float
) -> float:
    tolerance = abs(final) * tolerance_fraction
    outside = [index for index, value in enumerate(values) if abs(value - final) > tolerance]
    if not outside:
        return time[0]
    last = outside[-1]
    if last + 1 >= len(time):
        raise RuntimeError("trace is not settled at the end of the startup window")
    return time[last + 1]


def run_case(ngspice: str, mode: base.Mode, corner: pvt.Corner) -> dict[str, Any]:
    case_dir = BUILD / corner.name / mode.name
    case_dir.mkdir(parents=True, exist_ok=True)
    deck = case_dir / "startup.spice"
    trace = case_dir / "startup.tsv"
    log = case_dir / "ngspice.log"
    deck.write_text(startup_deck(mode, corner, trace.relative_to(ROOT)), encoding="utf-8")
    result = subprocess.run(
        [ngspice, "-b", "-o", str(log), str(deck)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=600,
        check=False,
    )
    if result.returncode != 0 or not trace.is_file():
        tail = log.read_text(errors="replace")[-5000:] if log.is_file() else result.stdout[-5000:]
        raise RuntimeError(f"startup case failed {corner.name}/{mode.name}: {result.returncode}\n{tail}")
    data = read_trace(trace)
    time = data["time"]
    results: dict[str, Any] = {
        "corner": corner.name,
        "process": corner.process,
        "supply_v": corner.supply_v,
        "temperature_c": corner.temperature_c,
        "mode": mode.name,
        "deck": str(deck.relative_to(ROOT)),
        "deck_sha256": sha256(deck),
        "trace": str(trace.relative_to(ROOT)),
        "trace_sha256": sha256(trace),
        "log": str(log.relative_to(ROOT)),
    }
    for name, key in (("vcm", "v(vcm)"), ("output_common_mode", "v(output_cm)"), ("vbias", "v(vbias)")):
        values = data[key]
        final_samples = [value for t, value in zip(time, values) if t >= STOP_S - 10e-6]
        final = statistics.fmean(final_samples)
        results[f"{name}_final_v"] = final
        results[f"{name}_t90_us"] = first_crossing(time, values, 0.9 * final) * 1e6
        results[f"{name}_settled_2pct_us"] = stable_time(time, values, final, 0.02) * 1e6
    results["output_common_mode_cross_0p8v_us"] = first_crossing(
        time, data["v(output_cm)"], 0.8
    ) * 1e6
    results["vcm_final_target_error_percent"] = abs(
        results["vcm_final_v"] - (2.0 / 3.0) * corner.supply_v
    ) / ((2.0 / 3.0) * corner.supply_v) * 100.0
    results["supply_final_v"] = statistics.fmean(
        value for t, value in zip(time, data["v(vdd_node)"]) if t >= STOP_S - 10e-6
    )
    return results


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    expected_count = len(pvt.CORNERS) + len(base.MODES) - 1
    # The output node is allowed to settle well before the slower VCM divider.
    # The externally visible operating contract remains the 60 us VCM limit;
    # 20 us is a deliberately tighter, subordinate output-node screen.
    gates = {
        "factorized_8_case_pvt_and_mode_matrix_completed": len(cases) == expected_count,
        "vcm_reaches_90_percent_within_25us": max(case["vcm_t90_us"] for case in cases) <= 25.0,
        "vcm_stays_within_2_percent_by_60us": max(case["vcm_settled_2pct_us"] for case in cases) <= 60.0,
        "vbias_reaches_90_percent_within_5us": max(case["vbias_t90_us"] for case in cases) <= 5.0,
        "output_common_mode_crosses_0p8v_within_5us": max(case["output_common_mode_cross_0p8v_us"] for case in cases) <= 5.0,
        "output_common_mode_stays_within_2_percent_by_20us": max(case["output_common_mode_settled_2pct_us"] for case in cases) <= 20.0,
        "final_vcm_within_1_percent_of_divider_target": max(case["vcm_final_target_error_percent"] for case in cases) <= 1.0,
    }
    return {
        "schema_version": 1,
        "status": "pass" if all(gates.values()) else "fail",
        "scope": "factorized power-on startup matrix for the selected schematic support circuit: all five bounded MOS/VDD/temperature corners in the reference mode plus all four vector-mode classes at TT",
        "stimulus": {
            "supply_ramp": "0 V through 20 ns, linear to final VDD at 40 ns",
            "quadrature_start_us": LO_START_S * 1e6,
            "simulation_stop_us": STOP_S * 1e6,
            "selected_load_ohm": LOAD_OHM,
            "selected_mim_count": MIM_COUNT,
            "selected_varactor_count": VARACTOR_COUNT,
            "selected_divider_scale_vs_v2": DIVIDER_SCALE,
        },
        "acceptance_limits": {
            "vcm_t90_us_max": 25.0,
            "vcm_settled_2pct_us_max": 60.0,
            "vbias_t90_us_max": 5.0,
            "output_common_mode_cross_0p8v_us_max": 5.0,
            "output_common_mode_settled_2pct_us_max": 20.0,
            "vcm_final_target_error_percent_max": 1.0,
            "rationale": "the output-node screen is subordinate to the slower VCM network; the operating procedure does not enable the beamformer until 60 us after VDD is stable",
        },
        "gates": gates,
        "worst_case": {
            "vcm_t90_us": max(case["vcm_t90_us"] for case in cases),
            "vcm_settled_2pct_us": max(case["vcm_settled_2pct_us"] for case in cases),
            "vbias_t90_us": max(case["vbias_t90_us"] for case in cases),
            "output_common_mode_cross_0p8v_us": max(case["output_common_mode_cross_0p8v_us"] for case in cases),
            "output_common_mode_settled_2pct_us": max(case["output_common_mode_settled_2pct_us"] for case in cases),
            "vcm_final_target_error_percent": max(case["vcm_final_target_error_percent"] for case in cases),
        },
        "recommended_operating_sequence": {
            "minimum_wait_after_vdd_ramp_us": 60.0,
            "procedure": "hold rst_n low and ena low during power ramp; wait at least 60 us after VDD is stable; release reset, apply a stable 16 MHz clock and controls, then assert ena",
        },
        "limitations": [
            "schematic support network, not a transient simulation of extracted distributed RC",
            "external source/package/board parasitics are not included",
            "the selected MIM model is nominal while MOS/VDD/temperature use the bounded PVT set",
        ],
        "cases": sorted(cases, key=lambda item: (item["corner"], item["mode"])),
        "provenance": {
            "generator": "v3/tools/run_four_channel_startup.py",
            "generator_sha256": sha256(Path(__file__)),
            "support_pvt_generator_sha256": sha256(ROOT / "v3/tools/run_four_channel_support_pvt.py"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--corners", default=",".join(corner.name for corner in pvt.CORNERS))
    parser.add_argument("--modes", default=",".join(mode.name for mode in base.MODES))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--resummarize-existing",
        action="store_true",
        help="recompute thresholds and provenance from the existing completed case set without rerunning ngspice",
    )
    args = parser.parse_args()
    if args.resummarize_existing:
        if not args.output.is_file():
            raise SystemExit(f"existing startup report not found: {args.output}")
        existing = json.loads(args.output.read_text(encoding="utf-8"))
        cases = existing.get("cases", [])
        if len(cases) != len(pvt.CORNERS) + len(base.MODES) - 1:
            raise SystemExit(f"existing report has an incomplete case set: {len(cases)}")
        report = summarize(cases)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(args.output)
        if report["status"] == "fail":
            raise SystemExit(1)
        return
    selected_corner_names = set(args.corners.split(","))
    selected_mode_names = set(args.modes.split(","))
    corners = [corner for corner in pvt.CORNERS if corner.name in selected_corner_names]
    modes = [mode for mode in base.MODES if mode.name in selected_mode_names]
    if len(corners) != len(selected_corner_names) or len(modes) != len(selected_mode_names):
        raise SystemExit("unknown corner or mode")
    full_matrix_requested = (
        len(corners) == len(pvt.CORNERS) and len(modes) == len(base.MODES)
    )
    if full_matrix_requested:
        reference_mode = next(mode for mode in modes if mode.name == "same_cardinal")
        nominal_corner = next(corner for corner in corners if corner.name == "tt_nominal")
        jobs = list(dict.fromkeys(
            [(corner, reference_mode) for corner in corners]
            + [(nominal_corner, mode) for mode in modes]
        ))
    else:
        jobs = [(corner, mode) for corner in corners for mode in modes]
    cases: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(run_case, args.ngspice, mode, corner): (corner, mode)
            for corner, mode in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            corner, mode = futures[future]
            cases.append(future.result())
            print(f"completed {corner.name} {mode.name}", flush=True)
    if full_matrix_requested:
        report = summarize(cases)
    else:
        report = {
            "schema_version": 1,
            "status": "diagnostic_subset",
            "corners": [corner.name for corner in corners],
            "modes": [mode.name for mode in modes],
            "cases": sorted(cases, key=lambda item: (item["corner"], item["mode"])),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    if report["status"] == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
