#!/usr/bin/env python3
"""Run a hash-bound nominal smoke test on a flattened V2 extracted netlist."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GDS = Path(
    "build/v2/control_routing/direct/v2_control_quadrature_routed.gds"
)
DEFAULT_BASE = Path(
    "build/v2/control_routing/final_rc/control_final_base.spice"
)
DEFAULT_RC = Path(
    "build/v2/control_routing/final_rc/control_final_rc.spice"
)
BUILD = Path("build/v2/postlayout_smoke")
GROUND = "sky130_fd_sc_hd__fill_1_2190.VNB"
CONTROL_NODES = {
    "beam_select[0]": "R025",
    "beam_select[1]": "R026",
    "cfg_clk": "R030",
    "cfg_data": "R032",
    "cfg_latch": "R033",
    "channel_enable[0]": "R038",
    "channel_enable[1]": "R039",
    "channel_enable[2]": "R040",
    "channel_enable[3]": "R041",
    "clk": "R046",
    "ena": "R067",
    "manual_mode": "R068",
    "rst_n": "R157",
}
PHASE_NODES = ("phase_0", "phase_90", "phase_180", "phase_270")
RC_PHASE_ROOT_NODES = tuple(
    f"v2_control_openroad_routes_0.R{route}"
    for route in (151, 152, 153, 154)
)
RC_PHASE_LEAF_NODES = (
    tuple(f"CH{channel}_PMUX_A.A0" for channel in range(4)),
    tuple(f"CH{channel}_PMUX_A.A1" for channel in range(4)),
    tuple(f"CH{channel}_PMUX_B.A0" for channel in range(4)),
    tuple(f"CH{channel}_PMUX_B.A1" for channel in range(4)),
)
MEASURE_RE = re.compile(
    r"^\s*([a-z][a-z0-9_]*)\s*=\s*([-+0-9.eE]+)", re.MULTILINE
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extracted_model_names(text: str) -> set[str]:
    return set(re.findall(r"\b(sky130_fd_pr__[^\s]+)", text))


def validate_extracted_netlist(text: str) -> None:
    expected_models = {
        "sky130_fd_pr__cap_mim_m3_1",
        "sky130_fd_pr__nfet_01v8",
        "sky130_fd_pr__pfet_01v8_hvt",
        "sky130_fd_pr__res_high_po_1p41",
        "sky130_fd_pr__res_xhigh_po_1p41",
        "sky130_fd_pr__special_nfet_01v8",
    }
    found = extracted_model_names(text)
    if found != expected_models:
        raise ValueError(
            f"extracted model set changed: found={sorted(found)}, "
            f"expected={sorted(expected_models)}"
        )
    required_nodes = {
        "VDPWR", GROUND, "ch0_input", "ch1_input", "ch2_input",
        "ch3_input", "ch0_out_p", "ch0_out_n", *CONTROL_NODES.values(),
        *PHASE_NODES,
    }
    missing = sorted(node for node in required_nodes if node not in text)
    if missing:
        raise ValueError(f"extracted netlist lacks required nodes: {missing}")
    if re.search(r"^\.subckt\b", text, re.MULTILINE):
        raise ValueError("expected a flattened top-level extracted netlist")


def input_source(channel: int, phase_deg: float) -> str:
    return "\n".join(
        (
            f"VIN{channel} source{channel} 0 "
            f"sin(0 {{VINPK}} {{FIN}} 0 0 {phase_deg:g})",
            f"CIN{channel} source{channel} input{channel}_pre 100p",
            f"RIN{channel} input{channel}_pre ch{channel}_input 500",
            f"CPAD{channel} ch{channel}_input 0 5p",
        )
    )


def deck_text(
    netlist: Path,
    netlist_hash: str,
    gds_hash: str,
    channel_mask: int = 0xF,
    beam: int = 0,
    input_phases_deg: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    distributed_rc: bool = False,
) -> str:
    if not 0 <= channel_mask <= 0xF:
        raise ValueError("channel mask must be a four-bit value")
    if not 0 <= beam <= 3:
        raise ValueError("beam must be between zero and three")
    controls = [
        f"VBEAM0 {CONTROL_NODES['beam_select[0]']} 0 "
        + ("{VDD}" if beam & 1 else "0"),
        f"VBEAM1 {CONTROL_NODES['beam_select[1]']} 0 "
        + ("{VDD}" if beam & 2 else "0"),
        f"VCFGCLK {CONTROL_NODES['cfg_clk']} 0 0",
        f"VCFGDATA {CONTROL_NODES['cfg_data']} 0 0",
        f"VCFGLATCH {CONTROL_NODES['cfg_latch']} 0 0",
        f"VENA {CONTROL_NODES['ena']} 0 {{VDD}}",
        f"VMANUAL {CONTROL_NODES['manual_mode']} 0 0",
        f"VRST {CONTROL_NODES['rst_n']} 0 "
        "pulse(0 {VDD} 250n 200p 200p 100u 200u)",
        f"VCLK {CONTROL_NODES['clk']} 0 "
        "pulse(0 {VDD} 0 200p 200p 31.05n 62.5n)",
    ]
    controls.extend(
        f"VCH{channel} {CONTROL_NODES[f'channel_enable[{channel}]']} 0 "
        + ("{VDD}" if channel_mask & (1 << channel) else "0")
        for channel in range(4)
    )
    phase_measures = "\n".join(
        f".measure tran phase{index}_min min v({node}) from=2u to=4u\n"
        f".measure tran phase{index}_max max v({node}) from=2u to=4u\n"
        f".measure tran phase{index}_period "
        f"trig v({node}) val=0.9 rise=1 td=2u "
        f"targ v({node}) val=0.9 rise=2 td=2u"
        for index, node in enumerate(PHASE_NODES)
    )
    rc_leaf_saves = ""
    rc_leaf_measures = ""
    if distributed_rc:
        rc_leaf_saves = "\n".join(
            f"+ v({node})" for leaves in RC_PHASE_LEAF_NODES for node in leaves
        )
        rc_leaf_measures = "\n".join(
            f".measure tran phase{phase}_ch{channel}_min min v({leaf}) "
            f"from=2u to=4u\n"
            f".measure tran phase{phase}_ch{channel}_max max v({leaf}) "
            f"from=2u to=4u\n"
            f".measure tran phase{phase}_ch{channel}_delay "
            f"trig v({RC_PHASE_ROOT_NODES[phase]}) val=0.9 rise=1 td=2u "
            f"targ v({leaf}) val=0.9 rise=1 td=2u"
            for phase, leaves in enumerate(RC_PHASE_LEAF_NODES)
            for channel, leaf in enumerate(leaves)
        )
    return f"""* V2 full-chip post-layout nominal smoke test.
* extracted_netlist_sha256={netlist_hash}
* final_gds_sha256={gds_hash}
.option scale=1e-6
.option method=gear reltol=1e-3 vabstol=1e-6 iabstol=1e-12
.temp 27
.include "spice/sky130/sky130_1v8_tt.inc"
.include "third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__tt.corner.spice"
.include "third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__mismatch.corner.spice"
.include "spice/sky130/sky130_passives_tt.inc"
.include "v2/spice/extracted_model_aliases.inc"
.include "{netlist.as_posix()}"

.param VDD=1.8 FIN=5meg VINPK=5m
VDD_SOURCE VDPWR 0 {{VDD}}
VSS_SOURCE {GROUND} 0 0
{chr(10).join(controls)}

{chr(10).join(input_source(index, phase) for index, phase in enumerate(input_phases_deg))}

ROUTP ch0_out_p outp_pad 500
ROUTN ch0_out_n outn_pad 500
COUTP outp_pad 0 10p
COUTN outn_pad 0 10p
RLOADP outp_pad 0 1meg
RLOADN outn_pad 0 1meg
EDIFF differential 0 outp_pad outn_pad 1
BCM common_mode 0 v=(v(outp_pad)+v(outn_pad))/2
RF1 differential filt1 1k
CF1 filt1 0 79.577p
RF2 filt1 filtered 1k
CF2 filtered 0 79.577p

.save v(filtered) v(outp_pad) v(outn_pad) v(common_mode) i(VDD_SOURCE)
+ v(phase_0) v(phase_90) v(phase_180) v(phase_270)
{rc_leaf_saves}
.tran 2n 4u 2u
.measure tran output_rms rms v(filtered) from=2u to=4u
.measure tran output_avg avg v(filtered) from=2u to=4u
.measure tran common_mode_avg avg v(common_mode) from=2u to=4u
.measure tran supply_avg avg i(VDD_SOURCE) from=2u to=4u
{phase_measures}
{rc_leaf_measures}
.end
"""


def parse_measures(text: str) -> dict[str, float]:
    return {name: float(value) for name, value in MEASURE_RE.findall(text)}


def analyze(
    values: dict[str, float], distributed_rc: bool = False
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    required = {"output_rms", "output_avg", "common_mode_avg", "supply_avg"}
    required.update(
        f"phase{index}_{field}"
        for index in range(4) for field in ("min", "max", "period")
    )
    if distributed_rc:
        required.update(
            f"phase{phase}_ch{channel}_{field}"
            for phase in range(4) for channel in range(4)
            for field in ("min", "max", "delay")
        )
    missing = sorted(required - values.keys())
    if missing:
        errors.append(f"missing measurements: {missing}")
    phases: list[dict[str, float]] = []
    if not missing:
        for index in range(4):
            low = values[f"phase{index}_min"]
            high = values[f"phase{index}_max"]
            period = values[f"phase{index}_period"]
            phases.append({"index": index, "min_v": low, "max_v": high, "period_s": period})
            if low > 0.2 or high < 1.6:
                errors.append(
                    f"phase {index} does not reach valid rails: min={low}, max={high}"
                )
            if abs(period - 250e-9) > 2.5e-9:
                errors.append(f"phase {index} period {period} is not nominal 250 ns")
        if not 0.5 < values["common_mode_avg"] < 1.82:
            errors.append("differential output common mode is outside a plausible range")
        if abs(values["supply_avg"]) < 1e-6:
            errors.append("extracted chip draws no measurable supply current")
        ac_rms = max(values["output_rms"] ** 2 - values["output_avg"] ** 2, 0.0) ** 0.5
        if ac_rms < 1e-6:
            errors.append("beamformed 1 MHz output is below the smoke-test floor")
    else:
        ac_rms = 0.0
    phase_leaf_skew: list[dict[str, Any]] = []
    if distributed_rc and not missing:
        for phase in range(4):
            delays = [
                values[f"phase{phase}_ch{channel}_delay"]
                for channel in range(4)
            ]
            skew = max(delays) - min(delays)
            phase_leaf_skew.append(
                {"phase_index": phase, "delays_s": delays, "skew_s": skew}
            )
            if skew > 100e-12:
                errors.append(
                    f"phase {phase} extracted leaf skew {skew} exceeds 100 ps"
                )
            for channel in range(4):
                low = values[f"phase{phase}_ch{channel}_min"]
                high = values[f"phase{phase}_ch{channel}_max"]
                if low > 0.2 or high < 1.6:
                    errors.append(
                        f"phase {phase} channel {channel} leaf does not reach "
                        f"valid rails: min={low}, max={high}"
                    )
    return {
        "output_ac_rms_v": ac_rms,
        "phases": phases,
        "phase_leaf_skew": phase_leaf_skew,
    }, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("base", "rc"), default="base")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--gds", type=Path, default=DEFAULT_GDS)
    parser.add_argument("--base-netlist", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--rc-netlist", type=Path, default=DEFAULT_RC)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    if not shutil.which(args.ngspice):
        raise SystemExit(f"ngspice not found: {args.ngspice}")
    netlist = args.base_netlist if args.view == "base" else args.rc_netlist
    for path in (args.gds, netlist):
        if not path.is_file():
            raise SystemExit(f"missing required artifact: {path}")
    validate_extracted_netlist(netlist.read_text(encoding="utf-8", errors="replace"))
    gds_hash = sha256(args.gds)
    netlist_hash = sha256(netlist)
    work = BUILD / args.view
    work.mkdir(parents=True, exist_ok=True)
    deck = work / "smoke.spice"
    log = work / "ngspice.log"
    report_path = work / "report.json"
    deck.write_text(
        deck_text(
            netlist, netlist_hash, gds_hash,
            distributed_rc=args.view == "rc",
        ),
        encoding="utf-8",
    )
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            [args.ngspice, "-b", "-o", str(log), str(deck)],
            cwd=ROOT, text=True, capture_output=True, check=False,
            timeout=args.timeout,
        )
        returncode = completed.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        returncode = 124
    elapsed_s = time.monotonic() - started
    log_text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    values = parse_measures(log_text)
    analysis, errors = analyze(values, distributed_rc=args.view == "rc")
    if timed_out:
        errors.append(f"ngspice exceeded the {args.timeout} second timeout")
    elif returncode:
        errors.append(f"ngspice exited with status {returncode}")
    report: dict[str, Any] = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "view": args.view,
        "gds": str(args.gds),
        "gds_sha256": gds_hash,
        "netlist": str(netlist),
        "netlist_sha256": netlist_hash,
        "ngspice": args.ngspice,
        "ngspice_returncode": returncode,
        "timed_out": timed_out,
        "elapsed_s": elapsed_s,
        "measurements": values,
        "analysis": analysis,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"report={report_path}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
