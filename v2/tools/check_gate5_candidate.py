#!/usr/bin/env python3
"""Audit the bounded Gate-5 electrical evidence for the frozen V2 candidate.

This is a hash-bound evidence checker, not a simulator.  It deliberately keeps
the open-PDK mismatch campaign and the unavailable periodically switched noise
analysis separate from a production-yield claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = Path("v2/layout/vcm_varactor_eco.json")
EXTRACTION = Path("build/v2/control_routing/final_rc/coverage_audit.json")
MISMATCH = Path("build/v2/gate5_mismatch_pilot/base_pilot_summary.json")
SENSITIVITY = Path("build/v2/signoff/gate5_sensitivity_pilot.json")
TWOTONE = Path("build/v2/gate5_twotone_pilot/base_summary.json")
CLOCK = Path("build/v2/signoff/gate5_clock_pilot.json")
RC_CODEBOOK = Path(
    "build/v2/postlayout_smoke/rc/codebook/summary_startup_op_step_5ns.json"
)
RC_HEAVY_LOAD = Path(
    "build/v2/postlayout_smoke/rc/codebook/"
    "selected_0_incident_0_startup_op_step_5ns_outcap_50pf/report.json"
)
RC_SLOW_LOW_HOT = Path(
    "build/v2/postlayout_smoke/rc/codebook/"
    "selected_0_incident_0_startup_op_step_10ns_corner_ss_vdd_1p62_"
    "temp_85c_passives_ll/report.json"
)
RC_FAST_HIGH_COLD = Path(
    "build/v2/postlayout_smoke/rc/codebook/"
    "selected_0_incident_0_startup_op_step_10ns_corner_ff_vdd_1p98_"
    "temp_m40c_passives_hh/report.json"
)
RC_FS_NOMINAL = Path(
    "build/v2/postlayout_smoke/rc/codebook/"
    "selected_0_incident_0_startup_op_step_10ns_corner_fs_vdd_1p8_"
    "temp_27c_passives_ll/report.json"
)
RC_SF_NOMINAL = Path(
    "build/v2/postlayout_smoke/rc/codebook/"
    "selected_0_incident_0_startup_op_step_10ns_corner_sf_vdd_1p8_"
    "temp_27c_passives_hh/report.json"
)
NOISE_SCOPE = Path("v2/evidence/noise_scope.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(root: Path, relative: Path, errors: list[str]) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        errors.append(f"missing evidence: {relative}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"invalid evidence {relative}: {error}")
        return {}


def check_bound_report(
    root: Path,
    relative: str | None,
    expected_hash: str | None,
    frozen_hash: str,
    netlist_hash: str,
    errors: list[str],
    label: str,
) -> dict[str, Any]:
    if not relative:
        errors.append(f"{label}: missing report path")
        return {}
    path = root / relative
    if not path.is_file():
        errors.append(f"{label}: missing report {relative}")
        return {}
    actual_hash = sha256(path)
    if expected_hash is not None and actual_hash != expected_hash:
        errors.append(f"{label}: report hash differs")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "pass" or report.get("timed_out"):
        errors.append(f"{label}: report is not passing")
    if report.get("gds_sha256") != frozen_hash:
        errors.append(f"{label}: report checks a different GDS")
    if report.get("netlist_sha256") != netlist_hash:
        errors.append(f"{label}: report checks a different extracted netlist")
    return report


def audit(root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    contract = read_json(root, CONTRACT, errors)
    extraction = read_json(root, EXTRACTION, errors)
    frozen_hash = contract.get("output_checkpoint", {}).get("sha256")
    base_hash = extraction.get("sha256", {}).get("base")
    rc_hash = extraction.get("sha256", {}).get("distributed_rc")
    if not all(isinstance(item, str) and len(item) == 64 for item in (
        frozen_hash, base_hash, rc_hash
    )):
        errors.append("candidate or extraction hashes are unavailable")

    mismatch = read_json(root, MISMATCH, errors)
    if mismatch.get("status") != "pass":
        errors.append("60-seed mismatch campaign is not passing")
    seed_count = int(mismatch.get("seed_count", 0))
    if seed_count < 60:
        errors.append(f"mismatch campaign has only {seed_count}/60 seeds")
    if mismatch.get("passing_seed_count") != seed_count:
        errors.append("not every mismatch seed meets the hard functional gates")
    if mismatch.get("seeds_meeting_12db_engineering_target") != seed_count:
        errors.append("not every mismatch seed meets the 12 dB engineering target")
    lower_bound = mismatch.get(
        "zero_failure_one_sided_95pct_pass_probability_lower_bound"
    )
    if not isinstance(lower_bound, (int, float)) or lower_bound < 0.95:
        errors.append("modeled mismatch pass-probability lower bound is below 0.95")
    if mismatch.get("gds_sha256") != frozen_hash:
        errors.append("mismatch campaign checks a different GDS")
    if mismatch.get("source_netlist_sha256") != base_hash:
        errors.append("mismatch campaign checks a different base netlist")
    model_manifest_relative = mismatch.get("model_manifest")
    model_manifest_path = root / model_manifest_relative if model_manifest_relative else None
    if model_manifest_path is None or not model_manifest_path.is_file():
        errors.append("mismatch model manifest is missing")
    else:
        if sha256(model_manifest_path) != mismatch.get("model_manifest_sha256"):
            errors.append("mismatch model manifest hash differs")
        model_manifest = json.loads(model_manifest_path.read_text(encoding="utf-8"))
        if model_manifest.get("bundle_sha256") != mismatch.get("model_bundle_sha256"):
            errors.append("mismatch model manifest bundle identity differs")
    rebinding_relative = mismatch.get("bundle_rebinding_audit")
    if rebinding_relative:
        rebinding_path = root / rebinding_relative
        if not rebinding_path.is_file():
            errors.append("mismatch bundle-rebinding audit is missing")
        else:
            if sha256(rebinding_path) != mismatch.get("bundle_rebinding_audit_sha256"):
                errors.append("mismatch bundle-rebinding audit hash differs")
            rebinding = json.loads(rebinding_path.read_text(encoding="utf-8"))
            if (
                rebinding.get("status") != "pass"
                or rebinding.get("seed_count") != seed_count
                or rebinding.get("semantic_bundle_sha256")
                != mismatch.get("model_bundle_sha256")
            ):
                errors.append("mismatch bundle-rebinding audit identity differs")
    mismatch_rejection: list[float] = []
    for seed, item in sorted(mismatch.get("seeds", {}).items()):
        if item.get("status") != "pass":
            errors.append(f"mismatch seed {seed} is not passing")
        metrics = item.get("metrics", {})
        rejection = metrics.get("corrected_rejection_db")
        if isinstance(rejection, (int, float)):
            mismatch_rejection.append(float(rejection))
        transform_relative = item.get("transform")
        transform_path = root / transform_relative if transform_relative else None
        transform: dict[str, Any] = {}
        if transform_path is None or not transform_path.is_file():
            errors.append(f"mismatch seed {seed}: transform is missing")
        else:
            if sha256(transform_path) != item.get("transform_sha256"):
                errors.append(f"mismatch seed {seed}: transform hash differs")
            transform = json.loads(transform_path.read_text(encoding="utf-8"))
        transformed_netlist_hash = transform.get("mismatch_netlist_sha256")
        transformed_netlist = transform.get("mismatch_netlist")
        if transform.get("source_netlist_sha256") != base_hash:
            errors.append(f"mismatch seed {seed}: transform uses a stale source netlist")
        if transform.get("model_bundle_sha256") != mismatch.get("model_bundle_sha256"):
            errors.append(f"mismatch seed {seed}: transform uses a different model bundle")
        if not isinstance(transformed_netlist_hash, str) or len(transformed_netlist_hash) != 64:
            errors.append(f"mismatch seed {seed}: transformed netlist hash is missing")
        # The generated per-seed netlist is intentionally omitted from the compact
        # tracked evidence.  When it is present in a validation workspace, still
        # prove that it matches the transform manifest.
        if transformed_netlist and (root / transformed_netlist).is_file():
            if sha256(root / transformed_netlist) != transformed_netlist_hash:
                errors.append(f"mismatch seed {seed}: transformed netlist hash differs")
        for case, relative in item.get("cases", {}).items():
            case_report = check_bound_report(
                root, relative, None, frozen_hash, transformed_netlist_hash, errors,
                f"mismatch seed {seed} {case}",
            )
            if case_report.get("model_bundle_sha256") != mismatch.get("model_bundle_sha256"):
                errors.append(f"mismatch seed {seed} {case}: model bundle differs")

    sensitivity = read_json(root, SENSITIVITY, errors)
    if sensitivity.get("status") != "pass" or sensitivity.get("case_count") != 8:
        errors.append("bounded sensitivity matrix is not passing all eight cases")
    if sensitivity.get("frozen_gds_sha256") != frozen_hash:
        errors.append("sensitivity matrix checks a different GDS")
    if sensitivity.get("base_netlist_sha256") != base_hash:
        errors.append("sensitivity matrix checks a different base netlist")
    for name, item in sorted(sensitivity.get("cases", {}).items()):
        check_bound_report(
            root, item.get("report"), item.get("report_sha256"),
            frozen_hash, base_hash, errors, f"sensitivity {name}",
        )
    compression = sensitivity.get("metrics", {}).get("compression_db", {})
    if float(compression.get("amplitude_50mvpk", float("inf"))) >= 1.0:
        errors.append("input reaches 1 dB compression at or below 50 mV peak")

    twotone = read_json(root, TWOTONE, errors)
    if twotone.get("status") != "pass" or twotone.get("analysis", {}).get("status") != "pass":
        errors.append("two-tone pilot is not passing")
    if twotone.get("gds_sha256") != frozen_hash or twotone.get("netlist_sha256") != base_hash:
        errors.append("two-tone pilot checks different physical artifacts")
    for name, item in sorted(twotone.get("cases", {}).items()):
        check_bound_report(
            root, item.get("report"), item.get("report_sha256"),
            frozen_hash, base_hash, errors, f"two-tone {name}",
        )
    im3 = twotone.get("analysis", {}).get("points", {}).get(
        "tone_10mvpk", {}
    ).get("fundamental_to_worst_im3_db")
    if not isinstance(im3, (int, float)) or im3 < 40.0:
        errors.append("10 mV/tone worst IM3 separation is below 40 dB")

    clock = read_json(root, CLOCK, errors)
    if clock.get("status") != "pass" or clock.get("case_count") != 4:
        errors.append("clock sensitivity pilot is not passing all four cases")
    if clock.get("frozen_gds_sha256") != frozen_hash or clock.get("base_netlist_sha256") != base_hash:
        errors.append("clock sensitivity pilot checks different physical artifacts")
    for name, item in sorted(clock.get("cases", {}).items()):
        check_bound_report(
            root, item.get("report"), item.get("report_sha256"),
            frozen_hash, base_hash, errors, f"clock {name}",
        )

    codebook = read_json(root, RC_CODEBOOK, errors)
    if codebook.get("status") != "pass" or codebook.get("case_count") != 20:
        errors.append("complete nominal distributed-RC codebook is not passing")
    metrics = codebook.get("metrics", {})
    hashes = metrics.get("artifact_hashes", {})
    if hashes.get("gds_sha256") != [frozen_hash] or hashes.get("netlist_sha256") != [rc_hash]:
        errors.append("distributed-RC codebook checks different physical artifacts")
    if float(metrics.get("minimum_rejection_db", float("-inf"))) < 6.0:
        errors.append("distributed-RC codebook rejection is below 6 dB")
    if float(metrics.get("constructive_spread_db", float("inf"))) > 3.0:
        errors.append("distributed-RC constructive spread exceeds 3 dB")
    expected_codebook_cases = {
        *((selected, (selected + 1) % 4, 0.0) for selected in range(4)),
        *((selected, incident, 0.005) for selected in range(4) for incident in range(4)),
    }
    actual_codebook_cases: set[tuple[int, int, float]] = set()
    for item in codebook.get("case_reports", []):
        identity = (
            item.get("selected_beam"),
            item.get("incident_beam"),
            item.get("input_peak_v"),
        )
        actual_codebook_cases.add(identity)
        if item.get("status") != "pass" or item.get("timed_out"):
            errors.append(f"distributed-RC codebook case {identity} is not passing")
        if item.get("gds_sha256") != frozen_hash or item.get("netlist_sha256") != rc_hash:
            errors.append(f"distributed-RC codebook case {identity} checks different artifacts")
        relative = item.get("path")
        path = root / relative if isinstance(relative, str) else None
        if path is None or not path.is_file():
            errors.append(f"distributed-RC codebook case {identity} report is missing")
        elif sha256(path) != item.get("sha256"):
            errors.append(f"distributed-RC codebook case {identity} report hash differs")
    if actual_codebook_cases != expected_codebook_cases:
        errors.append("distributed-RC codebook per-case manifest is incomplete")

    endpoint_reports: dict[str, dict[str, Any]] = {}
    for label, relative in (
        ("60 pF total load", RC_HEAVY_LOAD),
        ("SS/1.62 V/85 C/passive-LL", RC_SLOW_LOW_HOT),
        ("FF/1.98 V/-40 C/passive-HH", RC_FAST_HIGH_COLD),
        ("FS/1.8 V/27 C/passive-LL", RC_FS_NOMINAL),
        ("SF/1.8 V/27 C/passive-HH", RC_SF_NOMINAL),
    ):
        report = check_bound_report(
            root, str(relative), None, frozen_hash, rc_hash, errors, label
        )
        endpoint_reports[label] = report
        analysis = report.get("analysis", {})
        if float(analysis.get("output_tone_rms_v", 0.0)) < 0.010:
            errors.append(f"{label}: output tone is below 10 mV RMS")
        if float(analysis.get("output_common_mode_v", 0.0)) < 0.8:
            errors.append(f"{label}: output common mode is below 0.8 V")
        if float(analysis.get("minimum_time_aligned_gm_drain_to_tail_v", -1.0)) <= 0.0:
            errors.append(f"{label}: GM drain-to-tail margin is non-positive")

    noise = read_json(root, NOISE_SCOPE, errors)
    if noise.get("status") != "deferred_requires_periodic_noise_or_measurement":
        errors.append("noise characterization residual is not explicitly deferred")
    if (
        noise.get("candidate_gds_sha256") != frozen_hash
        or noise.get("base_netlist_sha256") != base_hash
        or noise.get("distributed_rc_netlist_sha256") != rc_hash
    ):
        errors.append("noise scope is bound to different physical artifacts")
    warnings.append(
        "Periodically switched mixer noise figure remains a documented first-silicon/periodic-noise characterization item."
    )

    return {
        "schema_version": 1,
        "gate": 5,
        "status": "pass_with_documented_noise_residual" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "scope": "bounded post-layout electrical characterization; not production-yield qualification",
        "frozen_gds_sha256": frozen_hash,
        "expected_netlist_sha256": {"base": base_hash, "rc": rc_hash},
        "evidence": {
            "mismatch": str(MISMATCH),
            "sensitivity": str(SENSITIVITY),
            "twotone": str(TWOTONE),
            "clock": str(CLOCK),
            "distributed_rc_codebook": str(RC_CODEBOOK),
            "heavy_load": str(RC_HEAVY_LOAD),
            "slow_low_hot": str(RC_SLOW_LOW_HOT),
            "fast_high_cold": str(RC_FAST_HIGH_COLD),
            "fs_nominal": str(RC_FS_NOMINAL),
            "sf_nominal": str(RC_SF_NOMINAL),
            "noise_scope": str(NOISE_SCOPE),
        },
        "metrics": {
            "mismatch_seed_count": seed_count,
            "mismatch_zero_failure_95pct_lower_bound": lower_bound,
            "minimum_mismatch_rejection_db": min(mismatch_rejection) if mismatch_rejection else None,
            "minimum_codebook_rejection_db": metrics.get("minimum_rejection_db"),
            "codebook_constructive_spread_db": metrics.get("constructive_spread_db"),
            "ten_mv_per_tone_im3_separation_db": im3,
            "fifty_mv_peak_compression_db": compression.get("amplitude_50mvpk"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path,
        default=Path("build/v2/signoff/gate5_audit.json"),
    )
    args = parser.parse_args()
    report = audit()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass_with_documented_noise_residual" else 1


if __name__ == "__main__":
    raise SystemExit(main())
