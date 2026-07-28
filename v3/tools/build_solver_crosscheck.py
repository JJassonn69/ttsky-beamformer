#!/usr/bin/env python3
"""Compare one frozen-factor mismatch case across SPARSE and KLU solvers."""

from __future__ import annotations

import cmath
import hashlib
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/solver_crosscheck"
MEASURE_RE = re.compile(r"^([a-z0-9_]+)\s*=\s*([-+0-9.eE]+)", re.MULTILINE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(prefix: str) -> dict[str, object]:
    deck_path = BUILD / f"{prefix}.spice"
    log_path = BUILD / f"{prefix}.log"
    log = log_path.read_text(errors="replace")
    values = {key: float(value) for key, value in MEASURE_RE.findall(log)}
    required = {"tone_i_avg", "tone_q_avg", "output_cm_avg", "supply_avg"}
    if not required.issubset(values):
        raise RuntimeError(f"{prefix} is missing {sorted(required - values.keys())}")
    solver_match = re.search(r"Using\s+(.+?)\s+as Direct Linear Solver", log)
    value = complex(values["tone_q_avg"], values["tone_i_avg"])
    return {
        "solver": solver_match.group(1) if solver_match else "unknown",
        "phasor_v": [value.real, value.imag],
        "tone_peak_v": 2.0 * abs(value),
        "phase_deg": math.degrees(cmath.phase(value)),
        "output_common_mode_v": values["output_cm_avg"],
        "supply_current_a": abs(values["supply_avg"]),
        "deck": str(deck_path.relative_to(ROOT)),
        "deck_sha256": sha256(deck_path),
        "log": str(log_path.relative_to(ROOT)),
        "log_sha256": sha256(log_path),
    }


def main() -> None:
    sparse = parse("local_sparse")
    klu = parse("remote_klu")
    sparse_value = complex(*sparse["phasor_v"])
    klu_value = complex(*klu["phasor_v"])
    deltas = {
        "tone_peak_percent": 100.0 * (abs(klu_value) / abs(sparse_value) - 1.0),
        "phase_deg": math.degrees(cmath.phase(klu_value / sparse_value)),
        "output_common_mode_uv": 1e6 * (
            float(klu["output_common_mode_v"]) - float(sparse["output_common_mode_v"])
        ),
        "supply_current_percent": 100.0 * (
            float(klu["supply_current_a"]) / float(sparse["supply_current_a"]) - 1.0
        ),
    }
    gate = {
        "tone_peak_difference_at_most_0p05_percent": abs(deltas["tone_peak_percent"]) <= 0.05,
        "phase_difference_at_most_0p05deg": abs(deltas["phase_deg"]) <= 0.05,
        "common_mode_difference_at_most_10uv": abs(deltas["output_common_mode_uv"]) <= 10.0,
        "supply_current_difference_at_most_0p05_percent": abs(deltas["supply_current_percent"]) <= 0.05,
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(gate.values()) else "fail",
        "scope": "one TT 20 mV-peak frozen-factor case; numerical solver cross-check only",
        "case": {"seed": 4001, "word": 8},
        "sparse": sparse,
        "klu": klu,
        "deltas": deltas,
        "gate": gate,
    }
    output = BUILD / "summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "deltas": deltas, "gate": gate}, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
