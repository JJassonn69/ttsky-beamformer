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
DEFAULT_VARACTOR_MODEL = Path(
    "v2/spice/sky130_fd_pr__cap_var_lvt.model.spice"
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
CONTROL_OBSERVATION_NODES = {
    "apply_config": "R024",
    "serial_phase_to_trim": "R158",
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
TRIM_ROUTE_NODES = (
    "R008", "R015", "R016", "R017",
    "R018", "R019", "R020", "R021",
    "R022", "R023", "R009", "R010",
    "R011", "R012", "R013", "R014",
)
PASSIVE_CORNERS = {
    "tt": "res_typical__cap_typical",
    "hh": "res_high__cap_high",
    "hl": "res_high__cap_low",
    "lh": "res_low__cap_high",
    "ll": "res_low__cap_low",
}
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
    base_models = {
        "sky130_fd_pr__cap_mim_m3_1",
        "sky130_fd_pr__nfet_01v8",
        "sky130_fd_pr__pfet_01v8_hvt",
        "sky130_fd_pr__res_high_po_1p41",
        "sky130_fd_pr__res_xhigh_po_1p41",
        "sky130_fd_pr__special_nfet_01v8",
    }
    expected_model_sets = (
        base_models,
        base_models | {"sky130_fd_pr__cap_var_lvt"},
    )
    found = extracted_model_names(text)
    if found not in expected_model_sets:
        raise ValueError(
            f"extracted model set changed: found={sorted(found)}, "
            f"expected one of={[sorted(item) for item in expected_model_sets]}"
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
                # Generated case directories may be copied from another
                # validation host or checkout path. Replacing a symlink is
                # safe; a real file or directory remains a hard error below.
                link.unlink()
                link.symlink_to(target, target_is_directory=True)
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


def parse_trim_codes(value: str) -> tuple[int, int, int, int]:
    try:
        codes = tuple(int(item, 0) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("trim codes must be four integers") from error
    if len(codes) != 4 or any(code < 0 or code > 15 for code in codes):
        raise argparse.ArgumentTypeError(
            "trim codes must be four comma-separated values from 0 through 15"
        )
    return codes  # type: ignore[return-value]


def serial_trim_sources(trim_codes: tuple[int, int, int, int]) -> list[str]:
    """Drive one faithful 24-bit LSB-first packet when trim differs from reset."""
    if trim_codes == (8, 8, 8, 8):
        return [
            f"VCFGCLK {CONTROL_NODES['cfg_clk']} 0 0",
            f"VCFGDATA {CONTROL_NODES['cfg_data']} 0 0",
            f"VCFGLATCH {CONTROL_NODES['cfg_latch']} 0 0",
        ]
    trim_word = sum(code << (4 * channel) for channel, code in enumerate(trim_codes))
    bits = [(trim_word >> index) & 1 for index in range(16)] + [0] * 8
    points = [f"0 {'{VDD}' if bits[0] else '0'}"]
    for index in range(1, len(bits)):
        transition_ns = 360 + 20 * (index - 1)
        old_level = "{VDD}" if bits[index - 1] else "0"
        new_level = "{VDD}" if bits[index] else "0"
        points.append(f"{transition_ns}n {old_level}")
        points.append(f"{transition_ns + 2}n {new_level}")
    # Generate exactly 24 shift edges and one latch edge.  A free-running
    # pulse source would resume shifting after cfg_latch fell and overwrite
    # the pending word with the final cfg_data level before the main-clock
    # safe boundary committed it.
    clock_points = ["0 0"]
    for edge in range(25):
        rise_ns = 350 + 20 * edge
        clock_points.extend((
            f"{rise_ns - 0.2:g}n 0",
            f"{rise_ns:g}n {{VDD}}",
            f"{rise_ns + 9.8:g}n {{VDD}}",
            f"{rise_ns + 10:g}n 0",
        ))
    return [
        f"VCFGCLK {CONTROL_NODES['cfg_clk']} 0 pwl({' '.join(clock_points)})",
        f"VCFGDATA {CONTROL_NODES['cfg_data']} 0 pwl({' '.join(points)})",
        f"VCFGLATCH {CONTROL_NODES['cfg_latch']} 0 "
        "pwl(0 0 824.8n 0 825n {VDD} 841.8n {VDD} 842n 0)",
    ]


def passive_model_includes(passive_corner: str) -> str:
    try:
        stem = PASSIVE_CORNERS[passive_corner]
    except KeyError as error:
        raise ValueError("unsupported passive corner") from error
    return "\n".join(
        (
            f'.include "third_party/sky130_fd_pr/models/r+c/{stem}.spice"',
            f'.include "third_party/sky130_fd_pr/models/r+c/{stem}__lin.spice"',
            '.include "third_party/sky130_fd_pr/models/sky130_fd_pr__model__linear.model.spice"',
            '.include "third_party/sky130_fd_pr/cells/cap_mim_m3/sky130_fd_pr__cap_mim_m3_1.model.spice"',
        )
    )


def clock_source(
    node: str,
    duty_percent: float = 50.0,
    jitter_ps: float = 0.0,
    stop_us: float = 4.0,
) -> str:
    """Create the rated 16 MHz master clock with optional deterministic jitter."""
    if not 35.0 <= duty_percent <= 65.0:
        raise ValueError("clock duty cycle must be between 35 and 65 percent")
    if not 0.0 <= jitter_ps <= 2000.0:
        raise ValueError("clock jitter must be between zero and 2000 ps")
    period_ns = 62.5
    rise_fall_ns = 0.2
    if jitter_ps == 0.0:
        pulse_width_ns = period_ns * duty_percent / 100.0 - rise_fall_ns
        return (
            f"VCLK {node} 0 pulse(0 {{VDD}} 100n 200p 200p "
            f"{pulse_width_ns:g}n 62.5n)"
        )

    # Use a deterministic, zero-mean five-cycle edge-offset pattern so the
    # exact stress is reproducible and reportable. Rising and falling edges in
    # one cycle move together, preserving the requested duty cycle while the
    # period varies from cycle to cycle.
    pattern = (-1.0, 1.0, 0.5, -0.5, 0.0)
    jitter_ns = jitter_ps / 1000.0
    points = ["0 0"]
    cycle = 0
    while True:
        rise_ns = 100.0 + cycle * period_ns + pattern[cycle % len(pattern)] * jitter_ns
        if rise_ns > stop_us * 1000.0 + period_ns:
            break
        fall_ns = rise_ns + period_ns * duty_percent / 100.0
        points.extend((
            f"{rise_ns:g}n 0",
            f"{rise_ns + rise_fall_ns:g}n {{VDD}}",
            f"{fall_ns:g}n {{VDD}}",
            f"{fall_ns + rise_fall_ns:g}n 0",
        ))
        cycle += 1
    return f"VCLK {node} 0 pwl({' '.join(points)})"


def deck_text(
    netlist: Path,
    netlist_hash: str,
    gds_hash: str,
    channel_mask: int = 0xF,
    beam: int = 0,
    input_phases_deg: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    input_peak_v: float = 0.005,
    input_frequency_mhz: float = 5.0,
    distributed_rc: bool = False,
    operating_point_startup: bool = False,
    analysis_start_us: float = 2.0,
    analysis_stop_us: float = 4.0,
    transient_step_ns: float = 2.0,
    enable_delay_us: float = 0.0,
    output_shunt_ohms: float | None = None,
    vbias_bypass_pf: float | None = None,
    output_damping_pf: float | None = None,
    vcm_bypass_pf: float | None = None,
    vcm_varactor_model: Path | None = None,
    extracted_varactor_model: Path | None = None,
    vcm_varactor_w_um: float = 25.0,
    vcm_varactor_l_um: float = 25.0,
    vcm_varactor_m: int = 1,
    process_corner: str = "tt",
    supply_voltage_v: float = 1.8,
    temperature_c: float = 27.0,
    trim_codes: tuple[int, int, int, int] = (8, 8, 8, 8),
    passive_corner: str = "tt",
    clock_duty_percent: float = 50.0,
    clock_jitter_ps: float = 0.0,
) -> str:
    if not 0 <= channel_mask <= 0xF:
        raise ValueError("channel mask must be a four-bit value")
    if not 0 <= beam <= 3:
        raise ValueError("beam must be between zero and three")
    if input_peak_v < 0.0:
        raise ValueError("input peak voltage cannot be negative")
    if input_frequency_mhz <= 4.0 or input_frequency_mhz > 20.0:
        raise ValueError("input frequency must be above the 4 MHz LO and at most 20 MHz")
    if process_corner not in {"tt", "ff", "ss", "fs", "sf"}:
        raise ValueError("unsupported process corner")
    if not 1.4 <= supply_voltage_v <= 2.1:
        raise ValueError("supply voltage must be between 1.4 and 2.1 V")
    if not -55.0 <= temperature_c <= 125.0:
        raise ValueError("temperature must be between -55 and 125 C")
    if not 35.0 <= clock_duty_percent <= 65.0:
        raise ValueError("clock duty cycle must be between 35 and 65 percent")
    if not 0.0 <= clock_jitter_ps <= 2000.0:
        raise ValueError("clock jitter must be between zero and 2000 ps")
    passive_includes = passive_model_includes(passive_corner)
    if len(trim_codes) != 4 or any(code < 0 or code > 15 for code in trim_codes):
        raise ValueError("trim codes must contain four values from zero through 15")
    if analysis_start_us <= 0.0 or analysis_stop_us <= analysis_start_us:
        raise ValueError("analysis window must have positive, increasing times")
    output_frequency_mhz = input_frequency_mhz - 4.0
    window_us = analysis_stop_us - analysis_start_us
    output_cycles = window_us * output_frequency_mhz
    if abs(output_cycles - round(output_cycles)) > 1e-9:
        raise ValueError("analysis window must span an integer number of output cycles")
    if not 0.5 <= transient_step_ns <= 10.0:
        raise ValueError("transient step must be between 0.5 and 10 ns")
    if enable_delay_us < 0.0 or enable_delay_us >= analysis_stop_us:
        raise ValueError("enable delay must be nonnegative and before analysis stop")
    if output_shunt_ohms is not None and output_shunt_ohms <= 0.0:
        raise ValueError("output shunt resistance must be positive")
    if vbias_bypass_pf is not None and vbias_bypass_pf <= 0.0:
        raise ValueError("VBIAS bypass capacitance must be positive")
    if output_damping_pf is not None and output_damping_pf <= 0.0:
        raise ValueError("output damping capacitance must be positive")
    if vcm_bypass_pf is not None and vcm_bypass_pf <= 0.0:
        raise ValueError("VCM bypass capacitance must be positive")
    if vcm_varactor_model is not None:
        if vcm_bypass_pf is not None:
            raise ValueError("choose either an ideal VCM bypass or a VCM varactor")
        if vcm_varactor_w_um <= 0.0 or vcm_varactor_l_um <= 0.0:
            raise ValueError("VCM varactor dimensions must be positive")
        if vcm_varactor_m <= 0:
            raise ValueError("VCM varactor multiplicity must be positive")
    start = f"{analysis_start_us:g}u"
    stop = f"{analysis_stop_us:g}u"
    step = f"{transient_step_ns:g}n"
    output_p_node = "ch0_out_p.n0" if distributed_rc else "ch0_out_p"
    output_n_node = "ch0_out_n.n0" if distributed_rc else "ch0_out_n"
    output_shunts = ""
    if output_shunt_ohms is not None:
        output_shunts = (
            f"RSHUNTP {output_p_node} VDPWR {output_shunt_ohms:.12g}\n"
            f"RSHUNTN {output_n_node} VDPWR {output_shunt_ohms:.12g}"
        )
    vbias_bypass = (
        f"CBIAS_BYPASS ch0_vbias 0 {vbias_bypass_pf:.12g}p"
        if vbias_bypass_pf is not None
        else ""
    )
    vcm_bypass = (
        f"CVCM_BYPASS ch0_vcm 0 {vcm_bypass_pf:.12g}p"
        if vcm_bypass_pf is not None
        else ""
    )
    vcm_varactor_include = ""
    vcm_varactor = ""
    model_path = extracted_varactor_model or vcm_varactor_model
    if model_path is not None:
        vcm_varactor_include = f'''* Nominal model closure for the SKY130 LVT accumulation varactor.
.param MC_MM_SWITCH=0
.param cnwvc_tox=41.6503 cnwvc_cdepmult=1 cnwvc_cintmult=1
.param cnwvc_vt1=0.3333 cnwvc_vt2=0.2380952 cnwvc_vtr=0.16
.param cnwvc_dwc=0 cnwvc_dlc=0 cnwvc_dld=0
.include "{model_path.as_posix()}"'''
    if vcm_varactor_model is not None:
        vcm_varactor = (
            "XVCM_VAR ch0_vcm 0 0 sky130_fd_pr__cap_var_lvt "
            f"w={vcm_varactor_w_um:.12g} l={vcm_varactor_l_um:.12g} "
            f"vm={vcm_varactor_m}"
        )
    output_damping = ""
    if output_damping_pf is not None:
        output_damping = (
            f"CDAMPP {output_p_node} VDPWR {output_damping_pf:.12g}p\n"
            f"CDAMPN {output_n_node} VDPWR {output_damping_pf:.12g}p"
        )
    ena_source = (
        f"VENA {CONTROL_NODES['ena']} 0 "
        f"pulse(0 {{VDD}} {enable_delay_us:g}u 200p 200p 100u 200u)"
        if enable_delay_us > 0.0
        else f"BENA {CONTROL_NODES['ena']} 0 v=v(VDPWR)"
    )
    controls = [
        f"VBEAM0 {CONTROL_NODES['beam_select[0]']} 0 "
        + ("{VDD}" if beam & 1 else "0"),
        f"VBEAM1 {CONTROL_NODES['beam_select[1]']} 0 "
        + ("{VDD}" if beam & 2 else "0"),
        ena_source,
        f"VMANUAL {CONTROL_NODES['manual_mode']} 0 0",
        f"VRST {CONTROL_NODES['rst_n']} 0 "
        "pulse(0 {VDD} 250n 200p 200p 100u 200u)",
        clock_source(
            CONTROL_NODES["clk"], clock_duty_percent, clock_jitter_ps,
            analysis_stop_us,
        ),
    ]
    controls[2:2] = serial_trim_sources(trim_codes)
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
    # Cold-start threshold timing needs samples from t=0 even when the
    # steady-state acceptance window is much later in the transient.
    # A non-default trim packet is shifted and committed before the steady
    # analog measurement window.  Retain those early samples so the extracted
    # apply_config pulse and serial handoff are proven rather than inferred
    # from the eventual analog gain.
    transient_start = (
        "0" if trim_codes != (8, 8, 8, 8)
        else start if operating_point_startup else "0"
    )
    transient = f".tran {step} {stop} {transient_start}" + (
        "" if operating_point_startup else " uic"
    )
    startup_measures = "" if operating_point_startup else """
* The last upward crossing is the conservative point after which VCM stays
* above the threshold if startup ringing causes more than one crossing.
.measure tran vcm_valid_first when v(ch0_vcm)=1.1 rise=1
.measure tran vcm_valid_settled when v(ch0_vcm)=1.1 rise=last
.measure tran vcm_near_nominal_first when v(ch0_vcm)=1.17 rise=1
.measure tran vcm_near_nominal_settled when v(ch0_vcm)=1.17 rise=last
"""
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
    trim_nodes = tuple(
        f"v2_control_openroad_routes_0.{node}" if distributed_rc else node
        for node in TRIM_ROUTE_NODES
    )
    trim_saves = ""
    trim_measures = ""
    if trim_codes != (8, 8, 8, 8):
        apply_node = (
            f"v2_control_openroad_routes_0.{CONTROL_OBSERVATION_NODES['apply_config']}"
            if distributed_rc else CONTROL_OBSERVATION_NODES["apply_config"]
        )
        serial_node = (
            f"v2_control_openroad_routes_0.{CONTROL_OBSERVATION_NODES['serial_phase_to_trim']}"
            if distributed_rc else CONTROL_OBSERVATION_NODES["serial_phase_to_trim"]
        )
        trim_saves = "\n".join(
            f"+ v({node})"
            for node in (*trim_nodes, apply_node, serial_node)
        )
        trim_measures = "\n".join(
            f".measure tran trim{index}_min min v({node}) from={start} to={stop}\n"
            f".measure tran trim{index}_max max v({node}) from={start} to={stop}"
            for index, node in enumerate(trim_nodes)
        )
        trim_measures += (
            f"\n.measure tran apply_config_max max v({apply_node}) from=0 to={start}"
            f"\n.measure tran serial_trim_min min v({serial_node}) from=0 to={start}"
            f"\n.measure tran serial_trim_max max v({serial_node}) from=0 to={start}"
            f"\n.measure tran cfg_clk_max max v({CONTROL_NODES['cfg_clk']}) from=0 to={start}"
            f"\n.measure tran cfg_data_max max v({CONTROL_NODES['cfg_data']}) from=0 to={start}"
            f"\n.measure tran cfg_latch_max max v({CONTROL_NODES['cfg_latch']}) from=0 to={start}"
        )
    return f"""* V2 full-chip post-layout nominal smoke test.
* extracted_netlist_sha256={netlist_hash}
* final_gds_sha256={gds_hash}
.option klu
.option scale=1e-6
.option method=gear reltol=1e-3 vabstol=1e-6 iabstol=1e-12
.temp {temperature_c:g}
.include "spice/sky130/sky130_1v8_{process_corner}.inc"
.include "third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__{process_corner}.corner.spice"
.include "third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__mismatch.corner.spice"
{passive_includes}
.include "v2/spice/extracted_model_aliases.inc"
{vcm_varactor_include}
.include "{netlist.as_posix()}"

.param VDD={supply_voltage_v:.12g} FIN={input_frequency_mhz:.12g}meg FOUT={output_frequency_mhz:.12g}meg FLO=4meg VINPK={input_peak_v:.12g}
{vdd_source}
VSS_SOURCE {GROUND} 0 0
{vbias_bypass}
{vcm_bypass}
{vcm_varactor}
{chr(10).join(controls)}

{chr(10).join(input_source(index, phase) for index, phase in enumerate(input_phases_deg))}

ROUTP {output_p_node} outp_pad 500
ROUTN {output_n_node} outn_pad 500
{output_shunts}
{output_damping}
COUTP outp_pad 0 10p
COUTN outn_pad 0 10p
RLOADP outp_pad 0 1meg
RLOADN outn_pad 0 1meg
EDIFF differential 0 outp_pad outn_pad 1
BCM common_mode 0 v=(v(outp_pad)+v(outn_pad))/2
ECORE_DIFF core_differential 0 {output_p_node} {output_n_node} 1
BCORE_CM core_common_mode 0 v=(v({output_p_node})+v({output_n_node}))/2
BTONEI tone_i 0 v=v(differential)*cos(2*pi*FOUT*time)
BTONEQ tone_q 0 v=v(differential)*sin(2*pi*FOUT*time)
BLOI lo_i 0 v=v(core_differential)*cos(2*pi*FLO*time)
BLOQ lo_q 0 v=v(core_differential)*sin(2*pi*FLO*time)
BCMLOI cm_lo_i 0 v=v(core_common_mode)*cos(2*pi*FLO*time)
BCMLOQ cm_lo_q 0 v=v(core_common_mode)*sin(2*pi*FLO*time)
BVCMRFI vcm_rf_i 0 v=v(ch0_vcm)*cos(2*pi*FIN*time)
BVCMRFQ vcm_rf_q 0 v=v(ch0_vcm)*sin(2*pi*FIN*time)
BVCMLOI vcm_lo_i 0 v=v(ch0_vcm)*cos(2*pi*FLO*time)
BVCMLOQ vcm_lo_q 0 v=v(ch0_vcm)*sin(2*pi*FLO*time)
{chr(10).join(f'BCH{channel}{branch.upper()}VDS ch{channel}_{branch}_vds_probe 0 v=v(ch{channel}_{branch})-v(ch{channel}_tail)' for channel in range(4) for branch in ("gm_p", "gm_n"))}
RF1 differential filt1 1k
CF1 filt1 0 79.577p
RF2 filt1 filtered 1k
CF2 filtered 0 79.577p

.save v(filtered) v(outp_pad) v(outn_pad) v(common_mode) v(ch0_vcm) v(ch0_vbias)
+ v(core_differential) v(core_common_mode) v(tone_i) v(tone_q)
+ v(lo_i) v(lo_q) v(cm_lo_i) v(cm_lo_q) i(VDD_SOURCE)
+ v(vcm_rf_i) v(vcm_rf_q) v(vcm_lo_i) v(vcm_lo_q)
+ {" ".join(f"v(ch{channel}_{node})" for channel in range(4) for node in ("gm_p", "gm_n", "tail"))}
+ {" ".join(f"v(ch{channel}_{branch}_vds_probe)" for channel in range(4) for branch in ("gm_p", "gm_n"))}
+ {" ".join(f"v({node})" for node in phase_nodes)}
{rc_leaf_saves}
{trim_saves}
{transient}
{startup_measures}
.measure tran output_rms rms v(filtered) from={start} to={stop}
.measure tran output_avg avg v(filtered) from={start} to={stop}
.measure tran common_mode_avg avg v(common_mode) from={start} to={stop}
.measure tran vcm_avg avg v(ch0_vcm) from={start} to={stop}
.measure tran vcm_min min v(ch0_vcm) from={start} to={stop}
.measure tran vcm_max max v(ch0_vcm) from={start} to={stop}
.measure tran vbias_avg avg v(ch0_vbias) from={start} to={stop}
.measure tran vbias_min min v(ch0_vbias) from={start} to={stop}
.measure tran vbias_max max v(ch0_vbias) from={start} to={stop}
.measure tran supply_avg avg i(VDD_SOURCE) from={start} to={stop}
.measure tran tone_i_avg avg v(tone_i) from={start} to={stop}
.measure tran tone_q_avg avg v(tone_q) from={start} to={stop}
.measure tran output_tone_rms param='sqrt(2*(tone_i_avg*tone_i_avg+tone_q_avg*tone_q_avg))'
.measure tran core_output_p_min min v({output_p_node}) from={start} to={stop}
.measure tran core_output_p_max max v({output_p_node}) from={start} to={stop}
.measure tran core_output_n_min min v({output_n_node}) from={start} to={stop}
.measure tran core_output_n_max max v({output_n_node}) from={start} to={stop}
.measure tran core_lo_i_avg avg v(lo_i) from={start} to={stop}
.measure tran core_lo_q_avg avg v(lo_q) from={start} to={stop}
.measure tran core_lo_rms param='sqrt(2*(core_lo_i_avg*core_lo_i_avg+core_lo_q_avg*core_lo_q_avg))'
.measure tran core_cm_lo_i_avg avg v(cm_lo_i) from={start} to={stop}
.measure tran core_cm_lo_q_avg avg v(cm_lo_q) from={start} to={stop}
.measure tran core_cm_lo_rms param='sqrt(2*(core_cm_lo_i_avg*core_cm_lo_i_avg+core_cm_lo_q_avg*core_cm_lo_q_avg))'
.measure tran vcm_rf_i_avg avg v(vcm_rf_i) from={start} to={stop}
.measure tran vcm_rf_q_avg avg v(vcm_rf_q) from={start} to={stop}
.measure tran vcm_rf_rms param='sqrt(2*(vcm_rf_i_avg*vcm_rf_i_avg+vcm_rf_q_avg*vcm_rf_q_avg))'
.measure tran vcm_lo_i_avg avg v(vcm_lo_i) from={start} to={stop}
.measure tran vcm_lo_q_avg avg v(vcm_lo_q) from={start} to={stop}
.measure tran vcm_lo_rms param='sqrt(2*(vcm_lo_i_avg*vcm_lo_i_avg+vcm_lo_q_avg*vcm_lo_q_avg))'
{chr(10).join(f'.measure tran ch{channel}_{node}_min min v(ch{channel}_{node}) from={start} to={stop}' + chr(10) + f'.measure tran ch{channel}_{node}_max max v(ch{channel}_{node}) from={start} to={stop}' for channel in range(4) for node in ("gm_p", "gm_n", "tail"))}
{chr(10).join(f'.measure tran ch{channel}_{branch}_vds_min min v(ch{channel}_{branch}_vds_probe) from={start} to={stop}' + chr(10) + f'.measure tran ch{channel}_{branch}_vds_max max v(ch{channel}_{branch}_vds_probe) from={start} to={stop}' for channel in range(4) for branch in ("gm_p", "gm_n"))}
{phase_measures}
{rc_leaf_measures}
{trim_measures}
.end
"""


def parse_measures(text: str) -> dict[str, float]:
    return {name: float(value) for name, value in MEASURE_RE.findall(text)}


def analyze(
    values: dict[str, float], distributed_rc: bool = False,
    require_output: bool = True,
    settled_startup: bool = False,
    full_channel_operation: bool = False,
    require_headroom_probes: bool = False,
    trim_codes: tuple[int, int, int, int] | None = None,
    supply_voltage_v: float = 1.8,
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
    if trim_codes is not None:
        required.update(
            f"trim{index}_{field}"
            for index in range(16) for field in ("min", "max")
        )
        required.update({
            "apply_config_max", "serial_trim_min", "serial_trim_max",
            "cfg_clk_max", "cfg_data_max", "cfg_latch_max",
        })
    if require_headroom_probes:
        required.update(
            f"ch{channel}_{branch}_vds_{edge}"
            for channel in range(4)
            for branch in ("gm_p", "gm_n")
            for edge in ("min", "max")
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
            if low > 0.2 * supply_voltage_v or high < 0.8 * supply_voltage_v:
                errors.append(
                    f"phase {index} does not reach valid rails: min={low}, max={high}"
                )
            if abs(period - 250e-9) > 2.5e-9:
                errors.append(f"phase {index} period {period} is not nominal 250 ns")
        if settled_startup:
            if full_channel_operation:
                if not 0.8 < values["common_mode_avg"] < 1.2:
                    errors.append(
                        "settled differential output common mode is out of range"
                    )
            elif not 0.5 < values["common_mode_avg"] < 1.75:
                errors.append("diagnostic output common mode is near a supply rail")
            vcm_low = 0.60 * supply_voltage_v
            vcm_high = 0.73 * supply_voltage_v
            if not vcm_low < values["vcm_avg"] < vcm_high:
                errors.append(
                    "settled VCM is outside its supply-scaled 0.60..0.73 VDD window"
                )
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
                if (
                    low > 0.2 * supply_voltage_v
                    or high < 0.8 * supply_voltage_v
                ):
                    errors.append(
                        f"phase {phase} channel {channel} leaf does not reach "
                        f"valid rails: min={low}, max={high}"
                    )
    verified_trim_codes: list[int] = []
    if trim_codes is not None and not missing:
        for signal in ("cfg_clk_max", "cfg_latch_max", "apply_config_max"):
            if values[signal] < 0.8 * supply_voltage_v:
                errors.append(
                    f"trim programming {signal} never reached a valid high rail: "
                    f"{values[signal]:.6g} V"
                )
        if any(trim_codes) and values["cfg_data_max"] < 0.8 * supply_voltage_v:
            errors.append("trim programming cfg_data never presented a high bit")
        if any(trim_codes) and values["serial_trim_max"] < 0.8 * supply_voltage_v:
            errors.append(
                "trim programming serial phase-to-trim handoff never presented a high bit"
            )
        for channel, code in enumerate(trim_codes):
            verified_code = 0
            for bit in range(4):
                index = channel * 4 + bit
                low = values[f"trim{index}_min"]
                high = values[f"trim{index}_max"]
                expected = (code >> bit) & 1
                if low >= 0.8 * supply_voltage_v:
                    verified_code |= 1 << bit
                    measured = 1
                elif high <= 0.2 * supply_voltage_v:
                    measured = 0
                else:
                    measured = int((low + high) / 2.0 >= 0.5 * supply_voltage_v)
                    errors.append(
                        f"trim bit {index} is not rail-stable: min={low:.6g} V, "
                        f"max={high:.6g} V"
                    )
                if measured != expected:
                    errors.append(
                        f"trim bit {index} measured {measured}, expected {expected} "
                        f"(min={low:.6g} V, max={high:.6g} V)"
                    )
            verified_trim_codes.append(verified_code)
    analysis: dict[str, Any] = {
        "output_ac_rms_v": ac_rms,
        "output_tone_rms_v": values.get("output_tone_rms", 0.0),
        "output_tone_i_v": values.get("tone_i_avg", 0.0),
        "output_tone_q_v": values.get("tone_q_avg", 0.0),
        "output_common_mode_v": values.get("common_mode_avg", 0.0),
        "core_lo_feedthrough_rms_v": values.get("core_lo_rms", 0.0),
        "core_common_mode_lo_rms_v": values.get("core_cm_lo_rms", 0.0),
        "core_output_p_range_v": [
            values.get("core_output_p_min", 0.0),
            values.get("core_output_p_max", 0.0),
        ],
        "core_output_n_range_v": [
            values.get("core_output_n_min", 0.0),
            values.get("core_output_n_max", 0.0),
        ],
        "vcm_v": values.get("vcm_avg", 0.0),
        "vcm_rf_rms_v": values.get("vcm_rf_rms", 0.0),
        "vcm_lo_rms_v": values.get("vcm_lo_rms", 0.0),
        "vcm_peak_to_peak_v": (
            values.get("vcm_max", 0.0) - values.get("vcm_min", 0.0)
        ),
        "vbias_v": values.get("vbias_avg", 0.0),
        "vbias_peak_to_peak_v": (
            values.get("vbias_max", 0.0) - values.get("vbias_min", 0.0)
        ),
        "supply_current_a": abs(values.get("supply_avg", 0.0)),
        "estimated_power_w": supply_voltage_v * abs(values.get("supply_avg", 0.0)),
        "minimum_time_aligned_gm_drain_to_tail_v": min(
            (
                values[f"ch{channel}_{branch}_vds_min"]
                for channel in range(4)
                for branch in ("gm_p", "gm_n")
                if f"ch{channel}_{branch}_vds_min" in values
            ),
            default=None,
        ),
        "phases": phases,
        "phase_leaf_skew": phase_leaf_skew,
        "verified_trim_codes": verified_trim_codes,
        "trim_programming": {
            "apply_config_max_v": values.get("apply_config_max", 0.0),
            "serial_phase_to_trim_range_v": [
                values.get("serial_trim_min", 0.0),
                values.get("serial_trim_max", 0.0),
            ],
            "cfg_clk_max_v": values.get("cfg_clk_max", 0.0),
            "cfg_data_max_v": values.get("cfg_data_max", 0.0),
            "cfg_latch_max_v": values.get("cfg_latch_max", 0.0),
        },
    }
    for measurement, field in (
        ("vcm_valid_first", "vcm_valid_first_crossing_s"),
        ("vcm_valid_settled", "vcm_valid_settled_crossing_s"),
        ("vcm_near_nominal_first", "vcm_near_nominal_first_crossing_s"),
        ("vcm_near_nominal_settled", "vcm_near_nominal_settled_crossing_s"),
    ):
        if measurement in values:
            analysis[field] = values[measurement]
    return analysis, errors


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
        "--input-frequency-mhz", type=float, default=5.0,
        help="element-input frequency; the quadrature LO remains fixed at 4 MHz",
    )
    parser.add_argument(
        "--startup",
        choices=("uic", "op"),
        default="uic",
        help="fast ramped UIC startup or exact DC operating-point startup",
    )
    parser.add_argument("--analysis-start-us", type=float, default=2.0)
    parser.add_argument("--analysis-stop-us", type=float, default=4.0)
    parser.add_argument("--transient-step-ns", type=float, default=2.0)
    parser.add_argument("--enable-delay-us", type=float, default=0.0)
    parser.add_argument("--output-shunt-ohms", type=float)
    parser.add_argument("--vbias-bypass-pf", type=float)
    parser.add_argument("--output-damping-pf", type=float)
    parser.add_argument("--vcm-bypass-pf", type=float)
    parser.add_argument(
        "--vcm-varactor-model",
        type=Path,
        help="experimental SKY130 LVT varactor model used as the VCM bypass",
    )
    parser.add_argument("--vcm-varactor-w-um", type=float, default=25.0)
    parser.add_argument("--vcm-varactor-l-um", type=float, default=25.0)
    parser.add_argument("--vcm-varactor-m", type=int, default=1)
    parser.add_argument(
        "--process-corner", choices=("tt", "ff", "ss", "fs", "sf"), default="tt"
    )
    parser.add_argument(
        "--passive-corner", choices=tuple(PASSIVE_CORNERS), default="tt"
    )
    parser.add_argument("--supply-voltage-v", type=float, default=1.8)
    parser.add_argument("--temperature-c", type=float, default=27.0)
    parser.add_argument("--clock-duty-percent", type=float, default=50.0)
    parser.add_argument(
        "--clock-jitter-ps", type=float, default=0.0,
        help="deterministic zero-mean master-clock edge jitter amplitude",
    )
    parser.add_argument(
        "--trim-codes",
        type=parse_trim_codes,
        default=(8, 8, 8, 8),
        metavar="CH0,CH1,CH2,CH3",
        help="four production switched-tail trim codes (default: 8,8,8,8)",
    )
    args = parser.parse_args()
    if not shutil.which(args.ngspice):
        raise SystemExit(f"ngspice not found: {args.ngspice}")
    netlist = args.base_netlist if args.view == "base" else args.rc_netlist
    if not 0 <= args.channel_mask <= 0xF:
        raise SystemExit("--channel-mask must be a four-bit value")
    if args.input_peak_v < 0.0:
        raise SystemExit("--input-peak-v cannot be negative")
    if args.input_frequency_mhz <= 4.0 or args.input_frequency_mhz > 20.0:
        raise SystemExit("--input-frequency-mhz must be above 4 and at most 20")
    if not 1.4 <= args.supply_voltage_v <= 2.1:
        raise SystemExit("--supply-voltage-v must be between 1.4 and 2.1")
    if not -55.0 <= args.temperature_c <= 125.0:
        raise SystemExit("--temperature-c must be between -55 and 125")
    if not 35.0 <= args.clock_duty_percent <= 65.0:
        raise SystemExit("--clock-duty-percent must be between 35 and 65")
    if not 0.0 <= args.clock_jitter_ps <= 2000.0:
        raise SystemExit("--clock-jitter-ps must be between zero and 2000")
    if args.analysis_start_us <= 0.0 or args.analysis_stop_us <= args.analysis_start_us:
        raise SystemExit("analysis window must have positive, increasing times")
    window_us = args.analysis_stop_us - args.analysis_start_us
    output_cycles = window_us * (args.input_frequency_mhz - 4.0)
    if abs(output_cycles - round(output_cycles)) > 1e-9:
        raise SystemExit("analysis window must span an integer number of output cycles")
    if not 0.5 <= args.transient_step_ns <= 10.0:
        raise SystemExit("--transient-step-ns must be between 0.5 and 10")
    if args.enable_delay_us < 0.0 or args.enable_delay_us >= args.analysis_stop_us:
        raise SystemExit("--enable-delay-us must be nonnegative and before analysis stop")
    if args.output_shunt_ohms is not None and args.output_shunt_ohms <= 0.0:
        raise SystemExit("--output-shunt-ohms must be positive")
    if args.vbias_bypass_pf is not None and args.vbias_bypass_pf <= 0.0:
        raise SystemExit("--vbias-bypass-pf must be positive")
    if args.output_damping_pf is not None and args.output_damping_pf <= 0.0:
        raise SystemExit("--output-damping-pf must be positive")
    if args.vcm_bypass_pf is not None and args.vcm_bypass_pf <= 0.0:
        raise SystemExit("--vcm-bypass-pf must be positive")
    if args.vcm_varactor_model is not None:
        if args.vcm_bypass_pf is not None:
            raise SystemExit("choose either --vcm-bypass-pf or --vcm-varactor-model")
        if args.vcm_varactor_w_um <= 0.0 or args.vcm_varactor_l_um <= 0.0:
            raise SystemExit("VCM varactor dimensions must be positive")
        if args.vcm_varactor_m <= 0:
            raise SystemExit("VCM varactor multiplicity must be positive")
    required_paths = [args.gds, netlist]
    if args.vcm_varactor_model is not None:
        required_paths.append(args.vcm_varactor_model)
    for path in required_paths:
        if not path.is_file():
            raise SystemExit(f"missing required artifact: {path}")
    netlist_text = netlist.read_text(encoding="utf-8", errors="replace")
    validate_extracted_netlist(netlist_text)
    extracted_varactor_model = (
        DEFAULT_VARACTOR_MODEL
        if "sky130_fd_pr__cap_var_lvt" in extracted_model_names(netlist_text)
        else None
    )
    if extracted_varactor_model is not None:
        if args.vcm_varactor_model is not None:
            raise SystemExit(
                "the extracted layout already contains VCM varactors; "
                "refusing to add an experimental duplicate"
            )
        if not extracted_varactor_model.is_file():
            raise SystemExit(
                f"missing extracted-varactor model: {extracted_varactor_model}"
            )
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
        and args.input_frequency_mhz == 5.0
        and args.startup == "uic"
        and args.analysis_start_us == 2.0
        and args.analysis_stop_us == 4.0
        and args.transient_step_ns == 2.0
        and args.enable_delay_us == 0.0
        and args.output_shunt_ohms is None
        and args.vbias_bypass_pf is None
        and args.output_damping_pf is None
        and args.vcm_bypass_pf is None
        and args.vcm_varactor_model is None
        and args.process_corner == "tt"
        and args.passive_corner == "tt"
        and args.supply_voltage_v == 1.8
        and args.temperature_c == 27.0
        and args.clock_duty_percent == 50.0
        and args.clock_jitter_ps == 0.0
        and args.trim_codes == (8, 8, 8, 8)
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
        if args.input_frequency_mhz != 5.0:
            case_label += f"_fin_{args.input_frequency_mhz:g}mhz".replace(".", "p")
        if args.startup == "op":
            case_label += "_startup_op"
        if args.analysis_start_us != 2.0 or args.analysis_stop_us != 4.0:
            case_label += (
                f"_window_{args.analysis_start_us:g}us_"
                f"{args.analysis_stop_us:g}us"
            ).replace(".", "p")
        if args.transient_step_ns != 2.0:
            case_label += f"_step_{args.transient_step_ns:g}ns".replace(".", "p")
        if args.enable_delay_us > 0.0:
            case_label += f"_enable_{args.enable_delay_us:g}us".replace(".", "p")
        if args.output_shunt_ohms is not None:
            case_label += f"_shunt_{args.output_shunt_ohms:g}ohm".replace(".", "p")
        if args.vbias_bypass_pf is not None:
            case_label += f"_vbiascap_{args.vbias_bypass_pf:g}pf".replace(".", "p")
        if args.output_damping_pf is not None:
            case_label += f"_outcap_{args.output_damping_pf:g}pf".replace(".", "p")
        if args.vcm_bypass_pf is not None:
            case_label += f"_vcmcap_{args.vcm_bypass_pf:g}pf".replace(".", "p")
        if args.vcm_varactor_model is not None:
            case_label += (
                f"_vcmvar_w{args.vcm_varactor_w_um:g}_l{args.vcm_varactor_l_um:g}"
            ).replace(".", "p")
            if args.vcm_varactor_m != 1:
                case_label += f"_m{args.vcm_varactor_m}"
        if (
            args.process_corner != "tt"
            or args.supply_voltage_v != 1.8
            or args.temperature_c != 27.0
        ):
            case_label += (
                f"_corner_{args.process_corner}_vdd_{args.supply_voltage_v:g}"
                f"_temp_{args.temperature_c:g}c"
            ).replace(".", "p").replace("-", "m")
        if args.passive_corner != "tt":
            case_label += f"_passives_{args.passive_corner}"
        if args.clock_duty_percent != 50.0:
            case_label += (
                f"_clkduty_{args.clock_duty_percent:g}pct"
            ).replace(".", "p")
        if args.clock_jitter_ps != 0.0:
            case_label += (
                f"_clkjitter_{args.clock_jitter_ps:g}ps"
            ).replace(".", "p")
        if args.trim_codes != (8, 8, 8, 8):
            case_label += "_trim_" + "_".join(str(code) for code in args.trim_codes)
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
            input_frequency_mhz=args.input_frequency_mhz,
            distributed_rc=args.view == "rc",
            operating_point_startup=args.startup == "op",
            analysis_start_us=args.analysis_start_us,
            analysis_stop_us=args.analysis_stop_us,
            transient_step_ns=args.transient_step_ns,
            enable_delay_us=args.enable_delay_us,
            output_shunt_ohms=args.output_shunt_ohms,
            vbias_bypass_pf=args.vbias_bypass_pf,
            output_damping_pf=args.output_damping_pf,
            vcm_bypass_pf=args.vcm_bypass_pf,
            vcm_varactor_model=args.vcm_varactor_model,
            extracted_varactor_model=extracted_varactor_model,
            vcm_varactor_w_um=args.vcm_varactor_w_um,
            vcm_varactor_l_um=args.vcm_varactor_l_um,
            vcm_varactor_m=args.vcm_varactor_m,
            process_corner=args.process_corner,
            supply_voltage_v=args.supply_voltage_v,
            temperature_c=args.temperature_c,
            trim_codes=args.trim_codes,
            passive_corner=args.passive_corner,
            clock_duty_percent=args.clock_duty_percent,
            clock_jitter_ps=args.clock_jitter_ps,
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
        full_channel_operation=(
            args.channel_mask == 0xF and args.output_shunt_ohms is None
            and args.output_damping_pf is None
            and args.vcm_bypass_pf is None
            and args.vcm_varactor_model is None
        ),
        require_headroom_probes=True,
        require_output=(
            args.input_peak_v > 0.0
            and (args.incident_beam is None or args.beam == args.incident_beam)
        ),
        trim_codes=(
            args.trim_codes if args.trim_codes != (8, 8, 8, 8) else None
        ),
        supply_voltage_v=args.supply_voltage_v,
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
        "input_frequency_mhz": args.input_frequency_mhz,
        "output_frequency_mhz": args.input_frequency_mhz - 4.0,
        "startup": args.startup,
        "analysis_window_us": [args.analysis_start_us, args.analysis_stop_us],
        "transient_step_ns": args.transient_step_ns,
        "enable_delay_us": args.enable_delay_us,
        "output_shunt_ohms": args.output_shunt_ohms,
        "vbias_bypass_pf": args.vbias_bypass_pf,
        "output_damping_pf": args.output_damping_pf,
        "vcm_bypass_pf": args.vcm_bypass_pf,
        "vcm_varactor_model": (
            str(args.vcm_varactor_model)
            if args.vcm_varactor_model is not None
            else None
        ),
        "vcm_varactor_w_um": args.vcm_varactor_w_um,
        "vcm_varactor_l_um": args.vcm_varactor_l_um,
        "vcm_varactor_m": args.vcm_varactor_m,
        "process_corner": args.process_corner,
        "supply_voltage_v": args.supply_voltage_v,
        "temperature_c": args.temperature_c,
        "clock_duty_percent": args.clock_duty_percent,
        "clock_jitter_ps": args.clock_jitter_ps,
        "passive_corner": args.passive_corner,
        "trim_codes": list(args.trim_codes),
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
