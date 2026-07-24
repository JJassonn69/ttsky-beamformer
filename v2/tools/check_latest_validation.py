#!/usr/bin/env python3
"""Check that the tracked V2 release evidence is honest and artifact-bound."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "v2/evidence/latest_validation.json"
FIGURES = ROOT / "v2/evidence/datasheet_figures.json"
NOISE = ROOT / "v2/evidence/noise_scope.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def check_file(record: dict[str, Any], label: str) -> Path:
    path = ROOT / record["path"]
    require(path.is_file(), f"missing tracked {label}: {path}")
    actual = sha256(path)
    require(actual == record["sha256"], f"{label} hash mismatch: {actual}")
    if "bytes" in record:
        require(path.stat().st_size == record["bytes"], f"{label} size mismatch")
    return path


def frozen_payload(record: dict[str, Any], label: str) -> dict[str, Any]:
    path = check_file(record, label)
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    require(wrapper.get("schema_version") == 1, f"{label}: wrapper schema")
    require(
        wrapper.get("source_sha256") == record.get("source_sha256"),
        f"{label}: source provenance hash differs",
    )
    payload = wrapper.get("payload")
    require(isinstance(payload, dict), f"{label}: payload is absent")
    return payload


def main() -> int:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    require(evidence.get("schema_version") == 3, "unsupported validation schema")
    candidate = evidence["candidate"]
    candidate_path = check_file(candidate, "candidate GDS")
    check_file(candidate["pre_varactor_user_route_source"], "user-routed source GDS")
    frozen_hash = candidate["sha256"]
    require(frozen_hash == sha256(candidate_path), "candidate GDS binding")

    submission = evidence["submission"]
    for key, label in (
        ("gds", "submission GDS"),
        ("lef", "submission LEF"),
        ("info_yaml", "info.yaml"),
        ("project_verilog", "project Verilog"),
    ):
        check_file(submission[key], label)
    submission_gds = submission["gds"]
    require(
        submission_gds.get("geometry_records_changed_from_candidate")
        == "deterministic_official_precheck_repair_and_pin_packaging",
        "submission repair provenance differs",
    )
    require(
        submission_gds.get("source_candidate_sha256") == frozen_hash,
        "submission repair is not bound to the simulated candidate",
    )
    require(
        submission["lef"]["width_um"] == 334.88
        and submission["lef"]["height_um"] == 225.76
        and submission["lef"]["analog_pin_count"] == 6
        and submission["lef"]["uses_vapwr"] is False,
        "submission LEF contract differs",
    )

    physical_path = check_file(
        evidence["submission_physical_signoff"], "submission physical signoff"
    )
    physical = json.loads(physical_path.read_text(encoding="utf-8"))
    require(
        physical.get("schema_version") == 1 and physical.get("status") == "pass",
        "submission physical signoff is not passing",
    )
    require(
        physical["submission"].get("sha256") == submission_gds["sha256"]
        and physical["submission"].get("bytes") == submission_gds["bytes"]
        and physical["submission"].get("top") == submission_gds["top"],
        "physical signoff is bound to a different submission GDS",
    )
    repair = physical["repair"]
    require(
        repair.get("status") == "pass"
        and repair.get("source_candidate_sha256") == frozen_hash
        and repair.get("electrical_repaired_sha256")
        == submission_gds.get("electrical_repaired_sha256"),
        "deterministic repair evidence differs",
    )
    for path, expected in (
        (ROOT / repair["generator_path"], repair["generator_sha256"]),
        (ROOT / "v2/layout/official_precheck_landing_plan.json",
         repair["landing_plan_sha256"]),
        (ROOT / "v2/layout/official_precheck_relocation_plan.json",
         repair["relocation_plan_sha256"]),
        (ROOT / "third_party/sky130_custom_cells/sky130_fd_pr__cap_var_lvt_88578Y.gds",
         repair["varactor_master_sha256"]),
    ):
        require(path.is_file() and sha256(path) == expected,
                f"physical repair input differs: {path}")
    exact = physical["exact_precheck"]
    require(
        exact.get("status") == "pass"
        and all(exact.get(name) == 0 for name in (
            "feol_markers", "beol_markers", "offgrid_markers",
            "zero_area_markers", "pin_purpose_overlap_markers",
            "magic_drc_markers",
        )),
        "exact local Tiny Tapeout precheck replication is not clean",
    )
    topology = physical["extracted_topology"]
    require(
        topology.get("status") == "pass"
        and topology.get("submission_magic_drc_count") == 0
        and topology.get("import_feedback_count") == 0
        and topology.get("extraction_feedback_count") == 0
        and topology.get("ext2spice_completion_count") >= 2
        and topology.get("flat_netlist_normalized_sha256")
        == topology.get("repaired_candidate_flat_netlist_sha256"),
        "submission topology equivalence is not passing",
    )

    geometry_path = check_file(
        evidence["submission_geometry_regression"],
        "submission geometry regression",
    )
    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    require(
        geometry.get("schema_version") == 1 and geometry.get("status") == "pass",
        "submission geometry regression is not passing",
    )
    require(
        geometry["submission_gds"].get("sha256") == submission_gds["sha256"]
        and geometry["submission_gds"].get("bytes") == submission_gds["bytes"],
        "geometry regression is bound to a different submission GDS",
    )
    geometry_extraction = geometry["extraction"]
    base_counts = geometry_extraction["base_counts"]
    rc_counts = geometry_extraction["distributed_rc_counts"]
    require(
        geometry_extraction.get("magic_drc_count") == 0
        and geometry_extraction.get("extraction_feedback_count") == 0
        and base_counts.get("resistors") == 0
        and rc_counts.get("resistors", 0) > 0
        and rc_counts.get("all_resistors_positive") == 1
        and base_counts.get("devices") == rc_counts.get("devices"),
        "exact-final extraction or distributed resistance differs",
    )
    geometry_codebook = geometry["base_codebook"]
    require(
        geometry_codebook.get("case_count") == 20
        and geometry_codebook.get("minimum_rejection_db", 0.0) >= 6.0
        and geometry_codebook.get("constructive_spread_db", 99.0) <= 3.0,
        "exact-final base codebook gate failed",
    )
    geometry_rc = geometry["distributed_rc_nominal"]
    require(
        geometry_rc.get("base_to_rc_loss_db", 99.0) < 1.0
        and 1.10 <= geometry_rc.get("vcm_v", 0.0) <= 1.30
        and geometry_rc.get("output_common_mode_v", 0.0) >= 0.8
        and geometry_rc.get("minimum_headroom_v", 0.0) > 0.0
        and geometry_rc.get("maximum_phase_tree_skew_s", 1.0) < 1e-12,
        "exact-final distributed-RC nominal gate failed",
    )

    checkpoint_path = check_file(evidence["checkpoint"], "routing checkpoint")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    require(checkpoint.get("schema_version") == 7, "routing checkpoint schema")
    require(checkpoint["gds"]["sha256"] == frozen_hash, "checkpoint is stale")
    base_hash = checkpoint["distributed_rc"]["base_netlist_sha256"]
    rc_hash = checkpoint["distributed_rc"]["distributed_rc_netlist_sha256"]

    frozen = evidence["frozen_evidence"]
    expected_names = {
        "clock", "extraction", "fast_high_cold", "fs_nominal", "gate3",
        "gate4", "gate5", "heavy_load", "mismatch", "rc_codebook",
        "sensitivity", "sf_nominal", "slow_low_hot", "startup", "trim", "twotone",
    }
    require(set(frozen) == expected_names, "frozen evidence set differs")
    payloads = {
        name: frozen_payload(record, f"frozen {name}")
        for name, record in frozen.items()
    }

    gate3 = payloads["gate3"]
    require(gate3.get("status") == "pass", "physical Gate 3 is not passing")
    require(gate3.get("frozen_candidate_sha256") == frozen_hash, "Gate 3 is stale")
    require(gate3.get("magic_drc_count") == 0, "Magic DRC is not clean")
    require(all(value == 0 for value in gate3["direct_flat_rule_counts"].values()), "flat rule gate failed")

    extraction = payloads["extraction"]
    require(extraction.get("status") == "pass", "distributed RC is not passing")
    require(extraction["sha256"]["base"] == base_hash, "base extraction differs")
    require(extraction["sha256"]["distributed_rc"] == rc_hash, "RC extraction differs")
    require(extraction["distributed_rc"]["resistors"] > 0, "distributed resistance absent")
    require(
        extraction["covered_routed_net_count"] == extraction["required_routed_net_count"],
        "distributed-RC route coverage incomplete",
    )

    gate4 = payloads["gate4"]
    require(gate4.get("status") == "pass" and gate4.get("case_count") == 10, "Gate 4 differs")
    require(gate4.get("frozen_gds_sha256") == frozen_hash, "Gate 4 is stale")
    require(gate4.get("expected_netlist_sha256") == {"base": base_hash, "rc": rc_hash}, "Gate 4 netlists differ")

    gate5 = payloads["gate5"]
    require(gate5.get("status") == "pass_with_documented_noise_residual", "Gate 5 is not passing")
    require(gate5.get("frozen_gds_sha256") == frozen_hash, "Gate 5 is stale")
    require(gate5.get("expected_netlist_sha256") == {"base": base_hash, "rc": rc_hash}, "Gate 5 netlists differ")
    metrics = gate5["metrics"]
    require(metrics["mismatch_seed_count"] >= 60, "mismatch campaign is too small")
    require(metrics["mismatch_zero_failure_95pct_lower_bound"] >= 0.95, "mismatch confidence bound failed")
    require(metrics["minimum_mismatch_rejection_db"] >= 12.0, "mismatch rejection target failed")
    require(metrics["minimum_codebook_rejection_db"] >= 6.0, "codebook rejection failed")
    require(metrics["codebook_constructive_spread_db"] <= 3.0, "codebook spread failed")
    require(metrics["fifty_mv_peak_compression_db"] < 1.0, "compression gate failed")
    require(metrics["ten_mv_per_tone_im3_separation_db"] >= 40.0, "IM3 gate failed")

    mismatch = payloads["mismatch"]
    require(
        mismatch.get("status") == "pass"
        and mismatch.get("seed_count") >= 60
        and mismatch.get("passing_seed_count") == mismatch.get("seed_count")
        and mismatch.get("seeds_meeting_12db_engineering_target") == mismatch.get("seed_count"),
        "mismatch campaign summary differs",
    )
    require(mismatch.get("gds_sha256") == frozen_hash and mismatch.get("source_netlist_sha256") == base_hash, "mismatch artifacts differ")

    codebook = payloads["rc_codebook"]
    require(codebook.get("status") == "pass" and codebook.get("case_count") == 20, "RC codebook differs")
    artifact_hashes = codebook["metrics"]["artifact_hashes"]
    require(artifact_hashes["gds_sha256"] == [frozen_hash] and artifact_hashes["netlist_sha256"] == [rc_hash], "RC codebook artifacts differ")
    require(codebook["metrics"].get("acceptance_basis") == "raw_unsubtracted_response", "codebook acceptance basis changed")
    expected_codebook_cases = {
        *((selected, (selected + 1) % 4, 0.0) for selected in range(4)),
        *((selected, incident, 0.005) for selected in range(4) for incident in range(4)),
    }
    actual_codebook_cases = set()
    for item in codebook.get("case_reports", []):
        identity = (
            item.get("selected_beam"),
            item.get("incident_beam"),
            item.get("input_peak_v"),
        )
        actual_codebook_cases.add(identity)
        require(item.get("status") == "pass" and not item.get("timed_out"), f"RC codebook case {identity} failed")
        require(item.get("gds_sha256") == frozen_hash and item.get("netlist_sha256") == rc_hash, f"RC codebook case {identity} artifacts differ")
        require(isinstance(item.get("sha256"), str) and len(item["sha256"]) == 64, f"RC codebook case {identity} hash missing")
    require(actual_codebook_cases == expected_codebook_cases, "RC codebook case manifest differs")

    trim = payloads["trim"]
    require(trim.get("status") == "pass" and trim.get("case_count") == 64, "trim evidence differs")
    require(trim["artifact_hashes"]["gds_sha256"] == [frozen_hash] and trim["artifact_hashes"]["netlist_sha256"] == [base_hash], "trim artifacts differ")
    require(min(trim["trim_span_db_by_channel"]) >= 1.5, "trim span failed")
    require(trim["injected_mismatch_stress"]["calibration"]["spread_db"] <= 0.1, "trim stress calibration failed")

    for name in (
        "heavy_load", "slow_low_hot", "fast_high_cold", "fs_nominal",
        "sf_nominal",
    ):
        report = payloads[name]
        require(report.get("status") == "pass" and not report.get("timed_out"), f"{name} failed")
        require(report.get("gds_sha256") == frozen_hash and report.get("netlist_sha256") == rc_hash, f"{name} artifacts differ")
        analysis = report["analysis"]
        require(analysis["output_tone_rms_v"] >= 0.010, f"{name} output is too small")
        require(analysis["output_common_mode_v"] >= 0.8, f"{name} common mode failed")
        require(analysis["minimum_time_aligned_gm_drain_to_tail_v"] > 0.0, f"{name} headroom failed")

    noise = json.loads(NOISE.read_text(encoding="utf-8"))
    require(noise.get("status") == "deferred_requires_periodic_noise_or_measurement", "noise residual missing")
    require(
        noise.get("candidate_gds_sha256") == frozen_hash
        and noise.get("base_netlist_sha256") == base_hash
        and noise.get("distributed_rc_netlist_sha256") == rc_hash,
        "noise residual is stale",
    )

    check_file(evidence["datasheet_figures"], "datasheet figure manifest")
    figures = json.loads(FIGURES.read_text(encoding="utf-8"))
    require(figures.get("candidate_gds_sha256") == frozen_hash, "figures are stale")
    require(figures.get("base_netlist_sha256") == base_hash and figures.get("distributed_rc_netlist_sha256") == rc_hash, "figure netlists differ")
    require(len(figures.get("figures", [])) == 6, "six datasheet figures are required")
    for record in figures["figures"]:
        check_file(record, "datasheet figure")

    visual_review = evidence["visual_review"]
    require(
        visual_review.get("source_gds_sha256") == frozen_hash,
        "visual-review images are stale",
    )
    require(len(visual_review.get("images", [])) == 2, "two visual-review images are required")
    for record in visual_review["images"]:
        check_file(record, "visual-review image")

    official = evidence["gates"]["official_tinytapeout"]
    if official["status"] == "pending":
        require(
            evidence["release_status"] == "local_signoff_passed_official_tinytapeout_workflow_pending",
            "pending workflow status overstates readiness",
        )
        require(not official.get("run_url") and not official.get("commit"), "pending workflow has fabricated attestation")
    elif official["status"] == "pass":
        require(evidence["release_status"] == "fab_ready_research_prototype", "passing workflow status differs")
        require(re.fullmatch(r"[0-9a-f]{40}", official.get("commit", "")) is not None, "official commit is invalid")
        require(official.get("run_url", "").startswith("https://github.com/"), "official run URL is invalid")
    else:
        raise SystemExit("unknown official workflow status")

    datasheet = (ROOT / "v2/docs/datasheet.md").read_text(encoding="utf-8")
    status_doc = (ROOT / "v2/evidence/latest_validation.md").read_text(encoding="utf-8")
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    lock = (ROOT / "submission/template.lock").read_text(encoding="utf-8")
    require(datasheet.count(frozen_hash) >= 2, "datasheet is not candidate-bound")
    require(frozen_hash in status_doc and frozen_hash in root_readme, "release docs are stale")
    require("not a measured-silicon datasheet" in datasheet, "datasheet limitation is missing")
    require(f"candidate_gds_sha256={frozen_hash}" in lock, "template lock candidate differs")
    require(f"validation_evidence_sha256={sha256(EVIDENCE)}" in lock, "template lock evidence differs")

    print(f"V2 compact validation evidence is current and honest for {frozen_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
