#!/usr/bin/env python3
"""Measure the wanted 1 MHz IF tone after extraction at several LO rates."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "spice" / "sky130" / "extracted_core_tb.spice"
MEASURE_RE = re.compile(
    r"^\s*(tone_i|tone_q|mode_cm|mode_supply)\s*=\s*([-+0-9.eE]+)",
    re.MULTILINE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frequencies", default="4,10,20,30",
                        help="comma-separated clock frequencies in MHz")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--netlist", default="build/layout/extracted.spice")
    parser.add_argument("--merge-existing", action="store_true",
                        help="replace only requested frequencies in the existing report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frequencies = [
        float(item) for item in args.frequencies.split(",") if item.strip()
    ]
    template = TEMPLATE.read_text(encoding="utf-8").replace(
        '.include "build/layout/extracted.spice"', f'.include "{args.netlist}"'
    )
    # Remove the broadband RMS measures.  Switching-carrier feedthrough can
    # dominate those values even though it is outside the wanted 1 MHz IF.
    template = re.sub(r"^\.measure tran (sum|null)_(rms|cm|supply).*$", "",
                      template, flags=re.MULTILINE)
    template = re.sub(r"^\.tran .*$", "", template, flags=re.MULTILINE)
    analysis = (
        "\n* Coherent quadrature detector for the wanted 1 MHz IF only.\n"
        "BIF_I if_i 0 v=v(filtered)*sin(2*pi*1meg*time)\n"
        "BIF_Q if_q 0 v=v(filtered)*cos(2*pi*1meg*time)\n"
        ".tran {TSTEP} 20u 10u\n"
        ".measure tran tone_i avg v(if_i) from=10u to=20u\n"
        ".measure tran tone_q avg v(if_q) from=10u to=20u\n"
        ".measure tran mode_cm avg v(common_mode) from=10u to=20u\n"
        ".measure tran mode_supply avg i(VDD) from=10u to=20u\n"
    )
    template = template.replace("\n.end", analysis + "\n.end")
    build = ROOT / "build" / "extracted_frequency"
    build.mkdir(parents=True, exist_ok=True)
    report_path = ROOT / "build" / "extracted_frequency_sweep.json"
    previous_results: list[dict[str, object]] = []
    if args.merge_existing and report_path.exists():
        previous_results = json.loads(
            report_path.read_text(encoding="utf-8")
        ).get("results", [])
    results: list[dict[str, object]] = []
    for frequency_mhz in frequencies:
        period_ns = 1000.0 / frequency_mhz
        high_ns = period_ns / 2.0 - 1.0
        step_ns = min(1.0, period_ns / 50.0)
        frequency_results: dict[str, dict[str, float]] = {}
        errors: list[str] = []
        for mode, select in (("sum", "0"), ("null", "{VDDVAL}")):
            tag = f"{frequency_mhz:g}mhz_{mode}".replace(".", "p")
            deck = build / f"{tag}.spice"
            log = build / f"{tag}.log"
            text = template.replace(".param FIN=5meg",
                                    f".param FIN={frequency_mhz + 1:g}meg")
            text = re.sub(
                r"^VCLK clk 0 .*$",
                f"VCLK clk 0 pulse(0 {{VDDVAL}} 100n 1n 1n {high_ns:g}n {period_ns:g}n)",
                text, flags=re.MULTILINE,
            )
            text = re.sub(r"^VSEL ui_in\[0\].*$",
                          f"VSEL ui_in[0] 0 {select}", text, flags=re.MULTILINE)
            text = text.replace("{TSTEP}", f"{step_ns:g}n")
            deck.write_text(text, encoding="utf-8")
            completed = subprocess.run(
                [args.ngspice, "-b", "-o", str(log), str(deck)], cwd=ROOT,
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            )
            values = {
                name: float(value)
                for name, value in MEASURE_RE.findall(
                    log.read_text(encoding="utf-8", errors="replace")
                    if log.exists() else ""
                )
            }
            required = {"tone_i", "tone_q", "mode_cm", "mode_supply"}
            if completed.returncode or required - values.keys():
                errors.append(f"{mode}: ngspice={completed.returncode}, values={values}")
            else:
                values["tone_rms"] = math.sqrt(
                    2.0 * (values["tone_i"] ** 2 + values["tone_q"] ** 2)
                )
                values["tone_phase_deg"] = math.degrees(
                    math.atan2(values["tone_q"], values["tone_i"])
                )
                frequency_results[mode] = values
        if errors:
            result: dict[str, object] = {
                "frequency_mhz": frequency_mhz, "passed": False,
                "error": "; ".join(errors),
            }
        else:
            sum_values = frequency_results["sum"]
            null_values = frequency_results["null"]
            null_db = -20.0 * math.log10(
                max(null_values["tone_rms"], 1e-30) / sum_values["tone_rms"]
            )
            checks = {
                # This coherent detector excludes LO feedthrough; the v1
                # release floor is therefore stated explicitly for the wanted
                # IF rather than inherited from the old broadband-RMS gate.
                "wanted_tone": sum_values["tone_rms"] >= 0.5e-3,
                "release_null_db": null_db >= 20.0,
                "common_mode": 1.0 < min(sum_values["mode_cm"], null_values["mode_cm"])
                and max(sum_values["mode_cm"], null_values["mode_cm"]) < 1.75,
                "supply_current": 0 < max(-sum_values["mode_supply"],
                                           -null_values["mode_supply"]) < 1e-3,
            }
            result = {
                "frequency_mhz": frequency_mhz,
                "sum": sum_values,
                "null": null_values,
                "null_db": null_db,
                "nominal_40db_target_met": null_db >= 40.0,
                "checks": checks,
                "passed": all(checks.values()),
            }
        results.append(result)
        print(("PASS" if result["passed"] else "FAIL"),
              f"{frequency_mhz:g} MHz", flush=True)
    if args.merge_existing:
        replaced = set(frequencies)
        results = [
            item for item in previous_results
            if float(item["frequency_mhz"]) not in replaced
        ] + results
        results.sort(key=lambda item: float(item["frequency_mhz"]))
        # Re-evaluate retained numerical results with the current release
        # criteria so a threshold update cannot leave stale PASS/FAIL labels.
        for item in results:
            if "sum" not in item or "null" not in item:
                continue
            sum_values = item["sum"]
            null_values = item["null"]
            null_db = float(item["null_db"])
            checks = {
                "wanted_tone": float(sum_values["tone_rms"]) >= 0.5e-3,
                "release_null_db": null_db >= 20.0,
                "common_mode": 1.0 < min(float(sum_values["mode_cm"]),
                                           float(null_values["mode_cm"]))
                and max(float(sum_values["mode_cm"]),
                        float(null_values["mode_cm"])) < 1.75,
                "supply_current": 0 < max(-float(sum_values["mode_supply"]),
                                           -float(null_values["mode_supply"])) < 1e-3,
            }
            item["checks"] = checks
            item["nominal_40db_target_met"] = null_db >= 40.0
            item["passed"] = all(checks.values())
    report = {
        "if_frequency_mhz": 1.0,
        "frequencies_mhz": [float(item["frequency_mhz"]) for item in results],
        "pass_count": sum(bool(item["passed"]) for item in results),
        "case_count": len(results),
        "results": results,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"{report['pass_count']}/{report['case_count']} functional cases passed; "
          f"report={report_path}")
    return 0 if report["pass_count"] == report["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
