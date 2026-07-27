#!/usr/bin/env python3
"""Audit distributed RC, load, and conservative edge skew of eight phase trees."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3" / "tools"))

from check_tail_reference_rc import (  # noqa: E402
    component,
    effective_resistance,
    parse_rnodes,
    parse_spice,
    resistor_graph,
    spice_number,
)


BUILD = ROOT / "build" / "v3" / "channel_phase_tree_pilot"
TOKENS = (
    "g1_lop", "g1_lon", "g2_lon", "g2_lop",
    "g4_lon", "g4_lop", "g8_lop", "g8_lon",
)
ROOT_COORDINATES = {
    "g1_lop": (4974, 22610),
    "g1_lon": (6174, 22610),
    "g2_lon": (7694, 22610),
    "g2_lop": (7824, 22610),
    "g4_lon": (7434, 22610),
    "g4_lop": (7564, 22610),
    "g8_lop": (7304, 22610),
    "g8_lon": (7164, 22610),
}
EXPECTED_GATE_COUNTS = {
    f"g{group}_{polarity}": count * 2
    for group, count in ((1, 1), (2, 2), (4, 4), (8, 8))
    for polarity in ("lop", "lon")
}

# A 0.65 x 0.15 um switch has far below 10 fF intrinsic gate capacitance in
# SKY130.  Using 10 fF per gate deliberately over-bounds unreported intrinsic
# model capacitance while extracted interconnect/coupling C is counted exactly.
INTRINSIC_GATE_CAP_BOUND_F = 10e-15
MAX_EDGE_SKEW_PS = 100.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(log: str, name: str) -> int | None:
    values = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def counts(records: dict[str, list[list[str]]]) -> dict[str, int]:
    return {"resistors": len(records["R"]), "capacitors": len(records["C"]), "devices": len(records["X"])}


def analyze(
    work: Path, token: str,
    root_coordinates: dict[str, tuple[int, int]] = ROOT_COORDINATES,
    top_prefix: str = "v3_channel_phase_tree_pilot_rc",
) -> dict[str, object]:
    base_path = work / f"phase_tree_{token}_base.spice"
    rc_path = work / f"phase_tree_{token}_rc.spice"
    res_path = work / f"{top_prefix}_{token}.res.ext"
    base = parse_spice(base_path)
    rc = parse_spice(rc_path)
    graph = resistor_graph(rc["R"])
    rnodes = parse_rnodes(res_path)
    candidates = sorted({node for node in rnodes.get(root_coordinates[token], []) if node in graph})
    if not candidates:
        raise ValueError(f"{token} has no resistor node at {root_coordinates[token]}")
    root = next((node for node in candidates if node.endswith("#")), candidates[0])
    connected = component(graph, root)
    gates = sorted({fields[2] for fields in rc["X"] if fields[2] in connected})
    expected = EXPECTED_GATE_COUNTS[token]
    if len(gates) != expected:
        raise ValueError(f"{token} reaches {len(gates)} switch gates, expected {expected}")
    resistances = {gate: effective_resistance(graph, root, gate) for gate in gates}
    incident_cap = sum(
        abs(spice_number(fields[3]))
        for fields in rc["C"]
        if fields[1] in connected or fields[2] in connected
    )
    bounded_cap = incident_cap + expected * INTRINSIC_GATE_CAP_BOUND_F
    maximum_resistance = max(resistances.values())
    minimum_resistance = min(resistances.values())
    # Every passive-tree arrival lies between zero and the slowest first-order
    # bound; therefore this also upper-bounds within-tree root-to-leaf skew.
    delay_bound_ps = 0.69 * maximum_resistance * bounded_cap * 1e12
    return {
        "root_coordinate_internal": list(root_coordinates[token]),
        "root_node": root,
        "root_candidates": candidates,
        "connected_resistor_nodes": len(connected),
        "switch_gate_nodes": gates,
        "switch_gate_count": len(gates),
        "root_to_gate_ohm": resistances,
        "minimum_root_to_gate_ohm": minimum_resistance,
        "maximum_root_to_gate_ohm": maximum_resistance,
        "root_to_gate_spread_ohm": maximum_resistance - minimum_resistance,
        "extracted_incident_capacitance_ff": incident_cap * 1e15,
        "intrinsic_gate_capacitance_bound_ff_per_gate": INTRINSIC_GATE_CAP_BOUND_F * 1e15,
        "bounded_total_tree_capacitance_ff": bounded_cap * 1e15,
        "worst_case_edge_delay_and_skew_bound_ps": delay_bound_ps,
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
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_channel_phase_tree_pilot.gds")
    parser.add_argument("--log", type=Path, default=BUILD / "rc" / "magic_rc.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument("--topology", type=Path, default=ROOT / "v3" / "evidence" / "channel_phase_tree_physical_gate.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "v3" / "layout" / "group_phase_trees.json")
    parser.add_argument("--output", type=Path, default=ROOT / "v3" / "evidence" / "channel_phase_tree_rc.json")
    parser.add_argument("--late-promotion", action="store_true")
    args = parser.parse_args()

    marker_prefix = "V3_CHANNEL_PHASE_TREE_RC"
    root_coordinates = ROOT_COORDINATES
    top_prefix = "v3_channel_phase_tree_pilot_rc"
    extractor = ROOT / "v3/layout/extract_channel_phase_tree_rc.tcl"
    if args.late_promotion:
        build = ROOT / "build/v3/channel_phase_tree_late_promotion"
        args.work = build / "rc"
        args.gds = build / "v3_channel_phase_tree_late_promotion.gds"
        args.log = build / "rc/magic_rc.log"
        args.precheck = build / "precheck_summary.json"
        args.topology = ROOT / "v3/evidence/channel_phase_tree_late_promotion_gate.json"
        args.manifest = ROOT / "v3/layout/group_phase_trees_late_promotion.json"
        args.output = ROOT / "v3/evidence/channel_phase_tree_late_promotion_rc.json"
        marker_prefix = "V3_CHANNEL_PHASE_TREE_LATE_RC"
        root_coordinates = {
            "g1_lon": (5444, 26166), "g1_lop": (5588, 26166),
            "g2_lon": (5732, 26166), "g2_lop": (5876, 26166),
            "g4_lon": (6020, 26166), "g4_lop": (6164, 26166),
            "g8_lon": (6308, 26166), "g8_lop": (6452, 26166),
        }
        top_prefix = "v3_channel_phase_tree_late_promotion_rc"
        extractor = ROOT / "v3/layout/extract_channel_phase_tree_late_promotion_rc.tcl"

    log = args.log.read_text(encoding="utf-8", errors="replace")
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    topology = json.loads(args.topology.read_text(encoding="utf-8"))
    views = {
        token: analyze(args.work, token, root_coordinates, top_prefix)
        for token in TOKENS
    }
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed = re.compile(
        r'^(?:Warning: Calma reading is not undoable!  I hope that.s OK\.|'
        r'Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.)$'
    )
    unexpected = [line for line in warnings if not allowed.fullmatch(line)]
    base_counts = [view["base"] for view in views.values()]
    rc_counts = [view["distributed_rc"] for view in views.values()]
    checks = {
        "magic_drc_zero_all_views": all(marker(log, f"{marker_prefix}_DRC_COUNT_{token}") == 0 for token in TOKENS),
        "magic_extraction_feedback_zero_all_views": all(marker(log, f"{marker_prefix}_EXTRACTION_FEEDBACK_COUNT_{token}") == 0 for token in TOKENS),
        "magic_outputs_complete": log.count("exttospice finished.") >= 2 * len(TOKENS),
        "only_classified_magic_warnings": not unexpected,
        "base_views_are_resistance_free": all(item["resistors"] == 0 for item in base_counts),
        "distributed_resistors_present": all(item["resistors"] > 0 for item in rc_counts),
        "capacitance_present_all_views": all(item["capacitors"] > 0 for item in base_counts + rc_counts),
        "one_hundred_five_devices_preserved": all(item["devices"] == 105 for item in base_counts + rc_counts),
        "exact_switch_gate_population_all_views": all(views[token]["switch_gate_count"] == EXPECTED_GATE_COUNTS[token] for token in TOKENS),
        "edge_skew_bound_below_100ps_all_views": all(views[token]["worst_case_edge_delay_and_skew_bound_ps"] < MAX_EDGE_SKEW_PS for token in TOKENS),
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(item["markers"] == 0 for item in precheck["checks"].values()),
        "precheck_is_for_exact_gds": precheck["gds_sha256"] == sha256(args.gds),
        "topology_gate_passes": topology["status"] == "pass",
        "topology_is_for_exact_gds": topology["gds_sha256"] == sha256(args.gds),
    }
    worst_token = max(TOKENS, key=lambda token: views[token]["worst_case_edge_delay_and_skew_bound_ps"])
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "eight exact V3 phase trees: distributed metal resistance/capacitance, switch-gate population, and conservative edge-skew bound",
        "checks": checks,
        "views": views,
        "maximum_allowed_edge_skew_ps": MAX_EDGE_SKEW_PS,
        "worst_case_tree": worst_token,
        "worst_case_edge_delay_and_skew_bound_ps": views[worst_token]["worst_case_edge_delay_and_skew_bound_ps"],
        "bound_method": "0.69 * maximum extracted root-to-gate resistance * (all incident extracted C + 10 fF per driven switch gate); conservative skew range starts at zero",
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "manifest_sha256": sha256(args.manifest),
        "unexpected_magic_warnings": unexpected,
        "sha256": {
            "magic_log": sha256(args.log),
            "precheck_summary": sha256(args.precheck),
            "topology_gate": sha256(args.topology),
            "extractor": sha256(extractor),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "integrate edge dummies and the compact input-bias path without moving the closed tree roots",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
