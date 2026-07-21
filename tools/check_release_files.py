#!/usr/bin/env python3
"""Dependency-free integrity checks for committed TinyTapeout release files."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "submission/template.lock"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    values: dict[str, str] = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value

    for kind in ("gds", "lef"):
        path = ROOT / values[f"{kind}_file"]
        actual = digest(path)
        expected = values[f"{kind}_sha256"]
        if actual != expected:
            raise SystemExit(f"{kind.upper()} SHA-256 mismatch: {actual} != {expected}")

    signoff = json.loads((ROOT / "submission/signoff.json").read_text(encoding="utf-8"))
    official_action = json.loads(
        (ROOT / "submission/official_action.json").read_text(encoding="utf-8")
    )
    simulation_inputs = json.loads(
        (ROOT / "submission/simulation_inputs.json").read_text(encoding="utf-8")
    )
    rc_coverage = json.loads(
        (ROOT / "submission/distributed_rc_coverage.json").read_text(encoding="utf-8")
    )
    route_matching = json.loads(
        (ROOT / "submission/route_matching.json").read_text(encoding="utf-8")
    )
    for kind in ("gds", "lef"):
        if signoff["artifacts"][kind]["sha256"] != values[f"{kind}_sha256"]:
            raise SystemExit(f"{kind.upper()} signoff hash does not match template.lock")
    for name, artifact in signoff["artifacts"].items():
        artifact_path = ROOT / artifact["path"]
        if not artifact_path.is_file() or digest(artifact_path) != artifact["sha256"]:
            raise SystemExit(f"signed artifact is missing or changed: {name}")
    physical = signoff["physical"]
    zero_count_gates = (
        "extraction_feedback_count",
        "flattened_gds_capm_spacing_count",
        "flattened_gds_met3_spacing_count",
        "flattened_gds_met4_area_count",
        "flattened_gds_met4_spacing_count",
        "flattened_gds_met4_width_count",
        "flattened_gds_via3_enclosure_count",
        "gds_writer_feedback_count",
        "magic_gds_readback_drc_count",
        "magic_internal_signoff_drc_count",
        "route_cross_net_overlap_count",
        "route_cross_net_via_overlap_count",
        "route_dead_end_via3_site_count",
        "route_disconnected_component_count",
        "route_top_boundary_m4_clearance_count",
        "distributed_rc_unanchored_components",
    )
    nonzero = {name: physical[name] for name in zero_count_gates if physical[name] != 0}
    if nonzero:
        raise SystemExit(f"physical signoff contains nonzero error counts: {nonzero}")
    pvt = signoff["electrical"]["extracted_pvt"]
    if pvt["pass_count"] != pvt["case_count"]:
        raise SystemExit("extracted PVT signoff is not fully passing")
    if pvt["case_count"] != 45:
        raise SystemExit(f"extracted PVT has {pvt['case_count']} cases, expected 45")
    if (
        pvt["minimum_output_high_headroom_v"]
        < pvt["minimum_output_high_headroom_spec_v"]
        or pvt["minimum_output_high_headroom_spec_v"] != 0.10
    ):
        raise SystemExit("extracted PVT output-headroom signoff is not passing")
    for name in (
        "frequency_sweep",
        "clock_sweep",
        "mismatch_surrogate",
        "independent_ngspice46_frequency_crosscheck",
    ):
        evidence = signoff["electrical"][name]
        if evidence["pass_count"] != evidence["case_count"]:
            raise SystemExit(f"{name} signoff is not fully passing")
    if signoff["physical"]["extracted_mos_fingers"] != 338:
        raise SystemExit("release does not contain the 338-finger matched layout")
    if signoff["physical"]["placed_devices"] != 70:
        raise SystemExit("release does not contain the 70-device matched layout")
    if (
        signoff["physical"]["official_action_prechecks_passed"]
        != signoff["physical"]["official_action_prechecks_run"]
        or signoff["physical"]["official_action_prechecks_run"] != 15
    ):
        raise SystemExit("official TinyTapeout Action is not recorded as 15/15 passing")
    if official_action["conclusion"] != "success":
        raise SystemExit("official TinyTapeout Action conclusion is not successful")
    if official_action["gds_sha256"] != values["gds_sha256"]:
        raise SystemExit("official TinyTapeout Action is stale for this GDS")
    if (
        simulation_inputs["extracted_spice_sha256"]
        != signoff["artifacts"]["extracted_spice"]["sha256"]
    ):
        raise SystemExit("simulation-input lock does not match extracted SPICE signoff")
    if simulation_inputs.get("extraction_view") != "distributed_rc":
        raise SystemExit("simulation-input lock is not a distributed-RC extraction")
    if signoff["artifacts"]["extracted_spice"]["path"] != "submission/extracted_rc.spice":
        raise SystemExit("signed extracted SPICE artifact is not the distributed-RC view")
    if not physical.get("distributed_rc_check_passed"):
        raise SystemExit("distributed-RC extraction coverage is not passing")
    if not physical.get("route_constraint_check_passed"):
        raise SystemExit("generated-route constraint audit is not passing")
    if not rc_coverage.get("passed"):
        raise SystemExit("frozen distributed-RC coverage report is not passing")
    if not route_matching.get("passed"):
        raise SystemExit("frozen generated-route audit is not passing")
    if (
        rc_coverage.get("sha256", {}).get("distributed_rc_netlist")
        != signoff["artifacts"]["extracted_spice"]["sha256"]
    ):
        raise SystemExit("distributed-RC report is not bound to the frozen RC netlist")
    route_counters = {
        "route_cross_net_overlap_count": "cross_net_overlap_count",
        "route_cross_net_via_overlap_count": "cross_net_via_overlap_count",
        "route_disconnected_component_count": "disconnected_route_component_count",
        "route_top_boundary_m4_clearance_count": "top_boundary_m4_clearance_count",
    }
    for signoff_name, report_name in route_counters.items():
        if physical[signoff_name] != route_matching[report_name]:
            raise SystemExit(f"route report/signoff counter mismatch: {signoff_name}")
    rc_counters = {
        "distributed_rc_resistors": ("distributed_rc", "resistors"),
        "distributed_rc_capacitors": ("distributed_rc", "capacitors"),
        "distributed_rc_internal_nodes": (
            "distributed_rc",
            "internal_resistor_nodes",
        ),
        "distributed_rc_resistor_components": (
            "distributed_rc",
            "resistor_components",
        ),
        "distributed_rc_top_route_annotations": ("annotation", "resistors"),
    }
    for signoff_name, (section, report_name) in rc_counters.items():
        if physical[signoff_name] != rc_coverage[section][report_name]:
            raise SystemExit(f"RC report/signoff counter mismatch: {signoff_name}")
    for name in (
        "distributed_rc_resistors",
        "distributed_rc_capacitors",
        "distributed_rc_internal_nodes",
        "distributed_rc_top_route_annotations",
        "distributed_rc_resistor_components",
    ):
        if physical.get(name, 0) <= 0:
            raise SystemExit(f"distributed-RC evidence count is empty: {name}")
    for relative, expected in simulation_inputs["files"].items():
        actual = digest(ROOT / relative)
        if actual != expected:
            raise SystemExit(f"simulation input changed after evidence freeze: {relative}")
    extracted_hash = signoff["artifacts"]["extracted_spice"]["sha256"]
    for report_name in (
        "extracted_pvt_summary.json",
        "extracted_frequency_sweep.json",
        "extracted_clock_sweep.json",
        "extracted_channel_balance.json",
        "independent_ngspice46_frequency_crosscheck.json",
    ):
        report = json.loads((ROOT / "submission" / report_name).read_text(encoding="utf-8"))
        if report.get("netlist_sha256") != extracted_hash:
            raise SystemExit(f"electrical report uses a different RC netlist: {report_name}")
        expected_version = (
            "46" if report_name.startswith("independent_") else "44.2"
        )
        if report.get("ngspice_version") != expected_version:
            raise SystemExit(
                f"electrical report uses unexpected ngspice version: {report_name}"
            )
    schematic_path = ROOT / "spice/sky130/beamformer_core.spice"
    for report_name in ("core_pvt_summary.json", "mismatch_mc_summary.json"):
        report = json.loads(
            (ROOT / "submission" / report_name).read_text(encoding="utf-8")
        )
        if (
            report.get("source") != "spice/sky130/beamformer_core.spice"
            or report.get("source_sha256") != digest(schematic_path)
            or report.get("ngspice_version") != "46"
        ):
            raise SystemExit(
                f"schematic report is not bound to current source/ngspice: {report_name}"
            )
    official_result = ROOT / "submission/official_precheck_results.md"
    official_magic = ROOT / "submission/official_magic_drc.txt"
    if digest(official_result) != official_action["results_sha256"]:
        raise SystemExit("official precheck report does not match its Action attestation")
    if digest(official_magic) != official_action["magic_drc_sha256"]:
        raise SystemExit("official Magic report does not match its Action attestation")
    for report in signoff["reports"].values():
        report_path = ROOT / report["path"]
        if digest(report_path) != report["sha256"]:
            raise SystemExit(f"signoff report hash mismatch: {report_path}")

    gds = (ROOT / values["gds_file"]).read_bytes()
    if not gds.startswith(b"\x00\x06\x00\x02"):
        raise SystemExit("GDS is not an uncompressed GDSII stream")

    lef = (ROOT / values["lef_file"]).read_text(encoding="utf-8")
    top = "tt_um_jjassonn69_beamformer"
    if f"MACRO {top}" not in lef or f"END {top}" not in lef:
        raise SystemExit("LEF top macro is missing or misnamed")
    if "SIZE 161.000 BY 225.760 ;" not in lef:
        raise SystemExit("LEF macro dimensions do not match the 1x2 boundary")
    pin_count = len(re.findall(r"^\s*PIN \S+", lef, re.MULTILINE))
    if pin_count != 53:
        raise SystemExit(f"LEF contains {pin_count} pins, expected 51 template + 2 power")

    required = [
        ROOT / "info.yaml",
        ROOT / "src/project.v",
        ROOT / "docs/info.md",
        ROOT / "docs/datasheet.md",
        ROOT / "docs/images/beamformer-gds.png",
        ROOT / "docs/images/beamformer-core-detail.png",
        ROOT / "docs/images/beamformer-mim-detail.png",
        ROOT / "docs/images/beamformer-top-boundary-detail.png",
        ROOT / "LICENSE",
        ROOT / "submission/official_magic_drc.txt",
        ROOT / "submission/official_precheck_results.md",
        ROOT / "submission/official_action.json",
        ROOT / "submission/core_pvt_summary.json",
        ROOT / "submission/extracted_pvt_summary.json",
        ROOT / "submission/extracted_frequency_sweep.json",
        ROOT / "submission/extracted_clock_sweep.json",
        ROOT / "submission/extracted_channel_balance.json",
        ROOT / "submission/distributed_rc_coverage.json",
        ROOT / "submission/route_matching.json",
        ROOT / "submission/extracted_rc.spice",
        ROOT / "submission/mismatch_mc_summary.json",
        ROOT / "submission/independent_ngspice46_frequency_crosscheck.json",
        ROOT / "submission/simulation_inputs.json",
        ROOT / "submission/signoff.json",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"required submission files missing: {missing}")

    print(
        "Release files passed: authenticated GDS/LEF hashes, plain GDSII, "
        "161x225.76 um macro, 53 LEF pins, zero physical error counts, "
        "45/45 extracted PVT, 4/4 frequency/clock sweeps, mismatch evidence, "
        "distributed-RC coverage, independent ngspice cross-check, authenticated "
        "simulation inputs, 15/15 "
        "official Action prechecks, and required metadata"
    )


if __name__ == "__main__":
    main()
