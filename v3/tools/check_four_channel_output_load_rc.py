#!/usr/bin/env python3
"""Audit pad-rooted distributed RC and differential output matching."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))
from check_tail_reference_rc import (  # noqa: E402
    component,
    effective_resistance,
    parse_rnodes,
    parse_spice,
    resistor_graph,
    spice_number,
)


BUILD = ROOT / "build/v3/four_channel_output_load_integration"
COORDINATES = {"p": (14996, 100), "n": (11132, 100)}
LOAD_OHM = 2910.0
SIGNAL_HZ = 5.0e6


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(text: str, name: str) -> int | None:
    values = re.findall(rf"^{re.escape(name)}=(\d+)\s*$", text, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def mismatch(a: float, b: float) -> float:
    return 200.0 * abs(a - b) / (a + b)


def model_index(fields: list[str]) -> int:
    return next(index for index, value in enumerate(fields) if value.startswith("sky130_"))


def counts(records: dict[str, list[list[str]]]) -> dict[str, int]:
    return {"resistors": len(records["R"]), "capacitors": len(records["C"]), "devices": len(records["X"])}


def analyze(work: Path, polarity: str, mim_cap_ff: float) -> dict[str, Any]:
    base_path = work / f"output_{polarity}_base.spice"
    rc_path = work / f"output_{polarity}_rc.spice"
    res_path = work / f"v3_four_channel_output_load_rc_{polarity}.res.ext"
    base = parse_spice(base_path)
    rc = parse_spice(rc_path)
    graph = resistor_graph(rc["R"])
    rnodes = parse_rnodes(res_path)
    candidates = sorted({node for node in rnodes.get(COORDINATES[polarity], []) if node in graph})
    if not candidates:
        raise ValueError(f"{polarity} output has no resistor node at {COORDINATES[polarity]}")
    root = next((node for node in candidates if node.endswith("#")), candidates[0])
    connected = component(graph, root)

    touching: dict[str, list[list[str]]] = {}
    for fields in rc["X"]:
        index = model_index(fields)
        hits = sorted(set(fields[1:index]) & connected)
        if hits:
            touching.setdefault(fields[index], []).append(hits)
    mos_hits = touching.get("sky130_fd_pr__nfet_01v8", [])
    load_hits = touching.get("sky130_fd_pr__res_high_po_1p41", [])
    mim_hits = touching.get("sky130_fd_pr__cap_mim_m3_1", [])
    if any(len(hits) != 1 for hits in mos_hits):
        raise ValueError(f"{polarity} output touches a mixer device more than once")
    mixer_resistance = [effective_resistance(graph, root, hits[0]) for hits in mos_hits]
    extracted_external_cap_f = sum(
        abs(spice_number(fields[3]))
        for fields in rc["C"]
        if (fields[1] in connected) != (fields[2] in connected)
    )
    total_cap_ff = extracted_external_cap_f * 1e15 + mim_cap_ff
    mean_r = sum(mixer_resistance) / len(mixer_resistance)
    tau_s = (LOAD_OHM + mean_r) * total_cap_ff * 1e-15
    pole_hz = 1.0 / (2.0 * math.pi * tau_s)
    ratio = SIGNAL_HZ / pole_hz
    loss_db = 10.0 * math.log10(1.0 + ratio * ratio)
    phase_deg = math.degrees(math.atan(ratio))
    return {
        "root_coordinate_internal": list(COORDINATES[polarity]),
        "root_node": root,
        "root_candidates": candidates,
        "connected_resistor_nodes": len(connected),
        "mixer_terminal_count": len(mos_hits),
        "output_load_terminal_count": len(load_hits),
        "compensation_mim_terminal_count": len(mim_hits),
        "minimum_pad_to_mixer_resistance_ohm": min(mixer_resistance),
        "maximum_pad_to_mixer_resistance_ohm": max(mixer_resistance),
        "mean_pad_to_mixer_resistance_ohm": mean_r,
        "within_net_resistance_spread_ohm": max(mixer_resistance) - min(mixer_resistance),
        "extracted_external_capacitance_ff": extracted_external_cap_f * 1e15,
        "intentional_mim_capacitance_ff_typical": mim_cap_ff,
        "total_effective_capacitance_ff_typical": total_cap_ff,
        "estimated_load_plus_mean_route_tau_ns": tau_s * 1e9,
        "estimated_output_pole_mhz": pole_hz / 1e6,
        "estimated_5mhz_gain_loss_db": loss_db,
        "estimated_5mhz_phase_lag_deg": phase_deg,
        "base": counts(base),
        "distributed_rc": counts(rc),
        "sha256": {
            "base_spice": sha256(base_path),
            "distributed_rc_spice": sha256(rc_path),
            "resistance_annotation": sha256(res_path),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=BUILD / "rc")
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_four_channel_output_load_integration.gds")
    parser.add_argument("--log", type=Path, default=BUILD / "rc_magic.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck/precheck_summary.json")
    parser.add_argument(
        "--topology", type=Path,
        default=ROOT / "v3/evidence/four_channel_output_load_integration_gate.json",
    )
    parser.add_argument(
        "--manifest", type=Path,
        default=ROOT / "v3/layout/four_channel_output_load_integration.json",
    )
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "v3/evidence/four_channel_output_load_rc.json",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    topology = json.loads(args.topology.read_text(encoding="utf-8"))
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    log = args.log.read_text(encoding="utf-8", errors="replace")
    cap = manifest["compensation_cap_block"]
    w, l = cap["size_um"]
    wc, lc = w - 0.025, l - 0.025
    calculated_mim_ff = 2.00 * wc * lc + 0.19 * 2.0 * (wc + lc)
    if abs(calculated_mim_ff - cap["typical_model_capacitance_ff"]) > 1e-6:
        raise ValueError("manifest MIM value does not match the foundry typical formula")
    views = {
        "p": analyze(args.work, "p", calculated_mim_ff),
        "n": analyze(args.work, "n", 0.0),
    }
    metrics = {
        "minimum_route_resistance_mismatch_percent": mismatch(
            views["p"]["minimum_pad_to_mixer_resistance_ohm"],
            views["n"]["minimum_pad_to_mixer_resistance_ohm"],
        ),
        "maximum_route_resistance_mismatch_percent": mismatch(
            views["p"]["maximum_pad_to_mixer_resistance_ohm"],
            views["n"]["maximum_pad_to_mixer_resistance_ohm"],
        ),
        "mean_route_resistance_mismatch_percent": mismatch(
            views["p"]["mean_pad_to_mixer_resistance_ohm"],
            views["n"]["mean_pad_to_mixer_resistance_ohm"],
        ),
        "total_effective_capacitance_mismatch_percent_typical": mismatch(
            views["p"]["total_effective_capacitance_ff_typical"],
            views["n"]["total_effective_capacitance_ff_typical"],
        ),
        "estimated_tau_mismatch_percent_typical": mismatch(
            views["p"]["estimated_load_plus_mean_route_tau_ns"],
            views["n"]["estimated_load_plus_mean_route_tau_ns"],
        ),
        "estimated_5mhz_differential_gain_error_db": abs(
            views["p"]["estimated_5mhz_gain_loss_db"]
            - views["n"]["estimated_5mhz_gain_loss_db"]
        ),
        "estimated_5mhz_differential_phase_error_deg": abs(
            views["p"]["estimated_5mhz_phase_lag_deg"]
            - views["n"]["estimated_5mhz_phase_lag_deg"]
        ),
    }
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed = re.compile(
        r'^(?:Warning: Calma reading is not undoable!  I hope that.s OK\.|'
        r'Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.)$'
    )
    unexpected = [line for line in warnings if not allowed.fullmatch(line)]
    checks = {
        "magic_drc_zero_both_views": all(
            marker(log, f"V3_FOUR_CHANNEL_OUTPUT_RC_DRC_COUNT_{polarity}") == 0
            for polarity in ("p", "n")
        ),
        "exactly_36_flattened_qualified_dummy_notices_both_views": all(
            marker(log, f"V3_FOUR_CHANNEL_OUTPUT_RC_EXTRACTION_FEEDBACK_COUNT_{polarity}") == 36
            for polarity in ("p", "n")
        ),
        "magic_outputs_complete": log.count("exttospice finished.") >= 4,
        "only_classified_magic_warnings": not unexpected,
        "base_views_are_resistance_free": all(view["base"]["resistors"] == 0 for view in views.values()),
        "distributed_resistors_present": all(view["distributed_rc"]["resistors"] > 0 for view in views.values()),
        "capacitance_present_both_views": all(
            view["base"]["capacitors"] > 0 and view["distributed_rc"]["capacitors"] > 0
            for view in views.values()
        ),
        "all_1315_devices_preserved": all(
            view["base"]["devices"] == 1315 and view["distributed_rc"]["devices"] == 1315
            for view in views.values()
        ),
        "exactly_120_mixers_and_one_load_per_output": all(
            view["mixer_terminal_count"] == 120 and view["output_load_terminal_count"] == 1
            for view in views.values()
        ),
        "compensation_mim_reaches_p_only": (
            views["p"]["compensation_mim_terminal_count"] == 1
            and views["n"]["compensation_mim_terminal_count"] == 0
        ),
        "minimum_route_resistance_mismatch_below_1_percent": metrics["minimum_route_resistance_mismatch_percent"] < 1.0,
        "maximum_route_resistance_mismatch_below_1_percent": metrics["maximum_route_resistance_mismatch_percent"] < 1.0,
        "mean_route_resistance_mismatch_below_1_percent": metrics["mean_route_resistance_mismatch_percent"] < 1.0,
        "total_effective_capacitance_mismatch_below_1_percent": metrics["total_effective_capacitance_mismatch_percent_typical"] < 1.0,
        "estimated_tau_mismatch_below_1_percent": metrics["estimated_tau_mismatch_percent_typical"] < 1.0,
        "estimated_output_poles_above_100mhz": all(view["estimated_output_pole_mhz"] > 100.0 for view in views.values()),
        "estimated_5mhz_differential_phase_error_below_0p1deg": metrics["estimated_5mhz_differential_phase_error_deg"] < 0.1,
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_is_for_exact_gds": precheck["gds_sha256"] == sha256(args.gds),
        "topology_gate_passes_for_exact_gds": (
            topology["status"] == "pass" and topology["gds_sha256"] == sha256(args.gds)
        ),
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "both complete pad-to-120-mixer output networks with distributed conductor R/C and intentional P-side MIM compensation",
        "checks": checks,
        "views": views,
        "differential_metrics": metrics,
        "uncompensated_baseline": {
            "p_extracted_capacitance_ff": manifest["matching"]["uncompensated_extracted_capacitance_ff"]["p"],
            "n_extracted_capacitance_ff": manifest["matching"]["uncompensated_extracted_capacitance_ff"]["n"],
            "mismatch_percent": manifest["matching"]["uncompensated_capacitance_mismatch_percent"],
            "status": "rejected and replaced by the hash-bound 4.20 um P-side MIM",
        },
        "model_assumptions": {
            "typical_mim_area_coefficient_ff_per_um2": 2.00,
            "typical_mim_perimeter_coefficient_ff_per_um": 0.19,
            "m3_dimension_adjustment_um": -0.025,
            "output_load_ohm": LOAD_OHM,
            "signal_frequency_hz": SIGNAL_HZ,
            "note": "geometric RC is extracted at the installed PDK nominal deck; final powered-top PVT transient/noise remains a later gate",
        },
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "unexpected_magic_warnings": unexpected,
        "sha256": {
            "magic_log": sha256(args.log),
            "precheck_summary": sha256(args.precheck),
            "topology_gate": sha256(args.topology),
            "manifest": sha256(args.manifest),
            "extractor": sha256(ROOT / "v3/layout/extract_four_channel_output_load_rc.tcl"),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "freeze this output stage, then close shared power, static control, and four analog-input pad escapes before powered-top PVT/noise simulation",
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
