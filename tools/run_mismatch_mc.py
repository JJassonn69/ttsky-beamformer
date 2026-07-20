#!/usr/bin/env python3
"""Foundry-slope-based random-mismatch Monte Carlo for the matched analog core.

The open SKY130 model bundle carries Spectre ``statistics`` blocks, which
ngspice does not execute.  This harness uses the published NMOS VTH Pelgrom
slope from that bundle and inserts independent gate offsets into only the
generated simulation decks.  It is a conservative surrogate, not a replacement
for foundry-qualified Spectre Monte Carlo.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "spice" / "sky130" / "beamformer_core.spice"
MEASURE_RE = re.compile(
    r"^\s*(sum_i|sum_q|null_i|null_q|sum_cm|null_cm|sum_supply|null_supply)"
    r"\s*=\s*([-+0-9.eE]+)", re.MULTILINE,
)
VTH_SLOPE_V_UM = 3.356e-3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--seed", type=int, default=130)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--load-sigma", type=float, default=0.005,
                        help="one-sigma independent output-load mismatch fraction")
    return parser.parse_args()


def sigma_vth(width_um: float, length_um: float) -> float:
    return VTH_SLOPE_V_UM / math.sqrt(width_um * length_um)


def make_deck(base: str, rng: random.Random, load_sigma: float) -> str:
    values = {
        "ch1_gm1": rng.gauss(0.0, sigma_vth(16.0, 0.30)),
        "ch1_gm2": rng.gauss(0.0, sigma_vth(16.0, 0.30)),
        "ch1_tail": rng.gauss(0.0, sigma_vth(38.0, 0.50)),
        "ch2_gm1": rng.gauss(0.0, sigma_vth(16.0, 0.30)),
        "ch2_gm2": rng.gauss(0.0, sigma_vth(16.0, 0.30)),
        "ch2_tail": rng.gauss(0.0, sigma_vth(38.0, 0.50)),
        "load_p": rng.gauss(0.0, load_sigma),
        "load_n": rng.gauss(0.0, load_sigma),
    }
    text = base.replace(
        ".subckt mixer_channel sig ref lop lon outp outn vbias vss",
        ".subckt mixer_channel sig ref lop lon outp outn vbias vss "
        "params: dv_gm1=0 dv_gm2=0 dv_tail=0",
    )
    text = text.replace(
        "XGM1 gm_p sig tail vss sky130_fd_pr__nfet_01v8 w=16 l=0.30",
        "BGM1 sig_mc vss v=v(sig,vss)+{dv_gm1}\n"
        "XGM1 gm_p sig_mc tail vss sky130_fd_pr__nfet_01v8 w=16 l=0.30",
    ).replace(
        "XGM2 gm_n ref tail vss sky130_fd_pr__nfet_01v8 w=16 l=0.30",
        "BGM2 ref_mc vss v=v(ref,vss)+{dv_gm2}\n"
        "XGM2 gm_n ref_mc tail vss sky130_fd_pr__nfet_01v8 w=16 l=0.30",
    ).replace(
        "XTAIL tail vbias vss vss sky130_fd_pr__nfet_01v8 w=38 l=0.50",
        "BTAIL vbias_mc vss v=v(vbias,vss)+{dv_tail}\n"
        "XTAIL tail vbias_mc vss vss sky130_fd_pr__nfet_01v8 w=38 l=0.50",
    )
    text = text.replace(
        "XCH1 sig1 vcm ch1_lop ch1_lon outp outn vbias vss mixer_channel",
        "XCH1 sig1 vcm ch1_lop ch1_lon outp outn vbias vss mixer_channel "
        f"dv_gm1={values['ch1_gm1']:.12g} dv_gm2={values['ch1_gm2']:.12g} "
        f"dv_tail={values['ch1_tail']:.12g}",
    ).replace(
        "XCH2 sig2 vcm ch2_lop ch2_lon outp outn vbias vss mixer_channel",
        "XCH2 sig2 vcm ch2_lop ch2_lon outp outn vbias vss mixer_channel "
        f"dv_gm1={values['ch2_gm1']:.12g} dv_gm2={values['ch2_gm2']:.12g} "
        f"dv_tail={values['ch2_tail']:.12g}",
    )
    text = text.replace(
        "XRLOADP vdd outp vss sky130_fd_pr__res_high_po_1p41 l=11.6117",
        "XRLOADP vdd outp vss sky130_fd_pr__res_high_po_1p41 "
        f"l={11.6117 * (1.0 + values['load_p']):.12g}",
    ).replace(
        "XRLOADN vdd outn vss sky130_fd_pr__res_high_po_1p41 l=11.6117",
        "XRLOADN vdd outn vss sky130_fd_pr__res_high_po_1p41 "
        f"l={11.6117 * (1.0 + values['load_n']):.12g}",
    )
    text = re.sub(r"^\.measure tran (sum|null)_rms.*$", "", text,
                  flags=re.MULTILINE)
    detector = (
        "\n* Simulation-only coherent 1 MHz mismatch detector.\n"
        "BSI sum_i_node 0 v=v(sfilt)*sin(2*pi*1meg*time)\n"
        "BSQ sum_q_node 0 v=v(sfilt)*cos(2*pi*1meg*time)\n"
        "BNI null_i_node 0 v=v(nfilt)*sin(2*pi*1meg*time)\n"
        "BNQ null_q_node 0 v=v(nfilt)*cos(2*pi*1meg*time)\n"
        ".measure tran sum_i avg v(sum_i_node) from=15u to=25u\n"
        ".measure tran sum_q avg v(sum_q_node) from=15u to=25u\n"
        ".measure tran null_i avg v(null_i_node) from=15u to=25u\n"
        ".measure tran null_q avg v(null_q_node) from=15u to=25u\n"
    )
    return re.sub(r"\n\.end\s*$", detector + "\n.end\n", text)


def run_trial(ngspice: str, deck: Path, log: Path) -> tuple[int, dict[str, float]]:
    completed = subprocess.run(
        [ngspice, "-b", "-o", str(log), str(deck)], cwd=ROOT,
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    values = {
        name: float(value)
        for name, value in MEASURE_RE.findall(
            log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        )
    }
    return completed.returncode, values


def main() -> int:
    args = parse_args()
    if args.trials < 1:
        raise SystemExit("--trials must be positive")
    base = TEMPLATE.read_text(encoding="utf-8")
    build = ROOT / "build" / "mismatch_mc"
    build.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    jobs: list[tuple[int, Path, Path]] = []
    for index in range(args.trials):
        deck = build / f"trial_{index:04d}.spice"
        log = build / f"trial_{index:04d}.log"
        deck.write_text(make_deck(base, rng, args.load_sigma), encoding="utf-8")
        jobs.append((index, deck, log))
    raw: dict[int, tuple[int, dict[str, float]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(run_trial, args.ngspice, deck, log): index
            for index, deck, log in jobs
        }
        for future in as_completed(futures):
            index = futures[future]
            raw[index] = future.result()
            print(f"trial {index + 1}/{args.trials}", flush=True)
    required = {"sum_i", "sum_q", "null_i", "null_q", "sum_cm", "null_cm",
                "sum_supply", "null_supply"}
    results: list[dict[str, object]] = []
    for index in range(args.trials):
        returncode, values = raw[index]
        if returncode or required - values.keys():
            result: dict[str, object] = {
                "trial": index, "passed": False,
                "error": f"ngspice={returncode}, missing={sorted(required-values.keys())}",
            }
        else:
            sum_rms = math.sqrt(2.0 * (values["sum_i"] ** 2 + values["sum_q"] ** 2))
            null_rms = math.sqrt(2.0 * (values["null_i"] ** 2 + values["null_q"] ** 2))
            null_db = -20.0 * math.log10(max(null_rms, 1e-30) / sum_rms)
            result = {
                "trial": index, **values, "sum_tone_rms": sum_rms,
                "null_tone_rms": null_rms, "null_db": null_db,
                "passed": null_db >= 20.0 and sum_rms >= 0.5e-3,
            }
        results.append(result)
    valid_nulls = sorted(float(item["null_db"]) for item in results if "null_db" in item)
    report = {
        "method": "ngspice surrogate using SKY130 NMOS VTH Pelgrom slope",
        "vth_slope_v_um": VTH_SLOPE_V_UM,
        "gm_vth_sigma_v": sigma_vth(16.0, 0.30),
        "tail_vth_sigma_v": sigma_vth(38.0, 0.50),
        "load_sigma_fraction": args.load_sigma,
        "seed": args.seed,
        "trial_count": args.trials,
        "pass_count": sum(bool(item["passed"]) for item in results),
        "minimum_null_db": min(valid_nulls) if valid_nulls else None,
        "median_null_db": statistics.median(valid_nulls) if valid_nulls else None,
        "p05_null_db": valid_nulls[max(0, math.ceil(0.05 * len(valid_nulls)) - 1)]
        if valid_nulls else None,
        "results": results,
    }
    report_path = ROOT / "build" / "mismatch_mc_summary.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"{report['pass_count']}/{args.trials} trials passed; report={report_path}")
    return 0 if report["pass_count"] == args.trials else 1


if __name__ == "__main__":
    raise SystemExit(main())
