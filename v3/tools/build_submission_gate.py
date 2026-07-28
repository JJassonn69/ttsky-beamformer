#!/usr/bin/env python3
"""Consolidate V3 electrical, physical, wrapper, and artifact signoff evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOP = "tt_um_jjassonn69_beamformer"
GDS_SHA256 = "824e38f94ce4fbff84d0c079dcb059d6944bca7569a0f657134c318f31553c14"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> None:
    frozen = ROOT / "v3/frozen/submission"
    paths = {
        "canonical_gds": ROOT / f"gds/{TOP}.gds",
        "frozen_gds": frozen / f"{TOP}.gds",
        "lef": ROOT / f"lef/{TOP}.lef",
        "verilog": ROOT / "src/project.v",
        "info": ROOT / "info.yaml",
        "packaging": frozen / "gds_packaging.json",
        "direct_precheck": frozen / "direct_precheck/precheck_summary.json",
        "official_contract": frozen / "official_contract.json",
        "github_attestation": frozen / "github_attestation.json",
        "topology": frozen / "topology_audit.json",
        "prelayout": ROOT / "v3/evidence/implementation_checkpoint.json",
        "periodic_noise": ROOT / "v3/evidence/periodic_noise_summary.json",
        "support_pvt": ROOT / "v3/evidence/four_channel_support_pvt.json",
        "startup": ROOT / "v3/evidence/four_channel_startup.json",
        "output_rc": ROOT / "v3/evidence/four_channel_output_load_rc.json",
        "input_rc": ROOT / "v3/frozen/analog_input_escapes/input_rc_audit.json",
    }
    missing = [rel(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise SystemExit(f"missing submission evidence: {missing}")

    errors: list[str] = []
    for name in ("canonical_gds", "frozen_gds"):
        if sha256(paths[name]) != GDS_SHA256:
            errors.append(f"{name} does not match the frozen V3 submission hash")

    package = load(paths["packaging"])
    direct = load(paths["direct_precheck"])
    contract = load(paths["official_contract"])
    github = load(paths["github_attestation"])
    topology = load(paths["topology"])
    prelayout = load(paths["prelayout"])
    periodic = load(paths["periodic_noise"])
    support = load(paths["support_pvt"])
    startup = load(paths["startup"])
    output_rc = load(paths["output_rc"])
    input_rc = load(paths["input_rc"])

    if package.get("status") != "pass" or package.get("submission_sha256") != GDS_SHA256:
        errors.append("frozen packaging report is stale or failed")
    if package.get("magic_extracted_preboundary_sha256") != "0226f6da17aa037bcc147c1726c8b1baa01d70c1954981feec709e8475edeee9":
        errors.append("electrical wrapper hash differs from the Magic-extracted candidate")
    if direct.get("status") != "pass" or direct.get("gds_sha256") != GDS_SHA256:
        errors.append("direct-GDS precheck is stale or failed")
    if any(check.get("markers") != 0 for check in direct.get("checks", {}).values()):
        errors.append("one or more direct-GDS marker groups is nonzero")
    if contract.get("status") != "pass" or contract.get("gds_sha256") != GDS_SHA256:
        errors.append("wrapper-contract mirror is stale or failed")
    if topology.get("status") != "pass" or topology.get("gds_sha256") != GDS_SHA256:
        errors.append("flattened topology gate is stale or failed")
    expected_github_jobs = {"gds", "precheck", "viewer", "validation-evidence"}
    github_jobs = github.get("jobs", {})
    if github.get("status") != "pass" or github.get("gds_sha256") != GDS_SHA256:
        errors.append("official GitHub attestation is stale or failed")
    if set(github_jobs) != expected_github_jobs or any(
        job.get("status") != "completed" or job.get("conclusion") != "success"
        for job in github_jobs.values()
    ):
        errors.append("one or more official GitHub jobs is not successfully completed")

    topology_checks = topology.get("checks", {})
    expected_topology = {
        "device_count": 6037,
        "all_24_digital_outputs_tied_to_vgnd": True,
        "vdpwr_separate_from_vgnd": True,
        "device_model_population_preserved": True,
        "distinct_used_interface_roots": 20,
        "distinct_unused_interface_roots": 7,
        "final_delta_is_only_non_electrical_prboundary": True,
    }
    for key, expected in expected_topology.items():
        if topology_checks.get(key) != expected:
            errors.append(f"topology check {key} differs: {topology_checks.get(key)!r}")

    electrical_checks = {
        "architecture": prelayout.get("architecture_gate_1", {}).get("status") == "pass",
        "five_corner_schematic_pvt": "pass" in prelayout.get("promoted_schematic_pvt_gate", {}).get("status", ""),
        "independent_per_die_mismatch_calibration": prelayout.get("mismatch_gate", {}).get("status") == "pass",
        "bounded_linearity_and_loading": prelayout.get("linearity_and_loading_gate", {}).get("status", "").startswith("pass"),
        "all_code_transition_settling": prelayout.get("transition_gate", {}).get("status") == "pass",
        "spur": prelayout.get("spur_and_noise_gate", {}).get("spur_status") == "pass",
        "periodic_noise_crosscheck": periodic.get("status") == "pass_by_crosschecked_transient_noise_equivalent",
        "integrated_support_pvt": support.get("status") == "pass" and all(support.get("gates", {}).values()),
        "power_on_startup": startup.get("status") == "pass" and all(startup.get("gates", {}).values()),
        "differential_output_distributed_rc": output_rc.get("status") == "pass" and all(output_rc.get("checks", {}).values()),
        "four_input_distributed_rc": input_rc.get("status") == "pass" and all(input_rc.get("checks", {}).values()),
    }
    for key, passed in electrical_checks.items():
        if not passed:
            errors.append(f"electrical gate did not close: {key}")

    physical_gate_names = [
        "four_channel_placement_gate.json",
        "four_channel_output_collection_gate.json",
        "four_channel_phase_distribution_gate.json",
        "four_channel_bias_reference_distribution_gate.json",
        "four_channel_shared_support_integration_gate.json",
        "four_channel_output_load_integration_gate.json",
        "four_channel_power_integration_gate.json",
        "physical_control_signal_routing_gate.json",
        "physical_control_power_gate.json",
        "physical_control_analog_handoff_gate.json",
        "physical_control_boundary_handoff_gate.json",
        "analog_input_escape_gate.json",
        "digital_output_tie_gate.json",
    ]
    physical_gates: dict[str, dict[str, Any]] = {}
    for name in physical_gate_names:
        path = ROOT / "v3/evidence" / name
        data = load(path)
        passed = data.get("status") == "pass"
        physical_gates[name] = {
            "status": data.get("status"),
            "gds_sha256": data.get("gds_sha256"),
            "artifact_sha256": sha256(path),
        }
        if not passed:
            errors.append(f"physical gate did not close: {name}")

    review_images = sorted((frozen / "review").glob("*.png"))
    if len(review_images) != 8:
        errors.append(f"expected 8 final review views, found {len(review_images)}")

    report = {
        "schema_version": 1,
        "status": "signoff_pass_official_github_attested" if not errors else "fail",
        "errors": errors,
        "top_module": TOP,
        "gds": rel(paths["canonical_gds"]),
        "gds_sha256": sha256(paths["canonical_gds"]),
        "release_scope": "TinyTapeout SKY130 2x2 V3 custom analog macro",
        "wrapper_contract": {
            "tiles": "2x2",
            "supply": "VDPWR/VGND at 1.8 V; VAPWR not used",
            "analog_pins_used": 6,
            "digital_inputs_used": 14,
            "digital_outputs_tied_low": 24,
            "unique_top": contract.get("checks", {}).get("unique_top"),
            "template_bbox_dbu": contract.get("checks", {}).get("top_bbox_dbu"),
            "analog_pin_adjacency": contract.get("checks", {}).get("analog_pin_adjacency"),
            "forbidden_layer_hits": contract.get("checks", {}).get("forbidden_layer_hits"),
            "nwell_urpm_markers": contract.get("checks", {}).get("nwell_urpm_markers"),
            "verilog_syntax_exit": contract.get("checks", {}).get("verilog_syntax_exit"),
        },
        "physical_signoff": {
            "direct_gds_marker_groups": {
                name: check.get("markers") for name, check in direct.get("checks", {}).items()
            },
            "magic_hierarchical": topology_checks.get("hierarchical_magic_metrics"),
            "magic_flat": topology_checks.get("flat_magic_metrics"),
            "classified_flat_dummy_warnings": topology_checks.get("flat_dummy_warning_count"),
            "extracted_device_count": topology_checks.get("device_count"),
            "vdpwr_terminal_hits": topology_checks.get("vdpwr_terminal_hits"),
            "vgnd_terminal_hits": topology_checks.get("vgnd_terminal_hits"),
            "physical_stage_gates": physical_gates,
        },
        "electrical_signoff": {
            "gates": electrical_checks,
            "guaranteed_phase_states": prelayout.get("architecture_gate_1", {}).get("guaranteed_phase_states"),
            "raw_words_per_channel": prelayout.get("architecture_gate_1", {}).get("raw_words_per_channel"),
            "mismatch_worst_phase_error_deg": prelayout.get("mismatch_gate", {}).get("validation_worst_phase_error_deg"),
            "mismatch_worst_gain_ripple_db": prelayout.get("mismatch_gate", {}).get("validation_worst_gain_span_db"),
            "maximum_code_transition_settling_us": prelayout.get("transition_gate", {}).get("maximum_settling_time_us"),
            "worst_filtered_signal_spur_dbc": prelayout.get("spur_and_noise_gate", {}).get("receiver_filtered_worst_signal_spur_dbc"),
            "minimum_nominal_snr_db_at_5mv_peak": prelayout.get("spur_and_noise_gate", {}).get("minimum_nominal_output_snr_db_at_5mv_peak"),
            "startup_worst_vcm_t90_us": startup.get("worst_case", {}).get("vcm_t90_us"),
            "startup_worst_vcm_settled_2pct_us": startup.get("worst_case", {}).get("vcm_settled_2pct_us"),
            "startup_required_wait_after_vdd_us": startup.get("recommended_operating_sequence", {}).get("minimum_wait_after_vdd_ramp_us"),
            "input_5mhz_phase_spread_deg": input_rc.get("matching_metrics", {}).get("intended_5mhz_1kohm_loading", {}).get("channel_phase_spread_deg"),
            "input_5mhz_gain_spread_db": input_rc.get("matching_metrics", {}).get("intended_5mhz_1kohm_loading", {}).get("channel_gain_spread_db"),
            "output_effective_capacitance_mismatch_percent": output_rc.get("differential_metrics", {}).get("total_effective_capacitance_mismatch_percent_typical"),
            "output_estimated_time_constant_mismatch_percent": output_rc.get("differential_metrics", {}).get("estimated_tau_mismatch_percent_typical"),
        },
        "external_signoff": {
            "status": github.get("status"),
            "repository": github.get("repository"),
            "branch": github.get("branch"),
            "attested_commit": github.get("commit"),
            "attested_gds_sha256": github.get("gds_sha256"),
            "workflow": github.get("workflow"),
            "jobs": github_jobs,
        },
        "measurement_and_system_limits_not_fabrication_blockers": [
            "open-source switched-noise equivalent is not native PNoise",
            "clock-source phase noise is not included",
            "package, PCB, source/load parasitics, and antenna behavior require board-level simulation and silicon measurement",
            "the unbuffered output is intended for a high-impedance, low-capacitance differential receiver, not direct 50-ohm drive",
            "the bounded mismatch campaign is a design screen, not a foundry-qualified yield estimate",
        ],
        "artifact_sha256": {rel(path): sha256(path) for path in paths.values()},
        "review_images": {rel(path): sha256(path) for path in review_images},
        "generator_sha256": sha256(Path(__file__)),
    }
    output = ROOT / "v3/evidence/submission_gate.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
