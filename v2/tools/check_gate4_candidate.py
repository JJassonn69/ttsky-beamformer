#!/usr/bin/env python3
"""Verify the frozen V2 candidate's bounded Gate-4 evidence without rerunning SPICE."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from run_gate4_targeted import canonical_sha256, extraction_binding


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path("build/v2/signoff/gate4_targeted_manifest.json")
CONTRACT = Path("v2/layout/vcm_varactor_eco.json")
EXTRACTION = Path("build/v2/control_routing/final_rc/coverage_audit.json")

EXPECTED_CASES = {
    "base_nominal_constructive",
    "base_zero_input_background",
    "rc_nominal_constructive",
    "rc_representative_null",
    "rc_zero_input_background",
    "rc_sf_headroom",
    "rc_ff_headroom",
    "rc_trim_low",
    "rc_trim_high",
    "rc_cold_start",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(root: Path = ROOT, manifest_data: dict[str, Any] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    contract = json.loads((root / CONTRACT).read_text())
    frozen_hash = contract["output_checkpoint"]["sha256"]
    extraction_path = root / EXTRACTION
    extraction = json.loads(extraction_path.read_text())
    expected_netlists = {
        "base": extraction["sha256"]["base"],
        "rc": extraction["sha256"]["distributed_rc"],
    }
    manifest_path = root / MANIFEST
    manifest = manifest_data or json.loads(manifest_path.read_text())

    if extraction.get("status") != "pass":
        errors.append("distributed-RC coverage audit is not passing")
    if manifest.get("status") != "pass":
        errors.append("Gate-4 runner manifest is not passing")
    if manifest.get("frozen_gds_sha256") != frozen_hash:
        errors.append("Gate-4 manifest is bound to a different GDS")
    if manifest.get("expected_netlist_sha256") != expected_netlists:
        errors.append("Gate-4 manifest is bound to stale extracted netlists")
    binding = extraction_binding(extraction)
    if manifest.get("extraction_binding") != binding:
        errors.append("Gate-4 manifest is bound to different RC coverage semantics")
    if manifest.get("extraction_binding_sha256") != canonical_sha256(binding):
        errors.append("Gate-4 RC coverage fingerprint differs")

    cases = manifest.get("cases", {})
    case_names = set(cases)
    if case_names != EXPECTED_CASES:
        errors.append(
            f"Gate-4 case set differs: missing={sorted(EXPECTED_CASES-case_names)} "
            f"extra={sorted(case_names-EXPECTED_CASES)}"
        )
    if manifest.get("case_count") != len(EXPECTED_CASES):
        errors.append("Gate-4 case count is not ten")

    reports: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []
    for name, item in sorted(cases.items()):
        relative = item.get("report")
        path = root / relative if relative else None
        if path is None or not path.is_file():
            errors.append(f"{name}: report is missing")
            continue
        actual_hash = sha256(path)
        if item.get("report_sha256") != actual_hash:
            errors.append(f"{name}: report hash differs from manifest")
        report = json.loads(path.read_text())
        reports[name] = report
        evidence.append({"case": name, "path": relative, "sha256": actual_hash})
        if item.get("returncode") != 0 or item.get("status") != "pass":
            errors.append(f"{name}: manifest case is not passing")
        if report.get("status") != "pass" or report.get("timed_out"):
            errors.append(f"{name}: SPICE report is not passing")
        if report.get("gds_sha256") != frozen_hash:
            errors.append(f"{name}: SPICE report checks a different GDS")
        view = report.get("view")
        if view not in expected_netlists:
            errors.append(f"{name}: unknown extraction view {view!r}")
        elif report.get("netlist_sha256") != expected_netlists[view]:
            errors.append(f"{name}: SPICE report checks a stale {view} netlist")

    metrics = manifest.get("metrics", {})
    if metrics.get("rc_representative_rejection_db", 0.0) < 6.0:
        errors.append("representative corrected rejection is below 6 dB")
    if metrics.get("base_to_rc_constructive_delta_db", float("inf")) > 3.0:
        errors.append("base-to-distributed-RC constructive delta exceeds 3 dB")

    expected_trim = {"rc_trim_low": [0, 0, 0, 0], "rc_trim_high": [15, 15, 15, 15]}
    for name, codes in expected_trim.items():
        if name in reports and reports[name].get("trim_codes") != codes:
            errors.append(f"{name}: wrong trim endpoint")
    for name in ("rc_sf_headroom", "rc_ff_headroom"):
        if name in reports:
            analysis = reports[name].get("analysis", {})
            if analysis.get("minimum_time_aligned_gm_drain_to_tail_v", -1.0) <= 0.0:
                errors.append(f"{name}: non-positive GM drain-to-tail margin")
    if "rc_trim_high" in reports:
        common_mode = reports["rc_trim_high"].get("analysis", {}).get("output_common_mode_v", 0.0)
        if common_mode < 0.8:
            errors.append("maximum-trim output common mode is below 0.8 V")
    if "rc_cold_start" in reports:
        startup = reports["rc_cold_start"].get("measurements", {})
        if startup.get("vcm_valid_settled", float("inf")) > 120e-6:
            errors.append("VCM did not settle above 1.1 V within 120 us")

    return {
        "schema_version": 1,
        "gate": 4,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "scope": "bounded post-layout electrical closure; not exhaustive characterization",
        "frozen_gds_sha256": frozen_hash,
        "expected_netlist_sha256": expected_netlists,
        "manifest": str(MANIFEST),
        "manifest_sha256": sha256(manifest_path) if manifest_path.is_file() else None,
        "case_count": len(reports),
        "metrics": metrics,
        "evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path,
        default=Path("build/v2/signoff/gate4_audit.json"),
    )
    args = parser.parse_args()
    report = audit()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
