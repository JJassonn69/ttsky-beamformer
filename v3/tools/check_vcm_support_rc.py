#!/usr/bin/env python3
"""Audit distributed metal RC of the exact V3 VCM support pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from check_tail_reference_rc import (
    component,
    effective_resistance,
    endpoint_nodes,
    marker,
    parse_rnodes,
    parse_spice,
    resistor_graph,
    spice_number,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORK = ROOT / "build" / "v3" / "vcm_support_pilot" / "rc"
DEFAULT_GDS = ROOT / "build" / "v3" / "vcm_support_pilot" / "v3_vcm_support_pilot.gds"
DEFAULT_MANIFEST = ROOT / "v3" / "layout" / "shared_support_placement.json"
DEFAULT_PRECHECK = ROOT / "build" / "v3" / "vcm_support_pilot" / "precheck_summary.json"
DEFAULT_TOPOLOGY = ROOT / "v3" / "evidence" / "vcm_support_topology_check.json"
DEFAULT_REPORT = ROOT / "v3" / "evidence" / "vcm_support_physical_gate.json"
MAX_ROUTE_RESISTANCE_OHM = 30.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model_counts(records: list[list[str]]) -> dict[str, int]:
    text = [" ".join(record) for record in records]
    return {
        "vcm_divider_resistors": sum("sky130_fd_pr__res_xhigh_po_1p41" in line for line in text),
        "vcm_mim_capacitors": sum("sky130_fd_pr__cap_mim_m3_1" in line for line in text),
    }


def maximum_connected_resistance(
    graph: dict[str, dict[str, float]],
    sources: list[str],
    sinks: list[str],
) -> tuple[float, dict[str, float]]:
    candidates = {
        f"{source}->{sink}": effective_resistance(graph, source, sink)
        for source in sources
        for sink in sinks
        if sink in component(graph, source)
    }
    if not candidates:
        raise ValueError(f"no connected RC endpoint pair for {sources} -> {sinks}")
    return max(candidates.values()), candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--gds", type=Path, default=DEFAULT_GDS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--precheck", type=Path, default=DEFAULT_PRECHECK)
    parser.add_argument("--topology", type=Path, default=DEFAULT_TOPOLOGY)
    parser.add_argument("--log", type=Path, default=DEFAULT_WORK / "magic_rc.log")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    topology = json.loads(args.topology.read_text(encoding="utf-8"))
    log = args.log.read_text(encoding="utf-8", errors="replace")
    base_path = args.work / "vcm_support_base.spice"
    rc_path = args.work / "vcm_support_rc.spice"
    res_ext_path = args.work / "v3_vcm_support_pilot_rc.res.ext"
    base = parse_spice(base_path)
    rc = parse_spice(rc_path)
    graph = resistor_graph(rc["R"])
    rnodes = parse_rnodes(res_ext_path)

    output = manifest["vcm"]["feed"]["segments"][-1]["to"]
    star = manifest["vcm"]["feed"]["named_star"]
    cap_points = {
        item["name"]: item["terminals"]["C1"][0]
        for item in manifest["vcm"]["bypass_capacitors"]
    }
    output_nodes = endpoint_nodes(rnodes, graph, output)
    route_results: dict[str, object] = {}
    star_resistance, star_candidates = maximum_connected_resistance(
        graph, output_nodes, endpoint_nodes(rnodes, graph, star)
    )
    route_results["divider_star"] = {
        "point_um": star,
        "effective_resistance_ohm": star_resistance,
        "candidate_resistances_ohm": star_candidates,
    }
    all_resistances = [star_resistance]
    for name, point in cap_points.items():
        resistance, candidates = maximum_connected_resistance(
            graph, output_nodes, endpoint_nodes(rnodes, graph, point)
        )
        route_results[name] = {
            "point_um": point,
            "effective_resistance_ohm": resistance,
            "candidate_resistances_ohm": candidates,
        }
        all_resistances.append(resistance)

    base_models = model_counts(base["X"])
    rc_models = model_counts(rc["X"])
    base_parasitic_capacitance_f = sum(spice_number(item[3]) for item in base["C"])
    rc_parasitic_capacitance_f = sum(spice_number(item[3]) for item in rc["C"])
    parasitic_capacitance_delta_percent = 100.0 * abs(
        rc_parasitic_capacitance_f - base_parasitic_capacitance_f
    ) / base_parasitic_capacitance_f
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed_warning = re.compile(
        r'^(?:Warning:\s+Calma reading is not undoable!  I hope that.s OK\.|'
        r'Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.)$'
    )
    unexpected_warnings = [line for line in warnings if not allowed_warning.fullmatch(line)]
    gds_hash = sha256(args.gds)
    checks = {
        "magic_drc_zero": marker(log, "V3_VCM_SUPPORT_RC_DRC_COUNT") == 0,
        "magic_extraction_feedback_zero": marker(log, "V3_VCM_SUPPORT_RC_EXTRACTION_FEEDBACK_COUNT") == 0,
        "magic_outputs_complete": log.count("exttospice finished.") >= 2,
        "only_classified_magic_warnings": not unexpected_warnings,
        "base_is_resistance_free": len(base["R"]) == 0,
        "distributed_resistors_present": len(rc["R"]) > 0,
        # extresist splits a conductor into additional nodes and therefore
        # emits more individual C records.  Preserve total extracted
        # capacitance instead of incorrectly requiring the record count to be
        # unchanged.
        "extracted_parasitic_capacitance_preserved": parasitic_capacitance_delta_percent <= 0.5,
        "divider_devices_preserved": base_models["vcm_divider_resistors"] == rc_models["vcm_divider_resistors"] == 6,
        "mim_devices_preserved": base_models["vcm_mim_capacitors"] == rc_models["vcm_mim_capacitors"] == 3,
        "all_named_endpoints_found": len(route_results) == 4,
        "route_resistance_within_limit": max(all_resistances) <= MAX_ROUTE_RESISTANCE_OHM,
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_is_for_exact_gds": precheck["gds_sha256"] == gds_hash,
        "topology_passes": topology["status"] == "pass",
        "topology_is_for_exact_gds": topology["provenance"]["gds_sha256"] == gds_hash,
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact three-MIM VCM divider/feed pilot: topology, direct-GDS geometry, and distributed metal RC; four-channel leaf integration remains a separate gate",
        "checks": checks,
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": gds_hash,
        "manifest_sha256": sha256(args.manifest),
        "distributed_rc": {
            "root_um": output,
            "base_counts": {"R": len(base["R"]), "C": len(base["C"]), "X": len(base["X"]), **base_models},
            "distributed_counts": {"R": len(rc["R"]), "C": len(rc["C"]), "X": len(rc["X"]), **rc_models},
            "base_parasitic_capacitance_f": base_parasitic_capacitance_f,
            "distributed_parasitic_capacitance_f": rc_parasitic_capacitance_f,
            "parasitic_capacitance_delta_percent": parasitic_capacitance_delta_percent,
            "maximum_allowed_parasitic_capacitance_delta_percent": 0.5,
            "routes": route_results,
            "maximum_effective_resistance_ohm": max(all_resistances),
            "maximum_allowed_route_resistance_ohm": MAX_ROUTE_RESISTANCE_OHM,
        },
        "unexpected_magic_warnings": unexpected_warnings,
        "sha256": {
            "base_spice": sha256(base_path),
            "distributed_rc_spice": sha256(rc_path),
            "resistance_annotation": sha256(res_ext_path),
            "magic_log": sha256(args.log),
            "precheck_summary": sha256(args.precheck),
            "topology_audit": sha256(args.topology),
            "extractor": sha256(ROOT / "v3" / "layout" / "extract_vcm_support_rc.tcl"),
            "auditor": sha256(Path(__file__)),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
