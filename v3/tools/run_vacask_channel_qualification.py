#!/usr/bin/env python3
"""Cross-check the complete noiseless V3 channel in ngspice and VACASK.

This is the hierarchy level above compact-model qualification.  It compares
all eight required vector states using the promoted 15-slice MOS-tail channel,
real bias pass/pulldown devices, output-path R/C loading, and identical 5 MHz
input / 4 MHz quadrature clocks.  VACASK uses only model cards whose hashes
appear in a passing exact-geometry qualification report.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "v3/model"
sys.path.insert(0, str(MODEL_DIR))

from beamformer_v3 import phase_table, unpack_group_codes  # noqa: E402


DEFAULT_BUILD = ROOT / "build/v3/vacask_channel_qualification"
DEFAULT_MODEL_BUILD = ROOT / "build/v3/vacask_sky130_qualification"
AXIS_LO_PAIR = {
    0: ("lo0", "lo180"),
    1: ("lo90", "lo270"),
    2: ("lo180", "lo0"),
    3: ("lo270", "lo90"),
}
GEOMETRIES_UM = {
    "gm": (0.84, 0.60),
    "switch": (0.65, 0.15),
    "tail": (5.066666666, 1.00),
    "bias_reference": (64.0, 1.00),
    "bias_pass": (2.0, 0.15),
    "bias_pulldown": (1.0, 0.15),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def runtime_environment(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{args.vacask_bin.parent}:{env.get('PATH', '')}"
    env["SIM_MODULE_PATH"] = str(args.module_dir)
    env["SIM_INCLUDE_PATH"] = str(args.include_dir)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(args.python_dir), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    if args.runtime_lib_dir:
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            [str(args.runtime_lib_dir), env.get("LD_LIBRARY_PATH", "")]
        ).rstrip(os.pathsep)
    return env


def run_command(
    command: list[str],
    cwd: Path,
    log_path: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    log_path.write_text(completed.stdout)
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            + "\n".join(completed.stdout.splitlines()[-80:])
        )
    return completed.stdout


def qualified_models(model_build: Path) -> tuple[str, dict[str, str]]:
    summary_path = model_build / "summary.json"
    summary = json.loads(summary_path.read_text())
    if summary.get("status") != "pass":
        raise RuntimeError(f"model qualification is not passing: {summary_path}")
    texts: list[str] = []
    hashes: dict[str, str] = {}
    for label in GEOMETRIES_UM:
        model_path = model_build / label / "vacask_model.inc"
        expected = summary["geometries"][label]["vacask_model_sha256"]
        observed = sha256(model_path)
        if observed != expected:
            raise RuntimeError(
                f"qualified model hash mismatch for {label}: {observed} != {expected}"
            )
        text = model_path.read_text().replace(
            "model candidate", f"model model_{label}", 1
        )
        texts.append(text)
        hashes[label] = observed
    return "\n".join(texts), hashes


def group_nodes(word: int) -> list[str]:
    return [
        node
        for code in unpack_group_codes(word)
        for node in AXIS_LO_PAIR[code]
    ]


def ngspice_deck(word: int, output_path: Path) -> str:
    nodes = " ".join(group_nodes(word))
    return f"""* V3 complete-channel ngspice reference, word=0x{word:02x}.
.option scale=1e-6
.option method=gear reltol=1e-4 vabstol=1e-7 iabstol=1e-12
.temp 27
.include "spice/sky130/sky130_1v8_tt.inc"
.include "v3/spice/vector_channel_15.inc"
VDD_SOURCE vdd 0 1.8
VSIG sig 0 sin(1.2 0.005 5meg)
VREF ref 0 1.2
RBIAS vdd vbias 10.5k
XBIAS_REF vbias vbias 0 0 sky130_fd_pr__nfet_01v8 w=64 l=1.00
CBIAS vbias 0 2p
VBIAS_ENABLE bias_enable 0 1.8
VBIAS_BLANK bias_blank 0 0
XBIAS_GATE vbias bias_enable bias_blank vbias_ch 0 v3_bias_blank_switch
VLO0 lo0 0 pulse(0 1.8 10n 5n 5n 120n 250n)
VLO180 lo180 0 pulse(1.8 0 10n 5n 5n 120n 250n)
VLO90 lo90 0 pulse(0 1.8 72.5n 5n 5n 120n 250n)
VLO270 lo270 0 pulse(1.8 0 72.5n 5n 5n 120n 250n)
XCHANNEL sig ref {nodes} outp outn vbias_ch 0 v3_vector_channel_15_mos
RLOADP vdd outp 5k
RLOADN vdd outn 5k
ROUTP outp outp_pad 500
ROUTN outn outn_pad 500
COUTP outp_pad 0 10p
COUTN outn_pad 0 10p
RINSTRP outp_pad 0 1meg
RINSTRN outn_pad 0 1meg
.control
set wr_vecnames
set wr_singlescale
set numdgt=16
save v(outp_pad) v(outn_pad) v(vbias_ch) i(VDD_SOURCE)
tran 2n 20u 10u
wrdata {output_path} v(outp_pad) v(outn_pad) v(vbias_ch) i(VDD_SOURCE)
quit
.endc
.end
"""


def vacask_unit_instances(word: int) -> str:
    lines: list[str] = []
    unit_number = 0
    for group, count in enumerate((1, 2, 4, 8)):
        lop, lon = AXIS_LO_PAIR[unpack_group_codes(word)[group]]
        for _ in range(count):
            prefix = f"u{unit_number}"
            gm_p = f"{prefix}_gm_p"
            gm_n = f"{prefix}_gm_n"
            tail = f"{prefix}_tail"
            lines.extend(
                (
                    f"m_{prefix}_gmp ({gm_p} sig {tail} 0) model_gm w=0.84u l=0.60u nf=1",
                    f"m_{prefix}_gmn ({gm_n} ref {tail} 0) model_gm w=0.84u l=0.60u nf=1",
                    f"m_{prefix}_swpp (outp {lop} {gm_p} 0) model_switch w=0.65u l=0.15u nf=1",
                    f"m_{prefix}_swpn (outn {lon} {gm_p} 0) model_switch w=0.65u l=0.15u nf=1",
                    f"m_{prefix}_swnp (outn {lop} {gm_n} 0) model_switch w=0.65u l=0.15u nf=1",
                    f"m_{prefix}_swnn (outp {lon} {gm_n} 0) model_switch w=0.65u l=0.15u nf=1",
                    f"m_{prefix}_tail ({tail} vbias_ch 0 0) model_tail w=5.066666666u l=1u nf=1",
                )
            )
            unit_number += 1
    if unit_number != 15:
        raise AssertionError(unit_number)
    return "\n".join(lines)


def vacask_deck(word: int, model_text: str) -> str:
    return f"""V3 complete-channel VACASK candidate, word=0x{word:02x}

ground 0
load "spice/bsim4v8.osdi"
load "resistor.osdi"
load "capacitor.osdi"
{model_text}
model resistor resistor
model capacitor capacitor
model vsource vsource

vdd_source (vdd 0) vsource dc=1.8
vsig (sig 0) vsource dc=1.2 type="sine" sinedc=1.2 ampl=0.005 freq=5meg
vref (ref 0) vsource dc=1.2
r_bias (vdd vbias) resistor r=10.5k
m_bias_ref (vbias vbias 0 0) model_bias_reference w=64u l=1u nf=1
c_bias (vbias 0) capacitor c=2p
v_bias_enable (bias_enable 0) vsource dc=1.8
v_bias_blank (bias_blank 0) vsource dc=0
m_bias_pass (vbias_ch bias_enable vbias 0) model_bias_pass w=2u l=0.15u nf=1
m_bias_pulldown (vbias_ch bias_blank 0 0) model_bias_pulldown w=1u l=0.15u nf=1

v_lo0 (lo0 0) vsource dc=0 type="pulse" val0=0 val1=1.8 delay=10n rise=5n fall=5n width=120n period=250n
v_lo180 (lo180 0) vsource dc=1.8 type="pulse" val0=1.8 val1=0 delay=10n rise=5n fall=5n width=120n period=250n
v_lo90 (lo90 0) vsource dc=0 type="pulse" val0=0 val1=1.8 delay=72.5n rise=5n fall=5n width=120n period=250n
v_lo270 (lo270 0) vsource dc=1.8 type="pulse" val0=1.8 val1=0 delay=72.5n rise=5n fall=5n width=120n period=250n

{vacask_unit_instances(word)}

r_loadp (vdd outp) resistor r=5k
r_loadn (vdd outn) resistor r=5k
r_outp (outp outp_pad) resistor r=500
r_outn (outn outn_pad) resistor r=500
c_outp (outp_pad 0) capacitor c=10p
c_outn (outn_pad 0) capacitor c=10p
r_instrp (outp_pad 0) resistor r=1meg
r_instrn (outn_pad 0) resistor r=1meg

control
  abort always
  options rawfile="binary" strictsave=1
  options reltol=1e-4 vntol=1e-7 abstol=1e-12
  options tran_method="euler" tran_itl=50 tran_predictor=0 tran_redofactor=0
  save outp_pad outn_pad vbias_ch p(vdd_source,i) default
  analysis channel tran stop=20u step=0.25n maxstep=0.25n
endc
"""


def load_ngspice(path: Path) -> dict[str, np.ndarray]:
    data = np.loadtxt(path, skiprows=1)
    if data.ndim != 2 or data.shape[1] != 5:
        raise RuntimeError(f"unexpected ngspice waveform shape {data.shape}")
    return {
        "time": data[:, 0],
        "outp": data[:, 1],
        "outn": data[:, 2],
        "vbias": data[:, 3],
        "supply": data[:, 4],
    }


def load_vacask(args: argparse.Namespace, path: Path) -> dict[str, np.ndarray]:
    sys.path.insert(0, str(args.python_dir))
    from rawfile import rawread  # type: ignore[import-not-found]

    raw = rawread(str(path)).get()
    return {
        "time": np.real(np.asarray(raw["time"])),
        "outp": np.real(np.asarray(raw["outp_pad"])),
        "outn": np.real(np.asarray(raw["outn_pad"])),
        "vbias": np.real(np.asarray(raw["vbias_ch"])),
        "supply": np.real(np.asarray(raw["vdd_source.i"])),
    }


def measurements(waveform: dict[str, np.ndarray]) -> dict[str, float]:
    time = waveform["time"]
    mask = (time >= 12e-6) & (time <= 20e-6)
    time = time[mask]
    outp = waveform["outp"][mask]
    outn = waveform["outn"][mask]
    differential = outp - outn
    tone_i = float(np.trapezoid(differential * np.cos(2 * np.pi * 1e6 * time), time) / (time[-1] - time[0]))
    tone_q = float(np.trapezoid(differential * np.sin(2 * np.pi * 1e6 * time), time) / (time[-1] - time[0]))
    phasor = complex(tone_q, tone_i)
    return {
        "tone_peak_v": 2.0 * abs(phasor),
        "phase_deg": math.degrees(math.atan2(phasor.imag, phasor.real)),
        "output_common_mode_v": float(np.mean((outp + outn) / 2.0)),
        "vbias_v": float(np.mean(waveform["vbias"][mask])),
        "supply_current_a": abs(float(np.mean(waveform["supply"][mask]))),
        "sample_count": int(np.count_nonzero(mask)),
    }


def wrap_phase(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def run_case(
    args: argparse.Namespace, build: Path, word: int, model_text: str
) -> dict[str, Any]:
    case_dir = build / f"word_{word:03d}"
    case_dir.mkdir(parents=True, exist_ok=True)
    ng_data = case_dir / "ngspice_waveform.dat"
    ng_deck = case_dir / "ngspice_channel.spice"
    vc_deck = case_dir / "vacask_channel.sim"
    write_if_changed(ng_deck, ngspice_deck(word, ng_data))
    write_if_changed(vc_deck, vacask_deck(word, model_text))
    run_command(
        [str(args.ngspice), "-b", str(ng_deck)],
        ROOT,
        case_dir / "ngspice.log",
        args.timeout,
    )
    run_command(
        [str(args.vacask_bin), "-dp", str(vc_deck)],
        case_dir,
        case_dir / "vacask.log",
        args.timeout,
        runtime_environment(args),
    )
    ng = measurements(load_ngspice(ng_data))
    vc = measurements(load_vacask(args, case_dir / "channel.raw"))
    deltas = {
        "tone_peak_percent": 100.0 * (vc["tone_peak_v"] / ng["tone_peak_v"] - 1.0),
        "phase_deg": wrap_phase(vc["phase_deg"] - ng["phase_deg"]),
        "output_common_mode_mv": 1e3 * (
            vc["output_common_mode_v"] - ng["output_common_mode_v"]
        ),
        "vbias_mv": 1e3 * (vc["vbias_v"] - ng["vbias_v"]),
        "supply_current_percent": 100.0
        * (vc["supply_current_a"] / ng["supply_current_a"] - 1.0),
    }
    gates = {
        "tone_peak_within_0p5_percent": abs(deltas["tone_peak_percent"]) <= 0.5,
        "phase_within_0p2deg": abs(deltas["phase_deg"]) <= 0.2,
        "output_common_mode_within_1mv": abs(deltas["output_common_mode_mv"]) <= 1.0,
        "vbias_within_1mv": abs(deltas["vbias_mv"]) <= 1.0,
        "supply_current_within_0p5_percent": abs(deltas["supply_current_percent"])
        <= 0.5,
    }
    return {
        "status": "pass" if all(gates.values()) else "fail",
        "word": word,
        "group_codes": list(unpack_group_codes(word)),
        "ngspice": ng,
        "vacask": vc,
        "deltas": deltas,
        "gates": gates,
        "ngspice_deck_sha256": sha256(ng_deck),
        "vacask_deck_sha256": sha256(vc_deck),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vacask-bin", type=Path, required=True)
    parser.add_argument("--module-dir", type=Path, required=True)
    parser.add_argument("--include-dir", type=Path, required=True)
    parser.add_argument("--python-dir", type=Path, required=True)
    parser.add_argument("--runtime-lib-dir", type=Path)
    parser.add_argument("--ngspice", type=Path, default=Path("/usr/bin/ngspice"))
    parser.add_argument("--model-build", type=Path, default=DEFAULT_MODEL_BUILD)
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--words", type=lambda value: int(value, 0), nargs="+")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--jobs", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build = args.build.resolve()
    build.mkdir(parents=True, exist_ok=True)
    for path in (
        args.vacask_bin,
        args.module_dir,
        args.include_dir,
        args.python_dir,
        args.ngspice,
        args.model_build,
    ):
        if not path.exists():
            raise FileNotFoundError(path)
    model_text, model_hashes = qualified_models(args.model_build.resolve())
    required_words = [entry.word for entry in phase_table(8)]
    selected_words = args.words if args.words is not None else required_words
    unknown = sorted(set(selected_words) - set(required_words))
    if unknown:
        raise ValueError(f"words are not in the required eight-state table: {unknown}")
    if args.jobs < 1:
        raise ValueError("--jobs must be positive")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            word: pool.submit(run_case, args, build, word, model_text)
            for word in selected_words
        }
        cases = [futures[word].result() for word in selected_words]
    aggregate = {
        "maximum_tone_peak_delta_percent": max(
            abs(case["deltas"]["tone_peak_percent"]) for case in cases
        ),
        "maximum_phase_delta_deg": max(
            abs(case["deltas"]["phase_deg"]) for case in cases
        ),
        "maximum_output_common_mode_delta_mv": max(
            abs(case["deltas"]["output_common_mode_mv"]) for case in cases
        ),
        "maximum_vbias_delta_mv": max(
            abs(case["deltas"]["vbias_mv"]) for case in cases
        ),
        "maximum_supply_current_delta_percent": max(
            abs(case["deltas"]["supply_current_percent"]) for case in cases
        ),
    }
    report = {
        "schema_version": 1,
        "status": (
            "pass"
            if all(case["status"] == "pass" for case in cases)
            and set(selected_words) == set(required_words)
            else "diagnostic_only" if all(case["status"] == "pass" for case in cases) else "fail"
        ),
        "scope": "TT complete one-channel noiseless cross-simulator qualification; no intrinsic transient noise or layout parasitics",
        "platform": platform.platform(),
        "python": sys.version,
        "numpy": np.__version__,
        "vacask_binary_sha256": sha256(args.vacask_bin),
        "vacask_bsim4_osdi_sha256": sha256(args.module_dir / "spice/bsim4v8.osdi"),
        "model_qualification_summary_sha256": sha256(
            args.model_build / "summary.json"
        ),
        "qualified_model_sha256": model_hashes,
        "required_state_count": len(required_words),
        "simulated_state_count": len(cases),
        "cases": cases,
        "aggregate": aggregate,
        "limitations": [
            "This is deterministic transient equivalence, not noise signoff.",
            "The channel is schematic-only and omits layout/package parasitics.",
            "The postprocessing extracts the unfiltered 1 MHz output tone identically from both simulators.",
        ],
    }
    summary = build / "summary.json"
    summary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] in {"pass", "diagnostic_only"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
