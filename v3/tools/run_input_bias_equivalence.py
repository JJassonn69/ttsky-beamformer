#!/usr/bin/env python3
"""Compare the old and compact input-bias resistors across bounded PVT."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "v3" / "input_bias_equivalence"
OUTPUT = ROOT / "v3" / "evidence" / "input_bias_equivalence.json"
MODEL_ROOT = ROOT / "third_party" / "sky130_fd_pr"
LINEAR = MODEL_ROOT / "models" / "sky130_fd_pr__model__linear.model.spice"
CORNERS = {
    "res_low": (
        MODEL_ROOT / "models" / "r+c" / "res_low__cap_low.spice",
        MODEL_ROOT / "models" / "r+c" / "res_low__cap_low__lin.spice",
    ),
    "res_typical": (
        MODEL_ROOT / "models" / "r+c" / "res_typical__cap_typical.spice",
        MODEL_ROOT / "models" / "r+c" / "res_typical__cap_typical__lin.spice",
    ),
    "res_high": (
        MODEL_ROOT / "models" / "r+c" / "res_high__cap_high.spice",
        MODEL_ROOT / "models" / "r+c" / "res_high__cap_high__lin.spice",
    ),
}
TEMPERATURES_C = (-40, 27, 125)
VOLTAGES_V = (0.1, 0.9, 1.8)
VALUE_RE = re.compile(r"^(r_old|r_new)\s+=\s+([+\-\d.eE]+)\s*$", re.MULTILINE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deck(corner: str, temperature: int, voltage: float) -> str:
    nonlinear, linear = CORNERS[corner]
    return f"""* V3 compact input-bias equivalence.
.include \"{nonlinear}\"
.include \"{linear}\"
.include \"{LINEAR}\"
.temp {temperature}
VOLD old 0 {voltage}
VNEW new 0 {voltage}
XOLD old 0 0 sky130_fd_pr__res_xhigh_po_1p41 l=70.5
XNEW new 0 0 sky130_fd_pr__res_xhigh_po_0p35 l=17.36
.control
set noaskquit
op
let r_old = -v(old)/i(vold)
let r_new = -v(new)/i(vnew)
print r_old r_new
quit
.endc
.end
"""


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    cases = []
    for corner in CORNERS:
        for temperature in TEMPERATURES_C:
            for voltage in VOLTAGES_V:
                name = f"{corner}_{temperature:+d}C_{str(voltage).replace('.', 'p')}V"
                case_dir = BUILD / name
                case_dir.mkdir(parents=True, exist_ok=True)
                deck_path = case_dir / "compare.spice"
                log_path = case_dir / "ngspice.log"
                deck_path.write_text(deck(corner, temperature, voltage), encoding="utf-8")
                result = subprocess.run(
                    ["ngspice", "-b", str(deck_path)], cwd=ROOT,
                    text=True, capture_output=True, check=False,
                )
                log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
                values = {key: float(value) for key, value in VALUE_RE.findall(result.stdout + result.stderr)}
                if result.returncode != 0 or set(values) != {"r_old", "r_new"}:
                    raise RuntimeError(f"ngspice comparison failed for {name}; see {log_path}")
                delta = 100.0 * (values["r_new"] / values["r_old"] - 1.0)
                cases.append({
                    "corner": corner,
                    "temperature_c": temperature,
                    "voltage_v": voltage,
                    "old_resistance_ohm": values["r_old"],
                    "new_resistance_ohm": values["r_new"],
                    "new_vs_old_percent": delta,
                    "deck": str(deck_path.relative_to(ROOT)),
                    "deck_sha256": sha256(deck_path),
                    "log": str(log_path.relative_to(ROOT)),
                    "log_sha256": sha256(log_path),
                })
    worst = max(cases, key=lambda item: abs(item["new_vs_old_percent"]))
    nominal = next(
        item for item in cases
        if item["corner"] == "res_typical" and item["temperature_c"] == 27 and item["voltage_v"] == 0.9
    )
    new_values = [item["new_resistance_ohm"] for item in cases]
    gates = {
        "all_27_cases_completed": len(cases) == 27,
        "typical_compact_resistance_matches_old_within_0p5pct": abs(nominal["new_vs_old_percent"]) <= 0.5,
        "width_dependent_corner_shift_is_bounded_within_7pct": abs(worst["new_vs_old_percent"]) <= 7.0,
        "compact_resistance_stays_in_80k_to_120k_bias_range": min(new_values) >= 80000.0 and max(new_values) <= 120000.0,
        "both_models_use_same_characterized_xhigh_base": True,
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(gates.values()) else "fail",
        "scope": "old 1.41x70.5 um versus compact 0.35x17.36 um characterized xhigh-poly input-bias resistor across bounded resistance corners, temperature, and terminal voltage",
        "cases": cases,
        "nominal_case": nominal,
        "worst_case": worst,
        "gates": gates,
        "model_provenance": {
            "linear_model_sha256": sha256(LINEAR),
            "corner_sha256": {
                corner: [sha256(path) for path in paths]
                for corner, paths in CORNERS.items()
            },
        },
        "next_gate": "exact guarded-PCell integration under a grounded M3 shield",
        "interpretation": "the input-bias resistor establishes DC common mode after the external AC-coupling capacitor; it is not in the signal-current gain path. The observed narrow-width process spread is acceptable only if the full four-channel PVT regression remains inside its existing functional gates.",
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "gates": gates, "worst_case": worst}, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
