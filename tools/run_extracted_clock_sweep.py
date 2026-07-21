#!/usr/bin/env python3
"""Measure extracted complementary and per-channel LO timing versus clock rate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from run_lock import acquire_run_lock
try:
    from simulation_provenance import ngspice_provenance
except ModuleNotFoundError:
    from tools.simulation_provenance import ngspice_provenance

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "spice" / "sky130" / "extracted_clock_tb.spice"
MEASURES = (
    "lop_delay", "lon_delay", "ch1_lop_delay", "ch2_lon_delay",
    "ch1_lon_delay", "ch2_lop_delay", "ch1_lop_rise", "ch2_lon_rise",
    "ch1_lon_fall", "ch2_lop_fall", "ch1_lop_high", "ch2_lon_high",
    "ch1_lon_low", "ch2_lop_low",
)
PAIRED_SKEW_LIMIT_S = 50e-12
COMPLEMENT_SKEW_LIMIT_S = 150e-12
EDGE_LIMIT_S = 250e-12
RAIL_MIN_V = -0.10
RAIL_MAX_V = 1.90


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frequencies", default="4,10,20,30",
                        help="comma-separated clock frequencies in MHz")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--netlist", default="build/layout/extracted_rc.spice")
    return parser.parse_args()


def measurements(path: Path) -> dict[str, float]:
    text = path.read_text(encoding="utf-8", errors="replace")
    values: dict[str, float] = {}
    for name in MEASURES:
        match = re.search(
            rf"^\s*{re.escape(name)}\s*=\s*([-+0-9.eE]+)", text, re.MULTILINE
        )
        if match:
            values[name] = float(match.group(1))
    return values


def main() -> int:
    args = parse_args()
    netlist_path = ROOT / args.netlist
    netlist_sha256 = hashlib.sha256(netlist_path.read_bytes()).hexdigest()
    frequencies = [float(item) for item in args.frequencies.split(",")]
    template = (f"* extracted_netlist_sha256={netlist_sha256}\n" +
                TEMPLATE.read_text(encoding="utf-8")).replace(
        '.include "build/layout/extracted.spice"', f'.include "{args.netlist}"'
    )
    build = ROOT / "build" / "extracted_clock"
    build.mkdir(parents=True, exist_ok=True)
    run_lock = acquire_run_lock(build / ".run.lock")
    results: list[dict[str, object]] = []
    for frequency_mhz in frequencies:
        tag = f"{frequency_mhz:g}mhz".replace(".", "p")
        deck = build / f"clock_{tag}.spice"
        log = build / f"clock_{tag}.log"
        deck.write_text(
            template.replace(".param FCLK=4meg", f".param FCLK={frequency_mhz:g}meg"),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [args.ngspice, "-b", "-o", str(log), str(deck)], cwd=ROOT,
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        values = measurements(log) if log.exists() else {}
        missing = sorted(set(MEASURES) - values.keys())
        if completed.returncode or missing:
            result: dict[str, object] = {
                "frequency_mhz": frequency_mhz,
                "passed": False,
                "error": f"ngspice={completed.returncode}, missing={missing}",
            }
        else:
            period = 1.0 / (frequency_mhz * 1e6)
            complement_skew = abs(values["lop_delay"] - values["lon_delay"])
            p_pair_skew = abs(values["ch1_lop_delay"] - values["ch2_lon_delay"])
            n_pair_skew = abs(values["ch1_lon_delay"] - values["ch2_lop_delay"])
            max_edge = max(
                values["ch1_lop_rise"], values["ch2_lon_rise"],
                values["ch1_lon_fall"], values["ch2_lop_fall"],
            )
            checks = {
                "rail_high": (
                    min(values["ch1_lop_high"], values["ch2_lon_high"]) > 1.70
                    and max(values["ch1_lop_high"], values["ch2_lon_high"])
                    < RAIL_MAX_V
                ),
                "rail_low": (
                    max(values["ch1_lon_low"], values["ch2_lop_low"]) < 0.10
                    and min(values["ch1_lon_low"], values["ch2_lop_low"])
                    > RAIL_MIN_V
                ),
                "paired_channel_skew": (
                    max(p_pair_skew, n_pair_skew) < PAIRED_SKEW_LIMIT_S
                ),
                "complement_skew": complement_skew < COMPLEMENT_SKEW_LIMIT_S,
                "absolute_edge_time": max_edge < EDGE_LIMIT_S,
                "edge_fraction": max_edge < 0.02 * period,
            }
            result = {
                "frequency_mhz": frequency_mhz,
                **values,
                "complement_skew_s": complement_skew,
                "positive_pair_skew_s": p_pair_skew,
                "negative_pair_skew_s": n_pair_skew,
                "max_edge_s": max_edge,
                "checks": checks,
                "passed": all(checks.values()),
            }
        results.append(result)
        print(("PASS" if result["passed"] else "FAIL"), tag, flush=True)
    report = {
        **ngspice_provenance(args.ngspice),
        "netlist": args.netlist,
        "netlist_sha256": netlist_sha256,
        "limits": {
            "paired_channel_skew_s": PAIRED_SKEW_LIMIT_S,
            "complement_skew_s": COMPLEMENT_SKEW_LIMIT_S,
            "edge_time_s": EDGE_LIMIT_S,
            "edge_fraction": 0.02,
            "rail_min_v": RAIL_MIN_V,
            "rail_max_v": RAIL_MAX_V,
        },
        "frequencies_mhz": frequencies,
        "pass_count": sum(bool(item["passed"]) for item in results),
        "case_count": len(results),
        "results": results,
    }
    report_path = ROOT / "build" / "extracted_clock_sweep.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"{report['pass_count']}/{report['case_count']} timing cases passed; report={report_path}")
    return 0 if report["pass_count"] == report["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
