#!/usr/bin/env python3
"""Measure extracted complementary and per-channel LO timing versus clock rate."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "spice" / "sky130" / "extracted_clock_tb.spice"
MEASURES = (
    "lop_delay", "lon_delay", "ch1_lop_delay", "ch2_lon_delay",
    "ch1_lon_delay", "ch2_lop_delay", "ch1_lop_rise", "ch2_lon_rise",
    "ch1_lon_fall", "ch2_lop_fall", "ch1_lop_high", "ch2_lon_high",
    "ch1_lon_low", "ch2_lop_low",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frequencies", default="4,10,20,30",
                        help="comma-separated clock frequencies in MHz")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--netlist", default="build/layout/extracted.spice")
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
    frequencies = [float(item) for item in args.frequencies.split(",")]
    template = TEMPLATE.read_text(encoding="utf-8").replace(
        '.include "build/layout/extracted.spice"', f'.include "{args.netlist}"'
    )
    build = ROOT / "build" / "extracted_clock"
    build.mkdir(parents=True, exist_ok=True)
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
                "rail_high": min(values["ch1_lop_high"], values["ch2_lon_high"]) > 1.70,
                "rail_low": max(values["ch1_lon_low"], values["ch2_lop_low"]) < 0.10,
                "paired_channel_skew": max(p_pair_skew, n_pair_skew) < 1e-9,
                "complement_skew": complement_skew < 1e-9,
                "edge_fraction": max_edge < 0.10 * period,
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
