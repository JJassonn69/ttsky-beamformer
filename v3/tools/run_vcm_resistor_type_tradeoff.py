#!/usr/bin/env python3
"""Compare compact six-unit VCM dividers using SKY130 resistor types.

All candidates retain the exact 2:4 common-centroid topology.  Only the
unit resistor model and legal PCell length change, so this study tests a
lower source-impedance root fix without adding capacitor area or unmatched
parallel branches.
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


BUILD = ROOT / "build" / "v3" / "vcm_resistor_type_tradeoff"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "vcm_resistor_type_tradeoff.json"
MEASURE_RE = re.compile(r"^([a-zA-Z0-9_]+)\s*=\s*([-+0-9.eE]+)", re.MULTILINE)
DIVIDER_ORIGINAL = """XRVCM_TOP VDD_NODE vcm 0 sky130_fd_pr__res_xhigh_po_1p41 l=47
XRVCM_BOTTOM vcm 0 0 sky130_fd_pr__res_xhigh_po_1p41 l=94"""
MODELS = {
    "xhigh_po": {
        "spice_model": "sky130_fd_pr__res_xhigh_po_1p41",
        "sheet_ohm_per_square": 2000.0,
        "terminal_ohm": 255.0,
    },
    "high_po": {
        "spice_model": "sky130_fd_pr__res_high_po_1p41",
        "sheet_ohm_per_square": 319.8,
        "terminal_ohm": 195.0,
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def divider(model_name: str, unit_length_um: float) -> str:
    model = MODELS[model_name]["spice_model"]
    return f"""* Six identical units permit exact B-A-B / B-A-B placement.
XRVCM_T0 VDD_NODE vcm_tmid 0 {model} l={unit_length_um:.12g}
XRVCM_T1 vcm_tmid vcm 0 {model} l={unit_length_um:.12g}
XRVCM_B0 vcm vcm_b1 0 {model} l={unit_length_um:.12g}
XRVCM_B1 vcm_b1 vcm_b2 0 {model} l={unit_length_um:.12g}
XRVCM_B2 vcm_b2 vcm_b3 0 {model} l={unit_length_um:.12g}
XRVCM_B3 vcm_b3 0 0 {model} l={unit_length_um:.12g}"""


def candidate_deck(
    mode: base.Mode,
    load_ohm: float,
    model_name: str,
    unit_length_um: float,
) -> str:
    text = base.deck(mode, load_ohm, 0)
    if DIVIDER_ORIGINAL not in text:
        raise RuntimeError("base VCM divider topology changed")
    return text.replace(DIVIDER_ORIGINAL, divider(model_name, unit_length_um), 1)


def run_case(
    ngspice: str,
    mode: base.Mode,
    load_ohm: float,
    model_name: str,
    unit_length_um: float,
) -> dict[str, Any]:
    slug = f"{model_name}_l_{unit_length_um:g}".replace(".", "p")
    case_dir = BUILD / slug / mode.name
    case_dir.mkdir(parents=True, exist_ok=True)
    deck_path = case_dir / "divider.spice"
    log_path = case_dir / "ngspice.log"
    deck_path.write_text(
        candidate_deck(mode, load_ohm, model_name, unit_length_um),
        encoding="utf-8",
    )
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
            f"missing={sorted(required - values.keys())}\n"
            + "\n".join(log.splitlines()[-50:])
        )
    return {
        "mode": mode.name,
        "resistor_type": model_name,
        "spice_model": MODELS[model_name]["spice_model"],
        "divider_unit_length_um": unit_length_um,
        "divider_unit_count": 6,
        "top_series_units": 2,
        "bottom_series_units": 4,
        "load_ohm": load_ohm,
        "mim_count": 1,
        "varactor_count": 0,
        "vcm_average_v": values["vcm_avg"],
        "vcm_peak_to_peak_v": values["vcm_max"] - values["vcm_min"],
        "output_common_mode_average_v": values["output_cm_avg"],
        "output_common_mode_minimum_v": values["output_cm_min"],
        "filtered_output_tone_peak_v": 2.0 * math.hypot(
            values["tone_i_avg"], values["tone_q_avg"]
        ),
        "supply_current_a": abs(values["supply_avg"]),
        "deck": str(deck_path.relative_to(ROOT)),
        "deck_sha256": sha256(deck_path),
        "log": str(log_path.relative_to(ROOT)),
    }


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = []
    choices = sorted({
        (case["resistor_type"], case["divider_unit_length_um"])
        for case in cases
    })
    for model_name, length in choices:
        selected = [
            case for case in cases
            if case["resistor_type"] == model_name
            and case["divider_unit_length_um"] == length
        ]
        model = MODELS[model_name]
        estimated_unit_ohm = (
            model["sheet_ohm_per_square"] * length / 1.41
            + model["terminal_ohm"]
        )
        estimated_total_ohm = 6.0 * estimated_unit_ohm
        gates = {
            "all_four_modes_completed": len(selected) == len(base.MODES),
            "vcm_peak_to_peak_at_most_15mv": max(
                case["vcm_peak_to_peak_v"] for case in selected
            ) <= 0.015,
            "output_common_mode_average_at_least_1p2v": min(
                case["output_common_mode_average_v"] for case in selected
            ) >= 1.2,
            "unit_length_at_least_5um": length >= 5.0,
        }
        candidates.append({
            "resistor_type": model_name,
            "spice_model": model["spice_model"],
            "divider_unit_length_um": length,
            "divider_unit_count": 6,
            "estimated_unit_resistance_ohm": estimated_unit_ohm,
            "estimated_total_divider_resistance_ohm": estimated_total_ohm,
            "estimated_divider_current_a": 1.8 / estimated_total_ohm,
            "estimated_divider_power_w": 3.24 / estimated_total_ohm,
            "maximum_vcm_peak_to_peak_v": max(
                case["vcm_peak_to_peak_v"] for case in selected
            ),
            "minimum_output_common_mode_average_v": min(
                case["output_common_mode_average_v"] for case in selected
            ),
            "minimum_instantaneous_output_common_mode_v": min(
                case["output_common_mode_minimum_v"] for case in selected
            ),
            "filtered_output_tone_peak_range_v": [
                min(case["filtered_output_tone_peak_v"] for case in selected),
                max(case["filtered_output_tone_peak_v"] for case in selected),
            ],
            "gates": gates,
            "status": "pass" if all(gates.values()) else "fail",
        })
    passing = [candidate for candidate in candidates if candidate["status"] == "pass"]
    selected_candidate = min(
        passing,
        key=lambda item: (
            item["estimated_divider_power_w"],
            -item["divider_unit_length_um"],
        ),
    ) if passing else None
    return {
        "schema_version": 1,
        "status": "pass" if selected_candidate else "fail",
        "scope": "nominal resistor-type selection for one compact six-unit common-centroid VCM divider; exact PCell dimensions, PVT, startup, mismatch, routing, and extraction remain open",
        "load_ohm": cases[0]["load_ohm"],
        "common_centroid_matrix": [["B", "A", "B"], ["B", "A", "B"]],
        "matrix_legend": {
            "A": "top-divider series unit",
            "B": "bottom-divider series unit",
        },
        "selection_policy": "lowest static divider power among candidates meeting the 15 mV VCM and 1.2 V output-common-mode gates",
        "selected_candidate": selected_candidate,
        "candidates": candidates,
        "cases": sorted(
            cases,
            key=lambda item: (
                item["resistor_type"],
                item["divider_unit_length_um"],
                item["mode"],
            ),
        ),
        "provenance": {
            "generator": "v3/tools/run_vcm_resistor_type_tradeoff.py",
            "generator_sha256": sha256(Path(__file__)),
            "base_support_generator": "v3/tools/run_four_channel_support_sweep.py",
            "base_support_generator_sha256": sha256(
                TOOLS / "run_four_channel_support_sweep.py"
            ),
        },
    }


def parse_candidates(value: str) -> list[tuple[str, float]]:
    result = []
    for item in value.split(","):
        model_name, length = item.split(":", 1)
        if model_name not in MODELS:
            raise ValueError(f"unknown resistor type {model_name}")
        result.append((model_name, float(length)))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--load", type=float, default=2925.0)
    parser.add_argument(
        "--candidates",
        default="xhigh_po:5.875,high_po:23.5,high_po:11.75,high_po:5.875",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    choices = parse_candidates(args.candidates)
    jobs = [
        (model_name, length, mode)
        for model_name, length in choices
        for mode in base.MODES
    ]
    cases: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                run_case,
                args.ngspice,
                mode,
                args.load,
                model_name,
                length,
            ): (model_name, length, mode)
            for model_name, length, mode in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            model_name, length, mode = futures[future]
            cases.append(future.result())
            print(
                f"completed type={model_name} length={length:g} {mode.name}",
                flush=True,
            )
    report = summarize(cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
