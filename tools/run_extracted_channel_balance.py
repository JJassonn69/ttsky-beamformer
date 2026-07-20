#!/usr/bin/env python3
"""Measure each extracted analog channel independently at the same output."""

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
    r"^\s*(mode_rms|mode_avg|mode_cm|mode_supply)\s*=\s*([-+0-9.eE]+)",
    re.MULTILINE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--netlist", default="build/layout/extracted.spice")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    template = TEMPLATE.read_text(encoding="utf-8").replace(
        '.include "build/layout/extracted.spice"', f'.include "{args.netlist}"'
    )
    template = re.sub(r"^VSEL ui_in\[0\].*$", "VSEL ui_in[0] 0 0",
                      template, flags=re.MULTILINE)
    template = re.sub(r"^\.tran .*$", ".tran 2n 20u 10u", template,
                      flags=re.MULTILINE)
    template = re.sub(
        r"^\.measure tran (sum|null)_(rms|cm|supply).*$", "", template,
        flags=re.MULTILINE,
    )
    template = template.replace(
        "\n.end",
        "\n.measure tran mode_rms rms v(filtered) from=10u to=20u\n"
        ".measure tran mode_avg avg v(filtered) from=10u to=20u\n"
        ".measure tran mode_cm avg v(common_mode) from=10u to=20u\n"
        ".measure tran mode_supply avg i(VDD) from=10u to=20u\n\n.end",
    )
    build = ROOT / "build" / "extracted_balance"
    build.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, float]] = {}
    errors: list[str] = []
    for channel, inactive_source in (("ch1", "VS2"), ("ch2", "VS1")):
        deck = build / f"{channel}.spice"
        log = build / f"{channel}.log"
        text = re.sub(
            rf"^{inactive_source} source[12] 0 sin\(0 \{{VINPK\}} \{{FIN\}}\)$",
            f"{inactive_source} " + ("source2" if inactive_source == "VS2" else "source1")
            + " 0 0",
            template,
            flags=re.MULTILINE,
        )
        deck.write_text(text, encoding="utf-8")
        completed = subprocess.run(
            [args.ngspice, "-b", "-o", str(log), str(deck)], cwd=ROOT,
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        values = {
            name: float(value)
            for name, value in MEASURE_RE.findall(
                log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
            )
        }
        required = {"mode_rms", "mode_avg", "mode_cm", "mode_supply"}
        if completed.returncode or required - values.keys():
            errors.append(f"{channel}: ngspice={completed.returncode}, values={values}")
        else:
            values["mode_ac_rms"] = max(
                values["mode_rms"] ** 2 - values["mode_avg"] ** 2, 0.0
            ) ** 0.5
            results[channel] = values
            print(f"{channel}: {values['mode_ac_rms']:.8g} Vac-rms", flush=True)
    if errors:
        print("; ".join(errors))
        return 1
    ch1 = results["ch1"]["mode_ac_rms"]
    ch2 = results["ch2"]["mode_ac_rms"]
    average = (ch1 + ch2) / 2.0
    mismatch = abs(ch1 - ch2) / average
    report: dict[str, object] = {
        "channels": results,
        "gain_mismatch_fraction": mismatch,
        "gain_mismatch_percent": 100.0 * mismatch,
        "estimated_amplitude_only_null_db": -20.0 * math.log10(
            max(mismatch / 2.0, 1e-30)
        ),
        "passed": mismatch < 0.02,
    }
    report_path = ROOT / "build" / "extracted_channel_balance.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"report={report_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
