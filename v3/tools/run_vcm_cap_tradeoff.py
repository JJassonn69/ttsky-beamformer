#!/usr/bin/env python3
"""Compare compact MIM/varactor VCM bypass combinations after divider scaling."""

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
import run_vcm_divider_tradeoff as divider_tradeoff  # noqa: E402


BUILD = ROOT / "build" / "v3" / "vcm_cap_tradeoff"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "vcm_cap_tradeoff.json"
MEASURE_RE = re.compile(r"^([a-zA-Z0-9_]+)\s*=\s*([-+0-9.eE]+)", re.MULTILINE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cap_deck(
    mode: base.Mode,
    load_ohm: float,
    divider_scale: float,
    mim_count: int,
    varactor_count: int,
) -> str:
    text = divider_tradeoff.tradeoff_deck(mode, load_ohm, varactor_count, divider_scale)
    original = f"CMIM vcm 0 {base.MIM_CAPACITANCE_PF:.12g}p"
    replacement = f"CMIM_EQUIVALENT vcm 0 {mim_count * base.MIM_CAPACITANCE_PF:.12g}p"
    if original not in text:
        raise RuntimeError("base MIM bypass topology changed")
    return text.replace(original, replacement, 1)


def run_case(
    ngspice: str,
    mode: base.Mode,
    load_ohm: float,
    divider_scale: float,
    mim_count: int,
    varactor_count: int,
) -> dict[str, Any]:
    case_dir = BUILD / f"scale_{divider_scale:.3f}" / f"mim_{mim_count}_var_{varactor_count}" / mode.name
    case_dir.mkdir(parents=True, exist_ok=True)
    deck_path = case_dir / "cap_tradeoff.spice"
    log_path = case_dir / "ngspice.log"
    deck_path.write_text(
        cap_deck(mode, load_ohm, divider_scale, mim_count, varactor_count),
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
            f"missing={sorted(required - values.keys())}\n" + "\n".join(log.splitlines()[-50:])
        )
    return {
        "mode": mode.name,
        "load_ohm": load_ohm,
        "divider_scale_vs_v2": divider_scale,
        "mim_count": mim_count,
        "varactor_count": varactor_count,
        "nominal_mim_capacitance_pf": mim_count * base.MIM_CAPACITANCE_PF,
        "nominal_varactor_capacitance_pf": varactor_count * base.VARACTOR_CAPACITANCE_PF,
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
    pairs = sorted({(case["mim_count"], case["varactor_count"]) for case in cases})
    for mim_count, varactor_count in pairs:
        selected = [
            case for case in cases
            if case["mim_count"] == mim_count and case["varactor_count"] == varactor_count
        ]
        area = mim_count * 24.16 * 22.40 + varactor_count * 20.11 * 19.69
        gates = {
            "all_four_modes_completed": len(selected) == len(base.MODES),
            "vcm_peak_to_peak_at_most_15mv": max(case["vcm_peak_to_peak_v"] for case in selected) <= 0.015,
            "output_common_mode_average_at_least_1p2v": min(case["output_common_mode_average_v"] for case in selected) >= 1.2,
        }
        candidates.append({
            "mim_count": mim_count,
            "varactor_count": varactor_count,
            "nominal_total_capacitance_pf": (
                mim_count * base.MIM_CAPACITANCE_PF
                + varactor_count * base.VARACTOR_CAPACITANCE_PF
            ),
            "estimated_pcell_bbox_area_um2": area,
            "maximum_vcm_peak_to_peak_v": max(case["vcm_peak_to_peak_v"] for case in selected),
            "minimum_output_common_mode_average_v": min(case["output_common_mode_average_v"] for case in selected),
            "filtered_output_tone_peak_range_v": [
                min(case["filtered_output_tone_peak_v"] for case in selected),
                max(case["filtered_output_tone_peak_v"] for case in selected),
            ],
            "gates": gates,
            "status": "pass" if all(gates.values()) else "fail",
        })
    passing = [candidate for candidate in candidates if candidate["status"] == "pass"]
    selected = min(
        passing,
        key=lambda item: (
            item["estimated_pcell_bbox_area_um2"], item["varactor_count"], item["mim_count"]
        ),
    ) if passing else None
    return {
        "schema_version": 1,
        "status": "pass" if selected else "fail",
        "scope": "nominal lumped-equivalent bypass topology selection; exact PCell routing/ESR, PVT, startup, mismatch, and extraction remain open",
        "divider_scale_vs_v2": cases[0]["divider_scale_vs_v2"],
        "load_ohm": cases[0]["load_ohm"],
        "selection_policy": "minimum measured PCell bbox area among passing candidates, then fewer nonlinear varactors",
        "selected_candidate": selected,
        "candidates": candidates,
        "cases": sorted(cases, key=lambda item: (item["mim_count"], item["varactor_count"], item["mode"])),
        "provenance": {
            "generator": "v3/tools/run_vcm_cap_tradeoff.py",
            "generator_sha256": sha256(Path(__file__)),
            "divider_generator": "v3/tools/run_vcm_divider_tradeoff.py",
            "divider_generator_sha256": sha256(TOOLS / "run_vcm_divider_tradeoff.py"),
        },
    }


def parse_configurations(value: str) -> list[tuple[int, int]]:
    result = []
    for item in value.split(","):
        mim, var = item.split(":", 1)
        pair = (int(mim), int(var))
        if pair[0] < 1 or pair[1] < 0:
            raise ValueError(f"invalid MIM:varactor pair {item}")
        result.append(pair)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--load", type=float, default=2925.0)
    parser.add_argument("--divider-scale", type=float, default=0.25)
    parser.add_argument("--configurations", default="1:0,1:2,1:4,2:0,2:2,4:0")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    configurations = parse_configurations(args.configurations)
    jobs = [
        (mim_count, varactor_count, mode)
        for mim_count, varactor_count in configurations for mode in base.MODES
    ]
    cases: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                run_case, args.ngspice, mode, args.load, args.divider_scale,
                mim_count, varactor_count,
            ): (mim_count, varactor_count, mode)
            for mim_count, varactor_count, mode in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            mim_count, varactor_count, mode = futures[future]
            cases.append(future.result())
            print(f"completed mim={mim_count} varactors={varactor_count} {mode.name}", flush=True)
    report = summarize(cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
