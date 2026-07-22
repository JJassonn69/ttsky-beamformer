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
SPICE_INIT = """* Isolated large-SKY130 ngspice configuration.
set ngbehavior=hsa
set skywaterpdk
set ng_nomodcheck
set num_threads=8
option noinit
option klu
"""
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
PHASE_NODES = (
    "ch0_phase_0_leaf",
    "ch0_phase_90_leaf",
    "ch0_phase_180_leaf",
    "ch0_phase_270_leaf",
)
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


def netlist_has_node(text: str, node: str) -> bool:
    """Match a base node or its Magic distributed-RC segment as a token."""
    pattern = rf"(?<!\S){re.escape(node)}(?:\.(?:t|n)\d+)?(?!\S)"
    return re.search(pattern, text) is not None


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
    missing = sorted(node for node in required_nodes if not netlist_has_node(text, node))
    if missing:
        raise ValueError(f"extracted netlist lacks required nodes: {missing}")
    if re.search(r"^\.subckt\b", text, re.MULTILINE):
        raise ValueError("expected a flattened top-level extracted netlist")


def prepare_runtime(work: Path) -> Path:
    """Create a local ngspice startup sandbox without changing user config."""
    runtime = work / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ("build", "spice", "third_party", "v2"):
        link = runtime / name
        target = (ROOT / name).resolve()
        if link.is_symlink():
            if link.resolve() != target:
                raise RuntimeError(f"runtime link points at the wrong target: {link}")
        elif link.exists():
            raise RuntimeError(f"runtime path blocks required link: {link}")
        else:
            link.symlink_to(target, target_is_directory=True)
    (runtime / ".spiceinit").write_text(SPICE_INIT, encoding="utf-8")
    return runtime


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


def codebook_input_phases(incident_beam: int) -> tuple[float, float, float, float]:
    """Return the four incident phases for one ideal transmit-array beam."""
    if not 0 <= incident_beam <= 3:
        raise ValueError("incident beam must be between zero and three")
    return tuple(
        float(90 * ((channel * incident_beam) % 4))
        for channel in range(4)
    )  # type: ignore[return-value]


def deck_text(
    netlist: Path,
    netlist_hash: str,
    gds_hash: str,
    channel_mask: int = 0xF,
    beam: int = 0,
    input_phases_deg: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    input_peak_v: float = 0.005,
    distributed_rc: bool = False,
    operating_point_startup: bool = False,
    analysis_start_us: float = 2.0,
    analysis_stop_us: float = 4.0,
) -> str:
    if not 0 <= channel_mask <= 0xF:
        raise ValueError("channel mask must be a four-bit value")
    if not 0 <= beam <= 3:
        raise ValueError("beam must be between zero and three")
    if input_peak_v < 0.0:
        raise ValueError("input peak voltage cannot be negative")
    if analysis_start_us <= 0.0 or analysis_stop_us <= analysis_start_us:
        raise ValueError("analysis window must have positive, increasing times")
    window_us = analysis_stop_us - analysis_start_us
    if abs(window_us - round(window_us)) > 1e-9:
        raise ValueError("analysis window must span an integer number of 1 MHz cycles")
    start = f"{analysis_start_us:g}u"
    stop = f"{analysis_stop_us:g}u"
    output_p_node = "ch0_out_p.n0" if distributed_rc else "ch0_out_p"
    output_n_node = "ch0_out_n.n0" if distributed_rc else "ch0_out_n"
    controls = [
        f"VBEAM0 {CONTROL_NODES['beam_select[0]']} 0 "
        + ("{VDD}" if beam & 1 else "0"),
        f"VBEAM1 {CONTROL_NODES['beam_select[1]']} 0 "
        + ("{VDD}" if beam & 2 else "0"),
        f"VCFGCLK {CONTROL_NODES['cfg_clk']} 0 0",
        f"VCFGDATA {CONTROL_NODES['cfg_data']} 0 0",
        f"VCFGLATCH {CONTROL_NODES['cfg_latch']} 0 0",
        f"BENA {CONTROL_NODES['ena']} 0 v=v(VDPWR)",
        f"VMANUAL {CONTROL_NODES['manual_mode']} 0 0",
        f"VRST {CONTROL_NODES['rst_n']} 0 "
        "pulse(0 {VDD} 250n 200p 200p 100u 200u)",
        f"VCLK {CONTROL_NODES['clk']} 0 "
        "pulse(0 {VDD} 100n 200p 200p 31.05n 62.5n)",
    ]
    controls.extend(
        (
            f"BCH{channel} {CONTROL_NODES[f'channel_enable[{channel}]']} 0 "
            "v=v(VDPWR)"
            if channel_mask & (1 << channel)
            else f"VCH{channel} "
            f"{CONTROL_NODES[f'channel_enable[{channel}]']} 0 0"
        )
        for channel in range(4)
    )
    phase_nodes = RC_PHASE_ROOT_NODES if distributed_rc else PHASE_NODES
    vdd_source = (
        "VDD_SOURCE VDPWR 0 {VDD}"
        if operating_point_startup
        else "VDD_SOURCE VDPWR 0 pulse(0 {VDD} 0 20n 20n 100u 200u)"
    )
    transient = f".tran 2n {stop} {start}" + (
        "" if operating_point_startup else " uic"
    )
    phase_measures = "\n".join(
        f".measure tran phase{index}_min min v({node}) from={start} to={stop}\n"
        f".measure tran phase{index}_max max v({node}) from={start} to={stop}\n"
        f".measure tran phase{index}_period "
        f"trig v({node}) val=0.9 rise=1 td={start} "
        f"targ v({node}) val=0.9 rise=2 td={start}"
        for index, node in enumerate(phase_nodes)
    )
    rc_leaf_saves = ""
    rc_leaf_measures = ""
    if distributed_rc:
        rc_leaf_saves = "\n".join(
            f"+ v({node})" for leaves in RC_PHASE_LEAF_NODES for node in leaves
        )
        rc_leaf_measures = "\n".join(
            f".measure tran phase{phase}_ch{channel}_min min v({leaf}) "
            f"from={start} to={stop}\n"
            f".measure tran phase{phase}_ch{channel}_max max v({leaf}) "
            f"from={start} to={stop}\n"
            f".measure tran phase{phase}_ch{channel}_delay "
            f"trig v({RC_PHASE_ROOT_NODES[phase]}) val=0.9 rise=1 td={start} "
            f"targ v({leaf}) val=0.9 rise=1 td={start}"
            for phase, leaves in enumerate(RC_PHASE_LEAF_NODES)
            for channel, leaf in enumerate(leaves)
        )
    return f"""* V2 full-chip post-layout nominal smoke test.
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
.include "{netlist.as_posix()}"

.param VDD=1.8 FIN=5meg FOUT=1meg VINPK={input_peak_v:.12g}
{vdd_source}
VSS_SOURCE {GROUND} 0 0
{chr(10).join(controls)}

{chr(10).join(input_source(index, phase) for index, phase in enumerate(input_phases_deg))}

ROUTP {output_p_node} outp_pad 500
ROUTN {output_n_node} outn_pad 500
COUTP outp_pad 0 10p
COUTN outn_pad 0 10p
RLOADP outp_pad 0 1meg
RLOADN outn_pad 0 1meg
EDIFF differential 0 outp_pad outn_pad 1
BCM common_mode 0 v=(v(outp_pad)+v(outn_pad))/2
BTONEI tone_i 0 v=v(differential)*cos(2*pi*FOUT*time)
BTONEQ tone_q 0 v=v(differential)*sin(2*pi*FOUT*time)
RF1 differential filt1 1k
CF1 filt1 0 79.577p
RF2 filt1 filtered 1k
CF2 filtered 0 79.577p

.save v(filtered) v(outp_pad) v(outn_pad) v(common_mode) v(ch0_vcm)
+ v(tone_i) v(tone_q) i(VDD_SOURCE)
+ {" ".join(f"v({node})" for node in phase_nodes)}
{rc_leaf_saves}
{transient}
.measure tran output_rms rms v(filtered) from={start} to={stop}
.measure tran output_avg avg v(filtered) from={start} to={stop}
.measure tran common_mode_avg avg v(common_mode) from={start} to={stop}
.measure tran vcm_avg avg v(ch0_vcm) from={start} to={stop}
.measure tran supply_avg avg i(VDD_SOURCE) from={start} to={stop}
.measure tran tone_i_avg avg v(tone_i) from={start} to={stop}
.measure tran tone_q_avg avg v(tone_q) from={start} to={stop}
.measure tran output_tone_rms param='sqrt(2*(tone_i_avg*tone_i_avg+tone_q_avg*tone_q_avg))'
{phase_measures}
{rc_leaf_measures}
.end
"""


def parse_measures(text: str) -> dict[str, float]:
    return {name: float(value) for name, value in MEASURE_RE.findall(text)}


def analyze(
    values: dict[str, float], distributed_rc: bool = False,
    require_output: bool = True,
    settled_startup: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    required = {
        "output_rms", "output_avg", "output_tone_rms", "tone_i_avg",
        "tone_q_avg", "common_mode_avg", "vcm_avg", "supply_avg"
    }
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
        if settled_startup:
            if not 0.8 < values["common_mode_avg"] < 1.2:
                errors.append("settled differential output common mode is out of range")
            if not 1.1 < values["vcm_avg"] < 1.3:
                errors.append("settled VCM is outside its nominal 1.2 V window")
        else:
            if not 0.5 < values["common_mode_avg"] < 1.82:
                errors.append(
                    "differential output common mode is outside a plausible range"
                )
            # UIC intentionally skips the DC solution and is retained only as
            # a short connectivity/clock smoke test.  Here reject only a hard
            # VCM rail short instead of making a false steady-state claim.
            if not 0.1 < values["vcm_avg"] < 1.7:
                errors.append("VCM appears stuck at a supply rail during startup")
        if abs(values["supply_avg"]) < 1e-6:
            errors.append("extracted chip draws no measurable supply current")
        ac_rms = max(values["output_rms"] ** 2 - values["output_avg"] ** 2, 0.0) ** 0.5
        if require_output and values["output_tone_rms"] < 1e-6:
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
        "output_tone_rms_v": values.get("output_tone_rms", 0.0),
        "output_tone_i_v": values.get("tone_i_avg", 0.0),
        "output_tone_q_v": values.get("tone_q_avg", 0.0),
        "output_common_mode_v": values.get("common_mode_avg", 0.0),
        "vcm_v": values.get("vcm_avg", 0.0),
        "supply_current_a": abs(values.get("supply_avg", 0.0)),
        "estimated_power_w": 1.8 * abs(values.get("supply_avg", 0.0)),
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
    parser.add_argument("--beam", type=int, choices=range(4), default=0)
    parser.add_argument("--incident-beam", type=int, choices=range(4))
    parser.add_argument(
        "--channel-mask",
        type=lambda value: int(value, 0),
        default=0xF,
        help="four-bit enabled-channel mask (for example 0xF or 0x1)",
    )
    parser.add_argument("--input-peak-v", type=float, default=0.005)
    parser.add_argument(
        "--startup",
        choices=("uic", "op"),
        default="uic",
        help="fast ramped UIC startup or exact DC operating-point startup",
    )
    parser.add_argument("--analysis-start-us", type=float, default=2.0)
    parser.add_argument("--analysis-stop-us", type=float, default=4.0)
    args = parser.parse_args()
    if not shutil.which(args.ngspice):
        raise SystemExit(f"ngspice not found: {args.ngspice}")
    netlist = args.base_netlist if args.view == "base" else args.rc_netlist
    if not 0 <= args.channel_mask <= 0xF:
        raise SystemExit("--channel-mask must be a four-bit value")
    if args.input_peak_v < 0.0:
        raise SystemExit("--input-peak-v cannot be negative")
    if args.analysis_start_us <= 0.0 or args.analysis_stop_us <= args.analysis_start_us:
        raise SystemExit("analysis window must have positive, increasing times")
    window_us = args.analysis_stop_us - args.analysis_start_us
    if abs(window_us - round(window_us)) > 1e-9:
        raise SystemExit("analysis window must span an integer number of 1 MHz cycles")
    for path in (args.gds, netlist):
        if not path.is_file():
            raise SystemExit(f"missing required artifact: {path}")
    validate_extracted_netlist(netlist.read_text(encoding="utf-8", errors="replace"))
    gds_hash = sha256(args.gds)
    netlist_hash = sha256(netlist)
    input_phases = (
        codebook_input_phases(args.incident_beam)
        if args.incident_beam is not None
        else (0.0, 0.0, 0.0, 0.0)
    )
    default_case = (
        args.beam == 0
        and args.incident_beam is None
        and args.channel_mask == 0xF
        and args.input_peak_v == 0.005
        and args.startup == "uic"
        and args.analysis_start_us == 2.0
        and args.analysis_stop_us == 4.0
    )
    if default_case:
        work = BUILD / args.view
    else:
        incident_label = (
            str(args.incident_beam)
            if args.incident_beam is not None
            else "custom"
        )
        case_label = f"selected_{args.beam}_incident_{incident_label}"
        if args.channel_mask != 0xF:
            case_label += f"_mask_{args.channel_mask:x}"
        if args.input_peak_v != 0.005:
            case_label += f"_vin_{round(args.input_peak_v * 1e9):d}nv"
        if args.startup == "op":
            case_label += "_startup_op"
        if args.analysis_start_us != 2.0 or args.analysis_stop_us != 4.0:
            case_label += (
                f"_window_{args.analysis_start_us:g}us_"
                f"{args.analysis_stop_us:g}us"
            ).replace(".", "p")
        work = BUILD / args.view / "codebook" / case_label
    work.mkdir(parents=True, exist_ok=True)
    deck = work / "smoke.spice"
    log = work / "ngspice.log"
    report_path = work / "report.json"
    deck.write_text(
        deck_text(
            netlist, netlist_hash, gds_hash,
            channel_mask=args.channel_mask,
            beam=args.beam,
            input_phases_deg=input_phases,
            input_peak_v=args.input_peak_v,
            distributed_rc=args.view == "rc",
            operating_point_startup=args.startup == "op",
            analysis_start_us=args.analysis_start_us,
            analysis_stop_us=args.analysis_stop_us,
        ),
        encoding="utf-8",
    )
    runtime = prepare_runtime(work)
    spiceinit_hash = hashlib.sha256(SPICE_INIT.encode()).hexdigest()
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            [
                args.ngspice, "-b", "-o", str(log.resolve()),
                str(deck.resolve()),
            ],
            cwd=runtime, text=True, capture_output=True, check=False,
            timeout=args.timeout,
        )
        returncode = completed.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        returncode = 124
    elapsed_s = time.monotonic() - started
    log_text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    values = parse_measures(log_text)
    analysis, errors = analyze(
        values,
        distributed_rc=args.view == "rc",
        settled_startup=args.startup == "op",
        require_output=(
            args.input_peak_v > 0.0
            and (args.incident_beam is None or args.beam == args.incident_beam)
        ),
    )
    if timed_out:
        errors.append(f"ngspice exceeded the {args.timeout} second timeout")
    elif returncode:
        errors.append(f"ngspice exited with status {returncode}")
    report: dict[str, Any] = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "view": args.view,
        "selected_beam": args.beam,
        "incident_beam": args.incident_beam,
        "channel_mask": args.channel_mask,
        "input_phases_deg": input_phases,
        "input_peak_v": args.input_peak_v,
        "startup": args.startup,
        "analysis_window_us": [args.analysis_start_us, args.analysis_stop_us],
        "gds": str(args.gds),
        "gds_sha256": gds_hash,
        "netlist": str(netlist),
        "netlist_sha256": netlist_hash,
        "ngspice": args.ngspice,
        "spiceinit_sha256": spiceinit_hash,
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
