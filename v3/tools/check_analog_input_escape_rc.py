#!/usr/bin/env python3
"""Audit distributed conductor RC and four-channel analog-input matching."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
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


BUILD = ROOT / "build/v3/analog_input_escapes"
COORDINATES = {
    "i0": (30452, 100),
    "i1": (26588, 100),
    "i2": (22724, 100),
    "i3": (18860, 100),
}
SIGNAL_HZ = 5.0e6
DIAGNOSTIC_HZ = 200.0e6
SOURCE_OHM = 1000.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(text: str, name: str) -> int | None:
    values = re.findall(rf"^{re.escape(name)}=(\d+)\s*$", text, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def counts(records: dict[str, list[list[str]]]) -> dict[str, int]:
    return {
        "resistors": len(records["R"]),
        "capacitors": len(records["C"]),
        "devices": len(records["X"]),
    }


def model_index(fields: list[str]) -> int:
    return next(index for index, value in enumerate(fields) if value.startswith("sky130_"))


def analyze(work: Path, token: str) -> dict[str, Any]:
    base_path = work / f"input_{token}_base.spice"
    rc_path = work / f"input_{token}_rc.spice"
    res_path = work / f"v3_analog_input_rc_{token}.res.ext"
    base = parse_spice(base_path)
    rc = parse_spice(rc_path)
    graph = resistor_graph(rc["R"])
    rnodes = parse_rnodes(res_path)
    candidates = sorted({
        node for node in rnodes.get(COORDINATES[token], []) if node in graph
    })
    if not candidates:
        raise ValueError(f"{token} has no resistor node at {COORDINATES[token]}")
    root = next((node for node in candidates if node.endswith("#")), candidates[0])
    connected = component(graph, root)

    touching: dict[str, list[list[str]]] = defaultdict(list)
    for fields in rc["X"]:
        index = model_index(fields)
        hits = sorted(set(fields[1:index]) & connected)
        if hits:
            touching[fields[index]].append(hits)
    gm_hits = touching.get("sky130_fd_pr__nfet_01v8", [])
    bias_hits = touching.get("sky130_fd_pr__res_xhigh_po_0p35", [])
    if any(len(hits) != 1 for hits in gm_hits):
        raise ValueError(f"{token} touches a gm device more than once")
    gm_resistances = [effective_resistance(graph, root, hits[0]) for hits in gm_hits]
    extracted_external_cap_f = sum(
        abs(spice_number(fields[3]))
        for fields in rc["C"]
        if (fields[1] in connected) != (fields[2] in connected)
    )
    return {
        "root_coordinate_internal": list(COORDINATES[token]),
        "root_node": root,
        "root_candidates": candidates,
        "connected_resistor_nodes": len(connected),
        "gm_terminal_count": len(gm_hits),
        "input_bias_resistor_terminal_count": len(bias_hits),
        "minimum_pad_to_gm_resistance_ohm": min(gm_resistances),
        "maximum_pad_to_gm_resistance_ohm": max(gm_resistances),
        "mean_pad_to_gm_resistance_ohm": sum(gm_resistances) / len(gm_resistances),
        "within_channel_resistance_spread_ohm": max(gm_resistances) - min(gm_resistances),
        "sorted_pad_to_gm_resistance_ohm": sorted(gm_resistances),
        "extracted_external_capacitance_ff": extracted_external_cap_f * 1e15,
        "base": counts(base),
        "distributed_rc": counts(rc),
        "sha256": {
            "base_spice": sha256(base_path),
            "distributed_rc_spice": sha256(rc_path),
            "resistance_annotation": sha256(res_path),
        },
    }


def mismatch_percent(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return 100.0 * (max(values) - min(values)) / mean


def loading_spread(cap_ff: list[float], frequency_hz: float, source_ohm: float) -> dict[str, float]:
    gains: list[float] = []
    phases: list[float] = []
    for capacitance_ff in cap_ff:
        ratio = 2.0 * math.pi * frequency_hz * source_ohm * capacitance_ff * 1e-15
        gains.append(-10.0 * math.log10(1.0 + ratio * ratio))
        phases.append(-math.degrees(math.atan(ratio)))
    return {
        "frequency_hz": frequency_hz,
        "source_resistance_ohm": source_ohm,
        "worst_gain_loss_db": abs(min(gains)),
        "channel_gain_spread_db": max(gains) - min(gains),
        "worst_phase_lag_deg": abs(min(phases)),
        "channel_phase_spread_deg": max(phases) - min(phases),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=BUILD / "rc")
    parser.add_argument("--gds", type=Path, default=BUILD / "direct/v3_four_channel_analog_inputs.gds")
    parser.add_argument("--log", type=Path, default=BUILD / "rc_magic.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck/precheck_summary.json")
    parser.add_argument("--topology", type=Path, default=BUILD / "input_topology_audit.json")
    parser.add_argument("--plan", type=Path, default=ROOT / "v3/layout/analog_input_escape_plan.json")
    parser.add_argument("--output", type=Path, default=BUILD / "input_rc_audit.json")
    args = parser.parse_args()

    views = {token: analyze(args.work, token) for token in COORDINATES}
    capacitances = [view["extracted_external_capacitance_ff"] for view in views.values()]
    minimum_resistances = [view["minimum_pad_to_gm_resistance_ohm"] for view in views.values()]
    maximum_resistances = [view["maximum_pad_to_gm_resistance_ohm"] for view in views.values()]
    mean_resistances = [view["mean_pad_to_gm_resistance_ohm"] for view in views.values()]
    resistance_vectors = [view["sorted_pad_to_gm_resistance_ohm"] for view in views.values()]
    metrics = {
        "minimum_route_resistance_mismatch_percent": mismatch_percent(minimum_resistances),
        "maximum_route_resistance_mismatch_percent": mismatch_percent(maximum_resistances),
        "mean_route_resistance_mismatch_percent": mismatch_percent(mean_resistances),
        "external_capacitance_span_percent": mismatch_percent(capacitances),
        "external_capacitance_min_ff": min(capacitances),
        "external_capacitance_max_ff": max(capacitances),
        "external_capacitance_mean_ff": sum(capacitances) / len(capacitances),
        "intended_5mhz_1kohm_loading": loading_spread(capacitances, SIGNAL_HZ, SOURCE_OHM),
        "diagnostic_200mhz_1kohm_loading": loading_spread(capacitances, DIAGNOSTIC_HZ, SOURCE_OHM),
    }

    log = args.log.read_text(encoding="utf-8", errors="replace")
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed = re.compile(
        r'^(?:Warning: Calma reading is not undoable!  I hope that.s OK\.|'
        r'Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.)$'
    )
    unexpected = [line for line in warnings if not allowed.fullmatch(line)]
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    topology = json.loads(args.topology.read_text(encoding="utf-8"))
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    checks = {
        "magic_drc_zero_all_four_views": all(
            marker(log, f"V3_ANALOG_INPUT_RC_DRC_COUNT_{token}") == 0
            for token in COORDINATES
        ),
        "exactly_36_flattened_qualified_dummy_notices_all_four_views": all(
            marker(log, f"V3_ANALOG_INPUT_RC_EXTRACTION_FEEDBACK_COUNT_{token}") == 36
            for token in COORDINATES
        ),
        "magic_outputs_complete": log.count("exttospice finished.") >= 8,
        "only_classified_magic_warnings": not unexpected,
        "base_views_are_resistance_free": all(view["base"]["resistors"] == 0 for view in views.values()),
        "distributed_resistors_present": all(view["distributed_rc"]["resistors"] > 0 for view in views.values()),
        "capacitance_present_all_views": all(
            view["base"]["capacitors"] > 0 and view["distributed_rc"]["capacitors"] > 0
            for view in views.values()
        ),
        "all_6037_devices_preserved": all(
            view["base"]["devices"] == 6037 and view["distributed_rc"]["devices"] == 6037
            for view in views.values()
        ),
        "exactly_15_gm_and_one_bias_resistor_per_input": all(
            view["gm_terminal_count"] == 15 and view["input_bias_resistor_terminal_count"] == 1
            for view in views.values()
        ),
        "all_four_resistance_vectors_are_identical": all(
            all(abs(a - b) < 1e-9 for a, b in zip(resistance_vectors[0], vector))
            for vector in resistance_vectors[1:]
        ),
        "mean_route_resistance_mismatch_below_0p01_percent": metrics["mean_route_resistance_mismatch_percent"] < 0.01,
        "external_capacitance_span_below_2_percent": metrics["external_capacitance_span_percent"] < 2.0,
        "estimated_5mhz_gain_spread_below_0p001db_at_1kohm": metrics["intended_5mhz_1kohm_loading"]["channel_gain_spread_db"] < 0.001,
        "estimated_5mhz_phase_spread_below_0p01deg_at_1kohm": metrics["intended_5mhz_1kohm_loading"]["channel_phase_spread_deg"] < 0.01,
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_is_for_exact_gds": precheck["gds_sha256"] == sha256(args.gds),
        "topology_gate_passes_for_exact_gds": (
            topology["status"] == "pass"
            and topology["artifact_sha256"]["gds"] == sha256(args.gds)
        ),
        "plan_is_exact_translation": plan["policy"]["all_four_routes_are_exact_translations"],
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "four complete TinyTapeout-pad-to-15-gm-gate analog-input networks with distributed conductor R/C and channel loading comparison",
        "checks": checks,
        "views": views,
        "matching_metrics": metrics,
        "model_assumptions": {
            "intended_signal_frequency_hz": SIGNAL_HZ,
            "bounded_source_resistance_ohm": SOURCE_OHM,
            "diagnostic_frequency_hz": DIAGNOSTIC_HZ,
            "note": "Magic geometric capacitance excludes equal transistor intrinsic gate capacitance and package/board parasitics; those common terms reduce the relative on-chip mismatch but must be added in final board-level simulation.",
        },
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "unexpected_magic_warnings": unexpected,
        "sha256": {
            "magic_log": sha256(args.log),
            "precheck_summary": sha256(args.precheck),
            "topology_audit": sha256(args.topology),
            "plan": sha256(args.plan),
            "extractor": sha256(ROOT / "v3/layout/extract_analog_input_escape_rc.tcl"),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "freeze the four matched analog inputs, then package the exact TinyTapeout top-level pins and run the full submission precheck and post-layout powered simulations",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
