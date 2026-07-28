#!/usr/bin/env python3
"""Audit distributed conductor RC and symmetry of the exact V3 vector unit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3" / "tools"))

from check_tail_reference_rc import (  # noqa: E402
    component,
    effective_resistance,
    parse_rnodes,
    parse_spice,
    resistor_graph,
)


BUILD = ROOT / "build" / "v3" / "vector_unit_pilot"
TOKENS = (
    "tail", "gmp", "gmn", "outp", "outn",
    "lop_left", "lon_left", "lon_right", "lop_right",
    "sig", "ref", "vbias",
)
ROOT_COORDINATES = {
    "tail": (4157, 4595),
    "gmp": (4100, 5887),
    "gmn": (4472, 5887),
    "outp": (4216, 6446),
    "outn": (4356, 6446),
    "lop_left": (3870, 6413),
    "lon_left": (3870, 6007),
    "lon_right": (4702, 6413),
    "lop_right": (4702, 6007),
    "sig": (4030, 4000),
    "ref": (4542, 4000),
    "vbias": (4286, 4000),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(log: str, name: str) -> int | None:
    values = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def mismatch_percent(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return 100.0 * (max(values) - min(values)) / mean


def count(records: dict[str, list[list[str]]]) -> dict[str, int]:
    return {
        "resistors": len(records["R"]),
        "capacitors": len(records["C"]),
        "devices": len(records["X"]),
    }


def analyze_view(work: Path, token: str) -> dict[str, object]:
    base_path = work / f"vector_unit_{token}_base.spice"
    rc_path = work / f"vector_unit_{token}_rc.spice"
    res_path = work / f"v3_vector_unit_pilot_rc_{token}.res.ext"
    base = parse_spice(base_path)
    rc = parse_spice(rc_path)
    graph = resistor_graph(rc["R"])
    rnodes = parse_rnodes(res_path)
    coordinate = ROOT_COORDINATES[token]
    candidates = sorted({node for node in rnodes.get(coordinate, []) if node in graph})
    if not candidates:
        raise ValueError(f"{token} has no resistor node at root {coordinate}")
    root_node = next((node for node in candidates if node.endswith("#")), candidates[0])
    connected = component(graph, root_node)
    terminals: list[str] = []
    for fields in rc["X"]:
        for node in fields[1:5]:
            if node in connected and node not in terminals:
                terminals.append(node)
    if not terminals:
        raise ValueError(f"{token} root reaches no transistor terminal")
    coordinates_by_node = {
        node: point
        for point, nodes in rnodes.items()
        for node in nodes
        if node in terminals or node == root_node
    }
    root_to_terminal = {
        node: effective_resistance(graph, root_node, node)
        for node in terminals
    }
    return {
        "root_coordinate_internal": list(coordinate),
        "root_node": root_node,
        "root_candidates": candidates,
        "terminal_nodes": terminals,
        "coordinates_by_node": {node: list(point) for node, point in coordinates_by_node.items()},
        "root_to_terminal_ohm": root_to_terminal,
        "base": count(base),
        "distributed_rc": count(rc),
        "sha256": {
            "base_spice": sha256(base_path),
            "distributed_rc_spice": sha256(rc_path),
            "resistance_annotation": sha256(res_path),
        },
        "_graph": graph,
    }


def terminal_order(view: dict[str, object]) -> list[str]:
    coordinates = view["coordinates_by_node"]
    assert isinstance(coordinates, dict)
    terminals = view["terminal_nodes"]
    assert isinstance(terminals, list)
    return sorted(terminals, key=lambda node: tuple(coordinates[node]))


def pair_resistance(view: dict[str, object], first: str, second: str) -> float:
    graph = view["_graph"]
    assert isinstance(graph, dict)
    return effective_resistance(graph, first, second)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=BUILD / "rc")
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_vector_unit_pilot.gds")
    parser.add_argument("--log", type=Path, default=BUILD / "rc" / "magic_rc.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument("--topology", type=Path, default=BUILD / "topology_audit.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "v3" / "layout" / "vector_unit_placement.json")
    parser.add_argument("--output", type=Path, default=ROOT / "v3" / "evidence" / "vector_unit_physical_gate.json")
    args = parser.parse_args()

    log = args.log.read_text(encoding="utf-8", errors="replace")
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    topology = json.loads(args.topology.read_text(encoding="utf-8"))
    views = {token: analyze_view(args.work, token) for token in TOKENS}

    tail_nodes = terminal_order(views["tail"])
    tail_device = min(tail_nodes, key=lambda node: views["tail"]["coordinates_by_node"][node][1])
    tail_gm = sorted((node for node in tail_nodes if node != tail_device), key=lambda node: views["tail"]["coordinates_by_node"][node][0])
    tail_paths = [pair_resistance(views["tail"], tail_device, node) for node in tail_gm]

    gm_paths: dict[str, dict[str, float]] = {}
    for token in ("gmp", "gmn"):
        nodes = terminal_order(views[token])
        gm_device = min(nodes, key=lambda node: views[token]["coordinates_by_node"][node][1])
        switches = sorted((node for node in nodes if node != gm_device), key=lambda node: views[token]["coordinates_by_node"][node][1])
        gm_paths[token] = {
            "lower_switch_ohm": pair_resistance(views[token], gm_device, switches[0]),
            "upper_switch_ohm": pair_resistance(views[token], gm_device, switches[1]),
        }

    output_paths: dict[str, dict[str, float]] = {}
    for token in ("outp", "outn"):
        nodes = terminal_order(views[token])
        root_values = views[token]["root_to_terminal_ohm"]
        output_paths[token] = {
            "left_switch_to_port_ohm": root_values[nodes[0]],
            "right_switch_to_port_ohm": root_values[nodes[1]],
        }

    lo_paths = {
        token: next(iter(views[token]["root_to_terminal_ohm"].values()))
        for token in ("lop_left", "lon_left", "lon_right", "lop_right")
    }
    input_paths = {
        token: next(iter(views[token]["root_to_terminal_ohm"].values()))
        for token in ("sig", "ref")
    }
    vbias_path = next(iter(views["vbias"]["root_to_terminal_ohm"].values()))

    gm_values = [value for pair in gm_paths.values() for value in pair.values()]
    output_values = [value for pair in output_paths.values() for value in pair.values()]
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed_warning = re.compile(
        r'^(?:Warning:\s+Calma reading is not undoable!  I hope that.s OK\.|'
        r'Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.)$'
    )
    unexpected_warnings = [line for line in warnings if not allowed_warning.fullmatch(line)]

    # Remove graphs only after every resistance calculation is complete.
    for view in views.values():
        view.pop("_graph", None)

    all_base = [views[token]["base"] for token in TOKENS]
    all_rc = [views[token]["distributed_rc"] for token in TOKENS]
    checks = {
        "magic_drc_zero_all_views": all(
            marker(log, f"V3_VECTOR_UNIT_RC_DRC_COUNT_{token}") == 0 for token in TOKENS
        ),
        "magic_extraction_feedback_zero_all_views": all(
            marker(log, f"V3_VECTOR_UNIT_RC_EXTRACTION_FEEDBACK_COUNT_{token}") == 0 for token in TOKENS
        ),
        "magic_outputs_complete": log.count("exttospice finished.") >= 2 * len(TOKENS),
        "only_classified_magic_warnings": not unexpected_warnings,
        "base_views_are_resistance_free": all(item["resistors"] == 0 for item in all_base),
        "distributed_resistors_present": all(item["resistors"] > 0 for item in all_rc),
        "capacitance_present_in_all_views": all(item["capacitors"] > 0 for item in all_base + all_rc),
        "seven_devices_preserved_in_all_views": all(item["devices"] == 7 for item in all_base + all_rc),
        "tail_pair_mismatch_within_0p5_percent": mismatch_percent(tail_paths) <= 0.5,
        "gm_current_paths_within_1_percent": mismatch_percent(gm_values) <= 1.0,
        "output_paths_within_1_percent": mismatch_percent(output_values) <= 1.0,
        "four_lo_gate_paths_within_0p5_percent": mismatch_percent(list(lo_paths.values())) <= 0.5,
        "sig_ref_paths_within_0p5_percent": mismatch_percent(list(input_paths.values())) <= 0.5,
        "current_path_resistance_below_350_ohm": max(tail_paths + gm_values + output_values) < 350.0,
        "gate_path_resistance_below_500_ohm": max([*lo_paths.values(), *input_paths.values(), vbias_path]) < 500.0,
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_is_for_exact_gds": precheck["gds_sha256"] == sha256(args.gds),
        "topology_audit_passes": topology["status"] == "pass",
        "topology_is_for_exact_gds": topology["gds_sha256"] == sha256(args.gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact V3 seven-transistor vector unit: Magic/direct-GDS geometry, extracted topology, and distributed conductor RC",
        "checks": checks,
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "manifest_sha256": sha256(args.manifest),
        "distributed_rc": {
            "views": views,
            "tail_paths_ohm": {"left_gm": tail_paths[0], "right_gm": tail_paths[1]},
            "tail_pair_mismatch_percent": mismatch_percent(tail_paths),
            "gm_current_paths": gm_paths,
            "gm_current_path_mismatch_percent": mismatch_percent(gm_values),
            "output_paths": output_paths,
            "output_path_mismatch_percent": mismatch_percent(output_values),
            "lo_gate_paths_ohm": lo_paths,
            "lo_gate_path_mismatch_percent": mismatch_percent(list(lo_paths.values())),
            "input_gate_paths_ohm": input_paths,
            "input_gate_path_mismatch_percent": mismatch_percent(list(input_paths.values())),
            "vbias_gate_path_ohm": vbias_path,
        },
        "unexpected_magic_warnings": unexpected_warnings,
        "sha256": {
            "magic_log": sha256(args.log),
            "precheck_summary": sha256(args.precheck),
            "topology_audit": sha256(args.topology),
            "extractor": sha256(ROOT / "v3" / "layout" / "extract_vector_unit_rc.tcl"),
            "auditor": sha256(Path(__file__)),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
