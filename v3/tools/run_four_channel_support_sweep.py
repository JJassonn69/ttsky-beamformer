#!/usr/bin/env python3
"""Screen the shared V3 VCM network and four-channel output load.

The earlier one-channel electrical gate intentionally used ideal 1.2 V input
common mode and a 5 kohm load.  That is insufficient for top-level layout:
four channels share one output-load pair, and AC-coupled pins require physical
bias resistors.  This bounded sweep inserts those shared components before
their PCells and coordinates are frozen.

The varactors use the V2 exact-layout 1.2 V small-signal linearization.  This
is a selection screen, not post-layout signoff; the selected nonlinear PCells
must be re-run after exact V3 extraction.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "v3" / "model"
sys.path.insert(0, str(MODEL_DIR))

from beamformer_v3 import phase_table, unpack_group_codes  # noqa: E402


BUILD = ROOT / "build" / "v3" / "four_channel_support"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "four_channel_support_sweep.json"

MEASURE_RE = re.compile(r"^([a-zA-Z0-9_]+)\s*=\s*([-+0-9.eE]+)", re.MULTILINE)
AXIS_LO_PAIR = {
    0: ("lo0", "lo180"),
    1: ("lo90", "lo270"),
    2: ("lo180", "lo0"),
    3: ("lo270", "lo90"),
}

# One M3 MIM PCell plus zero or more copies of the exact V2 varactor PCell.
MIM_CAPACITANCE_PF = 0.98
VARACTOR_CAPACITANCE_PF = 2.604860136214599
VARACTOR_SERIES_RESISTANCE_OHM = 1097.313345683077


@dataclass(frozen=True)
class Mode:
    name: str
    phase_indices: tuple[int, int, int, int]


MODES = (
    Mode("same_cardinal", (0, 0, 0, 0)),
    Mode("same_intermediate", (1, 1, 1, 1)),
    Mode("staggered_cardinal", (0, 2, 4, 6)),
    Mode("staggered_intermediate", (1, 3, 5, 7)),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mode_words(mode: Mode) -> tuple[int, int, int, int]:
    table = phase_table(8)
    return tuple(table[index].word for index in mode.phase_indices)


def channel_instance(index: int, word: int, phase_deg: float) -> str:
    group_nodes = [
        node
        for code in unpack_group_codes(word)
        for node in AXIS_LO_PAIR[code]
    ]
    return f"""* Channel {index}: coefficient word 0x{word:02X}.
VSRC{index} src{index} 0 sin(0 5m 5meg 0 0 {phase_deg:.12g})
CIN{index} src{index} pad{index} 100p
RPATH{index} pad{index} sig{index} 500
CPAD{index} sig{index} 0 5p
XRIN{index} sig{index} vcm 0 sky130_fd_pr__res_xhigh_po_1p41 l=70.5
XBIAS_GATE{index} vbias VDD_NODE 0 vbias_ch{index} 0 v3_bias_blank_switch
XCHANNEL{index} sig{index} vcm {' '.join(group_nodes)} outp outn vbias_ch{index} 0 v3_vector_channel_15_mos
"""


def capacitor_network(varactor_count: int) -> str:
    lines = [f"CMIM vcm 0 {MIM_CAPACITANCE_PF:.12g}p"]
    for index in range(varactor_count):
        lines.extend((
            f"CVAR{index} vcm vcap{index} {VARACTOR_CAPACITANCE_PF:.16g}p",
            f"RVAR{index} vcap{index} 0 {VARACTOR_SERIES_RESISTANCE_OHM:.16g}",
        ))
    return "\n".join(lines)


def deck(mode: Mode, load_ohm: float, varactor_count: int) -> str:
    table = phase_table(8)
    words = mode_words(mode)
    # Apply the opposite input phase so each channel's selected complex
    # coefficient adds constructively at the shared output.
    channels = "\n".join(
        channel_instance(index, word, -table[phase_index].target_phase_deg)
        for index, (word, phase_index) in enumerate(zip(words, mode.phase_indices))
    )
    return f"""* Generated V3 four-channel shared-support screen.
* mode={mode.name}, load={load_ohm:.12g} ohm, varactors={varactor_count}
.option scale=1e-6
.option method=gear reltol=2e-4 vabstol=1e-7 iabstol=1e-12
.temp 27
.include "spice/sky130/sky130_1v8_tt.inc"
.include "spice/sky130/sky130_passives_tt.inc"
.include "v3/spice/vector_channel_15.inc"

.param VDD=1.8 FIN=5meg FLO=4meg FOUT=1meg
VDD_SOURCE VDD_NODE 0 {{VDD}}

* Physical VCM divider inherited from V2.  Four input resistors are required
* because the Tiny Tapeout analog inputs are externally AC-coupled.
XRVCM_TOP VDD_NODE vcm 0 sky130_fd_pr__res_xhigh_po_1p41 l=47
XRVCM_BOTTOM vcm 0 0 sky130_fd_pr__res_xhigh_po_1p41 l=94
{capacitor_network(varactor_count)}

* Closed 64/1 um reference ratio and one enabled local pass gate per channel.
RBIAS VDD_NODE vbias 10.5k
XBIAS_REF vbias vbias 0 0 sky130_fd_pr__nfet_01v8 w=64 l=1
CBIAS vbias 0 2p

* Quadrature roots.  Complements are exact in this bounded analog screen.
VLO0 lo0 0 pulse(0 {{VDD}} 10n 1n 1n 123n 250n)
BLO180 lo180 0 v={{VDD}}-v(lo0)
VLO90 lo90 0 pulse(0 {{VDD}} 72.5n 1n 1n 123n 250n)
BLO270 lo270 0 v={{VDD}}-v(lo90)

{channels}

* One physical pair is shared by all four channels.
RLOADP VDD_NODE outp {load_ohm:.12g}
RLOADN VDD_NODE outn {load_ohm:.12g}
ROUTP outp outp_pad 500
ROUTN outn outn_pad 500
COUTP outp_pad 0 10p
COUTN outn_pad 0 10p
RINSTRP outp_pad 0 1meg
RINSTRN outn_pad 0 1meg
EDIFF differential 0 outp_pad outn_pad 1
BCM output_cm 0 v=(v(outp_pad)+v(outn_pad))/2

RF1 differential filt1 1k
CF1 filt1 0 79.577p
RF2 filt1 filtered 1k
CF2 filtered 0 79.577p
BTONEI tone_i 0 v=v(filtered)*cos(2*pi*FOUT*time)
BTONEQ tone_q 0 v=v(filtered)*sin(2*pi*FOUT*time)

* Integer 4/5 MHz periods make the synchronous VCM measurements reject DC.
BVCM4I vcm4i 0 v=v(vcm)*cos(2*pi*FLO*time)
BVCM4Q vcm4q 0 v=v(vcm)*sin(2*pi*FLO*time)
BVCM5I vcm5i 0 v=v(vcm)*cos(2*pi*FIN*time)
BVCM5Q vcm5q 0 v=v(vcm)*sin(2*pi*FIN*time)

.tran 2n 8u 2u
* The operating point starts the divider at DC.  Four microseconds before the
* measurement is more than eight nominal VCM time constants; the 4--8 us
* window contains exactly 16 LO and 20 RF periods.
.measure tran vcm_avg avg v(vcm) from=4u to=8u
.measure tran vcm_min min v(vcm) from=4u to=8u
.measure tran vcm_max max v(vcm) from=4u to=8u
.measure tran output_cm_avg avg v(output_cm) from=4u to=8u
.measure tran output_cm_min min v(output_cm) from=4u to=8u
.measure tran tone_i_avg avg v(tone_i) from=4u to=8u
.measure tran tone_q_avg avg v(tone_q) from=4u to=8u
.measure tran vcm4_i avg v(vcm4i) from=4u to=8u
.measure tran vcm4_q avg v(vcm4q) from=4u to=8u
.measure tran vcm5_i avg v(vcm5i) from=4u to=8u
.measure tran vcm5_q avg v(vcm5q) from=4u to=8u
.measure tran supply_avg avg i(VDD_SOURCE) from=4u to=8u
.end
"""


def run_case(ngspice: str, mode: Mode, load_ohm: float, varactor_count: int) -> dict[str, Any]:
    case_dir = BUILD / f"load_{load_ohm:.3f}" / f"var_{varactor_count}" / mode.name
    case_dir.mkdir(parents=True, exist_ok=True)
    deck_path = case_dir / "support.spice"
    log_path = case_dir / "ngspice.log"
    deck_path.write_text(deck(mode, load_ohm, varactor_count), encoding="utf-8")
    completed = subprocess.run(
        [ngspice, "-b", "-o", str(log_path), str(deck_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=600,
        check=False,
    )
    log = log_path.read_text(errors="replace") if log_path.exists() else completed.stdout
    values = {name.lower(): float(value) for name, value in MEASURE_RE.findall(log)}
    required = {
        "vcm_avg", "vcm_min", "vcm_max", "output_cm_avg", "output_cm_min",
        "tone_i_avg", "tone_q_avg", "vcm4_i", "vcm4_q", "vcm5_i", "vcm5_q",
        "supply_avg",
    }
    if completed.returncode != 0 or not required.issubset(values):
        missing = sorted(required - values.keys())
        raise RuntimeError(
            f"case {case_dir.relative_to(ROOT)} failed, return={completed.returncode}, "
            f"missing={missing}\n" + "\n".join(log.splitlines()[-40:])
        )
    tone_peak = 2.0 * math.hypot(values["tone_i_avg"], values["tone_q_avg"])
    return {
        "mode": mode.name,
        "phase_indices": list(mode.phase_indices),
        "words": list(mode_words(mode)),
        "load_ohm": load_ohm,
        "varactor_count": varactor_count,
        "total_nominal_vcm_capacitance_pf": (
            MIM_CAPACITANCE_PF + varactor_count * VARACTOR_CAPACITANCE_PF
        ),
        "vcm_average_v": values["vcm_avg"],
        "vcm_peak_to_peak_v": values["vcm_max"] - values["vcm_min"],
        "vcm_4mhz_peak_v": 2.0 * math.hypot(values["vcm4_i"], values["vcm4_q"]),
        "vcm_5mhz_peak_v": 2.0 * math.hypot(values["vcm5_i"], values["vcm5_q"]),
        "output_common_mode_average_v": values["output_cm_avg"],
        "output_common_mode_minimum_v": values["output_cm_min"],
        "filtered_output_tone_peak_v": tone_peak,
        "supply_current_a": abs(values["supply_avg"]),
        "deck": str(deck_path.relative_to(ROOT)),
        "deck_sha256": sha256(deck_path),
        "log": str(log_path.relative_to(ROOT)),
    }


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    pairs = sorted({(case["load_ohm"], case["varactor_count"]) for case in cases})
    for load_ohm, varactor_count in pairs:
        selected = [
            case for case in cases
            if case["load_ohm"] == load_ohm and case["varactor_count"] == varactor_count
        ]
        candidates.append({
            "load_ohm": load_ohm,
            "varactor_count": varactor_count,
            "total_nominal_vcm_capacitance_pf": selected[0]["total_nominal_vcm_capacitance_pf"],
            "minimum_output_common_mode_average_v": min(case["output_common_mode_average_v"] for case in selected),
            "minimum_instantaneous_output_common_mode_v": min(case["output_common_mode_minimum_v"] for case in selected),
            "maximum_vcm_peak_to_peak_v": max(case["vcm_peak_to_peak_v"] for case in selected),
            "maximum_vcm_4mhz_peak_v": max(case["vcm_4mhz_peak_v"] for case in selected),
            "maximum_vcm_5mhz_peak_v": max(case["vcm_5mhz_peak_v"] for case in selected),
            "filtered_output_tone_peak_range_v": [
                min(case["filtered_output_tone_peak_v"] for case in selected),
                max(case["filtered_output_tone_peak_v"] for case in selected),
            ],
        })
    return {
        "schema_version": 1,
        "status": "screen_complete",
        "scope": "nominal four-channel shared-support selection screen; not PVT, mismatch, extracted layout, or signoff",
        "circuit_corrections": [
            "four 70.5 um xhigh-poly input-bias resistors included after external AC coupling",
            "one output-load pair is shared by all four 15-slice channels",
            "physical VCM divider replaces the ideal 1.2 V source",
        ],
        "candidate_models": {
            "mim_capacitance_pf": MIM_CAPACITANCE_PF,
            "varactor_capacitance_pf_at_1p2v": VARACTOR_CAPACITANCE_PF,
            "varactor_series_resistance_ohm_at_1p2v": VARACTOR_SERIES_RESISTANCE_OHM,
            "varactor_source": "v2/spice/sky130_fd_pr__cap_var_lvt.linearized_1p2v.spice",
            "output_load_note": "2925 ohm is the nominal model value of V2 length-11.6117 high-poly load; other values are selection candidates",
        },
        "mode_count": len(MODES),
        "case_count": len(cases),
        "candidates": candidates,
        "cases": sorted(cases, key=lambda item: (item["load_ohm"], item["varactor_count"], item["mode"])),
        "next_gate": "select a bounded load/bypass pair, then run PVT and exact nonlinear passive checks before placement",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--loads", default="2500,2925,3300,4000,5000")
    parser.add_argument("--varactors", default="0,1,2,4")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    loads = [float(value) for value in args.loads.split(",")]
    varactors = [int(value) for value in args.varactors.split(",")]
    jobs = [(mode, load, count) for load in loads for count in varactors for mode in MODES]
    cases: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(run_case, args.ngspice, mode, load, count): (mode, load, count)
            for mode, load, count in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            mode, load, count = futures[future]
            cases.append(future.result())
            print(f"completed {mode.name} load={load:g} varactors={count}", flush=True)
    report = summarize(cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
