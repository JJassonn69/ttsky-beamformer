#!/usr/bin/env python3
"""Run a bounded two-tone post-layout IIP3 pilot at the nominal signal plan."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from run_control_postlayout_smoke import (
    DEFAULT_BASE,
    DEFAULT_GDS,
    DEFAULT_RC,
    DEFAULT_VARACTOR_MODEL,
    SPICE_INIT,
    deck_text,
    extracted_model_names,
    parse_measures,
    prepare_runtime,
    sha256,
)


ROOT = Path(__file__).resolve().parents[2]
BUILD = Path("build/v2/gate5_twotone_pilot")
FREQUENCIES_MHZ = {"im3_low": 0.7, "fund_low": 0.9, "fund_high": 1.1, "im3_high": 1.3}


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT) if path.is_absolute() else path)


def twotone_deck(netlist: Path, gds_hash: str, view: str, per_tone_peak_v: float) -> str:
    netlist_hash = sha256(ROOT / netlist if not netlist.is_absolute() else netlist)
    absolute_netlist = ROOT / netlist if not netlist.is_absolute() else netlist
    deck = deck_text(
        Path(relative(absolute_netlist)), netlist_hash, gds_hash,
        beam=0,
        input_phases_deg=(0.0, 0.0, 0.0, 0.0),
        input_peak_v=max(per_tone_peak_v, 1e-12),
        distributed_rc=view == "rc",
        operating_point_startup=True,
        analysis_start_us=5.0,
        analysis_stop_us=10.0,
        transient_step_ns=5.0,
        extracted_varactor_model=(
            DEFAULT_VARACTOR_MODEL
            if "sky130_fd_pr__cap_var_lvt" in extracted_model_names(absolute_netlist.read_text())
            else None
        ),
    )
    source_pattern = re.compile(
        r"^VIN([0-3]) source\1 0 sin\(0 \{VINPK\} \{FIN\} 0 0 0\)$",
        re.MULTILINE,
    )
    replacement = (
        r"BVIN\1 source\1 0 v={VINTONE*(sin(2*pi*F1*time)+sin(2*pi*F2*time))}"
    )
    deck, count = source_pattern.subn(replacement, deck)
    if count != 4:
        raise ValueError(f"expected four input voltage sources, replaced {count}")
    parameter_line = ".param VDD=1.8 FIN=5meg FOUT=1meg FLO=4meg VINPK="
    parameter_matches = [line for line in deck.splitlines() if line.startswith(parameter_line)]
    if len(parameter_matches) != 1:
        raise ValueError("nominal parameter line changed")
    extended = (
        parameter_matches[0]
        + f" F1=4.9meg F2=5.1meg VINTONE={per_tone_peak_v:.12g}"
    )
    deck = deck.replace(parameter_matches[0], extended)
    demodulators = []
    measures = []
    for name, frequency in FREQUENCIES_MHZ.items():
        demodulators.extend((
            f"B{name.upper()}I {name}_i 0 v=v(differential)*cos(2*pi*{frequency:g}meg*time)",
            f"B{name.upper()}Q {name}_q 0 v=v(differential)*sin(2*pi*{frequency:g}meg*time)",
        ))
        measures.extend((
            f".measure tran {name}_i_avg avg v({name}_i) from=5u to=10u",
            f".measure tran {name}_q_avg avg v({name}_q) from=5u to=10u",
            f".measure tran {name}_rms param='sqrt(2*({name}_i_avg*{name}_i_avg+{name}_q_avg*{name}_q_avg))'",
        ))
    marker = ".save v(filtered)"
    if deck.count(marker) != 1 or deck.count("\n.end") != 1:
        raise ValueError("smoke deck insertion markers changed")
    deck = deck.replace(marker, "\n".join(demodulators) + "\n" + marker)
    deck = deck.replace("\n.end", "\n" + "\n".join(measures) + "\n\n.end")
    return deck


def run_case(
    view: str,
    amplitude: float,
    netlist: Path,
    gds: Path,
    timeout: int,
    ngspice: str,
    build: Path,
) -> dict[str, Any]:
    label = "background" if amplitude == 0 else f"tone_{round(amplitude*1e6):d}uvpk"
    work = build / view / label
    work.mkdir(parents=True, exist_ok=True)
    deck_path = work / "twotone.spice"
    log_path = work / "ngspice.log"
    report_path = work / "report.json"
    deck_path.write_text(twotone_deck(netlist, sha256(gds), view, amplitude))
    runtime = prepare_runtime(work)
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            [ngspice, "-b", "-o", str(log_path.resolve()), str(deck_path.resolve())],
            cwd=runtime, text=True, capture_output=True, check=False, timeout=timeout,
        )
        returncode = completed.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        returncode = 124
    values = parse_measures(log_path.read_text(errors="replace") if log_path.is_file() else "")
    errors = []
    required = {
        f"{name}_{component}_avg" for name in FREQUENCIES_MHZ for component in ("i", "q")
    } | {"common_mode_avg", "supply_avg"}
    missing = sorted(required - values.keys())
    if missing:
        errors.append(f"missing measurements: {missing}")
    if timed_out:
        errors.append(f"ngspice exceeded the {timeout} second timeout")
    elif returncode:
        errors.append(f"ngspice exited with status {returncode}")
    report = {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "view": view,
        "input_tones_mhz": [4.9, 5.1],
        "lo_frequency_mhz": 4.0,
        "per_tone_peak_v": amplitude,
        "gds": relative(gds),
        "gds_sha256": sha256(gds),
        "netlist": relative(netlist),
        "netlist_sha256": sha256(netlist),
        "spiceinit_sha256": hashlib.sha256(SPICE_INIT.encode()).hexdigest(),
        "ngspice_returncode": returncode,
        "timed_out": timed_out,
        "elapsed_s": time.monotonic() - started,
        "measurements": values,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return {"report": relative(report_path), "result": report}


def complex_component(report: dict[str, Any], name: str) -> complex:
    values = report["measurements"]
    return complex(values[f"{name}_i_avg"], values[f"{name}_q_avg"])


def corrected_rms(report: dict[str, Any], background: dict[str, Any], name: str) -> float:
    value = complex_component(report, name) - complex_component(background, name)
    return math.sqrt(2.0) * abs(value)


def analyze_reports(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    if any(item.get("status") != "pass" for item in reports.values()):
        errors.append("one or more two-tone simulations failed")
    points: dict[str, Any] = {}
    if not errors:
        background = reports["background"]
        for label in ("tone_2mvpk", "tone_10mvpk"):
            report = reports[label]
            components = {
                name: corrected_rms(report, background, name) for name in FREQUENCIES_MHZ
            }
            fundamental = math.sqrt(components["fund_low"] * components["fund_high"])
            im3 = max(components["im3_low"], components["im3_high"])
            separation = math.inf if im3 == 0 else 20 * math.log10(fundamental/im3)
            input_rms_dbv = 20 * math.log10(report["per_tone_peak_v"] / math.sqrt(2.0))
            iip3 = input_rms_dbv + separation/2.0
            points[label] = {
                "components_rms_v": components,
                "fundamental_to_worst_im3_db": separation,
                "input_iip3_dbv_rms_per_tone": iip3,
            }
            if separation < 20.0:
                errors.append(f"{label}: fundamental-to-IM3 separation is below 20 dB")
        if len(points) == 2:
            estimates = [point["input_iip3_dbv_rms_per_tone"] for point in points.values()]
            spread = max(estimates) - min(estimates)
            if spread > 6.0:
                errors.append(f"two-tone IIP3 estimates disagree by {spread:.3f} dB")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "points": points,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("base", "rc"), default="base")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--gds", type=Path, default=DEFAULT_GDS)
    parser.add_argument("--base-netlist", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--rc-netlist", type=Path, default=DEFAULT_RC)
    parser.add_argument("--build", type=Path, default=BUILD)
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 3:
        raise SystemExit("jobs must be between one and three")
    if not shutil.which(args.ngspice):
        raise SystemExit(f"ngspice not found: {args.ngspice}")
    gds = ROOT / args.gds
    netlist = ROOT / (args.base_netlist if args.view == "base" else args.rc_netlist)
    build = ROOT / args.build
    amplitudes = (0.0, 0.002, 0.010)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(
                run_case, args.view, amplitude, netlist, gds,
                args.timeout, args.ngspice, build,
            ): amplitude
            for amplitude in amplitudes
        }
        items = [future.result() for future in concurrent.futures.as_completed(futures)]
    reports = {
        ("background" if item["result"]["per_tone_peak_v"] == 0 else
         f"tone_{round(item['result']['per_tone_peak_v']*1e3):d}mvpk"): item["result"]
        for item in items
    }
    analysis = analyze_reports(reports)
    summary = {
        "schema_version": 1,
        "gate": 5,
        "scope": "bounded two-tone IIP3 pilot; not a production guarantee",
        "status": analysis["status"],
        "errors": analysis["errors"],
        "view": args.view,
        "gds_sha256": sha256(gds),
        "netlist_sha256": sha256(netlist),
        "analysis": analysis,
        "cases": {
            label: {
                "report": item["report"],
                "report_sha256": sha256(ROOT / item["report"]),
            }
            for label, item in (
                ("background" if entry["result"]["per_tone_peak_v"] == 0 else
                 f"tone_{round(entry['result']['per_tone_peak_v']*1e3):d}mvpk", entry)
                for entry in items
            )
        },
    }
    report_path = build / f"{args.view}_summary.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"report={relative(report_path)}")
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
