#!/usr/bin/env python3
"""Generate and run the integrated beamformer PVT regression matrix."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path


MEASURE_RE = re.compile(
    r"^\s*(sum_rms|null_rms|sum_cm|null_cm|sum_supply|null_supply)\s*=\s*([-+0-9.eE]+)",
    re.MULTILINE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="run 5 corners x 3 supplies x 3 temperatures")
    parser.add_argument("--ngspice", default="ngspice")
    return parser.parse_args()


def evaluate(
    values: dict[str, float], null_db_min: float = 20.0
) -> tuple[dict[str, float], dict[str, bool]]:
    null_db = -20.0 * math.log10(max(values["null_rms"], 1e-30) / values["sum_rms"])
    sum_current = -values["sum_supply"]
    null_current = -values["null_supply"]
    derived = {
        "null_db": null_db,
        "sum_current_a": sum_current,
        "null_current_a": null_current,
    }
    checks = {
        "sum_rms": values["sum_rms"] > 1e-3,
        # beamformer_v1.md requires a 20 dB uncalibrated destructive null
        # across the signoff envelope.  Nominal verification separately keeps
        # the deliberately stronger 40 dB implementation target.
        "null_db": null_db >= null_db_min,
        "common_mode": 1.0 < min(values["sum_cm"], values["null_cm"]) and max(values["sum_cm"], values["null_cm"]) < 1.75,
        "supply_current": 0 < max(sum_current, null_current) < 1e-3,
        "mode_current_match": abs(sum_current / null_current - 1.0) < 0.10,
    }
    return derived, checks


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    template_path = root / "spice/sky130/beamformer_core.spice"
    template = template_path.read_text(encoding="utf-8")
    build_dir = root / "build/pvt"
    build_dir.mkdir(parents=True, exist_ok=True)

    corners = ("tt", "ss", "ff", "sf", "fs")
    supplies = (1.62, 1.80, 1.98) if args.full else (1.80,)
    temperatures = (-40, 27, 125) if args.full else (27,)
    results: list[dict[str, object]] = []

    for corner in corners:
        for supply in supplies:
            for temperature in temperatures:
                case = f"{corner}_{supply:.2f}v_{temperature:+d}c".replace("+", "p").replace("-", "m")
                netlist = template.replace(
                    'spice/sky130/sky130_1v8_tt.inc',
                    f'spice/sky130/sky130_1v8_{corner}.inc',
                )
                netlist = netlist.replace(".param VDDVAL=1.8", f".param VDDVAL={supply:.2f}")
                netlist = netlist.replace(".temp 27", f".temp {temperature}")
                netlist_path = build_dir / f"{case}.spice"
                log_path = build_dir / f"{case}.log"
                netlist_path.write_text(netlist, encoding="utf-8")

                completed = subprocess.run(
                    [args.ngspice, "-b", "-o", str(log_path), str(netlist_path)],
                    cwd=root,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                )
                text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
                values = {name: float(value) for name, value in MEASURE_RE.findall(text)}
                missing = sorted(set(MEASURE_RE.pattern.split("(")[1].split(")")[0].split("|")) - values.keys())
                if completed.returncode or missing:
                    result = {
                        "case": case,
                        "corner": corner,
                        "supply_v": supply,
                        "temperature_c": temperature,
                        "passed": False,
                        "error": f"ngspice={completed.returncode}, missing={missing}",
                    }
                else:
                    derived, checks = evaluate(values)
                    result = {
                        "case": case,
                        "corner": corner,
                        "supply_v": supply,
                        "temperature_c": temperature,
                        **values,
                        **derived,
                        "checks": checks,
                        "passed": all(checks.values()),
                    }
                results.append(result)
                status = "PASS" if result["passed"] else "FAIL"
                print(f"{status} {case}", flush=True)

    report = {
        "matrix": "full" if args.full else "quick",
        "null_db_min_spec": 20.0,
        "case_count": len(results),
        "pass_count": sum(bool(item["passed"]) for item in results),
        "results": results,
    }
    report_path = root / "build/core_pvt_summary.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{report['pass_count']}/{report['case_count']} cases passed; report={report_path}")
    return 0 if report["pass_count"] == report["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
