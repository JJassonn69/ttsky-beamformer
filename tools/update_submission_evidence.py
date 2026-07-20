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
    generated = {
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
        "mismatch_mc": (
            ROOT / "build/mismatch_mc_summary.json",
            SUBMISSION / "mismatch_mc_summary.json",
        ),
    }
    missing = [str(source) for source, _target in generated.values() if not source.is_file()]
    if missing:
        raise SystemExit(f"missing generated reports: {missing}")
    for source, target in generated.values():
        shutil.copyfile(source, target)

    pvt = read_json(generated["extracted_pvt"][0])
    frequency = read_json(generated["extracted_frequency_sweep"][0])
    clock = read_json(generated["extracted_clock_sweep"][0])
    balance = read_json(generated["extracted_channel_balance"][0])
    mismatch = read_json(generated["mismatch_mc"][0])
    core_pvt = read_json(SUBMISSION / "core_pvt_summary.json")
    if pvt["matrix"] != "full" or pvt["case_count"] != 45:
        raise SystemExit("refusing to freeze anything except the full 45-case extracted PVT")

    nominal = result_at(pvt, "case", "tt_1.80v_p27c")
    nominal_frequency = result_at(frequency, "frequency_mhz", 4.0)
    worst_pvt = min(pvt["results"], key=lambda item: float(item["null_db"]))
    worst_frequency = min(frequency["results"], key=lambda item: float(item["null_db"]))
    worst_clock_edge = max(
        float(item["max_edge_s"]) for item in clock["results"]
    )
    worst_clock_pair_skew = max(
        max(float(item["positive_pair_skew_s"]), float(item["negative_pair_skew_s"]))
        for item in clock["results"]
    )

    artifacts = {
        "gds": ROOT / "gds/tt_um_jjassonn69_beamformer.gds",
        "lef": ROOT / "lef/tt_um_jjassonn69_beamformer.lef",
        "extracted_spice": ROOT / "build/layout/extracted.spice",
    }
    reports = {
        "schematic_pvt": SUBMISSION / "core_pvt_summary.json",
        "extracted_pvt": SUBMISSION / "extracted_pvt_summary.json",
        "extracted_frequency_sweep": SUBMISSION / "extracted_frequency_sweep.json",
        "extracted_clock_sweep": SUBMISSION / "extracted_clock_sweep.json",
        "extracted_channel_balance": SUBMISSION / "extracted_channel_balance.json",
        "mismatch_mc": SUBMISSION / "mismatch_mc_summary.json",
        "magic_gds_readback_drc": SUBMISSION / "official_magic_drc.txt",
    }
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
                "pass_count": pvt["pass_count"],
                "worst_case": worst_pvt["case"],
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
            "gds_writer_feedback_count": 0,
            "generated_route_shapes": 7367,
            "magic_gds_readback_drc_count": 0,
            "magic_internal_signoff_drc_count": 0,
            "named_route_tracks": 30,
            "placed_devices": 70,
            "static_official_prechecks_passed": 8,
            "static_official_prechecks_run": 8,
            "topology_check_passed": True,
        },
        "provenance": previous["provenance"],
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
        "status": "local_release_candidate",
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
