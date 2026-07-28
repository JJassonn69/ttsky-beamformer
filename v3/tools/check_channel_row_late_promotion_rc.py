#!/usr/bin/env python3
"""Audit distributed analog-gate RC of the V3 late-promotion row."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

from check_tail_reference_rc import (  # noqa: E402
    component,
    effective_resistance,
    parse_rnodes,
    parse_spice,
    resistor_graph,
)


BUILD = ROOT / "build/v3/channel_architecture_row_late_promotion"
TOKENS = ("sig", "ref", "vbias")
ROOT_COORDINATES = {
    "sig": (6488, 9220),
    "vbias": (6628, 9220),
    "ref": (6768, 9220),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(log: str, name: str) -> int | None:
    values = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def mismatch_percent(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return 100.0 * (max(values) - min(values)) / mean


def analyze(work: Path, token: str) -> dict[str, object]:
    base_path = work / f"late_row_{token}_base.spice"
    rc_path = work / f"late_row_{token}_rc.spice"
    res_path = work / f"v3_channel_architecture_row_late_rc_{token}.res.ext"
    base = parse_spice(base_path)
    rc = parse_spice(rc_path)
    graph = resistor_graph(rc["R"])
    rnodes = parse_rnodes(res_path)
    candidates = sorted({
        node for node in rnodes.get(ROOT_COORDINATES[token], []) if node in graph
    })
    if not candidates:
        raise ValueError(f"{token} has no resistor root at {ROOT_COORDINATES[token]}")
    root = next((node for node in candidates if node.endswith("#")), candidates[0])
    connected = component(graph, root)
    gates = sorted({fields[2] for fields in rc["X"] if fields[2] in connected})
    if len(gates) != 3:
        raise ValueError(f"{token} reaches {len(gates)} transistor gates, expected 3")
    node_coordinates = {
        node: point for point, nodes in rnodes.items() for node in nodes if node in gates
    }
    missing = sorted(set(gates) - set(node_coordinates))
    if missing:
        raise ValueError(f"{token} gates missing RC coordinates: {missing}")
    gates.sort(key=lambda node: node_coordinates[node][0])
    resistances = [effective_resistance(graph, root, gate) for gate in gates]
    return {
        "root_coordinate_internal": list(ROOT_COORDINATES[token]),
        "root_node": root,
        "gate_nodes_left_to_right": gates,
        "gate_coordinates_internal": [list(node_coordinates[node]) for node in gates],
        "root_to_gate_ohm_left_to_right": resistances,
        "within_net_spread_percent": mismatch_percent(resistances),
        "base_counts": {
            "resistors": len(base["R"]), "capacitors": len(base["C"]), "devices": len(base["X"]),
        },
        "rc_counts": {
            "resistors": len(rc["R"]), "capacitors": len(rc["C"]), "devices": len(rc["X"]),
        },
        "sha256": {
            "base_spice": sha256(base_path),
            "rc_spice": sha256(rc_path),
            "res_ext": sha256(res_path),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=BUILD / "rc")
    parser.add_argument("--log", type=Path, default=BUILD / "rc/magic_rc.log")
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_channel_architecture_row_late_promotion.gds")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument("--output", type=Path, default=BUILD / "distributed_rc_audit.json")
    args = parser.parse_args()
    log = args.log.read_text(encoding="utf-8", errors="replace")
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    views = {token: analyze(args.work, token) for token in TOKENS}
    pair_mismatch = [
        100.0 * abs(sig - ref) / ((sig + ref) / 2.0)
        for sig, ref in zip(
            views["sig"]["root_to_gate_ohm_left_to_right"],
            views["ref"]["root_to_gate_ohm_left_to_right"],
        )
    ]
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed = re.compile(
        r'^(?:Warning: Calma reading is not undoable!  I hope that.s OK\.|'
        r'Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.)$'
    )
    unexpected = [line for line in warnings if not allowed.fullmatch(line)]
    checks = {
        "magic_drc_zero_all_views": all(
            marker(log, f"V3_CHANNEL_ROW_LATE_RC_DRC_COUNT_{token}") == 0 for token in TOKENS
        ),
        "magic_extraction_feedback_zero_all_views": all(
            marker(log, f"V3_CHANNEL_ROW_LATE_RC_EXTRACTION_FEEDBACK_COUNT_{token}") == 0
            for token in TOKENS
        ),
        "only_classified_magic_warnings": not unexpected,
        "distributed_resistors_present": all(view["rc_counts"]["resistors"] > 0 for view in views.values()),
        "twenty_one_devices_preserved": all(view["rc_counts"]["devices"] == 21 for view in views.values()),
        "three_gate_fanout_each": all(len(view["gate_nodes_left_to_right"]) == 3 for view in views.values()),
        "maximum_gate_path_below_500_ohm": max(
            value for view in views.values() for value in view["root_to_gate_ohm_left_to_right"]
        ) < 500.0,
        "sig_ref_per_unit_resistance_mismatch_below_1_percent": max(pair_mismatch) < 1.0,
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_matches_exact_gds": precheck["gds_sha256"] == sha256(args.gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "three-unit late-promotion SIG/REF/VBIAS distributed conductor RC",
        "checks": checks,
        "views": views,
        "sig_ref_per_unit_resistance_mismatch_percent_left_to_right": pair_mismatch,
        "maximum_sig_ref_pair_mismatch_percent": max(pair_mismatch),
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "unexpected_magic_warnings": unexpected,
        "sha256": {
            "magic_log": sha256(args.log),
            "precheck": sha256(args.precheck),
            "extractor": sha256(ROOT / "v3/layout/extract_channel_row_late_promotion_rc.tcl"),
            "auditor": sha256(Path(__file__)),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
