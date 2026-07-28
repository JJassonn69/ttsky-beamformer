#!/usr/bin/env python3
"""Audit distributed RC from each selector output through its analog tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from check_channel_phase_tree_rc import (
    EXPECTED_GATE_COUNTS,
    MAX_EDGE_SKEW_PS,
    TOKENS,
    analyze,
    marker,
)


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/channel_selector_late_promotion"
DEFAULT_OUTPUT = ROOT / "v3/evidence/channel_selector_late_promotion_rc.json"
ROOT_COORDINATES = {
    "g1_lon": (5444, 28684), "g1_lop": (5588, 28684),
    "g2_lon": (5732, 28684), "g2_lop": (5876, 28684),
    "g4_lon": (6020, 28684), "g4_lop": (6164, 28684),
    "g8_lon": (6308, 28684), "g8_lop": (6452, 28684),
}
TOP_PREFIX = "v3_channel_selector_late_promotion_rc"
MARKER_PREFIX = "V3_CHANNEL_SELECTOR_LATE_RC"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=BUILD / "rc")
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_channel_selector_late_promotion.gds")
    parser.add_argument("--log", type=Path, default=BUILD / "rc/magic_rc.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument(
        "--topology", type=Path,
        default=ROOT / "v3/evidence/channel_selector_late_promotion_gate.json",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    log = args.log.read_text(encoding="utf-8", errors="replace")
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    topology = json.loads(args.topology.read_text(encoding="utf-8"))
    views = {
        token: analyze(args.work, token, ROOT_COORDINATES, TOP_PREFIX)
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
    gds_hash = sha256(args.gds)
    checks = {
        "magic_drc_zero_all_views": all(
            marker(log, f"{MARKER_PREFIX}_DRC_COUNT_{token}") == 0 for token in TOKENS
        ),
        "exactly_nine_grounded_dummy_notices_all_views": all(
            marker(log, f"{MARKER_PREFIX}_EXTRACTION_FEEDBACK_COUNT_{token}") == 9
            for token in TOKENS
        ),
        "magic_outputs_complete": log.count("exttospice finished.") >= 2 * len(TOKENS),
        "only_classified_magic_warnings": not unexpected,
        "base_views_are_resistance_free": all(item["resistors"] == 0 for item in base_counts),
        "distributed_resistors_present": all(item["resistors"] > 0 for item in rc_counts),
        "capacitance_present_all_views": all(item["capacitors"] > 0 for item in base_counts + rc_counts),
        "all_323_devices_preserved": all(item["devices"] == 323 for item in base_counts + rc_counts),
        "exact_switch_gate_population_all_views": all(
            views[token]["switch_gate_count"] == EXPECTED_GATE_COUNTS[token]
            for token in TOKENS
        ),
        "edge_skew_bound_below_100ps_all_views": all(
            views[token]["worst_case_edge_delay_and_skew_bound_ps"] < MAX_EDGE_SKEW_PS
            for token in TOKENS
        ),
        "direct_gds_precheck_zero": (
            precheck["status"] == "pass"
            and all(item["markers"] == 0 for item in precheck["checks"].values())
        ),
        "precheck_is_for_exact_gds": precheck["gds_sha256"] == gds_hash,
        "integrated_topology_gate_passes": topology["status"] == "pass",
        "topology_is_for_exact_gds": topology["gds_sha256"] == gds_hash,
    }
    worst_token = max(
        TOKENS, key=lambda token: views[token]["worst_case_edge_delay_and_skew_bound_ps"]
    )
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "eight complete selector-output to analog-switch-gate paths, including the new matched joins and frozen phase trees",
        "checks": checks,
        "views": views,
        "maximum_allowed_edge_skew_ps": MAX_EDGE_SKEW_PS,
        "worst_case_tree": worst_token,
        "worst_case_edge_delay_and_skew_bound_ps": views[worst_token]["worst_case_edge_delay_and_skew_bound_ps"],
        "bound_method": "0.69 * maximum extracted selector-output-to-gate resistance * (all incident extracted C + 10 fF per driven switch gate); conservative skew range starts at zero",
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": gds_hash,
        "unexpected_magic_warnings": unexpected,
        "sha256": {
            "magic_log": sha256(args.log),
            "precheck_summary": sha256(args.precheck),
            "topology_gate": sha256(args.topology),
            "extractor": sha256(ROOT / "v3/layout/extract_channel_selector_late_promotion_rc.tcl"),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "flattened visual review and top-level port/pin planning",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
