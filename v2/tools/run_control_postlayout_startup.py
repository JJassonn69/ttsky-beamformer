#!/usr/bin/env python3
"""Measure exact-final V2 bias startup without unnecessary clock switching."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import run_control_postlayout_smoke as smoke


ROOT = Path(__file__).resolve().parents[2]
BUILD = Path("build/v2/postlayout_startup")
DEFAULT_STOP_US = 50.0
DEFAULT_FINAL_WINDOW_US = 5.0


def deck_text(
    netlist: Path,
    netlist_hash: str,
    gds_hash: str,
    *,
    stop_us: float = DEFAULT_STOP_US,
    step_ns: float = 20.0,
    final_window_us: float = DEFAULT_FINAL_WINDOW_US,
) -> str:
    if stop_us <= 0.0:
        raise ValueError("startup stop time must be positive")
    if not 1.0 <= step_ns <= 100.0:
        raise ValueError("startup step must be between 1 and 100 ns")
    if final_window_us <= 0.0 or final_window_us >= stop_us:
        raise ValueError("final window must be positive and shorter than the run")
    final_start_us = stop_us - final_window_us
    controls = "\n".join(
        f"VSTART_{index} {node} 0 0"
        for index, node in enumerate(smoke.CONTROL_NODES.values())
    )
    inputs = "\n".join(smoke.input_source(index, 0.0) for index in range(4))
    return f"""* V2 exact-final quiet cold-start characterization.
* extracted_netlist_sha256={netlist_hash}
* final_gds_sha256={gds_hash}
.option klu
.option scale=1e-6
.option method=gear reltol=1e-3 vabstol=1e-6 iabstol=1e-12
.temp 27
.include "spice/sky130/sky130_1v8_tt.inc"
.include "third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__tt.corner.spice"
.include "third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__mismatch.corner.spice"
.include "spice/sky130/sky130_passives_tt.inc"
.include "v2/spice/extracted_model_aliases.inc"
.param MC_MM_SWITCH=0
.param cnwvc_tox=41.6503 cnwvc_cdepmult=1 cnwvc_cintmult=1
.param cnwvc_vt1=0.3333 cnwvc_vt2=0.2380952 cnwvc_vtr=0.16
.param cnwvc_dwc=0 cnwvc_dlc=0 cnwvc_dld=0
.include "v2/spice/sky130_fd_pr__cap_var_lvt.model.spice"
.include "{netlist.as_posix()}"

.param VDD=1.8 FIN=5meg VINPK=0
VDD_SOURCE VDPWR 0 pwl(0 0 20n {{VDD}})
VSS_SOURCE {smoke.GROUND} 0 0
{controls}

{inputs}

ROUTP ch0_out_p.n0 outp_pad 500
ROUTN ch0_out_n.n0 outn_pad 500
COUTP outp_pad 0 10p
COUTN outn_pad 0 10p
RLOADP outp_pad 0 1meg
RLOADN outn_pad 0 1meg

.save v(ch0_vcm) v(ch0_vbias) v(VDPWR) i(VDD_SOURCE)
.tran {step_ns:g}n {stop_us:g}u 0 uic
.measure tran vcm_valid_first when v(ch0_vcm)=1.1 rise=1
.measure tran vcm_valid_settled when v(ch0_vcm)=1.1 rise=last
.measure tran vcm_near_nominal_first when v(ch0_vcm)=1.17 rise=1
.measure tran vcm_near_nominal_settled when v(ch0_vcm)=1.17 rise=last
.measure tran vcm_final_avg avg v(ch0_vcm) from={final_start_us:g}u to={stop_us:g}u
.measure tran vcm_final_min min v(ch0_vcm) from={final_start_us:g}u to={stop_us:g}u
.measure tran vcm_final_max max v(ch0_vcm) from={final_start_us:g}u to={stop_us:g}u
.measure tran vbias_final_avg avg v(ch0_vbias) from={final_start_us:g}u to={stop_us:g}u
.measure tran supply_final_avg avg i(VDD_SOURCE) from={final_start_us:g}u to={stop_us:g}u
.end
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("base", "rc"), default="rc")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--gds", type=Path, default=smoke.DEFAULT_GDS)
    parser.add_argument("--base-netlist", type=Path, default=smoke.DEFAULT_BASE)
    parser.add_argument("--rc-netlist", type=Path, default=smoke.DEFAULT_RC)
    parser.add_argument("--stop-us", type=float, default=DEFAULT_STOP_US)
    parser.add_argument("--step-ns", type=float, default=20.0)
    parser.add_argument(
        "--final-window-us", type=float, default=DEFAULT_FINAL_WINDOW_US
    )
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    if not shutil.which(args.ngspice):
        raise SystemExit(f"ngspice not found: {args.ngspice}")
    netlist = args.base_netlist if args.view == "base" else args.rc_netlist
    for path in (args.gds, netlist, smoke.DEFAULT_VARACTOR_MODEL):
        if not path.is_file():
            raise SystemExit(f"missing required artifact: {path}")
    netlist_text = netlist.read_text(encoding="utf-8", errors="replace")
    smoke.validate_extracted_netlist(netlist_text)
    if "sky130_fd_pr__cap_var_lvt" not in smoke.extracted_model_names(netlist_text):
        raise SystemExit("startup netlist is missing the four physical varactors")

    gds_hash = smoke.sha256(args.gds)
    netlist_hash = smoke.sha256(netlist)
    label = (
        f"quiet_{args.stop_us:g}us_step_{args.step_ns:g}ns"
        f"_final_{args.final_window_us:g}us"
    ).replace(".", "p")
    work = BUILD / args.view / label
    work.mkdir(parents=True, exist_ok=True)
    deck = work / "startup.spice"
    log = work / "ngspice.log"
    report_path = work / "report.json"
    deck.write_text(
        deck_text(
            netlist,
            netlist_hash,
            gds_hash,
            stop_us=args.stop_us,
            step_ns=args.step_ns,
            final_window_us=args.final_window_us,
        ),
        encoding="utf-8",
    )
    runtime = smoke.prepare_runtime(work)
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            [args.ngspice, "-b", "-o", str(log.resolve()), str(deck.resolve())],
            cwd=runtime,
            text=True,
            capture_output=True,
            check=False,
            timeout=args.timeout,
        )
        returncode = completed.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        returncode = 124
    elapsed_s = time.monotonic() - started
    log_text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    values = smoke.parse_measures(log_text)
    required = {
        "vcm_valid_first",
        "vcm_valid_settled",
        "vcm_near_nominal_first",
        "vcm_near_nominal_settled",
        "vcm_final_avg",
        "vcm_final_min",
        "vcm_final_max",
        "vbias_final_avg",
        "supply_final_avg",
    }
    errors: list[str] = []
    missing = sorted(required - values.keys())
    if missing:
        errors.append(f"missing measurements: {missing}")
    if timed_out:
        errors.append(f"ngspice exceeded the {args.timeout} second timeout")
    elif returncode:
        errors.append(f"ngspice exited with status {returncode}")
    if not missing:
        if not 1.1 < values["vcm_final_avg"] < 1.3:
            errors.append("final VCM is outside its nominal 1.2 V window")
        if values["vcm_final_max"] - values["vcm_final_min"] > 0.01:
            errors.append("final VCM changes by more than 10 mV")
        if abs(values["supply_final_avg"]) < 1e-6:
            errors.append("quiet-start circuit draws no measurable supply current")
    report = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "view": args.view,
        "mode": "quiet_cold_start",
        "stop_us": args.stop_us,
        "step_ns": args.step_ns,
        "final_window_us": args.final_window_us,
        "gds": str(args.gds),
        "gds_sha256": gds_hash,
        "netlist": str(netlist),
        "netlist_sha256": netlist_hash,
        "spiceinit_sha256": hashlib.sha256(smoke.SPICE_INIT.encode()).hexdigest(),
        "ngspice": args.ngspice,
        "ngspice_returncode": returncode,
        "timed_out": timed_out,
        "elapsed_s": elapsed_s,
        "measurements": values,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"report={report_path}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
