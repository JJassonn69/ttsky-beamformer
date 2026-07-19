#!/usr/bin/env python3
"""Run matched-time PVT regressions on the parasitic-extracted layout."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from run_core_pvt import evaluate
from run_extracted_sim import MEASURE_BLOCK

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "spice" / "sky130" / "extracted_core_tb.spice"
MODE_RE = re.compile(
    r"^\s*(mode_rms|mode_cm|mode_supply)\s*=\s*([-+0-9.eE]+)", re.MULTILINE
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def run_mode(
    ngspice: str,
    template: str,
    build: Path,
    case: str,
    mode: str,
    select: str,
) -> tuple[str, str, int, dict[str, float]]:
    deck = build / f"{case}_{mode}.spice"
    log = build / f"{case}_{mode}.log"
    measures = (
        ".measure tran mode_rms rms v(filtered) from=40u to=50u\n"
        ".measure tran mode_cm avg v(common_mode) from=40u to=50u\n"
        ".measure tran mode_supply avg i(VDD) from=40u to=50u"
    )
    text = re.sub(
        r"^VSEL ui_in\[0\].*$",
        f"VSEL ui_in[0] 0 {select}",
        template,
        flags=re.MULTILINE,
    ).replace(MEASURE_BLOCK, measures)
    deck.write_text(text)
    completed = subprocess.run(
        [ngspice, "-b", "-o", str(log), str(deck)],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    log_text = log.read_text(errors="replace") if log.exists() else ""
    values = {name: float(value) for name, value in MODE_RE.findall(log_text)}
    return case, mode, completed.returncode, values


def main() -> int:
    args = parse_args()
    template = TEMPLATE.read_text()
    build = ROOT / "build" / "extracted_pvt"
    build.mkdir(parents=True, exist_ok=True)
    corners = ("tt", "ss", "ff", "sf", "fs")
    supplies = (1.62, 1.80, 1.98) if args.full else (1.80,)
    temperatures = (-40, 27, 125) if args.full else (27,)
    cases: list[tuple[str, str, float, int, str]] = []
    for corner in corners:
        for supply in supplies:
            for temperature in temperatures:
                case = f"{corner}_{supply:.2f}v_{temperature:+d}c".replace("+", "p").replace("-", "m")
                case_template = template.replace(
                    "spice/sky130/sky130_1v8_tt.inc",
                    f"spice/sky130/sky130_1v8_{corner}.inc",
                ).replace(".param VDDVAL=1.8", f".param VDDVAL={supply:.2f}")
                case_template = case_template.replace(".temp 27", f".temp {temperature}")
                cases.append((case, corner, supply, temperature, case_template))

    raw: dict[tuple[str, str], tuple[int, dict[str, float]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = []
        for case, _corner, _supply, _temperature, case_template in cases:
            futures.append(
                executor.submit(run_mode, args.ngspice, case_template, build, case,
                                "sum", "0")
            )
            futures.append(
                executor.submit(run_mode, args.ngspice, case_template, build, case,
                                "null", "{VDDVAL}")
            )
        for future in as_completed(futures):
            case, mode, returncode, values = future.result()
            raw[(case, mode)] = (returncode, values)

    results: list[dict[str, object]] = []
    required = {"mode_rms", "mode_cm", "mode_supply"}
    for case, corner, supply, temperature, _template in cases:
        sum_rc, sum_values = raw[(case, "sum")]
        null_rc, null_values = raw[(case, "null")]
        if sum_rc or null_rc or required - sum_values.keys() or required - null_values.keys():
            result: dict[str, object] = {
                "case": case,
                "corner": corner,
                "supply_v": supply,
                "temperature_c": temperature,
                "passed": False,
                "error": f"ngspice=({sum_rc},{null_rc})",
            }
        else:
            values = {
                "sum_rms": sum_values["mode_rms"],
                "null_rms": null_values["mode_rms"],
                "sum_cm": sum_values["mode_cm"],
                "null_cm": null_values["mode_cm"],
                "sum_supply": sum_values["mode_supply"],
                "null_supply": null_values["mode_supply"],
            }
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
        print(("PASS" if result["passed"] else "FAIL"), case, flush=True)

    report = {
        "matrix": "full" if args.full else "quick",
        "null_db_min_spec": 20.0,
        "case_count": len(results),
        "pass_count": sum(bool(result["passed"]) for result in results),
        "measured_min_null_db": min(
            float(result["null_db"])
            for result in results
            if "null_db" in result
        ),
        "results": results,
    }
    report_path = ROOT / "build" / "extracted_pvt_summary.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"{report['pass_count']}/{report['case_count']} cases passed; report={report_path}")
    return 0 if report["pass_count"] == report["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
