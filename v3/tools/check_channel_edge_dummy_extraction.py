#!/usr/bin/env python3
"""Audit the exact V3 channel phase trees plus grounded edge dummies."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from check_channel_row_extraction import audit_unit, parse_mos


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "v3" / "channel_edge_dummy_pilot"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "channel_edge_dummy_physical_gate.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(log: str, name: str) -> int | None:
    values = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def close(first: object, second: float) -> bool:
    return math.isclose(float(first), second, rel_tol=0.0, abs_tol=1e-9)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spice", type=Path, default=BUILD / "v3_channel_edge_dummy_pilot_flat.spice")
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_channel_edge_dummy_pilot.gds")
    parser.add_argument("--log", type=Path, default=BUILD / "magic_extract.log")
    parser.add_argument("--feedback", type=Path, default=BUILD / "extraction_feedback.txt")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument("--matrix", type=Path, default=ROOT / "v3" / "layout" / "channel_matrix_placement.json")
    parser.add_argument("--dummies", type=Path, default=ROOT / "v3" / "layout" / "channel_edge_dummies.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    devices = parse_mos(args.spice)
    active = [item for item in devices if {str(item[key]) for key in ("d", "g", "s", "b")} != {"VGND"}]
    inert = [item for item in devices if item not in active]
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    dummy_manifest = json.loads(args.dummies.read_text(encoding="utf-8"))
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    log = args.log.read_text(encoding="utf-8", errors="replace")
    feedback = args.feedback.read_text(encoding="utf-8", errors="replace")

    expected_feedback = re.findall(
        r'feedback add "device missing 1 terminal;\s*connecting remainder to node VGND" pale',
        feedback,
    )
    unit_group = {
        f"u{index:02d}": int(instance["group_weight"])
        for index, instance in enumerate(sorted(
            matrix["matrix"]["instances"],
            key=lambda item: (item["row_top_to_bottom"], item["column_left_to_right"]),
        ))
    }
    by_prefix: dict[str, list[dict[str, object]]] = defaultdict(list)
    phase_counts: Counter[str] = Counter()
    topology_errors: list[str] = []
    for device in active:
        copied = dict(device)
        gate_match = re.match(r"^(u\d{2})_", str(device["g"]))
        output_prefixes = {
            match.group(1)
            for node in (str(device["d"]), str(device["s"]))
            if (match := re.match(r"^(u\d{2})_out[pn]$", node))
        }
        if gate_match:
            prefix = gate_match.group(1)
        elif len(output_prefixes) == 1 and re.fullmatch(r"g[1248]_(?:lop|lon)", str(device["g"])):
            prefix = next(iter(output_prefixes))
            expected_gate = f"g{unit_group[prefix]}_{str(device['g']).rsplit('_', 1)[1]}"
            if device["g"] != expected_gate:
                topology_errors.append(f"{device['name']} uses {device['g']}, expected {expected_gate}")
            phase_counts[str(device["g"])] += 1
            copied["g"] = f"{prefix}_{str(device['g']).rsplit('_', 1)[1]}"
        else:
            topology_errors.append(f"cannot assign active {device['name']}")
            continue
        by_prefix[prefix].append(copied)

    expected_prefixes = [f"u{index:02d}" for index in range(15)]
    for prefix in expected_prefixes:
        errors, _ = audit_unit(prefix, by_prefix[prefix])
        topology_errors.extend(errors)
    expected_phase_counts = {
        f"g{group}_{polarity}": count * 2
        for group, count in ((1, 1), (2, 2), (4, 4), (8, 8))
        for polarity in ("lop", "lon")
    }
    inert_types = Counter(
        "tail_w5p07_l1" if close(item["w"], 5.07) and close(item["l"], 1.0)
        else "switch_w0p65_l0p15" if close(item["w"], 0.65) and close(item["l"], 0.15)
        else "unexpected"
        for item in inert
    )
    checks = {
        "magic_drc_zero": marker(log, "V3_CHANNEL_EDGE_DUMMY_DRC_COUNT") == 0,
        "exactly_nine_classified_dummy_extraction_markers": marker(log, "V3_CHANNEL_EDGE_DUMMY_EXTRACTION_FEEDBACK_COUNT") == 9 and len(expected_feedback) == 9,
        "magic_gds_feedback_zero_after_classification": marker(log, "V3_CHANNEL_EDGE_DUMMY_GDS_FEEDBACK_COUNT") == 0,
        "active_device_count_unchanged": len(active) == 105,
        "active_unit_topology_unchanged": not topology_errors and all(len(by_prefix[prefix]) == 7 for prefix in expected_prefixes),
        "phase_switch_populations_unchanged": dict(sorted(phase_counts.items())) == dict(sorted(expected_phase_counts.items())),
        "nine_grounded_dummy_devices_extract": len(inert) == 9 and inert_types == Counter({"switch_w0p65_l0p15": 6, "tail_w5p07_l1": 3}),
        "dummy_manifest_matches_extraction": len(dummy_manifest["devices"]) == len(inert),
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(item["markers"] == 0 for item in precheck["checks"].values()),
        "precheck_is_for_exact_gds": precheck["gds_sha256"] == sha256(args.gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact 15-unit/eight-phase-tree channel plus type-matched top/bottom grounded edge dummies and enlarged shared guard",
        "checks": checks,
        "active_device_count": len(active),
        "dummy_device_count": len(inert),
        "dummy_device_types": dict(sorted(inert_types.items())),
        "phase_switch_counts": dict(sorted(phase_counts.items())),
        "topology_errors": topology_errors,
        "classified_extraction_marker": "one missing-terminal marker per intentionally D=G=S=B=VGND dummy; exact count required and cleared before GDS export",
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "sha256": {
            "spice": sha256(args.spice),
            "magic_log": sha256(args.log),
            "extraction_feedback": sha256(args.feedback),
            "precheck_summary": sha256(args.precheck),
            "dummy_manifest": sha256(args.dummies),
            "generator": sha256(ROOT / "v3" / "tools" / "generate_channel_edge_dummy_pilot.py"),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "integrate a compact 100 kohm-class input-bias path below the closed channel without moving phase roots or dummy devices",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
