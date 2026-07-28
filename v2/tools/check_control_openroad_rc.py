#!/usr/bin/env python3
"""Audit zero-pruning distributed RC coverage for all OpenROAD control nets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_distributed_rc import annotation_counts, rc_details, spice_elements
from v2.tools.check_magic_rc_log import FATAL_PATTERNS


MINIMUM_RESISTOR_EMISSION_RATIO = 0.90


def marker(log: str, name: str) -> int | None:
    values = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(
    base_path: Path,
    rc_path: Path,
    res_ext_path: Path,
    geometry: dict[str, Any],
    log: str,
) -> dict[str, Any]:
    base = spice_elements(base_path)
    rc = spice_elements(rc_path)
    labels = set(geometry["label_net_map"])
    details = rc_details(rc, labels)
    rnodes, annotated = annotation_counts(res_ext_path)
    emission_ratio = details["resistors"] / annotated if annotated else 0.0
    top_ext = res_ext_path.with_name(
        res_ext_path.name.removesuffix(".res.ext") + ".ext"
    )
    fatal = {
        name: pattern.search(log).group(0)
        for name, pattern in FATAL_PATTERNS.items() if pattern.search(log)
    }
    output_markers = all(
        re.search(rf"^{name}=\S+\s*$", log, flags=re.MULTILINE)
        for name in (
            "CONTROL_INTERNAL_BASE_SPICE",
            "CONTROL_INTERNAL_RC_SPICE",
            "CONTROL_INTERNAL_RES_EXT",
        )
    )
    checks = {
        "route_manifest_is_nonempty": len(labels) > 0,
        "magic_drc_clean": marker(log, "CONTROL_INTERNAL_RC_DRC_COUNT") == 0,
        "magic_feedback_clean": marker(
            log, "CONTROL_INTERNAL_RC_EXTRACTION_FEEDBACK_COUNT"
        ) == 0,
        "magic_outputs_complete": log.count("exttospice finished.") >= 2 and output_markers,
        "no_silent_magic_failures": not fatal,
        "base_is_resistance_free_reference": len(base["R"]) == 0,
        "resistance_annotation_exists": rnodes > 0 and annotated > 0,
        "resistance_annotation_is_fresh": (
            top_ext.is_file()
            and res_ext_path.stat().st_mtime_ns >= top_ext.stat().st_mtime_ns
        ),
        "explicit_resistors_emitted": (
            annotated > 0 and emission_ratio >= MINIMUM_RESISTOR_EMISSION_RATIO
        ),
        "distributed_capacitances_emitted": details["capacitors"] > len(base["C"]),
        "device_count_preserved": details["devices"] == len(base["X"]) > 0,
        "all_manifest_routes_resistively_covered": not details["uncovered_manifest_nets"],
        "internal_resistor_nodes_emitted": details["internal_resistor_nodes"] >= len(labels),
        "resistor_records_well_formed": not details["malformed_resistors"],
        "resistor_values_positive": not details["nonpositive_resistors"],
        "no_extraction_attribute_nodes": not details["attribute_like_resistor_nodes"],
    }
    covered_labels = sorted(labels - set(details["uncovered_manifest_nets"]))
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "required_route_count": len(labels),
        "resistively_covered_route_count": len(covered_labels),
        "covered_routes": [
            {"gds_label": label, "logical_net": geometry["label_net_map"][label]}
            for label in covered_labels
        ],
        "uncovered_route_labels": details["uncovered_manifest_nets"],
        "base": {
            "resistors": len(base["R"]),
            "capacitors": len(base["C"]),
            "devices": len(base["X"]),
        },
        "distributed_rc": {
            "resistors": details["resistors"],
            "capacitors": details["capacitors"],
            "devices": details["devices"],
            "internal_resistor_nodes": details["internal_resistor_nodes"],
            "resistor_components": details["resistor_components"],
            "malformed_resistors": details["malformed_resistors"],
            "nonpositive_resistors": details["nonpositive_resistors"],
            "attribute_like_resistor_nodes": details["attribute_like_resistor_nodes"],
        },
        "annotation": {
            "rnodes": rnodes,
            "resistors": annotated,
            "spice_to_annotation_ratio": emission_ratio,
            "minimum_spice_to_annotation_ratio": MINIMUM_RESISTOR_EMISSION_RATIO,
        },
        "magic_fatal_matches": fatal,
        "sha256": {
            "base": sha256(base_path),
            "distributed_rc": sha256(rc_path),
            "resistance_annotation": sha256(res_ext_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    work = Path("build/v2/control_routing/openroad_internal/rc")
    parser.add_argument("--base", type=Path, default=work / "control_internal_base.spice")
    parser.add_argument("--rc", type=Path, default=work / "control_internal_rc.spice")
    parser.add_argument(
        "--res-ext", type=Path,
        default=work / "v2_control_internal_routed_rc_flat.res.ext",
    )
    parser.add_argument(
        "--geometry", type=Path,
        default=Path("build/v2/control_routing/openroad_route_geometry.json"),
    )
    parser.add_argument(
        "--log", type=Path,
        default=Path("build/v2/control_routing/openroad_internal/magic_rc.log"),
    )
    parser.add_argument("--report", type=Path, default=work / "coverage_audit.json")
    args = parser.parse_args()
    report = audit(
        args.base,
        args.rc,
        args.res_ext,
        json.loads(args.geometry.read_text(encoding="utf-8")),
        args.log.read_text(encoding="utf-8", errors="replace"),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    counts = report["distributed_rc"]
    print(
        "Internal-control distributed-RC "
        + ("passed" if report["status"] == "pass" else "FAILED")
        + f": {counts['resistors']} resistors, {counts['capacitors']} capacitors, "
        + f"{report['resistively_covered_route_count']}/"
        + f"{report['required_route_count']} named routes covered"
    )
    if report["status"] != "pass":
        for name, passed in report["checks"].items():
            if not passed:
                print(f"FAIL: {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
