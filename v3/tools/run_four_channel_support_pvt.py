#!/usr/bin/env python3
"""Run selected V3 four-channel shared-support candidates over MOS PVT.

This is the second-stage gate after the nominal load/bypass screen.  It keeps
the physical 2:1 VCM divider, four AC-coupled input-bias resistors, and one
shared output-load pair, then explicitly checks the representative gm
drain-to-tail margin that an ideal 1.2 V source can hide at low VDD.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "v3" / "tools"
sys.path.insert(0, str(TOOLS))

import run_four_channel_support_sweep as base  # noqa: E402
import run_vcm_divider_tradeoff as divider_tradeoff  # noqa: E402
import run_vcm_cap_tradeoff as cap_tradeoff  # noqa: E402


BUILD = ROOT / "build" / "v3" / "four_channel_support_pvt"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "four_channel_support_pvt.json"
MEASURE_RE = re.compile(r"^([a-zA-Z0-9_]+)\s*=\s*([-+0-9.eE]+)", re.MULTILINE)


@dataclass(frozen=True)
class Corner:
    name: str
    process: str
    supply_v: float
    temperature_c: float


CORNERS = (
    Corner("tt_nominal", "tt", 1.80, 27.0),
    Corner("ff_high_cold", "ff", 1.98, -40.0),
    Corner("ss_low_hot", "ss", 1.62, 85.0),
    Corner("fs_nominal", "fs", 1.80, 27.0),
    Corner("sf_nominal", "sf", 1.80, 27.0),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corner_deck(
    mode: base.Mode,
    load_ohm: float,
    mim_count: int,
    varactor_count: int,
    divider_scale: float,
    corner: Corner,
) -> str:
    text = cap_tradeoff.cap_deck(
        mode, load_ohm, divider_scale, mim_count, varactor_count
    )
    text = text.replace(".temp 27\n", f".temp {corner.temperature_c:g}\n", 1)
    text = text.replace(
        '.include "spice/sky130/sky130_1v8_tt.inc"',
        f'.include "spice/sky130/sky130_1v8_{corner.process}.inc"',
        1,
    )
    text = text.replace(
        ".param VDD=1.8 FIN=5meg FLO=4meg FOUT=1meg",
        f".param VDD={corner.supply_v:.12g} FIN=5meg FLO=4meg FOUT=1meg",
        1,
    )
    extra = []
    for index in range(4):
        extra.extend((
            f"BGM_P_VDS{index} gm_p_vds{index} 0 v=v(xchannel{index}.xg0_0.gm_p)-v(xchannel{index}.xg0_0.tail)",
            f"BGM_N_VDS{index} gm_n_vds{index} 0 v=v(xchannel{index}.xg0_0.gm_n)-v(xchannel{index}.xg0_0.tail)",
            f".measure tran gm_p_vds_min_{index} min v(gm_p_vds{index}) from=4u to=8u",
            f".measure tran gm_n_vds_min_{index} min v(gm_n_vds{index}) from=4u to=8u",
            f".measure tran tail_min_{index} min v(xchannel{index}.xg0_0.tail) from=4u to=8u",
        ))
    return text.replace(".end\n", "\n".join(extra) + "\n.end\n", 1)


def run_case(
    ngspice: str,
    mode: base.Mode,
    load_ohm: float,
    mim_count: int,
    varactor_count: int,
    divider_scale: float,
    corner: Corner,
) -> dict[str, Any]:
    case_dir = BUILD / corner.name / f"load_{load_ohm:.3f}" / f"scale_{divider_scale:.3f}" / f"mim_{mim_count}_var_{varactor_count}" / mode.name
    case_dir.mkdir(parents=True, exist_ok=True)
    deck_path = case_dir / "support_pvt.spice"
    log_path = case_dir / "ngspice.log"
    deck_path.write_text(
        corner_deck(
            mode, load_ohm, mim_count, varactor_count, divider_scale, corner
        ),
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
        *(f"gm_p_vds_min_{index}" for index in range(4)),
        *(f"gm_n_vds_min_{index}" for index in range(4)),
        *(f"tail_min_{index}" for index in range(4)),
    }
    if completed.returncode != 0 or not required.issubset(values):
        raise RuntimeError(
            f"case {case_dir.relative_to(ROOT)} failed, return={completed.returncode}, "
            f"missing={sorted(required - values.keys())}\n" + "\n".join(log.splitlines()[-50:])
        )
    margins = [
        values[f"gm_{side}_vds_min_{index}"]
        for index in range(4) for side in ("p", "n")
    ]
    return {
        "corner": corner.name,
        "process": corner.process,
        "supply_v": corner.supply_v,
        "temperature_c": corner.temperature_c,
        "mode": mode.name,
        "load_ohm": load_ohm,
        "mim_count": mim_count,
        "varactor_count": varactor_count,
        "divider_scale_vs_v2": divider_scale,
        "divider_unit_length_um": 47.0 * divider_scale / 2.0,
        "vcm_average_v": values["vcm_avg"],
        "vcm_peak_to_peak_v": values["vcm_max"] - values["vcm_min"],
        "output_common_mode_average_v": values["output_cm_avg"],
        "output_common_mode_minimum_v": values["output_cm_min"],
        "filtered_output_tone_peak_v": 2.0 * math.hypot(values["tone_i_avg"], values["tone_q_avg"]),
        "minimum_gm_drain_to_tail_v": min(margins),
        "minimum_tail_v": min(values[f"tail_min_{index}"] for index in range(4)),
        "supply_current_a": abs(values["supply_avg"]),
        "deck": str(deck_path.relative_to(ROOT)),
        "deck_sha256": sha256(deck_path),
        "log": str(log_path.relative_to(ROOT)),
    }


def summarize(
    cases: list[dict[str, Any]],
    load_ohm: float,
    mim_count: int,
    varactor_count: int,
    divider_scale: float,
) -> dict[str, Any]:
    by_corner = {}
    for corner in CORNERS:
        selected = [case for case in cases if case["corner"] == corner.name]
        by_corner[corner.name] = {
            "minimum_output_common_mode_average_v": min(case["output_common_mode_average_v"] for case in selected),
            "minimum_instantaneous_output_common_mode_v": min(case["output_common_mode_minimum_v"] for case in selected),
            "minimum_gm_drain_to_tail_v": min(case["minimum_gm_drain_to_tail_v"] for case in selected),
            "maximum_vcm_peak_to_peak_v": max(case["vcm_peak_to_peak_v"] for case in selected),
            "vcm_average_range_v": [
                min(case["vcm_average_v"] for case in selected),
                max(case["vcm_average_v"] for case in selected),
            ],
            "filtered_output_tone_peak_range_v": [
                min(case["filtered_output_tone_peak_v"] for case in selected),
                max(case["filtered_output_tone_peak_v"] for case in selected),
            ],
        }
    gates = {
        "all_cases_completed": len(cases) == len(CORNERS) * len(base.MODES),
        "output_common_mode_average_at_least_0p8v": min(
            case["output_common_mode_average_v"] for case in cases
        ) >= 0.8,
        "instantaneous_output_common_mode_at_least_0p7v": min(
            case["output_common_mode_minimum_v"] for case in cases
        ) >= 0.7,
        "gm_drain_never_below_tail": min(
            case["minimum_gm_drain_to_tail_v"] for case in cases
        ) >= 0.0,
        "vcm_peak_to_peak_at_most_15mv": max(
            case["vcm_peak_to_peak_v"] for case in cases
        ) <= 0.015,
    }
    return {
        "schema_version": 1,
        "status": "pass" if all(gates.values()) else "fail",
        "scope": "selected schematic-level four-channel support PVT; passive PVT, nonlinear varactor, mismatch, extracted layout, and startup remain separate gates",
        "selected_candidate": {
            "load_ohm": load_ohm,
            "mim_count": mim_count,
            "varactor_count": varactor_count,
            "divider_scale_vs_v2": divider_scale,
            "divider_unit_count": 6,
            "divider_unit_length_um": 47.0 * divider_scale / 2.0,
        },
        "case_count": len(cases),
        "gates": gates,
        "by_corner": by_corner,
        "cases": sorted(cases, key=lambda item: (item["corner"], item["mode"])),
        "provenance": {
            "generator": "v3/tools/run_four_channel_support_pvt.py",
            "generator_sha256": sha256(Path(__file__)),
            "nominal_screen_generator": "v3/tools/run_four_channel_support_sweep.py",
            "nominal_screen_generator_sha256": sha256(TOOLS / "run_four_channel_support_sweep.py"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--load", type=float, default=2925.0)
    parser.add_argument("--mim-count", type=int, default=2)
    parser.add_argument("--varactors", type=int, default=0)
    parser.add_argument("--divider-scale", type=float, default=0.25)
    parser.add_argument("--corners", default=",".join(corner.name for corner in CORNERS))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    selected_names = set(args.corners.split(","))
    corners = [corner for corner in CORNERS if corner.name in selected_names]
    if {corner.name for corner in corners} != selected_names:
        raise SystemExit(f"unknown corners: {sorted(selected_names - {corner.name for corner in corners})}")
    jobs = [(corner, mode) for corner in corners for mode in base.MODES]
    cases: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                run_case, args.ngspice, mode, args.load, args.mim_count, args.varactors,
                args.divider_scale, corner,
            ): (corner, mode)
            for corner, mode in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            corner, mode = futures[future]
            cases.append(future.result())
            print(f"completed {corner.name} {mode.name}", flush=True)
    # A subset run is diagnostic and should not overwrite the final all-corner
    # evidence with a misleading gate status.
    if len(corners) == len(CORNERS):
        report = summarize(
            cases, args.load, args.mim_count, args.varactors, args.divider_scale
        )
    else:
        report = {
            "schema_version": 1,
            "status": "diagnostic_subset",
            "selected_candidate": {
                "load_ohm": args.load,
                "mim_count": args.mim_count,
                "varactor_count": args.varactors,
                "divider_scale_vs_v2": args.divider_scale,
            },
            "corners": [corner.name for corner in corners],
            "cases": sorted(cases, key=lambda item: (item["corner"], item["mode"])),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    if report["status"] == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
