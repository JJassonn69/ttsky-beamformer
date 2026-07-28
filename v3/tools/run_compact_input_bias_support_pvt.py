#!/usr/bin/env python3
"""Re-run the selected four-channel PVT gate with the compact bias resistor."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path

import run_four_channel_support_pvt as pvt
import run_four_channel_support_sweep as base


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "v3" / "compact_input_bias_support_pvt"
OUTPUT = ROOT / "v3" / "evidence" / "compact_input_bias_support_pvt.json"
OLD = "sky130_fd_pr__res_xhigh_po_1p41 l=70.5"
NEW = "sky130_fd_pr__res_xhigh_po_0p35 l=17.36"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact_deck(mode, load_ohm, mim_count, varactor_count, divider_scale, corner):
    text = ORIGINAL_DECK(mode, load_ohm, mim_count, varactor_count, divider_scale, corner)
    if text.count(OLD) != 4:
        raise RuntimeError("expected exactly four old input-bias devices")
    return text.replace(OLD, NEW)


ORIGINAL_DECK = pvt.corner_deck


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()
    pvt.BUILD = BUILD
    pvt.corner_deck = compact_deck
    load, mim_count, varactors, scale = 2925.0, 3, 0, 0.25
    jobs = [(corner, mode) for corner in pvt.CORNERS for mode in base.MODES]
    cases = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                pvt.run_case, args.ngspice, mode, load, mim_count, varactors,
                scale, corner,
            ): (corner, mode)
            for corner, mode in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            corner, mode = futures[future]
            cases.append(future.result())
            print(f"completed {corner.name} {mode.name}", flush=True)
    report = pvt.summarize(cases, load, mim_count, varactors, scale)
    report["scope"] = "selected 20-case four-channel MOS PVT rerun with four characterized compact res_xhigh_po_0p35 l=17.36 input-bias devices"
    report["input_bias"] = {
        "old": "four res_xhigh_po_1p41 l=70.5",
        "new": "four res_xhigh_po_0p35 l=17.36",
        "external_ac_coupling_pf": 100.0,
    }
    report["provenance"] = {
        **report["provenance"],
        "compact_regression_generator": "v3/tools/run_compact_input_bias_support_pvt.py",
        "compact_regression_generator_sha256": sha256(Path(__file__)),
        "input_bias_equivalence_sha256": sha256(ROOT / "v3" / "evidence" / "input_bias_equivalence.json"),
        "physical_gate_sha256": sha256(ROOT / "v3" / "evidence" / "channel_input_bias_physical_gate.json"),
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "case_count": report["case_count"], "gates": report["gates"]}, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
