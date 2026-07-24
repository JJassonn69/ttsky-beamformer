#!/usr/bin/env python3
"""Consolidate the frozen V2 physical/topology gate into one manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_gds_flat_rules import audit_rectangles, flatten_rectangles, parse_gds  # noqa: E402


REPORTS = (
    "build/v2/control_placement/control_placement_audit.json",
    "build/v2/control_power/control_power_audit.json",
    "build/v2/control_routing/openroad/route_audit.json",
    "build/v2/control_routing/trim_internal_override_audit.json",
    "build/v2/control_routing/control_trim_route_audit.json",
    "build/v2/control_routing/phase_route_audit.json",
    "build/v2/control_routing/quadrature_route_audit.json",
    "build/v2/control_routing/quadrature_extraction/final_signal_topology_audit.json",
    "build/v2/control_routing/quadrature_extraction/service_topology_audit.json",
    "build/v2/control_routing/quadrature_extraction/phase_topology_audit.json",
    "build/v2/control_routing/quadrature_extraction/power_topology_audit.json",
    "build/v2/control_routing/quadrature_extraction/quadrature_topology_audit.json",
    "build/v2/control_routing/quadrature_extraction/tail_bank_flat_audit.json",
    "build/v2/control_routing/quadrature_extraction/trim_topology_audit.json",
    "build/v2/control_routing/quadrature_extraction/vcm_varactor_audit.json",
    "build/v2/varactor_eco/topology_audit.json",
    "build/v2/varactor_eco/gds_assembly_audit.json",
    "build/v2/control_routing/direct/final_klayout_delta_audit.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    contract_path = root / "v2/layout/vcm_varactor_eco.json"
    contract = json.loads(contract_path.read_text())
    candidate = root / contract["output_checkpoint"]["gds"]
    source = root / contract["source_checkpoint"]["gds"]
    candidate_hash = sha256(candidate)
    source_hash = sha256(source)
    if candidate_hash != contract["output_checkpoint"]["sha256"]:
        errors.append("candidate GDS hash differs from frozen output checkpoint")
    if source_hash != contract["source_checkpoint"]["sha256"]:
        errors.append("pre-varactor source hash differs from frozen source checkpoint")

    evidence: list[dict[str, Any]] = []
    for relative in REPORTS:
        path = root / relative
        if not path.exists():
            errors.append(f"missing Gate 3 report {relative}")
            continue
        data = json.loads(path.read_text())
        status = data.get("status", data.get("passed"))
        evidence.append({
            "path": relative,
            "sha256": sha256(path),
            "status": status,
        })
        if status not in ("pass", True):
            errors.append(f"Gate 3 report is not passing: {relative}")

    assembly_path = root / "build/v2/varactor_eco/gds_assembly_audit.json"
    if assembly_path.exists():
        assembly = json.loads(assembly_path.read_text())
        if assembly.get("source_sha256") != source_hash:
            errors.append("assembly report source hash differs from frozen source")
        if assembly.get("output_sha256") != candidate_hash:
            errors.append("assembly report output hash differs from frozen candidate")

    delta_path = root / "build/v2/control_routing/direct/final_klayout_delta_audit.json"
    if delta_path.exists():
        delta = json.loads(delta_path.read_text())
        if delta.get("candidate_gds_sha256") != candidate_hash:
            errors.append("KLayout delta report checks a different candidate GDS")
        if delta.get("source_gds_sha256") != source_hash:
            errors.append("KLayout delta report checks a different pre-varactor GDS")
        if delta.get("added_category_counts") != {"ct.2": 10}:
            errors.append("KLayout delta is not limited to ten classified ct.2 markers")
        if delta.get("removed_marker_count") != 0:
            errors.append("KLayout candidate removed inherited markers")

    structures, database_um = parse_gds(candidate)
    rectangles = flatten_rectangles(
        structures, contract["output_checkpoint"]["top"], database_um
    )
    _components, flat_checks = audit_rectangles(rectangles)
    rejected_rules = (
        "met3 spacing", "met4 spacing", "met4 minimum area", "via3 enclosure",
        "via-only met3 island", "capm-to-unrelated-met3 spacing",
    )
    for rule in rejected_rules:
        if flat_checks[rule]:
            errors.append(f"direct-GDS flat rule {rule} has {len(flat_checks[rule])} markers")
    if len(flat_checks["met4 minimum width"]) != 1:
        errors.append("inherited M4 minimum-width marker count changed")

    log_path = root / "build/v2/control_routing/direct/quadrature_magic_extraction.log"
    log = log_path.read_text(errors="replace") if log_path.exists() else ""
    for marker in (
        "CONTROL_QUADRATURE_EXTRACTION_DRC_COUNT=0",
        "CONTROL_QUADRATURE_EXTRACTION_FEEDBACK_COUNT=0",
        "CONTROL_QUADRATURE_HIER_SPICE=",
        "CONTROL_QUADRATURE_FLAT_SPICE=",
    ):
        if marker not in log:
            errors.append(f"final Magic log lacks marker {marker}")
    if log.count("exttospice finished.") < 2:
        errors.append("final Magic extraction did not finish both topology views")

    return {
        "schema_version": 1,
        "gate": 3,
        "candidate": "32-fixed-unit tail bank with reset trim code 8",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "frozen_candidate_gds": str(candidate.relative_to(root)),
        "frozen_candidate_sha256": candidate_hash,
        "frozen_source_gds": str(source.relative_to(root)),
        "frozen_source_sha256": source_hash,
        "magic_drc_count": 0 if not any("DRC_COUNT" in error for error in errors) else None,
        "direct_flat_rule_counts": {
            rule: len(flat_checks[rule]) for rule in rejected_rules
        },
        "inherited_met4_minimum_width_marker_count": len(flat_checks["met4 minimum width"]),
        "klayout_policy": (
            "full-deck PCell marker baseline is accepted only by exact source-to-candidate "
            "delta; the ECO adds ten classified ct.2 markers and removes none"
        ),
        "evidence": evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path,
        default=Path("build/v2/signoff/gate3_manifest.json"),
    )
    args = parser.parse_args()
    report = build_manifest()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
