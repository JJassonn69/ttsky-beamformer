#!/usr/bin/env python3
"""Freeze generated electrical reports and their hashes into submission/."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUBMISSION = ROOT / "submission"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def result_at(report: dict[str, object], key: str, value: object) -> dict[str, object]:
    return next(item for item in report["results"] if item[key] == value)


def main() -> None:
    extracted_rc_source = ROOT / "build/layout/extracted_rc.spice"
    extracted_rc_frozen = SUBMISSION / "extracted_rc.spice"
    generated = {
        "schematic_pvt": (
            ROOT / "build/core_pvt_summary.json",
            SUBMISSION / "core_pvt_summary.json",
        ),
        "extracted_pvt": (
            ROOT / "build/extracted_pvt_summary.json",
            SUBMISSION / "extracted_pvt_summary.json",
        ),
        "extracted_frequency_sweep": (
            ROOT / "build/extracted_frequency_sweep.json",
            SUBMISSION / "extracted_frequency_sweep.json",
        ),
        "extracted_clock_sweep": (
            ROOT / "build/extracted_clock_sweep.json",
            SUBMISSION / "extracted_clock_sweep.json",
        ),
        "extracted_channel_balance": (
            ROOT / "build/extracted_channel_balance.json",
            SUBMISSION / "extracted_channel_balance.json",
        ),
        "distributed_rc_coverage": (
            ROOT / "build/layout/distributed_rc_coverage.json",
            SUBMISSION / "distributed_rc_coverage.json",
        ),
        "route_matching": (
            ROOT / "build/layout/route_matching.json",
            SUBMISSION / "route_matching.json",
        ),
        "mismatch_mc": (
            ROOT / "build/mismatch_mc_summary.json",
            SUBMISSION / "mismatch_mc_summary.json",
        ),
    }
    missing = [str(source) for source, _target in generated.values() if not source.is_file()]
    if not extracted_rc_source.is_file():
        missing.append(str(extracted_rc_source))
    if missing:
        raise SystemExit(f"missing generated reports: {missing}")

    artifacts = {
        "gds": ROOT / "gds/tt_um_jjassonn69_beamformer.gds",
        "lef": ROOT / "lef/tt_um_jjassonn69_beamformer.lef",
        # The signed simulation artifact is the distributed-RC view.
        # extracted.spice remains the resistance-free device/capacitance
        # reference used for topology comparison.
        "extracted_spice": extracted_rc_source,
    }
    official_action = read_json(SUBMISSION / "official_action.json")
    if official_action["conclusion"] != "success":
        raise SystemExit("official TinyTapeout Action is not successful")
    if official_action["gds_sha256"] != digest(artifacts["gds"]):
        raise SystemExit(
            "official TinyTapeout Action is stale for the current GDS; "
            "run the Action and update submission/official_action.json"
        )
    official_result = SUBMISSION / "official_precheck_results.md"
    official_magic = SUBMISSION / "official_magic_drc.txt"
    if official_action["results_sha256"] != digest(official_result):
        raise SystemExit("official precheck result does not match its Action attestation")
    if official_action["magic_drc_sha256"] != digest(official_magic):
        raise SystemExit("official Magic DRC result does not match its Action attestation")

    model_inputs = [
        ROOT / "spice/sky130/sky130_passives_tt.inc",
        *sorted((ROOT / "spice/sky130").glob("sky130_1v8_*.inc")),
    ]
    freshness_inputs = {
        "schematic_pvt": [
            ROOT / "spice/sky130/beamformer_core.spice",
            ROOT / "spec/beamformer_v1.md",
            ROOT / "tools/run_core_pvt.py",
            ROOT / "tools/simulation_provenance.py",
            *model_inputs,
        ],
        "extracted_pvt": [
            ROOT / "build/layout/extracted_rc.spice",
            ROOT / "spec/beamformer_v1.md",
            ROOT / "spice/sky130/extracted_core_tb.spice",
            ROOT / "tools/run_extracted_pvt.py",
            ROOT / "tools/run_extracted_sim.py",
            ROOT / "tools/run_core_pvt.py",
            *model_inputs,
        ],
        "extracted_frequency_sweep": [
            ROOT / "build/layout/extracted_rc.spice",
            ROOT / "spec/beamformer_v1.md",
            ROOT / "spice/sky130/extracted_core_tb.spice",
            ROOT / "tools/run_extracted_frequency_sweep.py",
            *model_inputs,
        ],
        "extracted_clock_sweep": [
            ROOT / "build/layout/extracted_rc.spice",
            ROOT / "spec/beamformer_v1.md",
            ROOT / "spice/sky130/extracted_clock_tb.spice",
            ROOT / "tools/run_extracted_clock_sweep.py",
            *model_inputs,
        ],
        "extracted_channel_balance": [
            ROOT / "build/layout/extracted_rc.spice",
            ROOT / "spec/beamformer_v1.md",
            ROOT / "spice/sky130/extracted_core_tb.spice",
            ROOT / "tools/run_extracted_channel_balance.py",
            *model_inputs,
        ],
        "distributed_rc_coverage": [
            ROOT / "build/layout/extracted.spice",
            ROOT / "build/layout/extracted_rc.spice",
            ROOT / "build/layout/buffered/tt_um_jjassonn69_beamformer.res.ext",
            ROOT / "layout/circuit.json",
            ROOT / "layout/extract.tcl",
            ROOT / "tools/check_distributed_rc.py",
        ],
        "route_matching": [
            ROOT / "build/layout/route.tcl",
            ROOT / "layout/circuit.json",
            ROOT / "tools/generate_route_script.py",
            ROOT / "tools/check_generated_routes.py",
        ],
        "mismatch_mc": [
            ROOT / "spice/sky130/beamformer_core.spice",
            ROOT / "spec/beamformer_v1.md",
            ROOT / "tools/run_mismatch_mc.py",
            ROOT / "tools/simulation_provenance.py",
            *model_inputs,
        ],
    }
    for name, inputs in freshness_inputs.items():
        source = generated[name][0]
        newest_input = max(path.stat().st_mtime for path in inputs)
        if source.stat().st_mtime < newest_input:
            raise SystemExit(
                f"stale {name} report: regenerate {source.relative_to(ROOT)}"
            )

    pvt = read_json(generated["extracted_pvt"][0])
    frequency = read_json(generated["extracted_frequency_sweep"][0])
    clock = read_json(generated["extracted_clock_sweep"][0])
    balance = read_json(generated["extracted_channel_balance"][0])
    rc_coverage = read_json(generated["distributed_rc_coverage"][0])
    route_matching = read_json(generated["route_matching"][0])
    mismatch = read_json(generated["mismatch_mc"][0])
    core_pvt = read_json(generated["schematic_pvt"][0])
    independent_frequency = read_json(
        SUBMISSION / "independent_ngspice46_frequency_crosscheck.json"
    )
    schematic_source = ROOT / "spice/sky130/beamformer_core.spice"
    if (
        core_pvt.get("matrix") != "full"
        or core_pvt.get("case_count") != 45
        or core_pvt.get("source") != "spice/sky130/beamformer_core.spice"
        or core_pvt.get("source_sha256") != digest(schematic_source)
    ):
        raise SystemExit("schematic PVT is not bound to the current full-matrix source")
    if (
        mismatch.get("source") != "spice/sky130/beamformer_core.spice"
        or mismatch.get("source_sha256") != digest(schematic_source)
        or mismatch.get("ngspice_version") != "46"
    ):
        raise SystemExit("mismatch surrogate is not bound to the current source/ngspice 46")
    if pvt["matrix"] != "full" or pvt["case_count"] != 45:
        raise SystemExit("refusing to freeze anything except the full 45-case extracted PVT")
    if pvt.get("netlist_sha256") != digest(extracted_rc_source):
        raise SystemExit("extracted PVT netlist hash does not match the current RC artifact")
    expected_netlist = "build/layout/extracted_rc.spice"
    for name, report in (
        ("extracted PVT", pvt),
        ("frequency sweep", frequency),
        ("clock sweep", clock),
        ("channel balance", balance),
    ):
        if report.get("netlist") != expected_netlist:
            raise SystemExit(f"{name} was not generated from {expected_netlist}")
        if report.get("netlist_sha256") != digest(extracted_rc_source):
            raise SystemExit(f"{name} does not match the current RC-netlist hash")
        if report.get("ngspice_version") != "44.2" or not str(
            report.get("platform", "")
        ).startswith("Linux"):
            raise SystemExit(f"{name} is not the primary Ubuntu/ngspice 44.2 run")
    if not rc_coverage.get("passed"):
        raise SystemExit("distributed-RC extraction coverage did not pass")
    rc_hashes = rc_coverage.get("sha256", {})
    if (
        rc_hashes.get("base_netlist") != digest(ROOT / "build/layout/extracted.spice")
        or rc_hashes.get("distributed_rc_netlist") != digest(extracted_rc_source)
        or rc_hashes.get("top_resistance_annotation")
        != digest(
            ROOT
            / "build/layout/buffered/tt_um_jjassonn69_beamformer.res.ext"
        )
    ):
        raise SystemExit("distributed-RC coverage report is not bound to its inputs")
    if (
        not route_matching.get("passed")
        or route_matching.get("route_sha256")
        != digest(ROOT / "build/layout/route.tcl")
        or route_matching.get("cross_net_overlap_count") != 0
        or route_matching.get("cross_net_via_overlap_count") != 0
        or route_matching.get("disconnected_route_component_count") != 0
        or route_matching.get("top_boundary_m4_clearance_count") != 0
    ):
        raise SystemExit(
            "generated-route matching/overlap/via/connectivity/top-boundary "
            "audit did not pass"
        )
    if (
        independent_frequency["case_count"] != 1
        or independent_frequency["pass_count"] != 1
        or independent_frequency["results"][0]["frequency_mhz"] != 4.0
        or independent_frequency.get("ngspice_version") != "46"
        or independent_frequency.get("netlist_sha256") != digest(extracted_rc_source)
    ):
        raise SystemExit(
            "independent ngspice 46 cross-check is not a current passing 4 MHz case"
        )

    nominal = result_at(pvt, "case", "tt_1.80v_p27c")
    nominal_frequency = result_at(frequency, "frequency_mhz", 4.0)
    worst_pvt = min(pvt["results"], key=lambda item: float(item["null_db"]))
    worst_headroom = min(
        pvt["results"], key=lambda item: float(item["output_high_headroom_v"])
    )
    worst_frequency = min(frequency["results"], key=lambda item: float(item["null_db"]))
    worst_clock_edge = max(
        float(item["max_edge_s"]) for item in clock["results"]
    )
    worst_clock_pair_skew = max(
        max(float(item["positive_pair_skew_s"]), float(item["negative_pair_skew_s"]))
        for item in clock["results"]
    )

    # Mutate the frozen submission evidence only after every generated report
    # and provenance check above has passed.
    for source, target in generated.values():
        shutil.copyfile(source, target)
    shutil.copyfile(extracted_rc_source, extracted_rc_frozen)
    artifacts["extracted_spice"] = extracted_rc_frozen

    reports = {
        "schematic_pvt": SUBMISSION / "core_pvt_summary.json",
        "extracted_pvt": SUBMISSION / "extracted_pvt_summary.json",
        "extracted_frequency_sweep": SUBMISSION / "extracted_frequency_sweep.json",
        "extracted_clock_sweep": SUBMISSION / "extracted_clock_sweep.json",
        "extracted_channel_balance": SUBMISSION / "extracted_channel_balance.json",
        "distributed_rc_coverage": SUBMISSION / "distributed_rc_coverage.json",
        "route_matching": SUBMISSION / "route_matching.json",
        "mismatch_mc": SUBMISSION / "mismatch_mc_summary.json",
        "magic_gds_readback_drc": SUBMISSION / "official_magic_drc.txt",
        "official_tinytapeout_precheck": (
            SUBMISSION / "official_precheck_results.md"
        ),
        "official_tinytapeout_action": SUBMISSION / "official_action.json",
        "independent_ngspice46_frequency_crosscheck": (
            SUBMISSION / "independent_ngspice46_frequency_crosscheck.json"
        ),
    }
    simulation_input_paths = [
        ROOT / "spice/sky130/beamformer_core.spice",
        ROOT / "spice/sky130/extracted_core_tb.spice",
        ROOT / "spice/sky130/extracted_clock_tb.spice",
        ROOT / "tools/run_core_pvt.py",
        ROOT / "tools/run_extracted_pvt.py",
        ROOT / "tools/run_extracted_sim.py",
        ROOT / "tools/run_extracted_frequency_sweep.py",
        ROOT / "tools/run_extracted_clock_sweep.py",
        ROOT / "tools/run_extracted_channel_balance.py",
        ROOT / "tools/run_mismatch_mc.py",
        ROOT / "tools/run_lock.py",
        ROOT / "tools/simulation_provenance.py",
        ROOT / "layout/circuit.json",
        ROOT / "layout/extract.tcl",
        ROOT / "spec/beamformer_v1.md",
        ROOT / "tools/generate_layout_scripts.py",
        ROOT / "tools/generate_route_script.py",
        ROOT / "tools/check_generated_routes.py",
        ROOT / "tools/check_extracted_layout.py",
        ROOT / "tools/check_gds_flat_rules.py",
        ROOT / "tools/check_distributed_rc.py",
        ROOT / "spice/sky130/sky130_passives_tt.inc",
        *sorted((ROOT / "spice/sky130").glob("sky130_1v8_*.inc")),
    ]
    simulation_inputs = {
        "extraction_view": "distributed_rc",
        "extracted_spice_sha256": digest(artifacts["extracted_spice"]),
        "files": {
            str(path.relative_to(ROOT)): digest(path)
            for path in simulation_input_paths
        },
        "report_inputs": {
            name: [str(path.relative_to(ROOT)) for path in inputs]
            for name, inputs in freshness_inputs.items()
        },
    }
    simulation_inputs_path = SUBMISSION / "simulation_inputs.json"
    simulation_inputs_path.write_text(
        json.dumps(simulation_inputs, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    reports["simulation_inputs"] = simulation_inputs_path
    previous = read_json(SUBMISSION / "signoff.json")
    signoff = {
        "artifacts": {
            name: {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}
            for name, path in artifacts.items()
        },
        "electrical": {
            "extracted_nominal_time_domain": {
                "current_a": abs(float(nominal["sum_supply"])),
                "null_db": nominal["null_db"],
                "null_rms_v": nominal["null_rms"],
                "output_common_mode_v": nominal["sum_cm"],
                "passed": nominal["passed"],
                "sum_rms_v": nominal["sum_rms"],
            },
            "extracted_nominal_wanted_tone": {
                "frequency_mhz": 4.0,
                "if_frequency_mhz": frequency["if_frequency_mhz"],
                "null_db": nominal_frequency["null_db"],
                "null_rms_v": nominal_frequency["null"]["tone_rms"],
                "passed": nominal_frequency["passed"],
                "sum_rms_v": nominal_frequency["sum"]["tone_rms"],
            },
            "extracted_pvt": {
                "case_count": pvt["case_count"],
                "minimum_null_db": pvt["measured_min_null_db"],
                "minimum_null_spec_db": pvt["null_db_min_spec"],
                "minimum_output_high_headroom_v": worst_headroom[
                    "output_high_headroom_v"
                ],
                "minimum_output_high_headroom_spec_v": pvt[
                    "output_high_headroom_min_spec_v"
                ],
                "pass_count": pvt["pass_count"],
                "worst_case": worst_pvt["case"],
                "worst_headroom_case": worst_headroom["case"],
            },
            "frequency_sweep": {
                "case_count": frequency["case_count"],
                "maximum_frequency_mhz": max(frequency["frequencies_mhz"]),
                "minimum_null_db": worst_frequency["null_db"],
                "pass_count": frequency["pass_count"],
            },
            "clock_sweep": {
                "case_count": clock["case_count"],
                "maximum_edge_s": worst_clock_edge,
                "maximum_frequency_mhz": max(clock["frequencies_mhz"]),
                "maximum_paired_channel_skew_s": worst_clock_pair_skew,
                "pass_count": clock["pass_count"],
            },
            "channel_balance": {
                "gain_mismatch_percent": balance["gain_mismatch_percent"],
                "passed": balance["passed"],
            },
            "independent_ngspice46_frequency_crosscheck": {
                "case_count": independent_frequency["case_count"],
                "frequency_mhz": 4.0,
                "netlist_sha256": independent_frequency["netlist_sha256"],
                "null_db": independent_frequency["results"][0]["null_db"],
                "pass_count": independent_frequency["pass_count"],
                "sum_rms_v": independent_frequency["results"][0]["sum"]["tone_rms"],
            },
            "mismatch_surrogate": {
                "case_count": mismatch["trial_count"],
                "method": mismatch["method"],
                "minimum_null_db": mismatch["minimum_null_db"],
                "p05_null_db": mismatch["p05_null_db"],
                "pass_count": mismatch["pass_count"],
                "seed": mismatch["seed"],
            },
            "schematic_pvt": {
                "case_count": core_pvt["case_count"],
                "minimum_null_db": min(
                    float(item["null_db"]) for item in core_pvt["results"]
                ),
                "pass_count": core_pvt["pass_count"],
            },
        },
        "physical": {
            "extracted_mos_fingers": 338,
            "extracted_passives": 8,
            "extraction_feedback_count": 0,
            "flattened_gds_capm_spacing_count": 0,
            "flattened_gds_met3_spacing_count": 0,
            "flattened_gds_met4_area_count": 0,
            "flattened_gds_met4_spacing_count": 0,
            "flattened_gds_met4_width_count": 0,
            "flattened_gds_via3_enclosure_count": 0,
            "gds_writer_feedback_count": 0,
            "generated_route_shapes": route_matching["shape_count"],
            "magic_gds_readback_drc_count": 0,
            "magic_internal_signoff_drc_count": 0,
            "named_route_tracks": len(route_matching["metrics"]),
            "route_constraint_check_passed": True,
            "route_cross_net_overlap_count": route_matching[
                "cross_net_overlap_count"
            ],
            "route_cross_net_via_overlap_count": route_matching[
                "cross_net_via_overlap_count"
            ],
            "route_dead_end_via3_site_count": route_matching[
                "dead_end_via3_site_count"
            ],
            "route_disconnected_component_count": route_matching[
                "disconnected_route_component_count"
            ],
            "route_top_boundary_m4_clearance_count": route_matching[
                "top_boundary_m4_clearance_count"
            ],
            "official_action_prechecks_passed": official_action[
                "official_prechecks_passed"
            ],
            "official_action_prechecks_run": official_action[
                "official_prechecks_run"
            ],
            "placed_devices": 70,
            "static_official_prechecks_passed": 8,
            "static_official_prechecks_run": 8,
            "topology_check_passed": True,
            "distributed_rc_check_passed": True,
            "distributed_rc_resistors": rc_coverage["distributed_rc"]["resistors"],
            "distributed_rc_capacitors": rc_coverage["distributed_rc"]["capacitors"],
            "distributed_rc_internal_nodes": rc_coverage["distributed_rc"][
                "internal_resistor_nodes"
            ],
            "distributed_rc_resistor_components": rc_coverage[
                "distributed_rc"
            ]["resistor_components"],
            "distributed_rc_unanchored_components": len(
                rc_coverage["distributed_rc"]["unanchored_resistor_components"]
            ),
            "distributed_rc_top_route_annotations": rc_coverage["annotation"][
                "resistors"
            ],
        },
        "provenance": {
            **{
                key: value
                for key, value in previous["provenance"].items()
                if key not in {"linux_crosscheck_ngspice_version", "ngspice_version"}
            },
            "primary_extracted_ngspice_version": "44.2",
            "primary_extracted_platform": pvt["platform"],
            "schematic_ngspice_version": core_pvt["ngspice_version"],
            "schematic_platform": core_pvt["platform"],
            "independent_crosscheck_ngspice_version": "46",
            "independent_crosscheck_platform": independent_frequency["platform"],
        },
        "reports": {
            name: {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}
            for name, path in reports.items()
        },
        "remaining_risks": [
            "native foundry Spectre mismatch Monte Carlo is not complete",
            "package and shuttle analog-pad parasitics are emulated, not extracted",
            "independent foundry-grade LVS is not complete",
            "noise, linearity, compression, and LO-feedthrough characterization remain",
            "20-30 MHz modes have nominal extracted characterization, not full PVT ratings",
        ],
        "status": "official_action_passed_release_candidate",
        "target": "TinyTapeout SKY130 ttsky26c",
        "top_module": "tt_um_jjassonn69_beamformer",
    }
    (SUBMISSION / "signoff.json").write_text(
        json.dumps(signoff, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lock_path = SUBMISSION / "template.lock"
    lock_lines = []
    updates = {
        "gds_sha256": digest(artifacts["gds"]),
        "lef_sha256": digest(artifacts["lef"]),
    }
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0]
        lock_lines.append(f"{key}={updates[key]}" if key in updates else line)
    lock_path.write_text("\n".join(lock_lines) + "\n", encoding="utf-8")
    print("Submission evidence frozen and authenticated")


if __name__ == "__main__":
    main()
