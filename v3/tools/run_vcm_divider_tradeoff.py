#!/usr/bin/env python3
"""Select a lower-impedance common-centroid V3 VCM divider.

The inherited 47/94 um two-resistor divider has the right 1:2 ratio but too
much Thevenin impedance for V3's sixty reference gates.  Each candidate here
implements the same ratio with six identical xhigh-poly units: two series
units above VCM and four below it.  A 2x3 A/B assignment can therefore make
the top and bottom resistor centroids identical in layout.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "v3" / "tools"
sys.path.insert(0, str(TOOLS))

import run_four_channel_support_sweep as base  # noqa: E402


BUILD = ROOT / "build" / "v3" / "vcm_divider_tradeoff"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "vcm_divider_tradeoff.json"
MEASURE_RE = re.compile(r"^([a-zA-Z0-9_]+)\s*=\s*([-+0-9.eE]+)", re.MULTILINE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def divider(scale: float) -> tuple[str, float]:
    unit_length = 47.0 * scale / 2.0
    text = f"""* Six equal units permit exact 2:4 common-centroid placement.
XRVCM_T0 VDD_NODE vcm_tmid 0 sky130_fd_pr__res_xhigh_po_1p41 l={unit_length:.12g}
XRVCM_T1 vcm_tmid vcm 0 sky130_fd_pr__res_xhigh_po_1p41 l={unit_length:.12g}
XRVCM_B0 vcm vcm_b1 0 sky130_fd_pr__res_xhigh_po_1p41 l={unit_length:.12g}
XRVCM_B1 vcm_b1 vcm_b2 0 sky130_fd_pr__res_xhigh_po_1p41 l={unit_length:.12g}
XRVCM_B2 vcm_b2 vcm_b3 0 sky130_fd_pr__res_xhigh_po_1p41 l={unit_length:.12g}
XRVCM_B3 vcm_b3 0 0 sky130_fd_pr__res_xhigh_po_1p41 l={unit_length:.12g}"""
    return text, unit_length


def tradeoff_deck(mode: base.Mode, load_ohm: float, varactor_count: int, scale: float) -> str:
    text = base.deck(mode, load_ohm, varactor_count)
    original = """XRVCM_TOP VDD_NODE vcm 0 sky130_fd_pr__res_xhigh_po_1p41 l=47
XRVCM_BOTTOM vcm 0 0 sky130_fd_pr__res_xhigh_po_1p41 l=94"""
    replacement, _ = divider(scale)
    if original not in text:
        raise RuntimeError("base VCM divider topology changed")
    return text.replace(original, replacement, 1)


def run_case(
    ngspice: str,
    mode: base.Mode,
    load_ohm: float,
    varactor_count: int,
    scale: float,
) -> dict[str, Any]:
    case_dir = BUILD / f"scale_{scale:.3f}" / f"var_{varactor_count}" / mode.name
    case_dir.mkdir(parents=True, exist_ok=True)
    deck_path = case_dir / "divider.spice"
    log_path = case_dir / "ngspice.log"
    deck_path.write_text(tradeoff_deck(mode, load_ohm, varactor_count, scale), encoding="utf-8")
    completed = subprocess.run(
        [ngspice, "-b", "-o", str(log_path), str(deck_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=600,
        check=False,
    )
    log = log_path.read_text(errors="replace") if log_path.exists() else completed.stdout
    values = {name.lower(): float(value) for name, value in MEASURE_RE.findall(log)}
    required = {
        "vcm_avg", "vcm_min", "vcm_max", "output_cm_avg", "output_cm_min",
        "tone_i_avg", "tone_q_avg", "supply_avg",
    }
    if completed.returncode != 0 or not required.issubset(values):
        raise RuntimeError(
            f"case {case_dir.relative_to(ROOT)} failed, return={completed.returncode}, "
            f"missing={sorted(required - values.keys())}\n" + "\n".join(log.splitlines()[-50:])
        )
    _, unit_length = divider(scale)
    return {
        "mode": mode.name,
        "divider_scale_vs_v2": scale,
        "divider_unit_count": 6,
        "divider_unit_length_um": unit_length,
        "top_series_units": 2,
        "bottom_series_units": 4,
        "load_ohm": load_ohm,
        "varactor_count": varactor_count,
        "total_nominal_vcm_capacitance_pf": (
            base.MIM_CAPACITANCE_PF + varactor_count * base.VARACTOR_CAPACITANCE_PF
        ),
        "vcm_average_v": values["vcm_avg"],
        "vcm_peak_to_peak_v": values["vcm_max"] - values["vcm_min"],
        "output_common_mode_average_v": values["output_cm_avg"],
        "output_common_mode_minimum_v": values["output_cm_min"],
        "filtered_output_tone_peak_v": 2.0 * math.hypot(values["tone_i_avg"], values["tone_q_avg"]),
        "supply_current_a": abs(values["supply_avg"]),
        "deck": str(deck_path.relative_to(ROOT)),
        "deck_sha256": sha256(deck_path),
        "log": str(log_path.relative_to(ROOT)),
    }


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = []
    pairs = sorted({(case["divider_scale_vs_v2"], case["varactor_count"]) for case in cases})
    for scale, varactor_count in pairs:
        selected = [
            case for case in cases
            if case["divider_scale_vs_v2"] == scale and case["varactor_count"] == varactor_count
        ]
        maximum_ripple = max(case["vcm_peak_to_peak_v"] for case in selected)
        minimum_cm = min(case["output_common_mode_average_v"] for case in selected)
        _, unit_length = divider(scale)
        # Nominal sheet estimate is only used to expose the power tradeoff;
        # the SPICE cases retain the PDK resistor model.
        estimated_total_resistance = 6.0 * (2000.0 * unit_length / 1.41 + 255.0)
        estimated_divider_current = 1.8 / estimated_total_resistance
        gates = {
            "all_four_modes_completed": len(selected) == len(base.MODES),
            "vcm_peak_to_peak_at_most_15mv": maximum_ripple <= 0.015,
            "output_common_mode_average_at_least_1p2v": minimum_cm >= 1.2,
            "unit_length_at_least_5um": unit_length >= 5.0,
        }
        candidates.append({
            "divider_scale_vs_v2": scale,
            "divider_unit_count": 6,
            "divider_unit_length_um": unit_length,
            "top_series_units": 2,
            "bottom_series_units": 4,
            "varactor_count": varactor_count,
            "total_nominal_vcm_capacitance_pf": selected[0]["total_nominal_vcm_capacitance_pf"],
            "maximum_vcm_peak_to_peak_v": maximum_ripple,
            "minimum_output_common_mode_average_v": minimum_cm,
            "minimum_instantaneous_output_common_mode_v": min(
                case["output_common_mode_minimum_v"] for case in selected
            ),
            "filtered_output_tone_peak_range_v": [
                min(case["filtered_output_tone_peak_v"] for case in selected),
                max(case["filtered_output_tone_peak_v"] for case in selected),
            ],
            "estimated_divider_current_a": estimated_divider_current,
            "estimated_divider_power_w": 1.8 * estimated_divider_current,
            "gates": gates,
            "status": "pass" if all(gates.values()) else "fail",
        })
    passing = [candidate for candidate in candidates if candidate["status"] == "pass"]
    # Prefer the fewest nonlinear capacitors, then the lowest divider current.
    selected = min(
        passing,
        key=lambda item: (item["varactor_count"], -item["divider_scale_vs_v2"]),
    ) if passing else None
    return {
        "schema_version": 1,
        "status": "pass" if selected else "fail",
        "scope": "nominal common-centroid VCM divider architecture selection; exact PCell, PVT, mismatch, startup, and extracted-layout checks remain open",
        "load_ohm": cases[0]["load_ohm"],
        "selection_policy": "fewest nonlinear varactors first, then highest resistance/lowest static current among passing candidates",
        "selected_candidate": selected,
        "common_centroid_matrix": [["B", "A", "B"], ["B", "A", "B"]],
        "matrix_legend": {"A": "top-divider series unit", "B": "bottom-divider series unit"},
        "candidates": candidates,
        "cases": sorted(cases, key=lambda item: (
            item["divider_scale_vs_v2"], item["varactor_count"], item["mode"]
        )),
        "provenance": {
            "generator": "v3/tools/run_vcm_divider_tradeoff.py",
            "generator_sha256": sha256(Path(__file__)),
            "base_support_generator": "v3/tools/run_four_channel_support_sweep.py",
            "base_support_generator_sha256": sha256(TOOLS / "run_four_channel_support_sweep.py"),
        },
        "next_gate": "run selected common-centroid candidate over PVT including low-supply gm headroom, then measure exact resistor PCell dimensions",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--load", type=float, default=2925.0)
    parser.add_argument("--scales", default="1,0.5,0.25")
    parser.add_argument("--varactors", default="0,1,2")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    scales = [float(value) for value in args.scales.split(",")]
    varactors = [int(value) for value in args.varactors.split(",")]
    jobs = [
        (scale, count, mode)
        for scale in scales for count in varactors for mode in base.MODES
    ]
    cases: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(run_case, args.ngspice, mode, args.load, count, scale): (scale, count, mode)
            for scale, count, mode in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            scale, count, mode = futures[future]
            cases.append(future.result())
            print(f"completed scale={scale:g} varactors={count} {mode.name}", flush=True)
    report = summarize(cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
