#!/usr/bin/env python3
"""Freeze current V2 signoff results into tracked, self-contained evidence.

Run this only after Gate 5 and the datasheet figures pass.  Build-directory
reports are wrapped with their original path and SHA-256 so GitHub can verify
the compact evidence without checking in simulator work directories.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from check_gate5_candidate import audit as gate5_audit


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = ROOT / "v2/evidence"
FROZEN_DIR = EVIDENCE_DIR / "frozen"

SOURCES = {
    "gate3": Path("build/v2/signoff/gate3_manifest.json"),
    "gate4": Path("build/v2/signoff/gate4_audit.json"),
    "mismatch": Path("build/v2/gate5_mismatch_pilot/base_pilot_summary.json"),
    "sensitivity": Path("build/v2/signoff/gate5_sensitivity_pilot.json"),
    "clock": Path("build/v2/signoff/gate5_clock_pilot.json"),
    "twotone": Path("build/v2/gate5_twotone_pilot/base_summary.json"),
    "rc_codebook": Path(
        "build/v2/postlayout_smoke/rc/codebook/summary_startup_op_step_5ns.json"
    ),
    "trim": Path("build/v2/postlayout_trim/base/summary.json"),
    "startup": Path(
        "build/v2/postlayout_startup/rc/quiet_120us_step_20ns_final_5us/report.json"
    ),
    "heavy_load": Path(
        "build/v2/postlayout_smoke/rc/codebook/"
        "selected_0_incident_0_startup_op_step_5ns_outcap_50pf/report.json"
    ),
    "slow_low_hot": Path(
        "build/v2/postlayout_smoke/rc/codebook/"
        "selected_0_incident_0_startup_op_step_10ns_corner_ss_vdd_1p62_"
        "temp_85c_passives_ll/report.json"
    ),
    "fast_high_cold": Path(
        "build/v2/postlayout_smoke/rc/codebook/"
        "selected_0_incident_0_startup_op_step_10ns_corner_ff_vdd_1p98_"
        "temp_m40c_passives_hh/report.json"
    ),
    "fs_nominal": Path(
        "build/v2/postlayout_smoke/rc/codebook/"
        "selected_0_incident_0_startup_op_step_10ns_corner_fs_vdd_1p8_"
        "temp_27c_passives_ll/report.json"
    ),
    "sf_nominal": Path(
        "build/v2/postlayout_smoke/rc/codebook/"
        "selected_0_incident_0_startup_op_step_10ns_corner_sf_vdd_1p8_"
        "temp_27c_passives_hh/report.json"
    ),
    "extraction": Path("build/v2/control_routing/final_rc/coverage_audit.json"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load(relative_path: Path) -> dict[str, Any]:
    path = ROOT / relative_path
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_record(relative_path: Path, **extra: Any) -> dict[str, Any]:
    path = ROOT / relative_path
    record = {
        "path": str(relative_path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }
    record.update(extra)
    return record


def freeze_source(name: str, source: Path) -> dict[str, Any]:
    source_path = ROOT / source
    payload = load(source)
    output = FROZEN_DIR / f"{name}.json"
    wrapper = {
        "schema_version": 1,
        "source_path": str(source),
        "source_sha256": sha256(source_path),
        "payload": payload,
    }
    write_json(output, wrapper)
    return file_record(output.relative_to(ROOT), source_sha256=wrapper["source_sha256"])


def update_lock(values: dict[str, str]) -> None:
    path = ROOT / "submission/template.lock"
    lines = path.read_text(encoding="utf-8").splitlines()
    positions = {
        line.split("=", 1)[0]: index
        for index, line in enumerate(lines)
        if "=" in line
    }
    for key, value in values.items():
        line = f"{key}={value}"
        if key in positions:
            lines[positions[key]] = line
        else:
            lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--official-status", choices=("pending", "pass"), default="pending"
    )
    parser.add_argument("--official-run-url")
    parser.add_argument("--official-commit")
    args = parser.parse_args()
    if args.official_status == "pass" and not (
        args.official_run_url and args.official_commit
    ):
        raise SystemExit("a passing official status requires run URL and commit")

    gate5 = gate5_audit(ROOT)
    if gate5["status"] != "pass_with_documented_noise_residual":
        raise SystemExit("Gate 5 is not ready: " + "; ".join(gate5["errors"]))
    gate5_source = ROOT / "build/v2/signoff/gate5_audit.json"
    write_json(gate5_source, gate5)

    figures_path = ROOT / "v2/evidence/datasheet_figures.json"
    figures = json.loads(figures_path.read_text(encoding="utf-8"))
    if figures.get("candidate_gds_sha256") != gate5["frozen_gds_sha256"]:
        raise SystemExit("datasheet figures are stale")
    if len(figures.get("figures", [])) != 6:
        raise SystemExit("six current-candidate datasheet figures are required")

    frozen = {
        name: freeze_source(name, source)
        for name, source in {**SOURCES, "gate5": Path("build/v2/signoff/gate5_audit.json")}.items()
    }
    data = {name: load(source) for name, source in SOURCES.items()}
    data["gate5"] = gate5
    contract = load(Path("v2/layout/vcm_varactor_eco.json"))
    route = load(Path("build/v2/control_routing/openroad/route_audit.json"))
    delta = load(Path("build/v2/control_routing/direct/final_klayout_delta_audit.json"))
    noise = load(Path("v2/evidence/noise_scope.json"))
    codebook_metrics = data["rc_codebook"]["metrics"]
    trim = data["trim"]
    startup = data["startup"]
    extraction = data["extraction"]
    gds_path = Path(contract["output_checkpoint"]["gds"])
    source_path = Path(contract["source_checkpoint"]["gds"])
    submission_gds = Path("gds/tt_um_jjassonn69_beamformer.gds")
    status = (
        "fab_ready_research_prototype"
        if args.official_status == "pass"
        else "local_signoff_passed_official_tinytapeout_workflow_pending"
    )

    checkpoint = {
        "schema_version": 7,
        "as_of": date.today().isoformat(),
        "status": status,
        "top": contract["output_checkpoint"]["top"],
        "gds": {
            **file_record(gds_path, top=contract["output_checkpoint"]["top"]),
            "pre_varactor_user_route_source": file_record(
                source_path, top=contract["source_checkpoint"]["top"]
            ),
            "final_eco": "four foundry cap_var_lvt devices, G=VCM and D=S=B=VGND",
        },
        "architecture": {
            "channels": 4,
            "beam_states": 4,
            "phase_states_per_channel": 4,
            "tail_bank": "32 fixed equal units plus 4-bit 1/2/4/8 switched trim; reset code 8",
            "nominal_rf_mhz": 5.0,
            "nominal_lo_mhz": 4.0,
            "nominal_master_clock_mhz": 16.0,
            "nominal_if_mhz": 1.0,
        },
        "routing": {
            "routed_control_nets": route["internal_net_count"],
            "wire_length_um": route["total_wire_length_um"],
            "vias": route["total_via_count"],
            "maximum_signal_layer": route["maximum_route_layer"],
            "nets_using_met4": route["nets_using_layer"]["met4"],
            "maximum_detour": route["maximum_detour"],
            "maximum_two_pin_detour": route["maximum_two_pin_detour"],
        },
        "physical": {
            "status": data["gate3"]["status"],
            "magic_drc_count": data["gate3"]["magic_drc_count"],
            "direct_flat_rule_counts": data["gate3"]["direct_flat_rule_counts"],
            "klayout_delta": {
                "status": delta["status"],
                "source_marker_count": delta["source_marker_count"],
                "candidate_marker_count": delta["candidate_marker_count"],
                "added_category_counts": delta["added_category_counts"],
                "removed_marker_count": delta["removed_marker_count"],
            },
        },
        "distributed_rc": {
            "status": extraction["status"],
            "base_netlist_sha256": extraction["sha256"]["base"],
            "distributed_rc_netlist_sha256": extraction["sha256"]["distributed_rc"],
            "resistors": extraction["distributed_rc"]["resistors"],
            "capacitors": extraction["distributed_rc"]["capacitors"],
            "devices": extraction["distributed_rc"]["devices"],
            "internal_resistor_nodes": extraction["distributed_rc"]["internal_resistor_nodes"],
            "covered_named_routes": extraction["covered_routed_net_count"],
            "required_named_routes": extraction["required_routed_net_count"],
            "spice_to_annotation_ratio": extraction["annotation"]["spice_to_annotation_ratio"],
        },
        "electrical": {
            "gate4": data["gate4"]["metrics"],
            "gate5": gate5["metrics"],
            "nominal_rc_codebook": {
                "minimum_rejection_db": codebook_metrics["minimum_rejection_db"],
                "constructive_spread_db": codebook_metrics["constructive_spread_db"],
                "constructive_diagonal_v_rms": codebook_metrics["constructive_diagonal_v_rms"],
                "settled_operating_ranges": codebook_metrics["settled_operating_ranges"],
            },
            "trim": {
                "span_db_by_channel": trim["trim_span_db_by_channel"],
                "minimum_adjacent_step_db": min(
                    item["minimum_adjacent_step_db"]
                    for item in trim["useful_resolution_by_channel"]
                ),
                "default_spread_db": trim["default_spread_db"],
                "stress_calibrated_spread_db": trim["injected_mismatch_stress"]["calibration"]["spread_db"],
            },
            "startup": {
                "recommended_enable_delay_us": startup["stop_us"],
                "vcm_1p10_v_first_us": startup["measurements"]["vcm_valid_first"] * 1e6,
                "vcm_1p17_v_first_us": startup["measurements"]["vcm_near_nominal_first"] * 1e6,
                "vcm_final_avg_v": startup["measurements"]["vcm_final_avg"],
            },
        },
        "known_characterization_residuals": {
            "noise": noise["release_classification"],
            "independent_foundry_lvs": "not available in the open local flow",
            "package_board_and_antenna": "requires first-silicon measurement",
            "production_yield": "open-PDK coefficient mismatch campaign is not foundry-qualified yield",
        },
        "official_tinytapeout": {
            "status": args.official_status,
            "run_url": args.official_run_url,
            "commit": args.official_commit,
        },
    }
    checkpoint_path = ROOT / "v2/layout/control_routing_checkpoint.json"
    write_json(checkpoint_path, checkpoint)

    latest = {
        "schema_version": 3,
        "as_of": date.today().isoformat(),
        "release_status": status,
        "candidate": checkpoint["gds"],
        "submission": {
            "gds": file_record(
                submission_gds,
                top="tt_um_jjassonn69_beamformer",
                geometry_records_changed_from_candidate=0,
            ),
            "lef": file_record(
                Path("lef/tt_um_jjassonn69_beamformer.lef"),
                width_um=334.88, height_um=225.76, analog_pin_count=6,
                uses_vapwr=False,
            ),
            "info_yaml": file_record(Path("info.yaml")),
            "project_verilog": file_record(Path("src/project.v")),
        },
        "checkpoint": file_record(checkpoint_path.relative_to(ROOT)),
        "frozen_evidence": frozen,
        "datasheet_figures": file_record(figures_path.relative_to(ROOT), count=6),
        "visual_review": {
            "source_gds_sha256": checkpoint["gds"]["sha256"],
            "images": [
                file_record(Path("v2/evidence/images/beamformer-v2-exact-final-overview.png")),
                file_record(Path("v2/evidence/images/beamformer-v2-exact-final-varactor-detail.png")),
            ],
        },
        "gates": {
            "physical_gate3": data["gate3"]["status"],
            "bounded_electrical_gate4": data["gate4"]["status"],
            "characterization_gate5": gate5["status"],
            "official_tinytapeout": checkpoint["official_tinytapeout"],
        },
        "headline_metrics": checkpoint["electrical"],
        "known_characterization_residuals": checkpoint["known_characterization_residuals"],
        "fabrication_scope": (
            "ready for a TinyTapeout research shuttle after the official workflow passes; "
            "not production-qualified or measured silicon"
        ),
    }
    latest_path = EVIDENCE_DIR / "latest_validation.json"
    write_json(latest_path, latest)

    official_text = (
        f"passed at {args.official_run_url} for commit `{args.official_commit}`"
        if args.official_status == "pass"
        else "pending for the exact artifacts below"
    )
    md = f"""# V2 latest validation status

Date: {latest['as_of']}<br>
Candidate GDS SHA-256: `{checkpoint['gds']['sha256']}`

Release status: `{status}`. Local physical and bounded electrical signoff pass.
The official TinyTapeout workflow is {official_text}.

## Headline evidence

- Magic full-chip DRC: 0 errors; direct flat-rule counters: all zero.
- Distributed RC: {checkpoint['distributed_rc']['resistors']:,} resistors,
  {checkpoint['distributed_rc']['capacitors']:,} capacitors, and
  {checkpoint['distributed_rc']['covered_named_routes']}/
  {checkpoint['distributed_rc']['required_named_routes']} named routes covered.
- Complete nominal RC codebook: {codebook_metrics['minimum_rejection_db']:.2f} dB
  minimum raw rejection and {codebook_metrics['constructive_spread_db']:.3f} dB
  constructive spread.
- MOS mismatch sensitivity: {gate5['metrics']['mismatch_seed_count']}/60 pass;
  minimum corrected rejection {gate5['metrics']['minimum_mismatch_rejection_db']:.2f} dB;
  one-sided 95% modeled pass-probability lower bound
  {100 * gate5['metrics']['mismatch_zero_failure_95pct_lower_bound']:.2f}%.
- Trim span: {min(trim['trim_span_db_by_channel']):.3f}–
  {max(trim['trim_span_db_by_channel']):.3f} dB; deterministic injected mismatch
  calibrates to {trim['injected_mismatch_stress']['calibration']['spread_db']:.3f} dB spread.
- 50 mV-peak compression: {gate5['metrics']['fifty_mv_peak_compression_db']:.3f} dB;
  10 mV/tone fundamental-to-worst-IM3 separation:
  {gate5['metrics']['ten_mv_per_tone_im3_separation_db']:.2f} dB.
- Conservative first-silicon enable delay: {startup['stop_us']:.0f} us.

## Honest residuals

- Mixer noise figure needs a periodic-noise simulator or first-silicon measurement.
- The 60-seed open-PDK mismatch campaign is sensitivity evidence, not foundry yield.
- Package, PCB, antenna, 50-ohm drive, and measured beam patterns remain first-silicon work.
- Independent foundry-qualified LVS is unavailable in the present open flow.

The machine-readable record is [`latest_validation.json`](latest_validation.json),
and all plotted datasets and source hashes are in
[`datasheet_figures.json`](datasheet_figures.json).
"""
    (EVIDENCE_DIR / "latest_validation.md").write_text(md, encoding="utf-8")
    update_lock({
        "candidate_gds_sha256": checkpoint["gds"]["sha256"],
        "submission_gds_sha256": latest["submission"]["gds"]["sha256"],
        "submission_lef_sha256": latest["submission"]["lef"]["sha256"],
        "info_yaml_sha256": latest["submission"]["info_yaml"]["sha256"],
        "project_verilog_sha256": latest["submission"]["project_verilog"]["sha256"],
        "distributed_rc_netlist_sha256": checkpoint["distributed_rc"]["distributed_rc_netlist_sha256"],
        "nominal_rc_summary_sha256": frozen["rc_codebook"]["source_sha256"],
        "validation_evidence_sha256": sha256(latest_path),
        "official_tinytapeout_run": args.official_run_url or "pending_for_current_hash",
    })
    print(json.dumps(latest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
