#!/usr/bin/env python3
"""Build the hash-bound V3 pre-layout checkpoint from completed gate reports."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/model"))

from beamformer_v3 import phase_table  # noqa: E402


EVIDENCE = ROOT / "v3/evidence/implementation_checkpoint.json"
REPORTS = {
    "transition": Path("build/v3/transition_settling/summary.json"),
    "spur_noise": Path("build/v3/spur_noise/summary.json"),
    "mismatch": Path("build/v3/per_die_calibration_validation/summary.json"),
    "mismatch_global_codebook_diagnostic": Path("build/v3/mismatch_calibration_split/summary.json"),
    "mismatch_geometry_root_fix": Path("build/v3/mismatch_geometry_sweep/followup_summary.json"),
    "pcell_dimensions": Path("build/v3/pcell_dimensions/summary.json"),
    "solver_crosscheck": Path("build/v3/solver_crosscheck/summary.json"),
    "amplitude_range": Path("build/v3/amplitude_range/summary.json"),
    "two_tone": Path("build/v3/twotone_pilot/summary.json"),
    "vacask_tool_qualification": Path("build/v3/vacask_qualification/summary.json"),
    "vacask_model_qualification": Path("build/v3/vacask_sky130_qualification/summary.json"),
    "vacask_channel_qualification": Path("build/v3/vacask_channel_qualification/summary.json"),
    "vacask_noise_scale_linearity": Path("build/v3/vacask_noise_scale_linearity/summary.json"),
    "vacask_switched_noise": Path("build/v3/vacask_switched_noise/summary.json"),
    "noise_folding_crosscheck": Path("build/v3/noise_folding_crosscheck/summary.json"),
    "tt": Path("build/v3/selected_geometry/tt_summary.json"),
    "sf": Path("build/v3/selected_geometry/sf_summary.json"),
    "fs": Path("build/v3/selected_geometry/fs_summary.json"),
    "ff": Path("build/v3/selected_geometry/ff_summary.json"),
    "ss": Path("build/v3/selected_geometry/ss_summary.json"),
    "vin20": Path("build/v3/selected_geometry/vin20_summary.json"),
    "vin50": Path("build/v3/selected_geometry/vin50_summary.json"),
    "load30": Path("build/v3/selected_geometry/load30_summary.json"),
    "load60": Path("build/v3/selected_geometry/load60_summary.json"),
}
SOURCE_FILES = (
    Path("v3/model/beamformer_v3.py"),
    Path("v3/spice/vector_channel_15.inc"),
    Path("v3/rtl/serial_config.v"),
    Path("v3/rtl/quadrature_generator.v"),
    Path("v3/rtl/vector_control_core.v"),
    Path("v3/tools/run_one_channel_vector_sweep.py"),
    Path("v3/tools/run_twotone_pilot.py"),
    Path("v3/tools/run_transition_settling.py"),
    Path("v3/tools/run_spur_noise_characterization.py"),
    Path("v3/tools/run_mismatch_calibration_split.py"),
    Path("v3/tools/run_per_die_calibration_validation.py"),
    Path("v3/tools/run_mismatch_geometry_sweep.py"),
    Path("v3/tools/run_amplitude_range.py"),
    Path("v3/tools/run_pcell_dimension_study.py"),
    Path("v3/tools/build_solver_crosscheck.py"),
    Path("v3/tools/run_vacask_tool_qualification.py"),
    Path("v3/tools/run_vacask_sky130_qualification.py"),
    Path("v3/tools/run_vacask_channel_qualification.py"),
    Path("v3/tools/run_vacask_noise_scale_linearity.py"),
    Path("v3/tools/run_vacask_switched_noise.py"),
    Path("v3/tools/run_noise_folding_crosscheck.py"),
    Path("v3/tools/render_periodic_noise_report.py"),
    Path("v3/tools/build_prelayout_checkpoint.py"),
    Path("v3/layout/measure_pcells.tcl"),
    Path("v3/spec/beamformer_v3.md"),
)
EVIDENCE_ARTIFACTS = (
    Path("v3/evidence/periodic_noise_summary.json"),
    Path("v3/evidence/periodic_noise_summary.svg"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_reports() -> dict[str, dict[str, Any]]:
    reports = {}
    for name, relative in REPORTS.items():
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"missing gate report: {relative}")
        reports[name] = json.loads(path.read_text())
    return reports


def case_map(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(case["word"]): case for case in report["cases"]}


def compression_db(reference: dict[str, Any], driven: dict[str, Any]) -> float:
    reference_cases = case_map(reference)
    driven_cases = case_map(driven)
    reference_input = float(reference["corner"]["input_peak_v"])
    driven_input = float(driven["corner"]["input_peak_v"])
    return max(
        -20.0 * math.log10(
            (driven_cases[word]["tone_peak_v"] / driven_input)
            / (reference_cases[word]["tone_peak_v"] / reference_input)
        )
        for word in reference_cases
    )


def load_loss_db(reference: dict[str, Any], loaded: dict[str, Any]) -> float:
    reference_cases = case_map(reference)
    loaded_cases = case_map(loaded)
    return max(
        -20.0 * math.log10(
            loaded_cases[word]["tone_peak_v"] / reference_cases[word]["tone_peak_v"]
        )
        for word in reference_cases
    )


def main() -> None:
    reports = load_reports()
    missing_artifacts = [
        str(relative)
        for relative in EVIDENCE_ARTIFACTS
        if not (ROOT / relative).is_file()
    ]
    if missing_artifacts:
        raise SystemExit(
            f"cannot build checkpoint; missing evidence artifacts: {missing_artifacts}"
        )
    required_passes = (
        "transition", "spur_noise", "mismatch", "mismatch_geometry_root_fix",
        "pcell_dimensions", "solver_crosscheck", "amplitude_range", "two_tone",
        "vacask_tool_qualification", "vacask_model_qualification",
        "vacask_channel_qualification", "vacask_noise_scale_linearity",
        "noise_folding_crosscheck", "tt", "sf",
        "fs", "ff", "ss", "vin20", "vin50", "load30", "load60",
    )
    failed = [name for name in required_passes if reports[name].get("status") != "pass"]
    if failed:
        raise SystemExit(f"cannot build checkpoint; failed reports: {failed}")
    noise_status = reports["spur_noise"]["noise_signoff"]["status"]
    if noise_status != "blocked_pending_periodic_noise_tool":
        raise SystemExit(f"unexpected noise signoff state: {noise_status}")
    switched = reports["vacask_switched_noise"]
    if switched.get("status") != "pass_pending_frequency_domain_crosscheck":
        raise SystemExit(
            "unexpected switched-noise state before independent folding: "
            f"{switched.get('status')}"
        )

    table = phase_table(8)
    pvt = {}
    for name in ("tt", "sf", "fs", "ff", "ss"):
        report = reports[name]
        pvt[name] = {
            "worst_phase_error_deg": report["worst_phase_error_deg"],
            "magnitude_span_db": report["tone_peak_span_db"],
            "tone_peak_range_v_at_5mv_input": report["tone_peak_range_v"],
            "conversion_gain_range_db": [
                20.0 * math.log10(value / 0.005)
                for value in report["tone_peak_range_v"]
            ],
            "output_common_mode_range_v": report["output_common_mode_range_v"],
            "tail_current_compliance_fraction": report["tail_compliance"]["current_fraction"],
            "minimum_commutating_gm_drain_to_tail_v": min(
                case["minimum_gm_drain_to_tail_v"] for case in report["cases"]
            ),
        }

    mismatch = reports["mismatch"]
    transition = reports["transition"]
    spur = reports["spur_noise"]
    folding = reports["noise_folding_crosscheck"]
    scale_linearity = reports["vacask_noise_scale_linearity"]
    channel_crosscheck = reports["vacask_channel_qualification"]
    dimensions = reports["pcell_dimensions"]["candidates"][0]
    periodic_mode = switched["configuration"]["primary_mode"]
    periodic_by_word = switched["mode_summary"][periodic_mode]["by_word"]
    worst_periodic_state_mean = max(
        entry["mean_periodogram_band_rms_v"]
        for entry in periodic_by_word.values()
    )
    worst_periodic_seed = max(
        entry["maximum_v"] for entry in periodic_by_word.values()
    )
    folded_full_noise = folding["aggregate"]["mean_folded_noise_v_rms_10hz_to_2mhz"]
    folded_direct_band = folding["aggregate"]["mean_folded_noise_v_rms_10khz_to_2mhz"]
    folded_low_frequency_increment = math.sqrt(
        max(folded_full_noise**2 - folded_direct_band**2, 0.0)
    )
    conservative_periodic_noise = math.hypot(
        worst_periodic_state_mean, folded_low_frequency_increment
    )
    checkpoint = {
        "schema_version": 3,
        "status": "pre-layout electrical gates complete; floorplan authorized; not layout or release signoff",
        "v2_frozen_base_commit": "b7eae2e6ecf20b1141d15029503c345dacc71b99",
        "layout_authorized": True,
        "gds_authorized": False,
        "selected_geometry": {
            "gm_width_um": 0.84,
            "gm_length_um": 0.60,
            "switch_width_um": 0.65,
            "switch_length_um": 0.15,
            "tail_width_um_per_slice": 5.066666666,
            "tail_length_um": 1.00,
            "shared_bias_reference_width_um": 64.0,
            "shared_bias_reference_length_um": 1.00,
            "bias_blank_pass_width_um": 2.0,
            "bias_blank_pulldown_width_um": 1.0,
            "selection_reason": "four-times gm/tail matching area at unchanged W/L closed the held-out mismatch gate; real bias pass/pulldown removes the ideal analog-control source",
        },
        "architecture_gate_1": {
            "status": "pass",
            "unit_slices_per_channel": 15,
            "raw_words_per_channel": 256,
            "guaranteed_phase_states": 8,
            "worst_ideal_phase_error_deg": max(abs(entry.phase_error_deg) for entry in table),
            "ideal_magnitude_span_db": 20.0 * math.log10(
                max(entry.magnitude for entry in table) / min(entry.magnitude for entry in table)
            ),
        },
        "promoted_schematic_pvt_gate": {
            "status": "five-corner pass",
            "corners": pvt,
        },
        "linearity_and_loading_gate": {
            "status": "pass with high-capacitance load limit retained",
            "worst_compression_db_at_20mv_peak": compression_db(reports["tt"], reports["vin20"]),
            "worst_compression_db_at_50mv_peak": compression_db(reports["tt"], reports["vin50"]),
            "gain_loss_db_at_30pf_per_pad": load_loss_db(reports["tt"], reports["load30"]),
            "gain_loss_db_at_60pf_per_pad": load_loss_db(reports["tt"], reports["load60"]),
        },
        "amplitude_calibration_gate": {
            "status": reports["amplitude_range"]["status"],
            "minimum_cardinal_outer_to_inner_range_db": min(
                item["minimum_amplitude_range_db"]
                for item in reports["amplitude_range"]["corners"].values()
            ),
            "worst_inner_to_outer_phase_delta_deg": max(
                item["worst_inner_to_outer_phase_delta_deg"]
                for item in reports["amplitude_range"]["corners"].values()
            ),
        },
        "transition_gate": {
            "status": transition["status"],
            "ordered_transition_count": transition["ordered_transition_count"],
            "blank_duration_ns": transition["blank_duration_ns"],
            "bounded_selector_edge_ns": transition["bounded_selector_edge_ns"],
            "maximum_settling_time_us": max(
                case["first_bounded_settled_time_us"] for case in transition["cases"]
            ),
            "bias_blank_interface": "real per-channel NMOS pass/pulldown pair",
            "scope": transition["scope"],
        },
        "spur_and_noise_gate": {
            "spur_status": spur["status"],
            "phase_state_count": len(spur["words"]),
            "raw_worst_signal_spur_dbc": max(
                item["worst_corrected_signal_spur_dbc"] for item in spur["words"]
            ),
            "receiver_filtered_worst_signal_spur_dbc": max(
                item["worst_two_pole_2mhz_receiver_spur_dbc"] for item in spur["words"]
            ),
            "held_lo_output_noise_v_rms_10hz_to_2mhz": max(
                item["held_lo_integrated_output_noise_range_v_rms"][1]
                for item in spur["words"]
            ),
            "held_lo_noise_status": noise_status,
            "held_lo_noise_reason": spur["noise_signoff"]["reason"],
            "periodic_noise_status": "pass_by_crosschecked_transient_noise_equivalent",
            "periodic_noise_method": switched["scope"],
            "periodic_noise_primary_algorithm": periodic_mode,
            "periodic_noise_state_count": len(switched["configuration"]["selected_words"]),
            "periodic_noise_seed_count_per_state": len(switched["configuration"]["primary_seeds"]),
            "periodic_noise_record_us": switched["configuration"]["stop_us"],
            "periodic_noise_post_settle_us": switched["configuration"]["stop_us"] - switched["configuration"]["settle_us"],
            "periodic_noise_source_band_hz": switched["configuration"]["source_noise_band_hz"],
            "periodic_noise_receiver_cutoff_hz": switched["configuration"]["receiver_cutoff_hz"],
            "periodic_noise_mean_v_rms_10khz_to_2mhz": switched["mode_summary"][switched["configuration"]["primary_mode"]]["mean_over_cases_v"],
            "periodic_noise_state_span_db_10khz_to_2mhz": switched["mode_summary"][switched["configuration"]["primary_mode"]]["state_span_db"],
            "periodic_noise_worst_state_mean_v_rms_10khz_to_2mhz": worst_periodic_state_mean,
            "periodic_noise_worst_observed_seed_v_rms_10khz_to_2mhz": worst_periodic_seed,
            "noise_scale_linearity_span_db": scale_linearity["fit"]["extrapolated_noise_span_db"],
            "noise_scale_linearity_r_squared": scale_linearity["fit"]["through_origin_r_squared"],
            "folded_noise_v_rms_10hz_to_2mhz": folding["aggregate"]["mean_folded_noise_v_rms_10hz_to_2mhz"],
            "folded_noise_v_rms_10khz_to_2mhz": folding["aggregate"]["mean_folded_noise_v_rms_10khz_to_2mhz"],
            "folded_noise_increment_v_rms_10hz_to_10khz": folded_low_frequency_increment,
            "conservative_worst_state_mean_v_rms_10hz_to_2mhz": conservative_periodic_noise,
            "frequency_domain_comparison": folding["comparison_to_switched_transient"],
            "minimum_nominal_output_snr_db_at_5mv_peak": 20.0 * math.log10(
                min(case["vacask"]["tone_peak_v"] for case in channel_crosscheck["cases"])
                / math.sqrt(2.0)
                / conservative_periodic_noise
            ),
            "scope_limit": "TT schematic only; clock-source phase noise, package noise, and layout parasitics remain later physical/system gates",
        },
        "mismatch_gate": {
            "status": mismatch["status"],
            "method": mismatch["method"],
            "calibrated_die_count": mismatch["validation_metrics"]["die_count"],
            "calibration_input_peak_v": mismatch["calibration"]["input_peak_v"],
            "validation_input_peak_v": mismatch["validation"]["input_peak_v"],
            "codebook_is_independently_selected_per_die": mismatch["gate"]["codebook_is_independently_selected_per_die"],
            "every_die_has_eight_unique_state_words": mismatch["gate"]["every_die_has_eight_unique_state_words"],
            "calibration_and_validation_samples_are_distinct": mismatch["gate"]["calibration_and_validation_input_levels_are_distinct"],
            "validation_worst_phase_error_deg": mismatch["validation_metrics"]["worst_phase_error_deg"],
            "validation_worst_gain_span_db": mismatch["validation_metrics"]["worst_gain_span_db"],
            "validation_minimum_output_common_mode_v": mismatch["validation_metrics"]["minimum_output_common_mode_v"],
            "selected_codebook_count": len(mismatch["selected_codebooks"]),
            "selected_codebooks_sha256": hashlib.sha256(
                json.dumps(mismatch["selected_codebooks"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "frozen_factor_values_sha256": mismatch["factor_values_sha256"],
            "codebook_policy": "one codebook calibrated and frozen independently per die through raw-vector mode",
            "independence_contract": mismatch["independence_contract"],
            "limitations": mismatch["limitations"],
        },
        "global_codebook_diagnostic": {
            "status": reports["mismatch_global_codebook_diagnostic"]["status"],
            "purpose": "non-gating stress test showing that one universal codebook cannot correct random per-die mismatch",
            "validation_worst_phase_error_deg": reports["mismatch_global_codebook_diagnostic"]["validation_metrics"]["worst_phase_error_deg"],
            "validation_worst_gain_span_db": reports["mismatch_global_codebook_diagnostic"]["validation_metrics"]["worst_gain_span_db"],
        },
        "pcell_dimension_gate": {
            "status": reports["pcell_dimensions"]["status"],
            "recommended_candidate": reports["pcell_dimensions"]["recommended_candidate"],
            "estimated_width_um": dimensions["estimated_width_um"],
            "estimated_height_um": dimensions["estimated_height_um"],
            "width_margin_um_on_19p32um_pitch": dimensions["width_margin_um"],
            "bias_blank_support_width_um": dimensions["bias_blank_support_width_um"],
            "all_group_centroids_are_exactly_common": reports["pcell_dimensions"]["centroid_assignment"]["all_group_centroids_are_exactly_common"],
            "scope": reports["pcell_dimensions"]["scope"],
        },
        "solver_crosscheck_gate": {
            "status": reports["solver_crosscheck"]["status"],
            "case": reports["solver_crosscheck"]["case"],
            "deltas": reports["solver_crosscheck"]["deltas"],
            "scope": reports["solver_crosscheck"]["scope"],
        },
        "report_sha256": {
            name: sha256(ROOT / relative) for name, relative in REPORTS.items()
        },
        "source_sha256": {
            str(relative): sha256(ROOT / relative) for relative in SOURCE_FILES
        },
        "evidence_artifact_sha256": {
            str(relative): sha256(ROOT / relative)
            for relative in EVIDENCE_ARTIFACTS
        },
        "remaining_before_floorplan": [],
        "remaining_before_release": [
            "four-channel common-centroid placement and constrained routing",
            "DRC, LVS, antenna, density, and direct-GDS checks",
            "post-layout extracted RC regression including selector and clock routes",
            "package/board loading and external clock phase-noise system budget",
        ],
    }
    EVIDENCE.write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n")
    print(f"wrote {EVIDENCE.relative_to(ROOT)}")
    print(f"sha256={sha256(EVIDENCE)}")


if __name__ == "__main__":
    main()
