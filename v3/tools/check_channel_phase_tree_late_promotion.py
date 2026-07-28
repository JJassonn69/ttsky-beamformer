#!/usr/bin/env python3
"""Audit the exact 15-cell late-promotion channel and its eight phase trees."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from check_channel_architecture_service import diffusions, markers, parse_mos


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/channel_phase_tree_late_promotion"
DEFAULT_OUTPUT = ROOT / "v3/evidence/channel_phase_tree_late_promotion_gate.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(first: float, second: float) -> bool:
    return math.isclose(first, second, rel_tol=0.0, abs_tol=1e-9)


def audit(devices: list[dict[str, object]]) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    tails = [item for item in devices if close(float(item["w"]), 5.07) and close(float(item["l"]), 1.0)]
    gms = [item for item in devices if close(float(item["w"]), 0.84) and close(float(item["l"]), 0.6)]
    switches = [item for item in devices if close(float(item["w"]), 0.65) and close(float(item["l"]), 0.15)]
    if (len(tails), len(gms), len(switches)) != (15, 30, 60):
        return [f"device classes changed: {len(tails)}/{len(gms)}/{len(switches)}"], {}
    if any(item["b"] != "VGND" for item in devices):
        errors.append("one or more MOS bodies are not tied to VGND")
    if Counter(str(item["g"]) for item in tails) != {"vbias": 15}:
        errors.append("tail gates are not fifteen shared vbias devices")
    if Counter(str(item["g"]) for item in gms) != {"sig": 15, "ref": 15}:
        errors.append("GM gates are not fifteen shared sig/ref pairs")

    expected_switch_gates = {
        f"g{group}_{polarity}": unit_count * 2
        for group, unit_count in ((1, 1), (2, 2), (4, 4), (8, 8))
        for polarity in ("lon", "lop")
    }
    observed_switch_gates = Counter(str(item["g"]) for item in switches)
    if observed_switch_gates != expected_switch_gates:
        errors.append(f"phase-gate populations changed: {dict(sorted(observed_switch_gates.items()))}")

    tail_nodes: list[str] = []
    gm_private_nodes: list[str] = []
    units_by_group: Counter[int] = Counter()
    for tail in tails:
        private = diffusions(tail) - {"VGND"}
        if "VGND" not in diffusions(tail) or len(private) != 1:
            errors.append(f"{tail['name']} is not between one private node and VGND")
            continue
        tail_node = next(iter(private))
        tail_nodes.append(tail_node)
        pair = [item for item in gms if tail_node in diffusions(item)]
        by_gate = {str(item["g"]): item for item in pair}
        if len(pair) != 2 or set(by_gate) != {"sig", "ref"}:
            errors.append(f"tail {tail_node} does not own one sig/ref GM pair")
            continue
        gm_nodes = {}
        for role, item in by_gate.items():
            other = diffusions(item) - {tail_node}
            if len(other) != 1:
                errors.append(f"tail {tail_node} has ambiguous {role} GM output")
            else:
                gm_nodes[role] = next(iter(other))
        if set(gm_nodes) != {"sig", "ref"}:
            continue
        gm_private_nodes.extend(gm_nodes.values())
        attached = [
            item for item in switches
            if any(node in diffusions(item) for node in gm_nodes.values())
        ]
        groups = {
            int(match.group(1))
            for item in attached
            if (match := re.fullmatch(r"g([1248])_(?:lon|lop)", str(item["g"])))
        }
        if len(attached) != 4 or len(groups) != 1:
            errors.append(f"tail {tail_node} does not own four switches from one group: {sorted(groups)}")
            continue
        group = next(iter(groups))
        units_by_group[group] += 1
        expected = {
            f"g{group}_lop": [
                {gm_nodes["sig"], "row_outp"}, {gm_nodes["ref"], "row_outn"},
            ],
            f"g{group}_lon": [
                {gm_nodes["sig"], "row_outn"}, {gm_nodes["ref"], "row_outp"},
            ],
        }
        for gate, wanted in expected.items():
            observed = [diffusions(item) for item in attached if item["g"] == gate]
            if len(observed) != 2 or any(value not in observed for value in wanted):
                errors.append(
                    f"tail {tail_node} {gate} topology changed: "
                    f"expected {[sorted(value) for value in wanted]}, got {[sorted(value) for value in observed]}"
                )

    if len(tail_nodes) != 15 or len(set(tail_nodes)) != 15:
        errors.append("tail nodes are not fifteen private nodes")
    if len(gm_private_nodes) != 30 or len(set(gm_private_nodes)) != 30:
        errors.append("a GM output node is shared between cells")
    if units_by_group != {1: 1, 2: 2, 4: 4, 8: 8}:
        errors.append(f"cell group ownership changed: {dict(sorted(units_by_group.items()))}")
    return errors, {
        "device_classes": {"tail": len(tails), "gm": len(gms), "switch": len(switches)},
        "switch_gate_counts": dict(sorted(observed_switch_gates.items())),
        "units_by_group": {str(key): value for key, value in sorted(units_by_group.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    spice = BUILD / "v3_channel_phase_tree_late_promotion_flat.spice"
    gds = BUILD / "v3_channel_phase_tree_late_promotion.gds"
    marker_path = BUILD / "physical_markers.txt"
    precheck_path = BUILD / "precheck_summary.json"
    log_path = BUILD / "magic_extract.log"
    matrix_path = ROOT / "v3/layout/channel_matrix_late_promotion.json"
    trees_path = ROOT / "v3/layout/group_phase_trees_late_promotion.json"
    devices = parse_mos(spice)
    topology_errors, topology = audit(devices)
    physical = markers(marker_path)
    expected_physical = {
        "V3_CHANNEL_PHASE_TREE_LATE_DRC_COUNT": 0,
        "V3_CHANNEL_PHASE_TREE_LATE_EXTRACTION_FEEDBACK_COUNT": 0,
        "V3_CHANNEL_PHASE_TREE_LATE_GDS_FEEDBACK_COUNT": 0,
    }
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    log = log_path.read_text(encoding="utf-8", errors="replace")
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed = re.compile(r'^Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.$')
    unexpected_warnings = [line for line in warnings if not allowed.fullmatch(line)]
    checks = {
        "magic_and_export_markers_zero": physical == expected_physical,
        "only_classified_magic_warnings": not unexpected_warnings,
        "exactly_one_hundred_five_nmos": len(devices) == 105,
        "all_fifteen_cell_topologies_exact": not topology_errors,
        "all_eight_phase_gate_populations_exact": topology.get("switch_gate_counts") == {
            "g1_lon": 2, "g1_lop": 2, "g2_lon": 4, "g2_lop": 4,
            "g4_lon": 8, "g4_lop": 8, "g8_lon": 16, "g8_lop": 16,
        },
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_matches_exact_gds": precheck["gds_sha256"] == sha256(gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact 15-cell late-promotion service channel plus eight global 1/2/4/8 LON/LOP phase trees",
        "checks": checks,
        "physical_markers": physical,
        "topology": topology,
        "topology_errors": topology_errors,
        "unexpected_magic_warnings": unexpected_warnings,
        "gds": str(gds.relative_to(ROOT)),
        "gds_sha256": sha256(gds),
        "sha256": {
            "spice": sha256(spice), "magic_log": sha256(log_path),
            "precheck": sha256(precheck_path), "matrix": sha256(matrix_path),
            "phase_trees": sha256(trees_path),
            "planner": sha256(ROOT / "v3/tools/plan_group_phase_trees_late_promotion.py"),
            "generator": sha256(ROOT / "v3/tools/generate_channel_phase_tree_late_promotion_pilot.py"),
            "checker": sha256(Path(__file__)),
        },
        "next_gate": "rendered visual review, then edge-dummy/input-bias/selector integration and distributed-RC extraction",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
